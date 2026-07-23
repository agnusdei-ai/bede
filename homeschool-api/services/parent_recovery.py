"""
Recovery code — the "PIN" leg of the parent account-recovery scheme
(core/database.py's ParentRecoveryCode / core/credential_hash.py). A
single, high-entropy, randomly-generated backup credential, shown to the
parent exactly once at enrollment, deliberately independent of both
PARENT_PASSWORD and CHILD_PIN so a leak of one doesn't expose the other.

routers/recovery.py orchestrates the actual "which factors did the parent
prove, is that >= 2" decision (it needs to call this module AND
services/mfa_service.py's TOTP/WebAuthn verification) — this module stays
scoped to the recovery code itself, same separation core/parent_lockout.py
and core/parent_credential.py keep from each other.
"""
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from core.credential_hash import hash_secret, verify_secret
from core.database import ParentRecoveryCode

_KEY = "recovery"

# Excludes visually ambiguous characters (0/O, 1/I/L) — this gets written
# down or stored in a password manager, not memorized, so readability under
# handwriting/OCR matters more than a couple of extra bits of entropy.
_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_GROUP_LENGTH = 5
_NUM_GROUPS = 4  # 20 chars from a 32-symbol alphabet ~= 100 bits of entropy


def _generate_code() -> str:
    groups = [
        "".join(secrets.choice(_ALPHABET) for _ in range(_GROUP_LENGTH))
        for _ in range(_NUM_GROUPS)
    ]
    return "-".join(groups)


async def has_recovery_code(db: AsyncSession) -> bool:
    return await db.get(ParentRecoveryCode, _KEY) is not None


async def enroll_recovery_code(db: AsyncSession) -> str:
    """Generates a brand new code, replacing any prior one (only one can
    ever be valid at a time — same "re-enrolling invalidates the old one"
    contract as TOTP). Returns the plaintext exactly once; only the hash
    persists after this call returns."""
    code = _generate_code()
    digest, salt = hash_secret(code)
    row = await db.get(ParentRecoveryCode, _KEY)
    if row is None:
        db.add(ParentRecoveryCode(key=_KEY, hash=digest, salt=salt))
    else:
        row.hash = digest
        row.salt = salt
    await db.commit()
    return code


async def revoke_recovery_code(db: AsyncSession) -> bool:
    row = await db.get(ParentRecoveryCode, _KEY)
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def verify_recovery_code(db: AsyncSession, submitted: str) -> bool:
    if not submitted:
        return False
    row = await db.get(ParentRecoveryCode, _KEY)
    if row is None:
        return False
    return verify_secret(submitted.strip().upper(), row.hash, row.salt)
