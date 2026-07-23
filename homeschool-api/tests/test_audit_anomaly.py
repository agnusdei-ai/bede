"""
AIUC-1 control E009 (alerting on anomalous access patterns). Before this,
core/audit.py's encrypted log was write-only — durable, but nothing ever
watched the pattern of events landing in it. Covers the in-process
sliding-window watch (_check_anomaly) and log_event()'s integration with
it: crossing a threshold for a security-relevant event from one IP writes
an AuditEvent.ANOMALY_ALERT entry and (best-effort) emails the parent via
the same Resend path as the existing safeguarding distress alert.
"""
import asyncio
import itertools

import pytest
from sqlalchemy import event

import core.audit as audit_module
from core.audit import _check_anomaly, AuditEvent, log_event, read_audit_log
from core.database import AuditLog


@pytest.fixture(autouse=True)
def _reset_anomaly_state():
    """Module-level sliding-window state would otherwise leak between
    tests (and between test files, all sharing one process)."""
    audit_module._anomaly_windows.clear()
    audit_module._anomaly_last_alert.clear()
    yield
    audit_module._anomaly_windows.clear()
    audit_module._anomaly_last_alert.clear()


@pytest.fixture(autouse=True)
def _assign_audit_ids():
    """AuditLog.id is a plain BigInteger PK (a real sequence on Postgres in
    production) that SQLite's rowid-alias autoincrement doesn't apply to —
    the same quirk documented in test_student_deletion.py for a couple of
    other tables. log_event() never sets an id explicitly, so assign one
    here instead, scoped to this file's tests."""
    counter = itertools.count(1)

    def _assign(mapper, connection, target):
        if target.id is None:
            target.id = next(counter)

    event.listen(AuditLog, "before_insert", _assign)
    yield
    event.remove(AuditLog, "before_insert", _assign)


@pytest.fixture
def audit_tasks(monkeypatch):
    """Captures every asyncio.create_task() call made from inside
    core.audit so a test can await them before asserting — log_event()'s
    anomaly alert is deliberately fire-and-forget."""
    tasks = []
    orig_create_task = asyncio.create_task

    def _tracking(coro, *a, **kw):
        t = orig_create_task(coro, *a, **kw)
        tasks.append(t)
        return t

    monkeypatch.setattr(audit_module.asyncio, "create_task", _tracking)
    return tasks


# ── _check_anomaly unit tests (no DB) ────────────────────────────────────────


def test_check_anomaly_fires_exactly_at_threshold():
    for _ in range(4):
        assert _check_anomaly(AuditEvent.AUTH_FAILURE, "9.9.9.9") is None
    assert _check_anomaly(AuditEvent.AUTH_FAILURE, "9.9.9.9") == 5


def test_check_anomaly_single_occurrence_rule_fires_immediately():
    assert _check_anomaly(AuditEvent.SUSPICIOUS_REQUEST, "1.1.1.1") == 1


def test_check_anomaly_moderation_flagged_fires_at_three_not_one():
    """AIUC-1 B005's moderation classifier flags routine boundary-testing
    fairly often — 3 in 10 minutes, not 1, so a single flag doesn't page
    the parent for something the in-the-moment redirect already handled."""
    ip = "5.5.5.5"
    assert _check_anomaly(AuditEvent.MODERATION_FLAGGED, ip) is None
    assert _check_anomaly(AuditEvent.MODERATION_FLAGGED, ip) is None
    assert _check_anomaly(AuditEvent.MODERATION_FLAGGED, ip) == 3


def test_check_anomaly_tool_invoked_fires_at_forty_not_one():
    """Ordinary tool use (offer_socratic_hint, celebrate_discovery, etc.)
    is frequent and expected across a multi-hour session — only a
    sustained burst well above that, from one address, is worth a
    parent's attention."""
    ip = "6.6.6.6"
    for _ in range(39):
        assert _check_anomaly(AuditEvent.TOOL_INVOKED, ip) is None
    assert _check_anomaly(AuditEvent.TOOL_INVOKED, ip) == 40


def test_check_anomaly_adversarial_detected_fires_at_three_not_one():
    """Mirrors MODERATION_FLAGGED's reasoning: services/policy_engine.py's
    decide() logs this for jailbreak_intent/social_engineering too, which
    never block a turn on their own — a single hit is routine boundary-
    testing, a sustained pattern from one address is what's worth a
    parent's attention."""
    ip = "8.8.4.4"
    assert _check_anomaly(AuditEvent.ADVERSARIAL_DETECTED, ip) is None
    assert _check_anomaly(AuditEvent.ADVERSARIAL_DETECTED, ip) is None
    assert _check_anomaly(AuditEvent.ADVERSARIAL_DETECTED, ip) == 3


def test_check_anomaly_tool_call_suppressed_fires_immediately():
    """A single trip of stream_tutor_response's per-turn tool-call cap is
    already anomalous by construction (see _MAX_TOOL_CALLS_PER_TURN) —
    same immediate-alert shape as SUSPICIOUS_REQUEST."""
    assert _check_anomaly(AuditEvent.TOOL_CALL_SUPPRESSED, "7.7.7.7") == 1


