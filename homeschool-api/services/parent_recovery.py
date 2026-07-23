"""
The "something you know" leg of the parent account-recovery scheme
(core/database.py's ParentRecoveryCode/ParentRecoveryPin, core/
credential_hash.py) — two mutually exclusive shapes a parent chooses
between at enrollment:

- **Recovery PIN** (favored/default) — short, parent-CHOSEN, memorable,
  same strength floor as CHILD_PIN/DEMO_PIN/SANDBOX_PIN
  (core/pin_policy.py's pin_is_strong()). Easiest to actually remember,
  which is the whole point — a secret nobody can recall when they need it
  isn't a usable recovery factor. Still meant to be written down as a
  backup too (the frontend's enrollment flow prompts for this), since
  "memorable" isn't the same guarantee as "will actually be remembered
  six months later."
- **Recovery code** (alternative) — longer, machine-generated, higher
  entropy, for a parent who'd rather have a stronger secret and doesn't
  mind storing it in a password manager or writing it down.

Enrolling one clears the other — see ParentRecoveryPin's own docstring for
why. Both are hashed, never reversibly encrypted, since neither ever needs
to be read back in plaintext once enrolled — deliberately independent of
both PARENT_PASSWORD and CHILD_PIN so a leak of one doesn't expose the
others.

routers/recovery.py orchestrates the actual "which factors did the parent
prove, is that >= 2" decision (it needs to call this module AND
services/mfa_service.py's TOTP/WebAuthn verification) — this module stays
scoped to the recovery secret itself, same separation core/
parent_lockout.py and core/parent_credential.py keep from each other.
"""
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from core.credential_hash import hash_secret, verify_secret
from core.database import ParentRecoveryCode, ParentRecoveryPin
from core.pin_policy import pin_is_strong

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


# ── Recovery code (machine-generated, longer) ────────────────────────────────

async def has_recovery_code(db: AsyncSession) -> bool:
    return await db.get(ParentRecoveryCode, _KEY) is not None


async def enroll_recovery_code(db: AsyncSession) -> str:
    """Generates a brand new code, replacing any prior one (only one can
    ever be valid at a time — same "re-enrolling invalidates the old one"
    contract as TOTP), and clears any enrolled recovery PIN — the two are
    mutually exclusive, a fresh choice each time either is (re-)enrolled.
    Returns the plaintext exactly once; only the hash persists after this
    call returns."""
    code = _generate_code()
    digest, salt = hash_secret(code)
    row = await db.get(ParentRecoveryCode, _KEY)
    if row is None:
        db.add(ParentRecoveryCode(key=_KEY, hash=digest, salt=salt))
    else:
        row.hash = digest
        row.salt = salt
    pin_row = await db.get(ParentRecoveryPin, _KEY)
    if pin_row is not None:
        await db.delete(pin_row)
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


# ── Recovery PIN (parent-chosen, memorable, favored) ─────────────────────────

async def has_recovery_pin(db: AsyncSession) -> bool:
    return await db.get(ParentRecoveryPin, _KEY) is not None


async def enroll_recovery_pin(db: AsyncSession, pin: str) -> None:
    """Raises ValueError for a PIN that doesn't clear pin_is_strong()'s bar
    — same floor as CHILD_PIN/DEMO_PIN/SANDBOX_PIN, not a separate, looser
    rule set just because this one's easier to guess-and-check against
    (routers/mfa.py's own rate limiting/lockout still applies, but the PIN
    itself shouldn't be the weak link). Clears any enrolled recovery code
    — mutually exclusive, same reasoning as enroll_recovery_code above."""
    if not pin_is_strong(pin):
        raise ValueError(
            "Recovery PIN must be 6+ digits and not an easily-guessable pattern — "
            "no sequential run (123456, 654321), repeated block (111111, 123123, 121212), "
            "or palindrome (669966). Repeated digits are fine otherwise, e.g. 602656 is a good PIN"
        )
    digest, salt = hash_secret(pin)
    row = await db.get(ParentRecoveryPin, _KEY)
    if row is None:
        db.add(ParentRecoveryPin(key=_KEY, hash=digest, salt=salt))
    else:
        row.hash = digest
        row.salt = salt
    code_row = await db.get(ParentRecoveryCode, _KEY)
    if code_row is not None:
        await db.delete(code_row)
    await db.commit()


async def revoke_recovery_pin(db: AsyncSession) -> bool:
    row = await db.get(ParentRecoveryPin, _KEY)
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def verify_recovery_pin(db: AsyncSession, submitted: str) -> bool:
    if not submitted:
        return False
    row = await db.get(ParentRecoveryPin, _KEY)
    if row is None:
        return False
    return verify_secret(submitted.strip(), row.hash, row.salt)


# ── Unified status (routers/mfa.py, routers/recovery.py) ────────────────────

async def recovery_secret_kind(db: AsyncSession) -> str | None:
    """Which shape (if either) is currently enrolled — "pin", "code", or
    None. At most one is ever true at a time (see enroll_* above); if
    somehow both existed (shouldn't happen), PIN wins as the actively-
    favored option rather than raising."""
    if await has_recovery_pin(db):
        return "pin"
    if await has_recovery_code(db):
        return "code"
    return None
