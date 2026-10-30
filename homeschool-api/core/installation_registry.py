"""
Startup side of the installation authorization flow
(docs/INSTALLATION_AUTHORIZATION_FLOW.md): importing a verified school receipt
and registering the permitted installation. Everything here is idempotent, so
running it on every boot is the design, and none of it can block startup or
unlock anything the receipt does not already permit.

SCHOOL IMPORT. A `verified` school receipt is copied into
`pilot_campus_data_authorizations` for the campus whose id equals the
receipt's location id (the only link the pilot tables have between a signed
location and a campus row). The row's `authorizer_ref` is the receipt id, which
is the idempotency key: a receipt already imported (even if the school later
withdrew at runtime) is never imported again, and an unrevoked authorization
for the current notice is never duplicated. An invalid, pending, withdrawn or
incomplete receipt imports nothing. If no campus row exists the import is
skipped and logged: this module does not invent campuses.

INVENTORY. A `verified` receipt gets one `installation_inventory` row per
(install id, receipt id). Registration with the license server reuses the
existing `/v1/activate` exchange in core/license_heartbeat.py (wire format
unchanged) and records the outcome. With LICENSE_SERVER_URL unset (the
default) the installation works offline and the local row stands alone
(`offline`).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from core import installation_receipt
from core.config import settings

log = logging.getLogger("bede.installation")

OUTCOMES = ("pending", "offline", "registered", "cap_reached", "unreachable", "revoked", "no_license_key")


def _accepted_at(st) -> datetime:
    raw = (st.accepted_at or "").replace("Z", "+00:00")
    try:
        at = datetime.fromisoformat(raw)
        if at.tzinfo is not None:
            return at.astimezone(timezone.utc)
    except ValueError:
        pass
    return datetime.now(timezone.utc)


async def import_school_receipt(db) -> str:
    """Import the current receipt if it is a verified school receipt.

    Returns one of: imported, already_imported, already_authorized,
    not_school_verified, campus_absent."""
    from core import school_authorization as sa
    from core.audit import AuditEvent, log_event
    from core.database import PilotCampus
    from core.database import PilotCampusDataAuthorization as A
    from core.encryption import encrypt_json

    st = installation_receipt.current()
    if not st.school_verified:
        return "not_school_verified"
    location = (st.location_id or "").strip()
    campus = await db.get(PilotCampus, location) if location else None
    if campus is None:
        log.warning("Verified school receipt %s: no pilot campus with id %s yet; nothing imported",
                    st.receipt_id, location)
        return "campus_absent"

    # Keyed by receipt id: any row it ever produced (revoked or not) counts.
    prior = (await db.execute(
        select(A.id).where(A.campus_id == campus.id, A.authorizer_ref == st.receipt_id,
                           A.notice_hash == sa.notice_hash()).limit(1)
    )).first()
    if prior is not None:
        return "already_imported"
    if await sa.is_authorized(db, campus.id):
        return "already_authorized"

    name = (st.last_record.get("authorizer") or {}).get("name", "").strip()
    row_id = str(uuid.uuid4())
    db.add(A(
        id=row_id, campus_id=campus.id, authorizer_role=st.authorizer_capacity,
        authorizer_ref=st.receipt_id,
        authorizer_name_enc=encrypt_json({"name": name}, sa._name_aad(campus.id, row_id)),
        notice_hash=sa.notice_hash(), scope=sa.SCOPE, granted_at=_accepted_at(st),
    ))
    await db.commit()
    await log_event(
        AuditEvent.INSTALLATION_SCHOOL_IMPORTED, role=None, success=True,
        detail=f"campus={campus.id} receipt={st.receipt_id} authorizer_role={st.authorizer_capacity} "
               f"notice={sa.notice_hash()[:12]}",
    )
    return "imported"


async def _outcome_for_license_server(db, install_id: str) -> str:
    from core import license_heartbeat

    if not license_heartbeat.enabled():
        return "offline"
    license_text = await license_heartbeat.current_license_text(db)
    if not license_text:
        return "no_license_key"
    spoke, report = await license_heartbeat.heartbeat_cycle(
        db, license_text=license_text, install_id=install_id, activate=True,
    )
    if not spoke:
        return "unreachable"
    if report is None:
        return "cap_reached"  # heartbeat_cycle's 409 path
    return "revoked" if report.status == "revoked" else "registered"


async def ensure_inventory_row(db, install_id: str) -> Optional[str]:
    """Create the (install id, receipt id) row if the receipt is verified.
    Returns the row id, or None when there is nothing to register."""
    from core.database import InstallationInventory as I

    st = installation_receipt.current()
    if not st.processing_enabled or not st.receipt_id:
        return None
    existing = (await db.execute(
        select(I).where(I.install_id == install_id, I.receipt_id == st.receipt_id)
    )).scalar_one_or_none()
    if existing is not None:
        return existing.id
    row = I(
        id=str(uuid.uuid4()), install_id=install_id, receipt_id=st.receipt_id, mode=st.mode,
        location_id=(st.location_id if st.mode == "school" else None),
        registered_at=datetime.now(timezone.utc),
        license_server_outcome="offline" if not _license_server_on() else "pending",
    )
    db.add(row)
    await db.commit()
    return row.id


def _license_server_on() -> bool:
    from core import license_heartbeat
    return license_heartbeat.enabled()


async def register_installation(session_factory) -> str:
    """Write the inventory row, then record the license-server outcome."""
    from core.audit import AuditEvent, log_event
    from core.database import InstallationInventory as I
    from core.encryption import get_or_create_install_id

    async with session_factory() as db:
        install_id = await get_or_create_install_id(db)
        row_id = await ensure_inventory_row(db, install_id)
    if row_id is None:
        return "not_registered"
    async with session_factory() as db:
        outcome = await _outcome_for_license_server(db, install_id)
    async with session_factory() as db:
        row = await db.get(I, row_id)
        if row is not None and row.license_server_outcome != outcome:
            row.license_server_outcome = outcome
            await db.commit()
    await log_event(
        AuditEvent.INSTALLATION_REGISTERED, role=None, success=True,
        detail=f"mode={installation_receipt.current().mode} outcome={outcome}",
    )
    return outcome


async def run_startup(session_factory) -> Optional[asyncio.Task]:
    """Boot-time work. Never raises and never waits on the network: the local
    steps run inline, the license-server leg runs as a background task."""
    try:
        async with session_factory() as db:
            result = await import_school_receipt(db)
        log.info("Installation receipt: school import %s", result)
    except Exception as exc:  # a failed import leaves processing off; it must not stop boot
        log.error("Installation receipt: school import failed (%s: %s); nothing imported",
                  type(exc).__name__, exc)
    try:
        from core.encryption import get_or_create_install_id

        async with session_factory() as db:
            install_id = await get_or_create_install_id(db)
            await ensure_inventory_row(db, install_id)
    except Exception as exc:
        log.error("Installation inventory row failed (%s: %s)", type(exc).__name__, exc)
        return None
    if not _license_server_on():
        return None
    return asyncio.create_task(_register_quietly(session_factory))


async def _register_quietly(session_factory) -> None:
    try:
        await register_installation(session_factory)
    except Exception as exc:
        log.warning("Installation registration failed (%s: %s)", type(exc).__name__, exc)