def test_check_anomaly_ignores_events_with_no_rule():
    for _ in range(50):
        assert _check_anomaly(AuditEvent.SESSION_START, "9.9.9.9") is None


def test_check_anomaly_ignores_unknown_ip():
    for _ in range(50):
        assert _check_anomaly(AuditEvent.AUTH_FAILURE, "unknown") is None


def test_check_anomaly_tracks_ips_independently():
    for _ in range(4):
        _check_anomaly(AuditEvent.AUTH_FAILURE, "1.1.1.1")
    # A different IP starts its own fresh window, not sharing 1.1.1.1's count.
    assert _check_anomaly(AuditEvent.AUTH_FAILURE, "2.2.2.2") is None


def test_check_anomaly_cooldown_suppresses_repeat_alert():
    for _ in range(4):
        _check_anomaly(AuditEvent.AUTH_FAILURE, "3.3.3.3")
    assert _check_anomaly(AuditEvent.AUTH_FAILURE, "3.3.3.3") == 5
    # Still within the 30-minute cooldown — must not fire again even though
    # the pattern continues.
    for _ in range(10):
        assert _check_anomaly(AuditEvent.AUTH_FAILURE, "3.3.3.3") is None


# ── log_event() integration (real encrypted DB round-trip) ─────────────────


@pytest.mark.asyncio
async def test_log_event_fires_alert_after_threshold_auth_failures(demo_db, audit_tasks, monkeypatch):
    sent = {}

    async def fake_send(event, ip, count, window_label="in the last 10 minutes"):
        sent["event"], sent["ip"], sent["count"] = event, ip, count
        return True

    monkeypatch.setattr("services.email_service.security_alert_configured", lambda: True)
    monkeypatch.setattr("services.email_service.send_security_alert", fake_send)

    for _ in range(5):
        await log_event(AuditEvent.AUTH_FAILURE, ip="10.0.0.5", success=False)
    await asyncio.gather(*audit_tasks)

    assert sent == {"event": AuditEvent.AUTH_FAILURE, "ip": "10.0.0.5", "count": 5}

    async with demo_db() as db:
        entries = await read_audit_log(db, limit=50)
    alert_entries = [e for e in entries if e.get("event") == AuditEvent.ANOMALY_ALERT]
    assert len(alert_entries) == 1
    assert "auth.failure x5 from 10.0.0.5" in alert_entries[0]["detail"]


@pytest.mark.asyncio
async def test_log_event_does_not_alert_below_threshold(demo_db, audit_tasks, monkeypatch):
    called = []
    monkeypatch.setattr("services.email_service.security_alert_configured", lambda: True)
    monkeypatch.setattr("services.email_service.send_security_alert", lambda *a, **kw: called.append(a))

    for _ in range(4):
        await log_event(AuditEvent.AUTH_FAILURE, ip="10.0.0.6", success=False)
    await asyncio.gather(*audit_tasks)

    assert called == []
    async with demo_db() as db:
        entries = await read_audit_log(db, limit=50)
    assert not any(e.get("event") == AuditEvent.ANOMALY_ALERT for e in entries)


@pytest.mark.asyncio
async def test_log_event_skips_email_when_not_configured_but_still_records_alert(demo_db, audit_tasks, monkeypatch):
    """Mirrors send_distress_alert's contract: an unconfigured PARENT_EMAIL/
    Resend must never block the underlying audit record from being written."""
    monkeypatch.setattr("services.email_service.security_alert_configured", lambda: False)

    for _ in range(5):
        await log_event(AuditEvent.AUTH_FAILURE, ip="10.0.0.7", success=False)
    await asyncio.gather(*audit_tasks)

    async with demo_db() as db:
        entries = await read_audit_log(db, limit=50)
    assert any(e.get("event") == AuditEvent.ANOMALY_ALERT for e in entries)


@pytest.mark.asyncio
async def test_anomaly_alert_recursion_does_not_trigger_itself(demo_db, audit_tasks, monkeypatch):
    """_fire_anomaly_alert calls log_event(ANOMALY_ALERT, ...) internally —
    ANOMALY_ALERT must not itself be a watched event, or this would recurse."""
    monkeypatch.setattr("services.email_service.security_alert_configured", lambda: False)

    for _ in range(5):
        await log_event(AuditEvent.AUTH_FAILURE, ip="10.0.0.8", success=False)
    await asyncio.gather(*audit_tasks)

    async with demo_db() as db:
        entries = await read_audit_log(db, limit=50)
    # Exactly one — if ANOMALY_ALERT were (incorrectly) a watched event
    # itself, log_event(ANOMALY_ALERT, ...) inside _fire_anomaly_alert
    # would recurse into another alert, and this would be >1.
    assert sum(1 for e in entries if e.get("event") == AuditEvent.ANOMALY_ALERT) == 1
