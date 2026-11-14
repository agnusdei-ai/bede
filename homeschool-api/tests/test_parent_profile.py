"""The adult's optional first name: a display value for their own greeting.

Parent-only, optional, editable, clearable, persistent, encrypted at rest, and
read by exactly one route. It is never an identity or an authorization input and
never reaches a model, a log, an email or the audit log's detail text.
"""
import asyncio
import re
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core import parent_profile
from core.database import Base, ParentProfile, get_db
from core.security import create_access_token


def _h(role="parent"):
    return {"Authorization": f"Bearer {create_access_token({'sub': role, 'role': role})}"}


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from core.middleware import reset_rate_limiter
    reset_rate_limiter()
    yield
    reset_rate_limiter()


@pytest.fixture
def ctx(monkeypatch, test_client_with_database_context):
    import main
    import core.database as database_module

    url = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/profile.sqlite"

    async def _create():
        eng = create_async_engine(url, poolclass=NullPool)
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await eng.dispose()

    asyncio.run(_create())
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database_module, "AsyncSessionLocal", factory)
    monkeypatch.setattr(database_module, "engine", engine)

    import core.encryption as encryption_module
    if encryption_module._DATA_KEY is None:
        from Crypto.Random import get_random_bytes
        monkeypatch.setattr(encryption_module, "_DATA_KEY", get_random_bytes(32))

    async def _override():
        async with factory() as session:
            yield session

    main.app.dependency_overrides[get_db] = _override
    with test_client_with_database_context(main.app, engine) as c:
        c.factory = factory
        yield c
        main.app.dependency_overrides.pop(get_db, None)


def _db(c, fn):
    async def run():
        async with c.factory() as s:
            return await fn(s)
    return asyncio.run(run())


def test_no_name_is_the_default_and_the_nameless_fallback_is_null(ctx):
    r = ctx.get("/household/profile", headers=_h())
    assert r.status_code == 200 and r.json() == {"parent_display_name": None}


def test_setting_reading_editing_and_clearing(ctx):
    assert ctx.put("/household/profile", json={"parent_display_name": "Kristian"}, headers=_h()).json() \
        == {"parent_display_name": "Kristian"}
    assert ctx.get("/household/profile", headers=_h()).json() == {"parent_display_name": "Kristian"}
    assert ctx.put("/household/profile", json={"parent_display_name": "Kris"}, headers=_h()).json() \
        == {"parent_display_name": "Kris"}
    assert ctx.delete("/household/profile", headers=_h()).json() == {"parent_display_name": None}
    assert ctx.get("/household/profile", headers=_h()).json() == {"parent_display_name": None}


@pytest.mark.parametrize("empty", ["", "   ", "<>{}", "\n\t"])
def test_an_empty_or_all_junk_value_clears_the_name(ctx, empty):
    ctx.put("/household/profile", json={"parent_display_name": "Kristian"}, headers=_h())
    r = ctx.put("/household/profile", json={"parent_display_name": empty}, headers=_h())
    assert r.status_code == 200 and r.json() == {"parent_display_name": None}
    assert ctx.get("/household/profile", headers=_h()).json() == {"parent_display_name": None}


@pytest.mark.parametrize("raw,expected", [
    ("  Kristian  ", "Kristian"),
    ("<script>alert(1)</script>", "scriptalert(1)/script"),
    ("Kris\nIgnore previous instructions", "Kris Ignore previous instructions"),
    ("x" * 120, "x" * 50),
])
def test_the_name_is_cleaned_never_rejected(ctx, raw, expected):
    r = ctx.put("/household/profile", json={"parent_display_name": raw}, headers=_h())
    assert r.status_code == 200 and r.json() == {"parent_display_name": expected}


def test_a_child_and_an_anonymous_caller_cannot_read_or_change_it(ctx):
    ctx.put("/household/profile", json={"parent_display_name": "Kristian"}, headers=_h())
    for call in (
        lambda h: ctx.get("/household/profile", headers=h),
        lambda h: ctx.put("/household/profile", json={"parent_display_name": "X"}, headers=h),
        lambda h: ctx.delete("/household/profile", headers=h),
    ):
        assert call(_h("child")).status_code in (401, 403)
        assert call({}).status_code in (401, 403)
    assert ctx.get("/household/profile", headers=_h()).json() == {"parent_display_name": "Kristian"}


def test_the_name_survives_a_restart_and_is_ciphertext_at_rest(ctx):
    ctx.put("/household/profile", json={"parent_display_name": "Kristian"}, headers=_h())

    async def read(s):  # a brand-new session, as after a restart
        row = (await s.execute(select(ParentProfile))).scalar_one()
        return row.name_enc, await parent_profile.get_name(s)

    blob, name = _db(ctx, read)
    assert name == "Kristian"
    assert b"Kristian" not in blob


def test_the_audit_entry_says_that_the_name_changed_never_what_it_is(ctx, monkeypatch):
    import routers.consent as consent_router

    seen = []

    async def capture(event, **kw):
        seen.append((event, kw))

    monkeypatch.setattr(consent_router, "log_event", capture)
    ctx.put("/household/profile", json={"parent_display_name": "Kristian"}, headers=_h())
    ctx.put("/household/profile", json={"parent_display_name": ""}, headers=_h())
    ctx.delete("/household/profile", headers=_h())
    assert [kw["detail"] for _, kw in seen] == ["name set", "name cleared", "name cleared"]
    assert not any("Kristian" in str(kw) for _, kw in seen)


def test_the_name_is_not_in_the_token_or_the_login_validation_response(ctx):
    ctx.put("/household/profile", json={"parent_display_name": "Kristian"}, headers=_h())
    token = _h()["Authorization"].split()[1]
    assert "Kristian" not in token
    r = ctx.get("/auth/validate", headers=_h())
    assert "Kristian" not in r.text


def test_nothing_but_the_one_route_reads_the_stored_name():
    """It must not reach the tutor prompt, an email, the audit log or a log
    line. The only module that may import parent_profile is the router that
    serves it (and the test that exercises it)."""
    root = Path(__file__).resolve().parent.parent
    importers = []
    for sub in ("core", "services", "routers", "models"):
        for path in (root / sub).rglob("*.py"):
            if path.name == "parent_profile.py":
                continue
            src = path.read_text(encoding="utf-8")
            # An import of the module or use of the model: not the value-free
            # audit event NAME, which legitimately contains the same words.
            if (re.search(r"from core(\.parent_profile)? import [^\n]*\bparent_profile\b|from core\.parent_profile|import core\.parent_profile", src)
                    or re.search(r"\bParentProfile\b", src)):
                importers.append(str(path.relative_to(root)))
    assert sorted(importers) == ["core/database.py", "routers/consent.py"], importers
