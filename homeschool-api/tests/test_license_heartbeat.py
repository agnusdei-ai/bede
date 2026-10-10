"""
core/license_heartbeat.py — the optional license-server heartbeat client,
and the server-tracked validity half of core/license_state.py.

The contract (spec D3, docs/PRODUCTION_SETUP.md#licensing): opting in via
LICENSE_SERVER_URL makes the server's answer outrank the signed payload's
nominal expiry in BOTH directions; opting out (the empty default) is
byte-for-byte today's fully-offline behavior — asserted at the httpx layer
itself, not just by inspecting our own call graph.
"""
import asyncio
import base64
import json
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from core import encryption, license_heartbeat, license_state, licensing
from core.config import settings
from core.database import EncryptionConfig, LicenseConfig


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign(key, *, licensee="Fam", tier="core", seats=6, expires=None):
    payload = {
        "id": str(uuid.uuid4()), "licensee": licensee, "tier": tier,
        "seats": seats, "issued": date.today().isoformat(),
        "expires": expires.isoformat() if expires else None,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = eddsa.new(key, "rfc8032").sign(payload_bytes)
    return f"{_b64url(payload_bytes)}.{_b64url(signature)}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _report(key_text, *, status="active", valid_until=None, reported_at=None,
            activations_used=1, max_activations=2):
    """A ServerReport bound to `key_text`'s digest — what a real exchange
    produces for the key it presented."""
    return license_state.ServerReport(
        status=status,
        valid_until=valid_until,
        reported_at=reported_at or _now(),
        key_digest=license_state._digest_text(key_text),
        activations_used=activations_used,
        max_activations=max_activations,
    )


@pytest.fixture()
def keypair(monkeypatch):
    key = ECC.generate(curve="ed25519")
    monkeypatch.setattr(licensing, "PUBLIC_KEY_PEM", key.public_key().export_key(format="PEM"))
    licensing._cached_verify.cache_clear()
    yield key
    licensing._cached_verify.cache_clear()


@pytest.fixture()
def family_instance(monkeypatch):
    """A non-demo family instance pointing at a (never-reached) license
    server. The conftest default sets DEMO_PIN, which makes
    is_demo_deployment true — a demo must never acquire an outbound
    license channel, so heartbeat tests run in family mode."""
    monkeypatch.setattr(settings, "demo_pin", "")
    monkeypatch.setattr(settings, "license_server_url", "https://license.example.invalid")


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    # Leave the module ungated for whatever test runs next.
    license_state.refresh("", None, required=False)


@pytest.fixture(autouse=True)
def _reset_kick():
    license_heartbeat._kick = None
    yield
    license_heartbeat._kick = None


