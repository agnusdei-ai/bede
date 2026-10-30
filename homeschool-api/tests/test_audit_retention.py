"""
COPPA readiness C-18 / F5: audit-log retention and IP minimisation.

core/audit.py's purge_audit_log():
  * deletes audit rows older than settings.audit_retention_days (365 by
    default, a placeholder pending an owner decision), and
  * after settings.audit_ip_truncate_days (30 by default) replaces the stored
    IP inside the encrypted payload with a keyed pseudonym and clears the
    user-agent, keeping the event itself for security review.

The IP lives inside event_enc, so minimisation must decrypt, change, and
re-encrypt under the same AAD. There is no hash chain in this module to
preserve; the tests assert that every other field survives unchanged.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from core import audit
from core.audit import AuditEvent, purge_audit_log
from core.config import settings
from core.database import AuditLog
from core.encryption import decrypt, encrypt

from core.audit import _AUDIT_AAD  # noqa: E402  (same AAD the writer uses)

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
REAL_IP = "192.168.1.44"
REAL_UA = "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)"


async def _insert(db, *, created_at, ip=REAL_IP, ua=REAL_UA, event=AuditEvent.AUTH_SUCCESS, detail="d"):
    entry = {
        "ts": created_at.replace(microsecond=0).isoformat(),
        "event": event,
        "ip": ip,
        "ua": ua,
        "success": True,
        "role": "parent",
        "detail": detail,
    }
    db.add(AuditLog(
        created_at=created_at,
        event_enc=encrypt(json.dumps(entry, separators=(",", ":")).encode(), _AUDIT_AAD),
    ))
    await db.commit()


async def _rows(db):
    result = await db.execute(select(AuditLog).order_by(AuditLog.id))
    out = []
    for row in result.scalars().all():
        out.append((row.created_at, json.loads(decrypt(row.event_enc, _AUDIT_AAD))))
    return out


def _as_aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_rows_past_retention_are_deleted_and_newer_rows_kept(demo_db, monkeypatch):
    monkeypatch.setattr(settings, "audit_retention_days", 365)
    async with demo_db() as db:
        await _insert(db, created_at=NOW - timedelta(days=400), detail="too old")
        await _insert(db, created_at=NOW - timedelta(days=100), detail="recent")

    result = await purge_audit_log(now=NOW)

    assert result["deleted"] == 1
    async with demo_db() as db:
        details = [entry["detail"] for _, entry in await _rows(db)]
    assert details == ["recent"]


@pytest.mark.asyncio
async def test_ip_is_pseudonymised_after_the_truncate_window_and_everything_else_survives(demo_db, monkeypatch):
    monkeypatch.setattr(settings, "audit_ip_truncate_days", 30)
    async with demo_db() as db:
        await _insert(db, created_at=NOW - timedelta(days=45), detail="login from tablet", event=AuditEvent.AUTH_FAILURE)

    result = await purge_audit_log(now=NOW)

    assert result["minimised"] == 1
    async with demo_db() as db:
        (_, entry), = await _rows(db)
    assert entry["ip"] != REAL_IP
    assert REAL_IP not in str(entry)
    assert entry["ip"].startswith("ip-pseudonym:")
    assert entry["ua"] == ""
    assert entry["event"] == AuditEvent.AUTH_FAILURE
    assert entry["detail"] == "login from tablet"
    assert entry["success"] is True
    assert entry["role"] == "parent"


@pytest.mark.asyncio
async def test_a_row_inside_the_truncate_window_keeps_its_live_ip(demo_db, monkeypatch):
    """Security review needs the real address for the first month, so a
    recent row must not be touched by minimisation."""
    monkeypatch.setattr(settings, "audit_ip_truncate_days", 30)
    async with demo_db() as db:
        await _insert(db, created_at=NOW - timedelta(days=5))

    result = await purge_audit_log(now=NOW)

    assert result["minimised"] == 0
    async with demo_db() as db:
        (_, entry), = await _rows(db)
    assert entry["ip"] == REAL_IP
    assert entry["ua"] == REAL_UA


@pytest.mark.asyncio
async def test_minimisation_is_idempotent(demo_db, monkeypatch):
    monkeypatch.setattr(settings, "audit_ip_truncate_days", 30)
    async with demo_db() as db:
        await _insert(db, created_at=NOW - timedelta(days=60))

    first = await purge_audit_log(now=NOW)
    second = await purge_audit_log(now=NOW)

    assert first["minimised"] == 1
    assert second["minimised"] == 0


@pytest.mark.asyncio
async def test_an_unknown_ip_is_left_alone(demo_db, monkeypatch):
    monkeypatch.setattr(settings, "audit_ip_truncate_days", 30)
    async with demo_db() as db:
        await _insert(db, created_at=NOW - timedelta(days=60), ip="unknown", ua="")

    result = await purge_audit_log(now=NOW)

    assert result["minimised"] == 0
    async with demo_db() as db:
        (_, entry), = await _rows(db)
    assert entry["ip"] == "unknown"


def test_pseudonym_is_stable_keyed_and_not_the_address(monkeypatch):
    first = audit.ip_pseudonym(REAL_IP)
    assert first == audit.ip_pseudonym(REAL_IP)
    assert REAL_IP not in first
    assert audit.ip_pseudonym("10.0.0.9") != first
    monkeypatch.setattr(settings, "secret_key", settings.secret_key + "-rotated")
    assert audit.ip_pseudonym(REAL_IP) != first


def test_the_periodic_task_invokes_the_purge():
    """Invocation guard: a purge nothing calls protects nothing. main.py's
    periodic data-purge loop must reach purge_audit_log."""
    import ast
    import pathlib

    main_src = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(main_src)
    loop = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_periodic_data_purge"
    )
    called = {
        (n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", None))
        for n in ast.walk(loop) if isinstance(n, ast.Call)
    }
    assert "purge_audit_log" in called


def test_retention_defaults_are_the_documented_placeholders():
    from core.config import Settings
    fields = Settings.model_fields
    assert fields["audit_retention_days"].default == 365
    assert fields["audit_ip_truncate_days"].default == 30
