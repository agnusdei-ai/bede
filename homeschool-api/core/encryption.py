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
