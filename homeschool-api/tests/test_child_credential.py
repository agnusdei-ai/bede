"""A parent changing the shared child PIN from inside the app.

Two documents justified having no child-role recovery scheme on the grounds
that "recovery for a child is asking a parent to change CHILD_PIN, a
capability that already exists." It did not exist. routers/auth.py compared
straight against settings.child_pin; there was no override table, no
endpoint, and no UI, so changing it meant editing .env on the server and
restarting the stack. The whole out-of-scope argument rested on something
nobody had built.

The behaviour these tests pin, in order of how easy it would be to get
wrong later:

  1. A change takes effect at the NEXT login and ends no session. A child
     part-way through a lesson keeps working. This is the one real
     difference from the parent password, which deliberately kills every
     other session, and it is a decision rather than an oversight.
  2. The PIN is judged by the same policy the installers use, so a PIN
     accepted here is one the API will boot on.
  3. A deployment that never uses this sees byte-for-byte the old
     behaviour: the env value, compared the same way.
"""
import pytest
import pytest_asyncio
from fastapi import HTTPException, Request
from sqlalchemy import select

from core import child_credential
from core.config import settings
from core.database import ChildCredentialOverride
from core.pin_policy import check_child_pin, suggest_pin
from models.schemas import ChangeChildPinRequest
from routers.mfa import change_child_pin, status_

pytestmark = [pytest.mark.usefixtures("demo_db")]


@pytest_asyncio.fixture
async def db_session(demo_db):
    async with demo_db() as session:
        yield session


def _fake_request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 12345),
                    "headers": [(b"user-agent", b"pytest")]})


@pytest.fixture(autouse=True)
def _clean_cache():
    """The override cache is module-level, so a test that sets it would
    otherwise leak into the next."""
    child_credential._set_cached(None)
    yield
    child_credential._set_cached(None)


# ── Falling back to the env value, for every deployment that never touches this ──

def test_with_no_override_the_env_pin_is_used(monkeypatch):
    monkeypatch.setattr(settings, "child_pin", "481973")
    assert child_credential.verify_child_pin("481973") is True
    assert child_credential.verify_child_pin("481974") is False
    assert child_credential.has_override() is False


@pytest.mark.asyncio
async def test_refresh_with_no_row_leaves_the_env_in_force(db_session, monkeypatch):
    monkeypatch.setattr(settings, "child_pin", "481973")
    await child_credential.refresh_from_db(db_session)
    assert child_credential.has_override() is False
    assert child_credential.verify_child_pin("481973") is True


# ── Setting a new PIN ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_new_pin_works_and_the_old_one_stops(db_session, monkeypatch):
    monkeypatch.setattr(settings, "child_pin", "481973")
    await child_credential.set_child_pin_override(db_session, "907183")

    assert child_credential.verify_child_pin("907183") is True
    assert child_credential.verify_child_pin("481973") is False, (
        "the PIN from .env still works after a parent changed it"
    )
    assert child_credential.has_override() is True


@pytest.mark.asyncio
async def test_the_pin_is_never_stored_in_plaintext(db_session):
    await child_credential.set_child_pin_override(db_session, "907183")
    row = (await db_session.execute(select(ChildCredentialOverride))).scalars().one()
    assert b"907183" not in row.hash
    assert b"907183" not in row.salt
    assert row.hash != row.salt


@pytest.mark.asyncio
async def test_changing_it_twice_replaces_rather_than_accumulates(db_session):
    await child_credential.set_child_pin_override(db_session, "907183")
    await child_credential.set_child_pin_override(db_session, "620574")

    rows = (await db_session.execute(select(ChildCredentialOverride))).scalars().all()
    assert len(rows) == 1
    assert child_credential.verify_child_pin("620574") is True
    assert child_credential.verify_child_pin("907183") is False


@pytest.mark.asyncio
async def test_a_new_process_picks_up_the_override_at_startup(db_session, monkeypatch):
    """The startup refresh main.py's lifespan performs. Without it the first
    login of the day would be checked against the stale env value."""
    monkeypatch.setattr(settings, "child_pin", "481973")
    await child_credential.set_child_pin_override(db_session, "907183")

    child_credential._set_cached(None)          # as if the process restarted
    assert child_credential.verify_child_pin("907183") is False  # not yet loaded
    await child_credential.refresh_from_db(db_session)
    assert child_credential.verify_child_pin("907183") is True


