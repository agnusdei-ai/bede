"""
AES-256-GCM encryption at rest.

Key hierarchy (the plaintext key material never leaves memory):
  MASTER_SECRET (env var)
       ↓ PBKDF2-HMAC-SHA256 + device_salt → KEK  (32 bytes, in memory only)
  DATA_KEY (32 random bytes)
       ↓ AES-256-GCM with KEK → stored in encryption_config table
  All user data
       ↓ AES-256-GCM with DATA_KEY → stored as BYTEA in Postgres

On-wire envelope (same format as before, now stored in DB columns):
  MAGIC(4) | VERSION(1) | NONCE(16) | TAG(16) | CIPHERTEXT(n)

MASTER_SECRET rotation (see rotate_master_secret() below and
scripts/rotate_master_secret.py) only ever re-wraps DATA_KEY — DATA_KEY
itself, and everything encrypted under it, never changes. That's what makes
rotation cheap: no user data is touched, only the one encryption_config
row holding the wrapped DATA_KEY. This used to be undocumented as a
possibility at all; docs/INCIDENT_RESPONSE.md's "Critical" severity entry
for a leaked MASTER_SECRET now points here instead of treating rotation as
unconditionally destructive.
"""

import asyncio
import logging
import struct
from typing import Optional

from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Random import get_random_bytes

log = logging.getLogger(__name__)

_MAGIC = b"SAGE"
_VERSION = 1
_HEADER_SIZE = 4 + 1 + 16 + 16   # magic + version + nonce + tag
_PBKDF2_ITERS = 600_000

_DATA_KEY: Optional[bytes] = None


# ── Low-level AES-GCM ────────────────────────────────────────────────────────

def _aes_encrypt(plaintext: bytes, key: bytes) -> bytes:
    nonce = get_random_bytes(16)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=16)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)
    return _MAGIC + struct.pack("B", _VERSION) + nonce + tag + ciphertext


def _aes_decrypt(blob: bytes, key: bytes) -> bytes:
    if len(blob) < _HEADER_SIZE + 1:
        raise ValueError("Encrypted blob too short")
    if blob[:4] != _MAGIC:
        raise ValueError("Bad magic — not a SAGE-encrypted value")
    version = struct.unpack("B", blob[4:5])[0]
    if version != _VERSION:
        raise ValueError(f"Unsupported encryption version {version}")
    nonce = blob[5:21]
    tag   = blob[21:37]
    ciphertext = blob[37:]
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=16)
    return cipher.decrypt_and_verify(ciphertext, tag)


# ── Key management ───────────────────────────────────────────────────────────

def _derive_kek(master_secret: str, salt: bytes) -> bytes:
    """
    Derives Key Encryption Key. CPU-bound (~0.3-1.5s depending on hardware) —
    run in executor.

    Uses hmac_hash_module (pycryptodome's optimized C-level PRF loop), not a
    custom Python prf= callback — the callback form calls back into Python
    600,000 times and was measured at ~15s here, ~42x slower for identical
    output. That gap matters most on the lowest-power hosts this targets
    (Raspberry Pi), where it could stretch first-boot startup considerably.
    """
    return PBKDF2(
        master_secret.encode("utf-8"),
        salt,
        dkLen=32,
        count=_PBKDF2_ITERS,
        hmac_hash_module=SHA256,
    )


async def initialize_encryption(master_secret: str, db) -> None:
    """
    Called once at startup via the FastAPI lifespan.

    Reads device_salt and data_key from the encryption_config table,
    creating them on first boot. After this coroutine completes,
    encrypt() and decrypt() are available for all subsequent requests.

    The master_secret and KEK are not retained in memory after the function
    returns (best-effort in Python — GC may not immediate collect them).
    """
    global _DATA_KEY

    from sqlalchemy import select
    from core.database import EncryptionConfig

    # ── 1. Load or generate device salt ─────────────────────────────────────
    result = await db.execute(
        select(EncryptionConfig).where(EncryptionConfig.key == "device_salt")
    )
    salt_row = result.scalar_one_or_none()

    if salt_row is None:
        device_salt = get_random_bytes(32)
        db.add(EncryptionConfig(key="device_salt", value=device_salt))
        await db.flush()
        log.info("First boot: generated device salt")
    else:
        device_salt = salt_row.value

    # ── 2. Derive KEK (CPU-bound — run off the event loop) ───────────────────
    loop = asyncio.get_running_loop()
    kek: bytes = await loop.run_in_executor(
        None, _derive_kek, master_secret, device_salt
    )

    # ── 3. Load or generate DATA_KEY ─────────────────────────────────────────
    result = await db.execute(
        select(EncryptionConfig).where(EncryptionConfig.key == "data_key")
    )
    key_row = result.scalar_one_or_none()

    if key_row is None:
        _DATA_KEY = get_random_bytes(32)
        wrapped = _aes_encrypt(_DATA_KEY, kek)
        db.add(EncryptionConfig(key="data_key", value=wrapped))
        log.info("First boot: generated and wrapped DATA_KEY")
    else:
        try:
            _DATA_KEY = _aes_decrypt(key_row.value, kek)
            log.info("DATA_KEY loaded from database")
        except Exception:
            log.critical(
                "Failed to unwrap DATA_KEY — wrong MASTER_SECRET or corrupted key row"
            )
            raise RuntimeError(
                "Encryption key decryption failed. Verify MASTER_SECRET env var."
            )

    await db.commit()

    # Scrub KEK (best-effort — CPython GC will collect it, but not guaranteed)
    kek = b"\x00" * len(kek)
    del kek