# ---------------------------------------------------------------------------
# The opt-out promise: an unset LICENSE_SERVER_URL issues NO http requests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_opt_out_issues_no_http_requests(keypair, monkeypatch):
    """The permanent opt-out, asserted at the transport layer: with
    LICENSE_SERVER_URL unset, evaluating, gating, and "running" the
    heartbeat performs ZERO outbound HTTP — the offline behavior is
    byte-for-byte today's, and the assertion watches httpx itself rather
    than trusting our call graph."""
    monkeypatch.setattr(settings, "demo_pin", "")  # a plain family instance
    monkeypatch.setattr(settings, "license_server_url", "")

    attempts = []
    real_post = httpx.AsyncClient.post

    async def recording_post(self, *args, **kwargs):
        attempts.append((args, kwargs))
        return await real_post(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", recording_post)

    # The heartbeat is disabled, even with a license configured.
    assert not license_heartbeat.enabled()

    # The full offline evaluation path — expired license resolving to the
    # gated mode — exercises refresh(), effective_info(), and the gate
    # without a single network call.
    expired = _sign(keypair, expires=date.today() - timedelta(days=1))
    state = license_state.refresh(expired, None, required=True)
    assert not state.ok and license_state.is_gated()
    assert license_state.effective_info() is None

    # A cached report must not survive an opt-out: an instance that turns
    # the heartbeat OFF reverts to pure signed-payload governance.
    assert await license_heartbeat.read_cached_report(None) is None

    # The background loop, "run" directly: it returns immediately (the app
    # never starts it in this configuration) — and still makes no requests.
    await asyncio.wait_for(license_heartbeat.run_periodic(), timeout=5)

    assert attempts == [], f"opted-out instance issued {len(attempts)} outbound request(s)"


@pytest.mark.asyncio
async def test_demo_deployment_never_enables_heartbeat(monkeypatch):
    """The public demo is license-exempt by design and promises no phone-
    home: even with a URL configured, a demo deployment (DEMO_PIN set)
    must not enable the heartbeat."""
    monkeypatch.setattr(settings, "demo_pin", "384756")
    monkeypatch.setattr(settings, "license_server_url", "https://license.example.invalid")
    assert not license_heartbeat.enabled()
    await asyncio.wait_for(license_heartbeat.run_periodic(), timeout=5)  # returns, never sleeps


# ---------------------------------------------------------------------------
# The decision order: a server row outranks the nominal signed expiry,
# both directions
# ---------------------------------------------------------------------------

def test_active_server_report_extends_past_nominal_expiry(keypair, family_instance):
    """A renewed license: the signed expiry is in the past, and the server
    says active-in-term. The instance stays UNGATED — no re-paste for a
    renewal."""
    key_text = _sign(keypair, expires=date.today() - timedelta(days=30))
    report = _report(
        key_text,
        status="active",
        valid_until=_now() + timedelta(days=335),
        reported_at=_now(),
    )
    state = license_state.refresh(key_text, None, required=True, server_report=report)
    assert state.ok and not license_state.is_gated()
    assert state.server_status == "active"
    assert license_state.effective_info() is not None  # past nominal expiry, honored anyway
    assert state.server_valid_until == report.valid_until


def test_revoked_server_report_gates(keypair, family_instance):
    """A refund/cancellation: the signed payload is still perfectly valid,
    but the server says revoked — the instance gates. The server outranks
    the signature, both directions."""
    key_text = _sign(keypair, expires=date.today() + timedelta(days=300))
    report = _report(key_text, status="revoked", valid_until=None)
    state = license_state.refresh(key_text, None, required=True, server_report=report)
    assert not state.ok and license_state.is_gated()
    assert state.server_status == "revoked"
    assert license_state.effective_info() is None


def test_past_term_active_report_gates(keypair, family_instance):
    """'active' but the server-tracked term has ended (no renewal yet):
    gated — status alone is not enough, the term must be live."""
    key_text = _sign(keypair, expires=date.today() + timedelta(days=300))
    report = _report(
        key_text,
        status="active",
        valid_until=_now() - timedelta(days=2),
        reported_at=_now(),
    )
    state = license_state.refresh(key_text, None, required=True, server_report=report)
    assert not state.ok and license_state.is_gated()


def test_unknown_server_answer_falls_back_to_signed_payload(keypair, family_instance):
    """The unknown-key invariant: a signature-valid key the server has
    never seen (a legacy hand-issued license) keeps governing itself by
    its own signed payload — turning the heartbeat on must never break a
    license that was already valid."""
    key_text = _sign(keypair, expires=date.today() + timedelta(days=100))
    report = _report(key_text, status="unknown", valid_until=None)
    state = license_state.refresh(key_text, None, required=True, server_report=report)
    assert state.ok and not license_state.is_gated()
    assert state.server_status == "unknown"
    assert license_state.effective_info().licensee == "Fam"


def test_unreachable_server_falls_back_to_signed_payload(keypair):
    """server_report=None (heartbeat off or unreachable) — exactly today's
    behavior, expired and valid alike."""
    valid = _sign(keypair, expires=date.today() + timedelta(days=100))
    state = license_state.refresh(valid, None, required=True, server_report=None)
    assert state.ok and not license_state.is_gated()

    expired = _sign(keypair, expires=date.today() - timedelta(days=1))
    state = license_state.refresh(expired, None, required=True, server_report=None)
    assert not state.ok and license_state.is_gated()


def test_signature_check_still_comes_first(keypair, family_instance):
    """A signature-invalid key gates immediately, server answer or not —
    the server can never launder a forged key into validity."""
    key_text = _sign(keypair, expires=date.today() + timedelta(days=100))
    other_key = ECC.generate(curve="ed25519")
    forged = _sign(other_key, expires=date.today() + timedelta(days=100))  # wrong keypair
    report = _report(key_text, status="active", valid_until=_now() + timedelta(days=300))
    # The forged key presents itself; the report is what a genuine server
    # row for the REAL key looks like. Signature verification of `forged`
    # fails first, and nothing downstream can rescue it.
    state = license_state.refresh(forged, None, required=True, server_report=report)
    assert not state.ok and license_state.is_gated()
    assert license_state.effective_info() is None


def test_server_report_bound_to_the_presented_key(keypair, family_instance):
    """A server answer describing key A must not vouch for key B: the
    digest binding means a re-pasted key re-governs itself until the next
    heartbeat answers for IT."""
    key_a = _sign(keypair, licensee="A", expires=date.today() - timedelta(days=10))
    key_b = _sign(keypair, licensee="B", expires=date.today() + timedelta(days=10))
    active_for_a = _report(key_a, status="active", valid_until=_now() + timedelta(days=300))
    state = license_state.refresh(key_a, None, required=True, server_report=active_for_a)
    assert state.ok  # A is extended by its own report...

    state = license_state.refresh(key_a, key_b, required=True, server_report=active_for_a)
    # ...but the DB key is B: the report is for A, so B's signed payload
    # governs (valid — B is unexpired) rather than A's term.
    assert state.ok
    assert state.server_status is None  # the report was not applied to B
    assert license_state.effective_info().licensee == "B"


# ---------------------------------------------------------------------------
# Grace: the last good answer carries the instance, tamper-evidently
# ---------------------------------------------------------------------------

def test_grace_within_window_carries_active_state(keypair, family_instance):
    """Server unreachable for 29 days with a cached 'active': still
    ungated — outages are invisible up to the uniform 30-day grace."""
    key_text = _sign(keypair, expires=date.today() + timedelta(days=300))
    report = _report(
        key_text,
        status="active",
        valid_until=_now() + timedelta(days=335),
        reported_at=_now() - timedelta(days=29),
    )
    state = license_state.refresh(key_text, None, required=True, server_report=report)
    assert state.ok and not license_state.is_gated()


def test_grace_expiry_gates_with_reconnect_message(keypair, family_instance):
    """31 days without a successful heartbeat: the cached answer is too
    old — the instance gates with the reconnect-to-revalidate message,
    reusing the existing gated-mode UX."""
    key_text = _sign(keypair, expires=date.today() + timedelta(days=300))
    report = _report(
        key_text,
        status="active",
        valid_until=_now() + timedelta(days=335),
        reported_at=_now() - timedelta(days=31),
    )
    state = license_state.refresh(key_text, None, required=True, server_report=report)
    assert not state.ok and license_state.is_gated()
    assert state.server_status == "active"  # it's not a revocation...
    assert "reconnect" in (state.problem or "").lower()  # ...it's a stale check-in


@pytest.mark.asyncio
async def test_cache_roundtrip_is_tamper_evident(demo_db, keypair, family_instance):
    """The tamper-evident cache: a stored answer reads back faithfully,
    and a casually edited one (e.g. 'revoked' rewritten to 'active') fails
    its integrity check and is treated as ABSENT — never trusted, never
    fatal."""
    # Seed the cache with a REVOKED answer, then tamper it toward 'active'
    # — exactly what a casual edit of a leaked DB row looks like (rewriting
    # the answer that gates you) — without touching the MAC.
    report = _report(
        "some-license-key",
        status="revoked",
        valid_until=None,
    )
    async with demo_db() as db:
        await license_heartbeat.write_cache(db, report)
        loaded = await license_heartbeat.read_cached_report(db)
    assert loaded is not None
    assert loaded.status == "revoked"
    assert loaded.valid_until is None
    assert loaded.key_digest == report.key_digest
    assert loaded.activations_used == 1
    assert loaded.max_activations == 2

    # Now the tamper: rewrite the stored status without touching the MAC —
    # exactly what a casual edit of a leaked DB row looks like.
    async with demo_db() as db:
        row = await db.get(EncryptionConfig, "license_heartbeat_cache")
        blob = json.loads(row.value.decode("utf-8"))
        blob["report"]["status"] = "active"  # the edit that un-gates the app
        row.value = json.dumps(blob, separators=(",", ":")).encode("utf-8")
        await db.commit()
        tampered = await license_heartbeat.read_cached_report(db)
    assert tampered is None  # integrity check failed → absent, not trusted


@pytest.mark.asyncio
async def test_garbage_cache_is_treated_as_absent(demo_db, family_instance):
    """A cache row that isn't even the right shape (truncated write, bad
    JSON) is treated as absent — the signed payload governs instead."""
    async with demo_db() as db:
        db.add(EncryptionConfig(key="license_heartbeat_cache", value=b"not json at all"))
        await db.commit()
        assert await license_heartbeat.read_cached_report(db) is None


# ---------------------------------------------------------------------------
# The exchange: activate once, then validate; failures are never fatal
# ---------------------------------------------------------------------------

class _FakeServer:
    """Stands in for the (possibly not-yet-merged) license server: records
    requests, replies from a scripted queue of (status, payload)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def __call__(self, path, body):
        self.requests.append((path, dict(body)))
        status, payload = self.responses.pop(0)
        if isinstance(status, Exception):
            raise status
        return status, payload


@pytest.fixture()
def fake_server(monkeypatch):
    server = _FakeServer([])
    monkeypatch.setattr(license_heartbeat, "_post_json", server)
    return server


@pytest.mark.asyncio
async def test_activate_then_validate_request_shapes(demo_db, keypair, fake_server, family_instance):
    """The wire contract, client side: POST /v1/activate first, then
    /v1/validate — bodies exactly {license_key, install_id} per the pinned
    protocol; a 200 {status, valid_until, activations_used,
    max_activations} answer lands in the license state (and the cache)
    immediately."""
    fake_server.responses = [
        (200, {"status": "active", "valid_until": "2027-10-09T00:00:00Z",
               "activations_used": 1, "max_activations": 2}),
        (200, {"status": "active", "valid_until": "2027-10-09T00:00:00Z",
               "activations_used": 1, "max_activations": 2}),
    ]
    key_text = _sign(keypair, expires=date.today() + timedelta(days=300))
    async with demo_db() as db:
        install_id = await encryption.get_or_create_install_id(db)
        # The report binds to the presented key (the key-digest check):
        # seed the license the way a real install holds it, so the
        # server's answer has a key to bind to.
        db.add(LicenseConfig(key="license", license_text=key_text))
        await db.commit()

        spoke, report = await license_heartbeat.heartbeat_cycle(
            db, license_text=key_text, install_id=install_id, activate=True
        )
        assert spoke and report is not None
        assert fake_server.requests[0][0] == "/v1/activate"
        assert fake_server.requests[0][1] == {"license_key": key_text, "install_id": install_id}

        spoke, report = await license_heartbeat.heartbeat_cycle(
            db, license_text=key_text, install_id=install_id, activate=False
        )
        assert spoke
        assert fake_server.requests[1][0] == "/v1/validate"

        # The answer took effect in-process AND is cached for restarts.
        state = license_state.current()
        assert state.server_status == "active"
        assert state.activations_used == 1 and state.max_activations == 2
        cached = await license_heartbeat.read_cached_report(db)
        assert cached is not None and cached.status == "active"


@pytest.mark.asyncio
async def test_transient_failure_never_gates(demo_db, keypair, fake_server, family_instance):
    """A network failure is an outage, not an error: the cycle logs,
    returns spoke=False, refreshes nothing, and a previously-valid license
    is STILL valid — the cached answer holds within grace."""
    key_text = _sign(keypair, expires=date.today() + timedelta(days=300))
    state = license_state.refresh(key_text, None, required=True)
    assert state.ok

    fake_server.responses = [(httpx.ConnectError("no route to host"), None)]
    async with demo_db() as db:
        install_id = await encryption.get_or_create_install_id(db)
        spoke, report = await license_heartbeat.heartbeat_cycle(
            db, license_text=key_text, install_id=install_id, activate=True
        )
        assert spoke is False and report is None

    # Unchanged: still governed by the signed payload, still un-gated.
    state = license_state.current()
    assert state.ok and not license_state.is_gated()
    assert state.server_status is None  # no half-applied answer


@pytest.mark.asyncio
async def test_unexpected_status_is_treated_as_transient(demo_db, keypair, fake_server, family_instance):
    """A 500 (or any status outside the pinned protocol) is a transient
    outage too — logged, not fatal, nothing applied."""
    key_text = _sign(keypair, expires=date.today() + timedelta(days=300))
    license_state.refresh(key_text, None, required=True)
    fake_server.responses = [(500, {"error": "boom"})]
    async with demo_db() as db:
        install_id = await encryption.get_or_create_install_id(db)
        spoke, report = await license_heartbeat.heartbeat_cycle(
            db, license_text=key_text, install_id=install_id, activate=True
        )
    assert spoke is False and report is None
    assert license_state.current().server_status is None


@pytest.mark.asyncio
async def test_revocation_410_persists_and_gates(demo_db, keypair, fake_server, family_instance):
    """The server's 410 {"error": "revoked"} is an unambiguous answer:
    persisted (revocation survives restarts) and applied — the instance
    gates."""
    fake_server.responses = [(410, {"error": "revoked"})]
    key_text = _sign(keypair, expires=date.today() + timedelta(days=300))
    async with demo_db() as db:
        install_id = await encryption.get_or_create_install_id(db)
        # The revoked report binds to the presented key — seed the license
        # the way a real install holds it.
        db.add(LicenseConfig(key="license", license_text=key_text))
        await db.commit()
        spoke, report = await license_heartbeat.heartbeat_cycle(
            db, license_text=key_text, install_id=install_id, activate=False
        )
    assert spoke and report is not None and report.status == "revoked"
    state = license_state.current()
    # The revocation is recorded and honored at the state layer. In
    # production (required=True) this state IS the gated mode — the gate
    # arithmetic under required is covered by the state-level tests, and
    # a dev instance stays un-gated by the same exemption it has today.
    assert state.server_status == "revoked" and not state.server_grants_validity
    async with demo_db() as db:
        cached = await license_heartbeat.read_cached_report(db)
    assert cached is not None and cached.status == "revoked"


@pytest.mark.asyncio
async def test_activation_cap_409_keeps_signed_governance(demo_db, keypair, fake_server, family_instance):
    """A DIFFERENT install at the activation cap gets 409. The client
    treats it as 'the server heard us, but this install is not the
    activated one': no report is applied, and this install keeps governing
    itself by its signed payload — casual-copy resistance, not DRM."""
    fake_server.responses = [(409, {"error": "activation_cap_reached"})]
    key_text = _sign(keypair, expires=date.today() + timedelta(days=300))
    license_state.refresh(key_text, None, required=True)
    async with demo_db() as db:
        install_id = await encryption.get_or_create_install_id(db)
        spoke, report = await license_heartbeat.heartbeat_cycle(
            db, license_text=key_text, install_id=install_id, activate=True
        )
    assert spoke and report is None  # spoke, but nothing to apply
    state = license_state.current()
    assert state.ok and not license_state.is_gated()  # unchanged — signed payload governs
    assert state.server_status is None


@pytest.mark.asyncio
async def test_malformed_200_is_transient(demo_db, keypair, fake_server, family_instance):
    """A 200 without a status field violates the protocol — treated like
    an outage, never half-applied."""
    fake_server.responses = [(200, {"oops": True})]
    key_text = _sign(keypair, expires=date.today() + timedelta(days=300))
    license_state.refresh(key_text, None, required=True)
    async with demo_db() as db:
        install_id = await encryption.get_or_create_install_id(db)
        spoke, report = await license_heartbeat.heartbeat_cycle(
            db, license_text=key_text, install_id=install_id, activate=True
        )
    assert spoke is False and report is None
    assert license_state.current().server_status is None


# ---------------------------------------------------------------------------
# The loop: activates once, then validates daily; a kick wakes it early
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_periodic_activates_once_then_validates_and_kicks(
    demo_db, keypair, monkeypatch, family_instance
):
    """The full loop, scheduled fast: first exchange is ACTIVATE, the next
    is VALIDATE (same install_id both times — re-activating an install
    must be idempotent server-side, so the client only activates once),
    and a kick() (new key pasted) cuts the daily wait short."""
    answer = (200, {"status": "active", "valid_until": "2027-10-09T00:00:00Z",
                    "activations_used": 1, "max_activations": 2})
    fake = _FakeServer([answer, answer, answer])
    monkeypatch.setattr(license_heartbeat, "_post_json", fake)
    # run_periodic imports AsyncSessionLocal from core.database inside the
    # loop body, so demo_db's patch is picked up as-is.
    monkeypatch.setattr(license_heartbeat, "_INITIAL_JITTER_SECONDS", 0.01)
    monkeypatch.setattr(license_heartbeat, "_INTERVAL_SECONDS", 3600)  # long — the kick must cut it
    monkeypatch.setattr(license_heartbeat, "_JITTER_SECONDS", 0)

    key_text = _sign(keypair, expires=date.today() + timedelta(days=300))
    async with demo_db() as db:
        db.add(LicenseConfig(key="license", license_text=key_text))
        await db.commit()

    task = asyncio.create_task(license_heartbeat.run_periodic())
    try:
        for _ in range(200):  # ≤10s: two exchanges (activate, validate)
            await asyncio.sleep(0.05)
            if len(fake.requests) >= 2:
                break
        assert [p for p, _ in fake.requests] == ["/v1/activate", "/v1/validate"]
        assert fake.requests[0][1]["install_id"] == fake.requests[1][1]["install_id"]

        # A pasted key kicks the loop: a third exchange, immediately.
        license_heartbeat.kick()
        for _ in range(200):
            await asyncio.sleep(0.05)
            if len(fake.requests) >= 3:
                break
        assert len(fake.requests) >= 3
        assert [p for p, _ in fake.requests][2] == "/v1/validate"  # already activated
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_run_periodic_survives_cycle_failures(demo_db, keypair, monkeypatch, family_instance):
    """The loop itself never dies: one cycle failing (here: the server
    goes dark after the first success) logs and keeps the schedule — a
    bad cycle must not end days of revalidation."""
    answer = (200, {"status": "active", "valid_until": "2027-10-09T00:00:00Z",
                    "activations_used": 1, "max_activations": 2})
    fake = _FakeServer([answer, (httpx.ConnectError("gone"), None), (httpx.ConnectError("gone"), None)])
    monkeypatch.setattr(license_heartbeat, "_post_json", fake)
    monkeypatch.setattr(license_heartbeat, "_INITIAL_JITTER_SECONDS", 0.01)
    monkeypatch.setattr(license_heartbeat, "_INTERVAL_SECONDS", 0.2)
    monkeypatch.setattr(license_heartbeat, "_JITTER_SECONDS", 0)

    key_text = _sign(keypair, expires=date.today() + timedelta(days=300))
    async with demo_db() as db:
        db.add(LicenseConfig(key="license", license_text=key_text))
        await db.commit()

    task = asyncio.create_task(license_heartbeat.run_periodic())
    try:
        await asyncio.sleep(1.0)  # several intervals pass; the loop is still alive
        assert task.done() is False  # did NOT die
        assert len(fake.requests) >= 1
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# The parent-facing surface: activation counts on GET /admin/license
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_license_payload_includes_activation_fields(demo_db, keypair, family_instance):
    """GET /admin/license's payload gains activations_used /
    max_activations once the heartbeat has reported — None before."""
    from routers import admin as admin_router

    key_text = _sign(keypair, expires=date.today() + timedelta(days=300))
    async with demo_db() as db:
        db.add(LicenseConfig(key="license", license_text=key_text))
        await db.commit()

    # No server answer yet: the fields exist (the parent UI can rely on
    # them) but are None.
    license_state.refresh(settings.license_key, key_text, required=True, server_report=None)
    payload = admin_router._license_status_payload()
    assert payload is not None and payload["activations_used"] is None
    assert payload["max_activations"] is None

    # After a successful heartbeat: the parent can see their own count.
    report = _report(
        key_text, status="active",
        valid_until=_now() + timedelta(days=300),
        activations_used=1, max_activations=2,
    )
    license_state.refresh(settings.license_key, key_text, required=True, server_report=report)
    payload = admin_router._license_status_payload()
    assert payload["activations_used"] == 1
    assert payload["max_activations"] == 2
