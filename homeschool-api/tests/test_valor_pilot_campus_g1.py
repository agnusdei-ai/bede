"""Valor pilot G1: real DB grants, duplicate names, cross-campus denials.

Only fake instructors/campuses/learner names. Not a school deployment test.
"""
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, PilotLearner
from core.encryption import initialize_encryption
from routers.pilot_campuses import (
    CampusInput, LearnerInput, approve_educator_membership,
    approve_roster_grant, create_campus, create_learner, get_my_learner,
    list_my_learners, revoke_roster_grant, disable_campus_membership,
)
from services.educator_access import provision_educator

ADMIN = {"role": "parent", "auth_method": "webauthn_uv"}


@pytest_asyncio.fixture
async def db(monkeypatch):
    monkeypatch.setattr(settings, "educator_pilot_enabled", True)
    monkeypatch.setattr(settings, "is_demo_deployment", False)
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await initialize_encryption(settings.master_secret, session)
        yield session
    await engine.dispose()


def token(account):
    return {"role": "educator", "auth_method": "webauthn_uv",
            "sub": account["id"], "ev": 1}


async def fixture_two_campuses(db):
    teacher_a = await provision_educator(db, "valor.teacher.a", "synthetic-passphrase-a-strong")
    teacher_b = await provision_educator(db, "valor.teacher.b", "synthetic-passphrase-b-strong")
    a = (await create_campus(CampusInput(title="Synthetic campus A"), auth=ADMIN, db=db))["campus_id"]
    b = (await create_campus(CampusInput(title="Synthetic campus B"), auth=ADMIN, db=db))["campus_id"]
    same_a = (await create_learner(a, LearnerInput(display_name="Alex"), auth=ADMIN, db=db))["learner_id"]
    same_b = (await create_learner(b, LearnerInput(display_name="Alex"), auth=ADMIN, db=db))["learner_id"]
    await approve_educator_membership(a, teacher_a["id"], auth=ADMIN, db=db)
    await approve_educator_membership(b, teacher_b["id"], auth=ADMIN, db=db)
    await approve_roster_grant(a, teacher_a["id"], same_a, auth=ADMIN, db=db)
    await approve_roster_grant(b, teacher_b["id"], same_b, auth=ADMIN, db=db)
    return teacher_a, teacher_b, a, b, same_a, same_b


@pytest.mark.asyncio
async def test_duplicate_names_cannot_cross_synthetic_campus(db):
    ea, eb, a, b, la, lb = await fixture_two_campuses(db)
    assert a != b and la != lb
    assert await list_my_learners(auth=token(ea), db=db) == [
        {"learner_id": la, "campus_id": a, "display_name": "Alex"}
    ]
    assert (await get_my_learner(la, auth=token(ea), db=db))["display_name"] == "Alex"
    for teacher, forbidden in [(ea, lb), (eb, la)]:
        with pytest.raises(HTTPException) as exc:
            await get_my_learner(forbidden, auth=token(teacher), db=db)
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_admin_cannot_use_passkeyless_identity_to_manage_pilot(db):
    with pytest.raises(HTTPException) as exc:
        await create_campus(
            CampusInput(title="Denied campus"),
            auth={"role": "parent", "auth_method": "password"},
            db=db,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_cross_campus_grant_denied_and_unassigned_learner_hidden(db):
    ea, eb, a, b, la, lb = await fixture_two_campuses(db)
    with pytest.raises(HTTPException) as exc:
        await approve_roster_grant(a, ea["id"], lb, auth=ADMIN, db=db)
    assert exc.value.status_code == 404
    extra = (await create_learner(a, LearnerInput(display_name="Unassigned"), auth=ADMIN, db=db))["learner_id"]
    with pytest.raises(HTTPException) as exc:
        await get_my_learner(extra, auth=token(ea), db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_grant_revocation_invalidates_teacher_token_and_denies_roster(db):
    ea, eb, a, b, la, lb = await fixture_two_campuses(db)
    await revoke_roster_grant(a, ea["id"], la, auth=ADMIN, db=db)
    with pytest.raises(HTTPException) as exc:
        await list_my_learners(auth=token(ea), db=db)
    assert exc.value.status_code == 401
    new_token = token(ea) | {"ev": 2}
    assert await list_my_learners(auth=new_token, db=db) == []
    with pytest.raises(HTTPException) as exc:
        await get_my_learner(la, auth=new_token, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_disabled_membership_blocks_all_learners(db):
    ea, eb, a, b, la, lb = await fixture_two_campuses(db)
    await disable_campus_membership(a, ea["id"], auth=ADMIN, db=db)
    with pytest.raises(HTTPException) as exc:
        await get_my_learner(la, auth=token(ea) | {"ev": 2}, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_campus_identity_and_name_are_not_plaintext_in_learner_table(db):
    ea, eb, a, b, la, lb = await fixture_two_campuses(db)
    row = await db.get(PilotLearner, la)
    assert b"Alex" not in row.display_enc
    assert row.id == la and row.campus_id == a


@pytest.mark.asyncio
async def test_missing_invalid_or_unapproved_ids_never_enumerate(db):
    ea, eb, a, b, la, lb = await fixture_two_campuses(db)
    for bad in ("Alex", "not-a-uuid", "00000000-0000-0000-0000-000000000000"):
        with pytest.raises(HTTPException) as exc:
            await get_my_learner(bad, auth=token(ea), db=db)
        assert exc.value.status_code == 404
