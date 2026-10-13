"""Parent-entered assessment interoperability: privacy, provenance, and framework boundaries."""
from datetime import date

import pytest
import pytest_asyncio
from fastapi.params import Depends
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, EducatorAssessmentEvidence, StudentConfig
from core.deps import require_parent
from core.encryption import encrypt_json
from routers.diagnostic import (
    create_educator_assessment_record, delete_educator_assessment_record,
    get_educator_assessment_records, get_assessment_frameworks,
)
from services.assessment_interop import (
    EducatorAssessmentInput, delete_assessment, frameworks_catalog,
    list_assessments, record_assessment,
)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        from core.encryption import initialize_encryption
        await initialize_encryption(settings.master_secret, session)
        session.add(StudentConfig(student_name="Alice", config_enc=encrypt_json({"test": True})))
        session.add(StudentConfig(student_name="Bob", config_enc=encrypt_json({"test": True})))
        await session.commit()
        yield session
    await engine.dispose()


def dibels(**overrides):
    args = dict(
        framework="dibels8", measure="ORF_WC", assessed_on=date(2026, 10, 10),
        source_name="Educator's independent DIBELS 8 report", score=86,
        score_unit="correct_per_minute", reported_band="below_benchmark",
    )
    args.update(overrides)
    return EducatorAssessmentInput(**args)


def classical(**overrides):
    args = dict(
        framework="classical", measure="oral_narration",
        assessed_on=date(2026, 10, 10),
        source_name="Instructor observation", assistance="with_a_hint",
    )
    args.update(overrides)
    return EducatorAssessmentInput(**args)


def test_catalog_has_no_proprietary_material_or_cut_scores():
    x = frameworks_catalog()
    assert [e["id"] for e in x] == ["dibels8", "classical", "external_other"]
    assert x[0]["interpretation"] == "educator_supplied_only"
    assert "ORF_WC" in x[0]["supported_measures"]
    assert "oral_narration" in x[1]["supported_measures"]
    assert not any("cut_score" in entry for entry in x)


@pytest.mark.parametrize("values", [
    {"measure": "wrong_measure"},
    {"score": None},
    {"score_unit": None},
    {"assistance": "unaided"},
    {"assessed_on": date(2099, 1, 1)},
    {"answer_text": "Do not persist assessment stimuli"},
])
def test_dibels_rejects_invalid_or_raw_answer_payloads(values):
    with pytest.raises(ValidationError):
        dibels(**values)


def test_classical_cannot_be_quantitatively_scored_or_normed():
    with pytest.raises(ValidationError):
        classical(score=99)
    with pytest.raises(ValidationError):
        classical(reported_band="at_or_above_benchmark")
    with pytest.raises(ValidationError):
        classical(assistance=None)


@pytest.mark.asyncio
async def test_encrypted_roundtrip_and_student_isolation(db):
    recorded = await record_assessment(db, "Alice", dibels())
    assert recorded["score"] == 86
    assert recorded["record_status"] == "educator_entered_unverified"
    row = (await db.execute(select(EducatorAssessmentEvidence))).scalar_one()
    assert b"86" not in row.detail_enc
    assert b"below_benchmark" not in row.detail_enc
    assert b"ORF_WC" not in row.detail_enc
    assert "ORF_WC" in str(await list_assessments(db, "Alice"))
    assert await list_assessments(db, "Bob") == []


@pytest.mark.asyncio
async def test_classical_and_external_are_separate_from_dibels(db):
    a = await record_assessment(db, "Alice", classical())
    b = await record_assessment(db, "Alice", EducatorAssessmentInput(
        framework="external_other", measure="Reading fluency", score=7,
        score_unit="points", assessed_on=date(2026, 10, 10),
        source_name="Independent local reading assessment",
    ))
    records = await list_assessments(db, "Alice")
    assert {r["framework"] for r in records} == {"classical", "external_other"}
    assert records[0]["reported_band"] is None
    assert records[1]["assistance"] == "with_a_hint"
    assert a["student_name"] == b["student_name"] == "Alice"


@pytest.mark.asyncio
async def test_instructor_can_correct_only_selected_students_record(db):
    record = await record_assessment(db, "Alice", dibels())
    assert not await delete_assessment(db, "Bob", record["id"])
    assert len(await list_assessments(db, "Alice")) == 1
    assert await delete_assessment(db, "Alice", record["id"])
    assert await list_assessments(db, "Alice") == []


@pytest.mark.asyncio
async def test_forged_ciphertext_is_not_displayed_as_evidence(db):
    await record_assessment(db, "Alice", dibels())
    row = (await db.execute(select(EducatorAssessmentEvidence))).scalar_one()
    row.detail_enc = b"invalid encrypted payload"
    await db.commit()
    assert await list_assessments(db, "Alice") == []


@pytest.mark.asyncio
async def test_unknown_student_cannot_create_a_record(db):
    with pytest.raises(LookupError):
        await record_assessment(db, "Unknown", dibels())


def test_all_routes_explicitly_require_parent():
    import inspect
    from fastapi.params import Depends as DependsType
    for route in (
        create_educator_assessment_record, delete_educator_assessment_record,
        get_educator_assessment_records, get_assessment_frameworks,
    ):
        dep = inspect.signature(route).parameters["auth"].default
        assert isinstance(dep, DependsType)
        assert dep.dependency is require_parent


@pytest.mark.asyncio
async def test_real_route_invocation_records_data(db):
    record = await create_educator_assessment_record(
        "Alice", dibels(), auth={"role": "parent"}, db=db,
    )
    rows = await get_educator_assessment_records(
        "Alice", limit=60, auth={"role": "parent"}, db=db,
    )
    assert [x["id"] for x in rows] == [record["id"]]
    await delete_educator_assessment_record(
        "Alice", record["id"], auth={"role": "parent"}, db=db,
    )
    assert await list_assessments(db, "Alice") == []
