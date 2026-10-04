"""An expiry has to actually take effect on an instance nobody restarts.

`core/license_state.py`'s `current()` returns a CACHED verdict, and before
this `refresh()` had exactly two call sites: `main.py`'s startup lifespan
(once) and `routers/admin.py`'s paste endpoint. `docker-compose.yml` runs the
API under `restart: unless-stopped`, which restarts on a crash or a host
reboot and never on a schedule — so a self-hosted family's LAN server kept
whatever verdict it computed at boot, indefinitely.

For a perpetual or 365-day key that was invisible. It stops being invisible
the moment a SHORT-dated key exists: a 30-day trial expires on day 31 by
design, for every trial that does not convert, and with nothing recomputing
the verdict the gate never goes up and **the trial becomes perpetual** —
which is precisely what `docs/DECISIONS.md` entry 2 rejected ("Pay-per-use,
never zero"), reached by a cached variable rather than by a decision.

These tests drive the REAL chain — `license_state.refresh` ->
`licensing.verify_license` -> `LicenseInfo.is_expired` -> `is_gated()` — over
a throwaway keypair, rather than stubbing the verdict they are meant to
prove. The keypair convention is `tests/test_licensing.py`'s.
"""

from __future__ import annotations

import base64
import inspect
import json
import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

import main
from core import license_state, licensing


# ── minting, borrowed from tests/test_licensing.py's convention ──────────


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign(key, *, tier="trial", licensee="Trial Family", seats=6, expires=None):
    payload = {
        "id": str(uuid.uuid4()),
        "licensee": licensee,
        "tier": tier,
        "seats": seats,
        "issued": date.today().isoformat(),
        "expires": expires.isoformat() if expires else None,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"{_b64url(raw)}.{_b64url(eddsa.new(key, 'rfc8032').sign(raw))}"


@pytest.fixture
def keypair(monkeypatch):
    key = ECC.generate(curve="ed25519")
    monkeypatch.setattr(licensing, "PUBLIC_KEY_PEM", key.public_key().export_key(format="PEM"))
    return key


@pytest.fixture(autouse=True)
def restore_license_state():
    """`license_state._state` is process-global — leaking it across tests
    would make an unrelated suite's verdict depend on this one's order."""
    before = license_state.current()
    yield
    license_state._state = before


@pytest.fixture
def production(monkeypatch):
    """Gating applies only to a production, non-demo deployment."""
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(license_key="", is_production=True, is_demo_deployment=False),
    )


# ── a stand-in for the DB read, honest about its one job ────────────────


class _FakeSession:
    def __init__(self, row, *, raises=False):
        self._row = row
        self._raises = raises

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, _model, _pk):
        if self._raises:
            raise RuntimeError("database is unreachable")
        return self._row


def _session_factory(row=None, *, raises=False):
    return lambda: _FakeSession(row, raises=raises)


# ── the function ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_expired_license_gates_the_instance_on_the_next_cycle(
    monkeypatch, keypair, production
):
    """The whole point, driven through the real verify/expiry chain.

    A trial that lapsed yesterday must leave the instance gated after one
    cycle — with nothing recomputing, `is_gated()` stays False forever.
    """
    live = _sign(keypair, expires=date.today() + timedelta(days=5))
    license_state.refresh("", live, required=True)
    assert license_state.is_gated() is False, "a live license should not gate"

    lapsed = _sign(keypair, expires=date.today() - timedelta(days=1))
    monkeypatch.setattr(
        main, "AsyncSessionLocal", _session_factory(SimpleNamespace(license_text=lapsed))
    )

    await main._refresh_license_once()

    assert license_state.is_gated() is True, (
        "an expired trial did not gate the instance — the trial has become "
        "perpetual, which is what entry 2 refused"
    )
    assert "expired" in (license_state.current().problem or "").lower()


