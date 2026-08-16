"""
Behavioral equivalence for the P7 policy-layer refactor.

core/deps.py moved from performing authorization inline to delegating it to
core/policy.py. That refactor claims to change WHERE the decision is made,
not WHAT gets decided — and a claim of behavioral equivalence is worth
exactly as much as the test that would fail if it were false. These are
those tests: every guard, every role, asserting the same status codes and
user-visible messages the guards produced before the layer existed.

Two deliberate exceptions to strict equivalence are asserted explicitly at
the bottom, since a silent behavior change is worse than a documented one.

tests/test_policy.py covers the decision table itself. This file covers
enforcement: does the guard raise, with the right status, and does session
liveness still apply.
"""
import pytest
import pytest_asyncio
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from core import parent_credential
from core.deps import (
    require_auth,
    require_demo_preview,
    require_email_summary,
    require_mfa_pending,
    require_parent,
    require_parent_recovery,
    require_real_user,
)
from core.middleware import compute_fingerprint
from core.security import create_access_token

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


@pytest_asyncio.fixture
async def db_session(demo_db):
    async with demo_db() as session:
        yield session


@pytest.fixture(autouse=True)
def _reset_cache():
    parent_credential._set_cached_version(0)
    yield
    parent_credential._set_cached_version(0)


def _fake_request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 12345), "headers": [(b"user-agent", b"pytest")]})


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _token(role: str, **extra) -> str:
    """A valid, correctly-fingerprinted token for `role`. Authentication is
    never what's under test here — authorization is."""
    fp = compute_fingerprint("127.0.0.1", "pytest")
    payload = {"sub": role, "role": role}
    if role in ("parent", "parent_pending"):
        payload["cv"] = 0
    payload.update(extra)
    return create_access_token(payload, fingerprint=fp)


async def _expect_denied(guard, role: str, status: int, message_fragment: str, **extra):
    with pytest.raises(HTTPException) as exc:
        await guard(_fake_request(), _bearer(_token(role, **extra)))
    assert exc.value.status_code == status
    assert message_fragment in exc.value.detail


async def _expect_allowed(guard, role: str, **extra):
    payload = await guard(_fake_request(), _bearer(_token(role, **extra)))
    assert payload["role"] == role


# ── require_parent ──────────────────────────────────────────────────────────

async def test_require_parent_allows_parent():
    await _expect_allowed(require_parent, "parent")


@pytest.mark.parametrize("role", ["child", "parent_pending", "parent_recovery"])
async def test_require_parent_rejects_non_parents(role):
    expected = {
        "child": (403, "This action requires parent authorisation"),
        "parent_pending": (401, "Second-factor verification required"),
        "parent_recovery": (403, "No account recovery is in progress"),
    }[role]
    await _expect_denied(require_parent, role, *expected)


async def test_require_parent_rejects_demo_code(demo_db):
    await _expect_denied(
        require_parent, "demo_code", 403,
        "This action requires parent authorisation", code="abc123",
    )


# ── require_real_user ───────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ["parent", "child"])
async def test_require_real_user_allows_family_roles(role):
    await _expect_allowed(require_real_user, role)


async def test_require_real_user_rejects_demo_with_the_original_message(demo_db):
    await _expect_denied(
        require_real_user, "demo_code", 403, "Not available in demo mode", code="abc123",
    )


# ── require_auth ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ["parent", "child"])
async def test_require_auth_allows_fully_authenticated_roles(role):
    await _expect_allowed(require_auth, role)


async def test_require_auth_rejects_parent_pending_with_401():
    await _expect_denied(
        require_auth, "parent_pending", 401, "Second-factor verification required",
    )


# ── require_mfa_pending / require_parent_recovery ───────────────────────────

async def test_require_mfa_pending_allows_only_parent_pending():
    await _expect_allowed(require_mfa_pending, "parent_pending")
    for role in ["parent", "child"]:
        await _expect_denied(
            require_mfa_pending, role, 403, "No second-factor verification is pending",
        )


async def test_require_parent_recovery_allows_only_parent_recovery():
    await _expect_allowed(require_parent_recovery, "parent_recovery")
    await _expect_denied(
        require_parent_recovery, "parent", 403, "No account recovery is in progress",
    )
    await _expect_denied(
        require_parent_recovery, "parent_pending", 401, "Second-factor verification required",
    )


# ── The guards that replaced inline router checks ───────────────────────────

async def test_require_email_summary_matches_the_old_inline_check():
    """Was `role not in ("parent", "demo_code")` in routers/tutor.py."""
    await _expect_allowed(require_email_summary, "parent")
    await _expect_denied(
        require_email_summary, "child", 403, "Not authorized for this action",
    )


async def test_require_demo_preview_matches_the_old_inline_checks():
    """Was `role != "demo_code"` in routers/sandbox.py and the
    _require_demo_code helper in routers/diagnostic.py."""
    for role in ["parent", "child"]:
        await _expect_denied(
            require_demo_preview, role, 403,
            "This preview is only available through the public demo login",
        )


# ── Session liveness still applies where it did ─────────────────────────────

async def test_demo_liveness_check_still_runs_after_the_policy_decision(demo_db, monkeypatch):
    """Liveness is a database read, so it can't live in the pure policy
    layer — it stays in enforcement. A demo token whose code was logged out
    must still 401, not sail through on an allow decision."""
    import core.deps as deps

    async def _gone(_code):
        return False

    monkeypatch.setattr(deps, "demo_code_exists", _gone)
    await _expect_denied(
        require_auth, "demo_code", 401, "This session ended", code="abc123",
    )


async def test_live_demo_code_passes(demo_db, monkeypatch):
    import core.deps as deps

    async def _live(_code):
        return True

    monkeypatch.setattr(deps, "demo_code_exists", _live)
    await _expect_allowed(require_auth, "demo_code", code="abc123")


# ── Deliberate, documented differences from the old behavior ────────────────

async def test_parent_recovery_no_longer_passes_require_auth():
    """SECURITY FIX, not an equivalence break.

    The old require_auth rejected parent_pending by name and said nothing
    about parent_recovery, so a recovery token — issued after proving 2 of 3
    factors and scoped to exactly one action — passed require_auth and could
    reach any of the 17 endpoints behind it. Enumerating transient roles in
    core/policy.py closes this structurally: a role gets what its table row
    grants it, and nothing else."""
    await _expect_denied(
        require_auth, "parent_recovery", 403, "No account recovery is in progress",
    )
    await _expect_denied(
        require_real_user, "parent_recovery", 403, "No account recovery is in progress",
    )


async def test_demo_code_denied_by_require_parent_before_liveness_is_checked(demo_db, monkeypatch):
    """Ordering change, deliberate and safe.

    Previously require_parent composed on require_auth, so a demo token hit
    the liveness check (a DB read that can 401 "this session ended") BEFORE
    the role rejection. Now the policy decision comes first, so it 403s
    without the lookup. Better: an unauthorized caller learns nothing about
    whether a given code exists, and an authorization denial doesn't depend
    on a database round-trip."""
    import core.deps as deps

    async def _boom(_code):
        raise AssertionError("liveness must not be checked for an unauthorized role")

    monkeypatch.setattr(deps, "demo_code_exists", _boom)
    await _expect_denied(
        require_parent, "demo_code", 403,
        "This action requires parent authorisation", code="abc123",
    )
