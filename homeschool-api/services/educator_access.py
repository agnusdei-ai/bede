"""Classical educator identities and explicitly parent-approved roster access.

Single operator-owned Bede appliance only. No cross-family entitlement model
or automatic Portal/Locuto data sharing. Teacher can never grant themselves
a learner, change the system, or authenticate without TOTP and password.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

import pyotp
from fastapi import HTTPException
from sqlalchemy import delete, select

from core import student_keys
from core.credential_hash import hash_secret, verify_secret
from core.database import ClassicalEducator, EducatorRosterAssignment, StudentConfig
from core.encryption import aad_for, decrypt_json, encrypt_json

MAX_CLASS_ROSTER = 90
LOCUTO_POD_MIN = 3
LOCUTO_POD_MAX = 10
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_username(value: str) -> str:
    name = value.strip().lower()
    if not _USERNAME.fullmatch(name):
        raise ValueError("Use 3–64 lowercase letters, digits, dots, hyphens or underscores")
    return name


def _otp_aad(identifier: str) -> bytes:
    return aad_for("classical_educators", "totp_enc", identifier)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt


async def provision_educator(db, username: str, password: str) -> dict:
    name = normalize_username(username)
    if len(password) < 14 or len(password) > 256:
        raise ValueError("Use an educator password of 14 to 256 characters")
    existing = (await db.execute(
        select(ClassicalEducator.id).where(ClassicalEducator.username == name)
    )).scalar_one_or_none()
    if existing:
        raise ValueError("That educator username is already enrolled")
    identifier = str(uuid.uuid4())
    secret = pyotp.random_base32()
    digest, salt = hash_secret(password)
    db.add(ClassicalEducator(
        id=identifier, username=name, password_hash=digest,
        password_salt=salt,
        totp_enc=encrypt_json({"secret": secret}, _otp_aad(identifier)),
    ))
    await db.commit()
    return {
        "id": identifier, "username": name,
        # Show exactly once to the elevated parent for secure handoff.
        # NEVER store plaintext or include in audit logs.
        "totp_provisioning_uri": pyotp.TOTP(secret).provisioning_uri(
            name=name, issuer_name="Bede Classical Educator",
        ),
        "totp_secret": secret,
        "security_notice": "Share directly with this instructor; do not put a login secret in a class group.",
    }


async def authenticate_educator(db, username: str, password: str, totp: str) -> dict | None:
    try:
        name = normalize_username(username)
    except ValueError:
        return None
    row = (await db.execute(
        select(ClassicalEducator)
        .where(ClassicalEducator.username == name)
        .with_for_update()
    )).scalar_one_or_none()
    if row is None or not row.enabled:
        return None
    now = _now()
    if _aware(row.locked_until) and now < _aware(row.locked_until):
        return None
    secret = decrypt_json(row.totp_enc, _otp_aad(row.id))["secret"]
    # Verify each possible TOTP time-step explicitly to prevent replay
    # even with valid_window=1; UTC and last step persisted in DB.
    current_step = int(now.timestamp() // 30)
    accepted = None
    if isinstance(totp, str) and len(totp) == 6 and totp.isascii() and totp.isdigit():
        for step in (current_step - 1, current_step, current_step + 1):
            if (row.last_totp_step is None or step > row.last_totp_step) and (
                pyotp.TOTP(secret).verify(totp, for_time=step * 30, valid_window=0)
            ):
                accepted = step
                break
    if not verify_secret(password, row.password_hash, row.password_salt) or accepted is None:
        row.failures += 1
        if row.failures >= 5:
            row.locked_until = now + timedelta(minutes=15)
            row.failures = 0
        await db.commit()
        return None
    row.failures = 0
    row.locked_until = None
    row.last_totp_step = accepted
    await db.commit()
    return {"role": "educator", "sub": row.id, "ev": row.credential_version}


async def live_educator(db, token: dict) -> ClassicalEducator:
    if token.get("role") != "educator" or not token.get("sub"):
        raise HTTPException(status_code=403, detail="Educator access required")
    row = await db.get(ClassicalEducator, token["sub"])
    if (row is None or not row.enabled
            or token.get("ev") != row.credential_version):
        raise HTTPException(status_code=401, detail="Educator session revoked; sign in again")
    return row


async def require_assignment(db, token: dict, student_name: str) -> None:
    account = await live_educator(db, token)
    link = await db.get(EducatorRosterAssignment, (account.id, student_name))
    if link is None:
        # Same response for absent and unassigned learners: no enumeration.
        raise HTTPException(status_code=404, detail="Learner not assigned")


async def roster_configs(db, token: dict) -> list:
    from models.schemas import SessionConfig
    account = await live_educator(db, token)
    rows = (await db.execute(
        select(StudentConfig).join(
            EducatorRosterAssignment,
            EducatorRosterAssignment.student_name == StudentConfig.student_name,
        ).where(EducatorRosterAssignment.educator_id == account.id)
        .order_by(StudentConfig.student_name)
    )).scalars().all()
    return [
        SessionConfig(**decrypt_json(
            row.config_enc,
            _config_aad(row.student_name),
            await student_keys.get_existing(db, row.student_name),
        )) for row in rows
    ]


def _config_aad(student_name: str) -> bytes:
    from core.encryption import student_aad
    return student_aad("student_configs", "config_enc", student_name)


async def assign_class_roster(db, educator_id: str, configs: list) -> dict:
    """Elevated parent's complete replacement of one teacher's class roster.

    New learner configurations are created. Existing configuration and
    curriculum settings are NEVER rewritten by an import: data belongs to
    the operator/parent. A preexisting name is only assigned, not altered.
    """
    account = await db.get(ClassicalEducator, educator_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Educator not found")
    names = [c.student_name for c in configs]
    if not 1 <= len(names) <= MAX_CLASS_ROSTER:
        raise ValueError(f"Class roster must have 1–{MAX_CLASS_ROSTER} students")
    if len(set(names)) != len(names):
        raise ValueError("Duplicate learner names in the roster")
    from core import license_state
    limit = license_state.effective_info()
    existing = set((await db.execute(select(StudentConfig.student_name))).scalars().all())
    if limit is not None and len(existing | set(names)) > limit.seats:
        raise HTTPException(status_code=403, detail="Student seat limit reached")
    # Resolve keys BEFORE adding config rows/roster links. Student key
    # creation currently commits its own transaction, so no roster
    # modifications may be pending when this happens.
    for config in configs:
        if config.student_name not in existing:
            await student_keys.get_or_create(db, config.student_name)
    await db.execute(delete(EducatorRosterAssignment).where(
        EducatorRosterAssignment.educator_id == educator_id,
    ))
    for config in configs:
        if config.student_name not in existing:
            key = await student_keys.get_existing(db, config.student_name)
            db.add(StudentConfig(
                student_name=config.student_name,
                config_enc=encrypt_json(
                    config.model_dump(), _config_aad(config.student_name), key,
                ),
            ))
        db.add(EducatorRosterAssignment(
            educator_id=educator_id, student_name=config.student_name,
        ))
    await db.commit()
    return {
        "educator_id": educator_id, "learner_count": len(names),
        "new_learner_count": len(set(names) - existing),
        "messaging": locuto_pod_plan(names),
    }


def locuto_pod_plan(names: list[str]) -> dict:
    """Local *capacity-only* grouping, never a Locuto API call.

    Locuto v1: min 3 and max 10 PERSONS per Pod, including instructor.
    Its group-thread behavior has not been cleared for release.
    No student name, learning record or messaging credentials go to Locuto.
    """
    n = len(names)
    if n < 2:
        groups = []
    else:
        sizes = []
        remaining = n
        while remaining:
            take = min(9, remaining)
            if remaining - take == 1:
                take -= 1
            sizes.append(take)
            remaining -= take
        groups = [{"learner_count": size, "member_count_including_educator": size + 1}
                  for size in sizes]
    return {
        "provider": "Locuto", "integration_status": "planning_only_not_connected",
        "active_group_messages_enabled": False,
        "minimum_members": LOCUTO_POD_MIN,
        "maximum_members": LOCUTO_POD_MAX,
        "groups": groups,
        "requires_opt_in_and_separate_verified_membership": True,
        "roster_or_student_data_transferred": False,
    }


async def disable_educator(db, educator_id: str) -> None:
    row = await db.get(ClassicalEducator, educator_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Educator not found")
    row.enabled = False
    row.credential_version += 1
    await db.commit()
