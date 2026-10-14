"""Signed roster capacity != Locuto membership capacity.

Synthetic students/credentials only. No Locuto or OpenAI services contacted.
"""
from types import SimpleNamespace

import pytest
from fastapi.params import Depends
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, StudentConfig
from core.deps import require_parent
from routers.pod import get_roster_capacity
from services.roster_capacity import snapshot, LOCUTO_V1_MESSAGING_POD_MAX_MEMBERS


@pytest.mark.asyncio
async def test_signed_classroom_capacity_can_exceed_ten_messaging_members(monkeypatch):
    from core import license_state
    monkeypatch.setattr(license_state, "effective_info", lambda: SimpleNamespace(seats=75))
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:
            for number in range(24):
                db.add(StudentConfig(
                    student_name=f"Synthetic-{number:03d}",
                    config_enc=b"FAKE TEST FIXTURE NOT A REAL STUDENT CONFIG",
                ))
            await db.commit()
            status = await snapshot(db)
            assert status["enrolled_students"] == 24
            assert status["licensed_children"] == 75
            assert status["remaining_licensed_children"] == 51
            assert status["capacity_authority"] == "signed_bede_license"
            assert status["locuto_messaging_pod_max_members"] == 10
            assert status["messaging_limit_applies_to_student_roster"] is False
            assert status["locuto_entitlement_verified"] is False
            assert status["locuto_organization_max_children"] is None
            # The actual route uses the same snapshot, not a different calculation.
            response = await get_roster_capacity(_={"role": "parent"}, db=db)
            assert response == status
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_no_license_does_not_invent_a_locuto_org_limit(monkeypatch):
    from core import license_state
    monkeypatch.setattr(license_state, "effective_info", lambda: None)
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:
            result = await snapshot(db)
            assert result["capacity_authority"] == "no_active_signed_student_limit"
            assert result["licensed_children"] is None
            assert result["remaining_licensed_children"] is None
            assert result["locuto_organization_max_children"] is None
    finally:
        await engine.dispose()


def test_roster_capacity_requires_actual_parent_not_educator_or_child():
    import inspect
    depends = inspect.signature(get_roster_capacity).parameters["_"].default
    assert isinstance(depends, Depends)
    assert depends.dependency is require_parent


def test_locuto_v1_pod_limit_is_not_an_organizational_entitlement():
    assert LOCUTO_V1_MESSAGING_POD_MAX_MEMBERS == 10
    # A future Locuto entitlement adapter must check the entitlement's
    # authentic signature and its max_children in its own domain; neither
    # a guessed 250 nor a per-conversation limit constitutes that evidence.
    assert not hasattr(__import__("services.roster_capacity", fromlist=["x"]), "ORGANIZATIONAL_MAX_STUDENTS")
