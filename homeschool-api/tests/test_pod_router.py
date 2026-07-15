"""
Tests for routers/pod.py — saving, listing, fetching, updating, and
deleting a student's pod config. Before this file, no test in the suite
imported anything from routers/pod.py at all: the parent-only gating on
save/list/delete, the require_real_user gating on the child-facing
fetch/voice-narration-toggle endpoints, and the actual encrypt/decrypt
round trip were all implemented but unverified by CI. This closes R6 from
docs/COMPLIANCE_TRACEABILITY.md (the pod-config half of "a family can
delete a child's data") plus general coverage for the rest of the router
while it was already at zero.

Wiring tests (does each endpoint depend on the role it claims to?) and
logic tests (does the endpoint behave correctly given a resolved auth
dict?) are kept separate, same rationale as tests/test_voice_router.py:
calling an endpoint directly with a hand-built auth dict bypasses
FastAPI's dependency injection entirely, so it can't catch a wiring
regression (e.g. require_parent silently swapped for require_auth) —
only introspecting the Depends(...) default can.

The encrypt/decrypt round trip uses a real in-memory SQLite engine via
aiosqlite, with core.encryption.initialize_encryption() run for real
against it — same pattern as tests/diagnostic/test_facade_persisted.py
and tests/test_audit_log.py — not mocked.
"""
import inspect

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, StudentConfig
from core.deps import require_parent, require_real_user
from models.schemas import GradeStage, PodConfigsRequest, SessionConfig, VoiceNarrationPreferenceRequest
from routers import pod


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        from core.encryption import initialize_encryption
        await initialize_encryption(settings.master_secret, session)
        yield session

    await engine.dispose()


def _config(student_name: str = "Emma") -> SessionConfig:
    return SessionConfig(student_name=student_name, grade="3", grade_stage=GradeStage.core_mastery)


def _dependency_of(func, param_name: str):
    default = inspect.signature(func).parameters[param_name].default
    return getattr(default, "dependency", None)


# ── Wiring: does each endpoint actually require the role it claims to? ──────

@pytest.mark.parametrize(
    "endpoint,param",
    [
        (pod.save_pod_configs, "_"),
        (pod.list_pod_configs, "_"),
        (pod.delete_student_config, "_"),
    ],
)
def test_parent_only_endpoints_depend_on_require_parent(endpoint, param):
    assert _dependency_of(endpoint, param) is require_parent


@pytest.mark.parametrize(
    "endpoint,param",
    [
        (pod.get_student_config, "_"),
        (pod.update_voice_narration_preference, "_"),
    ],
)
def test_child_reachable_endpoints_depend_on_require_real_user(endpoint, param):
    assert _dependency_of(endpoint, param) is require_real_user


# ── Logic: save / list / get ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_then_list_round_trips_through_real_encryption(db_session):
    req = PodConfigsRequest(configs=[_config("Emma"), _config("Noah")])
    await pod.save_pod_configs(req, _={"role": "parent"}, db=db_session)

    configs = await pod.list_pod_configs(_={"role": "parent"}, db=db_session)
    assert {c.student_name for c in configs} == {"Emma", "Noah"}


@pytest.mark.asyncio
async def test_saving_twice_upserts_rather_than_duplicating(db_session):
    await pod.save_pod_configs(PodConfigsRequest(configs=[_config("Emma")]), _={"role": "parent"}, db=db_session)
    await pod.save_pod_configs(
        PodConfigsRequest(configs=[SessionConfig(student_name="Emma", grade="4", grade_stage=GradeStage.core_mastery)]),
        _={"role": "parent"}, db=db_session,
    )

    configs = await pod.list_pod_configs(_={"role": "parent"}, db=db_session)
    assert len(configs) == 1
    assert configs[0].grade == "4"


@pytest.mark.asyncio
async def test_get_student_config_404s_for_an_unknown_student(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await pod.get_student_config("Ghost", _={"role": "child"}, db=db_session)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_student_config_returns_the_saved_config(db_session):
    await pod.save_pod_configs(PodConfigsRequest(configs=[_config("Emma")]), _={"role": "parent"}, db=db_session)

    config = await pod.get_student_config("Emma", _={"role": "child"}, db=db_session)
    assert config.student_name == "Emma"


# ── Logic: voice-narration preference toggle ─────────────────────────────

@pytest.mark.asyncio
async def test_voice_narration_toggle_updates_only_that_field(db_session):
    await pod.save_pod_configs(
        PodConfigsRequest(configs=[_config("Emma")]), _={"role": "parent"}, db=db_session,
    )

    await pod.update_voice_narration_preference(
        "Emma", VoiceNarrationPreferenceRequest(voice_narration_enabled=False),
        _={"role": "child"}, db=db_session,
    )

    config = await pod.get_student_config("Emma", _={"role": "child"}, db=db_session)
    assert config.voice_narration_enabled is False
    assert config.grade == "3"  # untouched


@pytest.mark.asyncio
async def test_voice_narration_toggle_404s_for_an_unknown_student():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            await pod.update_voice_narration_preference(
                "Ghost", VoiceNarrationPreferenceRequest(voice_narration_enabled=True),
                _={"role": "child"}, db=session,
            )
        assert exc_info.value.status_code == 404
    await engine.dispose()


# ── Logic: delete (R6) ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_removes_the_row(db_session):
    await pod.save_pod_configs(PodConfigsRequest(configs=[_config("Emma")]), _={"role": "parent"}, db=db_session)

    await pod.delete_student_config("Emma", _={"role": "parent"}, db=db_session)

    result = await db_session.execute(select(StudentConfig).where(StudentConfig.student_name == "Emma"))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_is_a_no_op_for_an_unknown_student(db_session):
    # Deliberately does not 404 (matches routers/pod.py's own behavior: a
    # missing row is silently skipped) — this pins that choice down as a
    # test rather than leaving it as unverified, implicit behavior.
    await pod.delete_student_config("Ghost", _={"role": "parent"}, db=db_session)

    result = await db_session.execute(select(StudentConfig))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_delete_only_removes_the_named_student(db_session):
    await pod.save_pod_configs(
        PodConfigsRequest(configs=[_config("Emma"), _config("Noah")]), _={"role": "parent"}, db=db_session,
    )

    await pod.delete_student_config("Emma", _={"role": "parent"}, db=db_session)

    configs = await pod.list_pod_configs(_={"role": "parent"}, db=db_session)
    assert {c.student_name for c in configs} == {"Noah"}