@pytest.mark.asyncio
async def test_a_failed_database_read_never_revokes_a_valid_license(
    monkeypatch, keypair, production
):
    """The inverse risk, and the one that would actually hurt a family.

    The DB key WINS over the env key, so refreshing with `None` for the DB
    half after a transient error would discard an in-app renewal and gate a
    family who had paid. A failed read must change nothing at all.
    """
    # Verifying this guard needs care. Simply deleting the `return` does NOT
    # reach refresh(): `db_text` is then unbound, so building the call raises
    # UnboundLocalError and the second `except` swallows it — the test passes
    # for the wrong reason. The realistic mistake is pre-initialising
    # `db_text = None` and then dropping the guard, which is what this was
    # verified against, and which fails both assertions below.
    renewal = _sign(keypair, tier="core", expires=date.today() + timedelta(days=300))
    license_state.refresh("", renewal, required=True)
    before = license_state.current()
    assert before.ok and before.source == "db"

    called = []
    monkeypatch.setattr(main, "AsyncSessionLocal", _session_factory(raises=True))
    real_refresh = license_state.refresh
    monkeypatch.setattr(
        license_state, "refresh", lambda *a, **k: called.append((a, k)) or real_refresh(*a, **k)
    )

    await main._refresh_license_once()

    assert called == [], (
        "refresh() was called after the database read failed — with the DB "
        "half missing it would fall back to the env key and gate a family "
        "who renewed in-app"
    )
    assert license_state.current() == before, "the verdict changed on a failed read"


@pytest.mark.asyncio
async def test_a_renewal_pasted_in_app_survives_the_cycle(monkeypatch, keypair, production):
    """A refresh must not undo the thing `POST /admin/license` just did."""
    renewal = _sign(keypair, tier="core", expires=date.today() + timedelta(days=200))
    monkeypatch.setattr(
        main, "AsyncSessionLocal", _session_factory(SimpleNamespace(license_text=renewal))
    )

    await main._refresh_license_once()

    state = license_state.current()
    assert state.ok is True
    assert state.source == "db", "the DB-applied renewal lost to the env key"
    assert state.info is not None and state.info.tier == "core"


@pytest.mark.asyncio
async def test_no_stored_license_row_is_not_an_error(monkeypatch, keypair, production):
    """An instance licensed purely from `.env` has no DB row at all."""
    env_key = _sign(keypair, tier="core", expires=date.today() + timedelta(days=100))
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(license_key=env_key, is_production=True, is_demo_deployment=False),
    )
    monkeypatch.setattr(main, "AsyncSessionLocal", _session_factory(None))

    await main._refresh_license_once()

    state = license_state.current()
    assert state.ok is True and state.source == "env"


@pytest.mark.asyncio
async def test_a_broken_refresh_does_not_kill_the_task(monkeypatch, keypair, production):
    """A raising refresh must be swallowed, or one bad cycle ends the loop
    for the life of the process and enforcement silently stops."""
    monkeypatch.setattr(
        main, "AsyncSessionLocal", _session_factory(SimpleNamespace(license_text="whatever"))
    )

    def _boom(*_a, **_k):
        raise RuntimeError("refresh exploded")

    monkeypatch.setattr(license_state, "refresh", _boom)
    await main._refresh_license_once()  # must not raise


# ── the invocation ──────────────────────────────────────────────────────


def test_the_loop_actually_calls_the_body() -> None:
    """A body nothing invokes is the `bayesian_update`-unpassed-`params`
    defect this repo's standing rule was written after."""
    source = inspect.getsource(main._periodic_license_refresh)
    assert "_refresh_license_once()" in source, (
        "the periodic loop no longer calls _refresh_license_once, so every "
        "assertion above covers code that never runs"
    )
    assert "_LICENSE_REFRESH_INTERVAL_SECONDS" in source


def test_the_lifespan_starts_and_cancels_the_task() -> None:
    """Read the REAL lifespan, not a reconstructed replica — the reason
    `test_app_composition.py` reads `main.app`'s own middleware config."""
    source = inspect.getsource(main.lifespan)
    assert "_periodic_license_refresh()" in source, (
        "the lifespan does not start the license-refresh task, so the "
        "verdict is still computed once at boot and never again"
    )
    assert "license_refresh_task.cancel()" in source, (
        "the task is never cancelled on shutdown, leaving it running against "
        "a disposed engine"
    )


def test_the_interval_is_daily_because_expiry_is_date_granular() -> None:
    """`LicenseInfo.is_expired` is `expires < date.today()`, so the verdict
    can only change at local midnight. A shorter interval does the same work
    repeatedly for one possible transition; a longer one lets a lapsed
    license keep serving for more than a day."""
    assert main._LICENSE_REFRESH_INTERVAL_SECONDS == 24 * 60 * 60
    assert "date.today()" in inspect.getsource(licensing.LicenseInfo.is_expired.fget)