# ── Public encrypt/decrypt (called after initialize_encryption) ──────────────

def encrypt(plaintext: bytes) -> bytes:
    """Encrypt bytes with DATA_KEY. Raises if called before initialization."""
    if _DATA_KEY is None:
        raise RuntimeError("Encryption not initialised — call initialize_encryption() at startup")
    return _aes_encrypt(plaintext, _DATA_KEY)


def decrypt(blob: bytes) -> bytes:
    """Decrypt bytes with DATA_KEY."""
    if _DATA_KEY is None:
        raise RuntimeError("Encryption not initialised")
    return _aes_decrypt(blob, _DATA_KEY)


def encrypt_json(obj: dict | list) -> bytes:
    import json
    return encrypt(json.dumps(obj, separators=(",", ":")).encode("utf-8"))


def decrypt_json(blob: bytes) -> dict | list:
    import json
    return json.loads(decrypt(blob).decode("utf-8"))


# ── MASTER_SECRET rotation ───────────────────────────────────────────────────

async def rotate_master_secret(old_master_secret: str, new_master_secret: str, db) -> None:
    """
    Re-wraps the stored DATA_KEY under a new MASTER_SECRET. DATA_KEY itself
    never changes, so every row already encrypted under it — student
    configs, transcripts, voice profiles, everything — stays valid with
    zero rewriting. Only the one encryption_config row holding the wrapped
    DATA_KEY is touched.

    This is the crypto half only. It does not read or write .env/the
    deployment's secrets store, and it does not affect any already-running
    process (which keeps its in-memory DATA_KEY and keeps serving requests
    on the old KEK derivation until it next restarts). The operator is
    responsible for updating MASTER_SECRET and restarting afterward — see
    scripts/rotate_master_secret.py, the CLI wrapper meant to actually be
    run, and docs/INCIDENT_RESPONSE.md's rotation procedure for the full
    sequence including that step.

    Raises ValueError if there's nothing to rotate yet, or if
    old_master_secret does not actually unwrap the stored DATA_KEY (wrong
    secret, or it's actually the new one) — aborts without writing anything
    in either case. Raises RuntimeError (also without writing) if the
    freshly re-wrapped blob fails its own round-trip check, which should
    never happen and would indicate a bug in this function rather than bad
    input.
    """
    from sqlalchemy import select
    from core.database import EncryptionConfig

    result = await db.execute(select(EncryptionConfig).where(EncryptionConfig.key == "device_salt"))
    salt_row = result.scalar_one_or_none()
    if salt_row is None:
        raise ValueError(
            "No device_salt found in encryption_config — nothing has been "
            "encrypted yet on this deployment, so there's nothing to rotate."
        )
    device_salt = salt_row.value

    result = await db.execute(select(EncryptionConfig).where(EncryptionConfig.key == "data_key"))
    key_row = result.scalar_one_or_none()
    if key_row is None:
        raise ValueError(
            "No data_key found in encryption_config — nothing has been "
            "encrypted yet on this deployment, so there's nothing to rotate."
        )

    old_kek = _derive_kek(old_master_secret, device_salt)
    try:
        data_key = _aes_decrypt(key_row.value, old_kek)
    except Exception as exc:
        raise ValueError(
            "Could not unwrap the stored DATA_KEY with the supplied OLD "
            "master secret. Check it's actually the value currently set as "
            "MASTER_SECRET — not the new one, and not a typo."
        ) from exc
    finally:
        old_kek = b"\x00" * len(old_kek)  # best-effort — see initialize_encryption's identical caveat

    new_kek = _derive_kek(new_master_secret, device_salt)
    try:
        rewrapped = _aes_encrypt(data_key, new_kek)
        # Round-trip verify BEFORE committing: decrypt what we're about to
        # store and confirm it's byte-identical to the DATA_KEY we started
        # with, so a bug here fails loudly rather than silently writing a
        # wrapper that decrypts to the wrong thing (or nothing).
        if _aes_decrypt(rewrapped, new_kek) != data_key:
            raise RuntimeError(
                "Round-trip verification failed after re-wrapping — refusing "
                "to write. No change was made; the old wrapping is still in "
                "place and the deployment is unaffected."
            )
    finally:
        new_kek = b"\x00" * len(new_kek)
        data_key = b"\x00" * len(data_key)

    key_row.value = rewrapped
    await db.commit()
    log.info("MASTER_SECRET rotation: DATA_KEY re-wrapped successfully")
