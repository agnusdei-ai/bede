"""
One-way hashing for verify-only secrets — the parent password override
(core/parent_credential.py) and the recovery code (services/
parent_recovery.py). Unlike every other secret in this app, these never
need to be read back in plaintext, only compared against — so a proper
one-way KDF is a strictly stronger property than this app's usual
reversible AES-256-GCM encrypt_json/decrypt_json (core/encryption.py),
which exists specifically because things like the TOTP secret DO need to
be decrypted back to plaintext to compute a code.

Reuses the exact PBKDF2-HMAC-SHA256 primitive core/encryption.py's
_derive_kek already uses (pycryptodome's hmac_hash_module — measured ~42x
faster than a Python prf= callback, see that module's own comment) rather
than stdlib hashlib.pbkdf2_hmac, for the same performance reason and to
avoid a second KDF implementation in the codebase.
"""
import hmac

from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Random import get_random_bytes

# Lower than core/encryption.py's 600,000 (that one derives a long-lived
# key once per process boot; this one runs on every login/recovery attempt
# and every credential change — still well above any realistic online
# brute-force rate this app's own rate limiting/lockout already caps).
_PBKDF2_ITERS = 200_000
_SALT_BYTES = 16
_KEY_LEN = 32


def hash_secret(secret: str) -> tuple[bytes, bytes]:
    """Returns (hash, salt) — both to be stored. Never raises on empty
    input; callers are responsible for their own minimum-length checks
    (core/config.py's MIN_PASSWORD_LENGTH, services/parent_recovery.py's
    own code length) before this is ever called."""
    salt = get_random_bytes(_SALT_BYTES)
    digest = PBKDF2(secret.encode("utf-8"), salt, dkLen=_KEY_LEN, count=_PBKDF2_ITERS, hmac_hash_module=SHA256)
    return digest, salt


def verify_secret(secret: str, stored_hash: bytes, salt: bytes) -> bool:
    """Constant-time compare against a hash produced by hash_secret()."""
    candidate = PBKDF2(secret.encode("utf-8"), salt, dkLen=_KEY_LEN, count=_PBKDF2_ITERS, hmac_hash_module=SHA256)
    return hmac.compare_digest(candidate, stored_hash)