# ── The decision: a change must not end a child's lesson ─────────────────

@pytest.mark.asyncio
async def test_changing_the_pin_ends_no_session(db_session):
    """The explicit product decision. Changing the PARENT password bumps
    credentials_version and every other parent JWT dies at once, which is
    what ends a takeover. Doing that here would eject a child from a lesson
    in progress the moment a parent tidied up credentials.

    Asserted structurally rather than by driving a session: this table has
    no version column at all, and no token carries a child credential
    version, so there is no mechanism by which an existing child token could
    be invalidated. That is the guarantee, and it cannot be weakened without
    a schema change this test would fail on.
    """
    await child_credential.set_child_pin_override(db_session, "907183")
    row = (await db_session.execute(select(ChildCredentialOverride))).scalars().one()

    assert not hasattr(row, "credentials_version"), (
        "a version column here would let a PIN change invalidate live child "
        "sessions — see this test's docstring before adding one"
    )
    import core.child_credential as mod
    source = open(mod.__file__).read()
    assert "credentials_version" not in source.split('"""')[2], (
        "child_credential must not bump any credentials version"
    )


# ── Agreement with the policy the installers enforce ─────────────────────

@pytest.mark.parametrize("bad,fragment", [
    ("", "choose a PIN"),
    ("12ab56", "Digits only"),
    ("1234", "longer"),
    ("123456", "easily-guessable"),
    ("111111", "easily-guessable"),
    ("669966", "easily-guessable"),
    ("602656", "published"),
])
def test_the_endpoint_policy_matches_the_installer_policy(bad, fragment):
    """The endpoint calls check_child_pin — the exact function the setup
    wizard's form and its live typing feedback use. A separate rule here
    would be the fifth copy of this policy, which is the mistake that
    produced the 602656 defect."""
    assert fragment in check_child_pin(bad)


def test_a_generated_pin_passes_the_same_check():
    for _ in range(20):
        assert check_child_pin(suggest_pin()) == ""


# ── The endpoint a parent actually reaches ───────────────────────────────

@pytest.mark.asyncio
async def test_the_endpoint_sets_a_new_pin(db_session, monkeypatch):
    monkeypatch.setattr(settings, "child_pin", "481973")
    result = await change_child_pin(
        ChangeChildPinRequest(new_pin="907183"), _fake_request(), db_session, {"role": "parent"},
    )
    assert result["success"] is True
    assert result["applies"] == "next_login"
    assert child_credential.verify_child_pin("907183") is True
    assert child_credential.verify_child_pin("481973") is False


@pytest.mark.asyncio
async def test_the_endpoint_refuses_a_pin_the_api_would_not_boot_on(db_session):
    """The reason it calls check_child_pin rather than its own rule: a PIN
    accepted here must be one the installers would accept and the container
    will start with."""
    for bad in ["602656", "111111", "123456", "1234", "12ab56"]:
        with pytest.raises(HTTPException) as exc:
            await change_child_pin(
                ChangeChildPinRequest(new_pin=bad), _fake_request(), db_session, {"role": "parent"},
            )
        assert exc.value.status_code == 400
    assert (await db_session.execute(select(ChildCredentialOverride))).scalars().all() == []


@pytest.mark.asyncio
async def test_a_rejected_pin_leaves_the_previous_one_working(db_session):
    await child_credential.set_child_pin_override(db_session, "907183")
    with pytest.raises(HTTPException):
        await change_child_pin(
            ChangeChildPinRequest(new_pin="111111"), _fake_request(), db_session, {"role": "parent"},
        )
    assert child_credential.verify_child_pin("907183") is True


@pytest.mark.asyncio
async def test_status_reports_whether_the_pin_was_changed_but_never_the_pin(db_session):
    before = await status_(db_session, {"role": "parent"})
    assert before["child_pin_overridden"] is False

    await child_credential.set_child_pin_override(db_session, "907183")
    after = await status_(db_session, {"role": "parent"})
    assert after["child_pin_overridden"] is True
    assert "907183" not in str(after), "the settings endpoint leaked the PIN"
