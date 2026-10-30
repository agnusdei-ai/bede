"""Practice Coach, PR 1 (docs/PRACTICE_COACH.md, register entry 39).

Golden test #1 is a parent's real graded Latin quiz, hand-typed into
services/practice/packs/latin/golden/ so the photos never enter this public
repository. The diagnosis and practice checks below run from that file alone.
"""
import base64
import copy
import inspect
import json
from pathlib import Path

import pytest
import pytest_asyncio

from fastapi import HTTPException
from fastapi.params import Depends as DependsType
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, PracticeAssessment, PracticeSetRecord, StudentConfig
from core.deps import require_parent
from core.encryption import encrypt_json
from models.practice import (
    ApproveSetRequest,
    ConfirmAssessmentRequest,
    Diagnosis,
    GradedAssessment,
    PhotoPage,
    ReadPhotosRequest,
    teacher_mark_count,
)
from routers import practice as practice_router
from services.practice import upload_safety
from services.practice import core_checks, extract, pipeline
from services.practice.core_checks import normalize
from services.practice.packs import get_pack

GOLDEN = json.loads(
    (Path(__file__).resolve().parents[1] / "services/practice/packs/latin/golden/latin_quiz_1.expected.json")
    .read_text(encoding="utf-8")
)


def _image(fmt: str, color) -> bytes:
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(out, format=fmt)
    return out.getvalue()


PNG = _image("PNG", (200, 30, 30))
JPEG = _image("JPEG", (30, 30, 200))


def golden() -> GradedAssessment:
    return GradedAssessment.model_validate(copy.deepcopy(GOLDEN["assessment"]))


def settled() -> GradedAssessment:
    """The golden quiz after the parent confirms the two flagged readings."""
    data = copy.deepcopy(GOLDEN["assessment"])
    for section in data["sections"]:
        for item in section["items"]:
            if item.get("ask_parent"):
                item["ask_parent"] = None
                item["confidence"] = 0.95
    return GradedAssessment.model_validate(data)


def refs(errors, category):
    return {e.item_ref for e in errors if e.category == category}


# ── Golden test #1 ────────────────────────────────────────────────────────────

def test_golden_teacher_count_and_flagged_readings():
    a = golden()
    assert teacher_mark_count(a) == GOLDEN["expected_teacher_mark_count"]
    flagged = {line.split(":")[0] for line in a.needs_parent()}
    assert flagged == set(GOLDEN["expected_ask_parent_refs"])


def test_golden_diagnosis_includes_what_it_must():
    d = pipeline.diagnose(settled())
    for want in GOLDEN["expected_diagnosis"]["must_include"]:
        match = [e for e in d.errors if e.category == want["category"] and e.item_ref == want["item_ref"]]
        assert match, f"missing {want}"
        assert match[0].audience == want["audience"]
    assert {s.category for s in d.strengths} >= set(GOLDEN["expected_diagnosis"]["must_include_strengths"])


def test_golden_diagnosis_never_flags_alba_or_an_unmarked_macron():
    d = pipeline.diagnose(settled())
    for banned in GOLDEN["expected_diagnosis"]["must_not_include"]:
        assert banned["item_ref"] not in refs(d.errors, banned["category"]), banned


def test_golden_practice_meets_its_constraints():
    a = settled()
    d = pipeline.diagnose(a)
    ps = pipeline.plan(d, a)
    want = GOLDEN["expected_practice_constraints"]
    assert set(want["targets_include"]) <= set(ps.targets)
    assert ps.est_minutes <= want["max_minutes"]
    assert ps.recheck_schedule == want["recheck_schedule"]
    bank = {normalize(w) for w in a.word_bank()}
    for item in ps.items:
        for word in normalize(item.expected_answer).split():
            assert word in bank, f"{word!r} is not a word the child has met"
    for banned in want["must_not_repeat_verbatim"]:
        for item in ps.items:
            assert not (item.prompt == banned["prompt"] and banned["stimulus"] in item.prompt)
    # The missed scene itself (a duck swimming) is not re-asked.
    assert not any("duck swimming" in i.prompt for i in ps.items)
    assert any(i.kind == "retrieval" for i in ps.items)


def test_golden_summary_states_only_what_was_diagnosed():
    a = settled()
    d = pipeline.diagnose(a)
    text = pipeline.parent_summary(a, d, pipeline.plan(d, a))
    assert text.startswith("12 of 13, by the teacher's marks.")
    assert "avis (bird) for anas (duck)" in text
    assert "complete sentences" in text
    assert "3 days" in text


# ── The rules a careless implementation gets wrong ────────────────────────────

def _quiz(items, fmt="color_fill", bank=None):
    return GradedAssessment.model_validate({"subject": "latin", "sections": [{
        "label": "Part 3", "instructions": "", "required_format": fmt,
        "word_bank": bank or [], "items": items}]})


def test_a_blank_the_teacher_marked_correct_is_never_unanswered():
    a = _quiz([{"number": 1, "prompt": "Alba", "student_response": None, "teacher_mark": "correct"}])
    assert not refs(pipeline.diagnose(a).errors, "core.unanswered")


def test_a_genuine_blank_is_reported_to_the_parent_only():
    a = _quiz([{"number": 1, "prompt": "Fusca", "student_response": "", "teacher_mark": "unmarked"}])
    errors = [e for e in pipeline.diagnose(a).errors if e.category == "core.unanswered"]
    assert errors and errors[0].audience == "parent_only"


def test_macron_omission_only_when_the_teacher_marked_it():
    item = {"number": 1, "prompt": "___ in aquā.", "student_response": "rēmos", "teacher_correction": "rēmōs"}
    marked = _quiz([dict(item, teacher_mark="incorrect")], fmt="single_word", bank=["rēmōs"])
    unmarked = _quiz([dict(item, teacher_mark="correct", teacher_correction=None)], fmt="single_word", bank=["rēmōs"])
    assert refs(pipeline.diagnose(marked).errors, "latin.macron_omission") == {"Part 3 #1"}
    assert not refs(pipeline.diagnose(unmarked).errors, "latin.macron_omission")


def test_an_unsettled_reading_is_neither_diagnosed_nor_planned():
    data = copy.deepcopy(GOLDEN["assessment"])
    data["sections"][0]["items"][4]["confidence"] = 0.5  # #5 unclear
    a = GradedAssessment.model_validate(data)
    d = pipeline.diagnose(a)
    assert not refs(d.errors, "latin.vocab.hypernym_substitution")
    with pytest.raises(ValueError):
        pipeline.plan(d, a)


def test_answering_what_with_doing_is_its_own_category():
    a = _quiz([{"number": 1, "prompt": "Quid est?", "student_response": "volat",
                "teacher_mark": "incorrect", "teacher_correction": "avis"}],
              fmt="single_word", bank=["avis", "volat", "est"])
    assert refs(pipeline.diagnose(a).errors, "latin.question.what_vs_doing") == {"Part 3 #1"}


def test_no_identity_field_can_be_stored():
    data = copy.deepcopy(GOLDEN["assessment"])
    for extra in ({"student_name": "x"}, {"school": "x"}, {"teacher": "x"}, {"date": "2026-01-30"}):
        with pytest.raises(ValidationError):
            GradedAssessment.model_validate({**data, **extra})


def test_every_category_has_a_remediation_strategy_and_detects_are_real():
    pack = get_pack("latin")
    cats = pack.taxonomy["categories"]
    assert all(c.get("remediation_strategy") for c in cats.values())
    assert set(pack.manifest["detects"]) <= set(cats)
    assert all(v["remediation_strategy"] for v in core_checks.TAXONOMY.values())


# ── Reading photos ────────────────────────────────────────────────────────────

def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


@pytest.mark.asyncio
async def test_only_jpeg_png_and_pdf_pages_are_accepted():
    pages = await upload_safety.prepare_pages([b64(PNG), b64(JPEG)])
    assert [m for m, _ in pages] == ["image/png", "image/png"]  # always re-encoded to a fresh PNG
    for bad in (b"GIF89a....", b"not an image", PNG[:40], b"\xff\xd8\xff" + b"junk" * 8):
        with pytest.raises(extract.PhotoRejected):
            await upload_safety.prepare_pages([b64(bad)])
    with pytest.raises(extract.PhotoRejected):
        await upload_safety.prepare_pages(["***not base64***"])
    with pytest.raises(extract.PhotoRejected):
        await upload_safety.prepare_pages([b64(PNG + b"0" * upload_safety.MAX_PAGE_BYTES)])


class _Reply:
    def __init__(self, text):
        self.content = [type("B", (), {"text": text})()]


class StubClient:
    def __init__(self, text):
        self.text, self.calls = text, []
        self.messages = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Reply(self.text)


def _routing(monkeypatch, *, local: bool, cloud: str | None, local_client=None, cloud_client=None):
    from services.adapters import router
    import services.ai_service as ai_service

    configured = (["local"] if local else []) + ([cloud] if cloud else [])
    monkeypatch.setattr(router, "configured_adapters", lambda *a, **k: configured)
    monkeypatch.setattr(router, "preference_order", lambda *a, **k: ["local", "openai", "mistral", "anthropic"])
    monkeypatch.setattr(router, "resolve_local_only", lambda *a, **k: local_client)
    if cloud_client is not None:
        monkeypatch.setattr(ai_service, "_client", cloud_client)


def _req(**kw):
    return ReadPhotosRequest(subject="latin", pages=[PhotoPage(data=b64(PNG)), PhotoPage(data=b64(JPEG))], **kw)


@pytest.mark.asyncio
async def test_cloud_reading_needs_consent_and_makes_no_call_without_it(monkeypatch):
    cloud = StubClient(json.dumps(GOLDEN["assessment"]))
    _routing(monkeypatch, local=False, cloud="openai", cloud_client=cloud)
    with pytest.raises(extract.ConsentRequired) as exc:
        await extract.read_pages(_req())
    assert exc.value.provider == "openai"
    assert cloud.calls == []
    assert (await extract.read_pages(_req(cloud_consent=True))).subject == "latin"
    assert len(cloud.calls) == 1


@pytest.mark.asyncio
async def test_a_local_model_is_used_by_default_and_never_falls_back(monkeypatch):
    local, cloud = StubClient(json.dumps(GOLDEN["assessment"])), StubClient("{}")
    _routing(monkeypatch, local=True, cloud="openai", local_client=local, cloud_client=cloud)
    await extract.read_pages(_req())
    assert len(local.calls) == 1 and cloud.calls == []
    _routing(monkeypatch, local=False, cloud="openai", cloud_client=cloud)
    with pytest.raises(extract.ReadingUnavailable):
        await extract.read_pages(_req(route="local"))
    assert cloud.calls == []


@pytest.mark.asyncio
async def test_pages_go_out_in_the_drawing_canvas_shape_the_real_adapter_accepts(monkeypatch):
    """Validated against the real OpenAI-compatible translator, not a looser stub."""
    from services.adapters.openai_compatible_adapter import _build_request

    local = StubClient(json.dumps(GOLDEN["assessment"]))
    _routing(monkeypatch, local=True, cloud=None, local_client=local)
    await extract.read_pages(_req())
    sent = local.calls[0]
    blocks = sent["messages"][0]["content"]
    assert [b["type"] for b in blocks] == ["image", "image", "text"]
    assert blocks[0]["source"]["media_type"] == "image/png"
    assert base64.b64decode(blocks[0]["source"]["data"]).startswith(b"\x89PNG")
    translated = _build_request("vision-model", sent)
    parts = translated["messages"][-1]["content"]
    assert sum(1 for p in parts if p["type"] == "image_url") == 2
    assert "Never transcribe a person's name" in sent["system"]
    assert "alba" in sent["system"].lower()  # the Latin pack's own hints


@pytest.mark.asyncio
async def test_a_reading_that_smuggles_in_a_name_is_refused(monkeypatch):
    bad = {**GOLDEN["assessment"], "student_name": "Someone"}
    _routing(monkeypatch, local=True, cloud=None, local_client=StubClient(json.dumps(bad)))
    with pytest.raises(extract.ReadingFailed):
        await extract.read_pages(_req())


# ── Routes and storage ────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        from core.encryption import initialize_encryption
        await initialize_encryption(settings.master_secret, session)
        for name in ("Alice", "Bob"):
            session.add(StudentConfig(student_name=name, config_enc=encrypt_json({"test": True})))
        await session.commit()
        yield session
    await engine.dispose()


PARENT = {"role": "parent"}


def test_every_practice_route_requires_a_parent():
    for route in practice_router.router.routes:
        deps = [p.default for p in inspect.signature(route.endpoint).parameters.values()
                if isinstance(p.default, DependsType)]
        assert any(d.dependency is require_parent for d in deps), route.path


@pytest.mark.asyncio
async def test_the_whole_flow_and_the_photo_is_never_stored(db, monkeypatch):
    _routing(monkeypatch, local=True, cloud=None, local_client=StubClient(json.dumps(GOLDEN["assessment"])))
    read = await practice_router.read_assessment("Alice", _req(), auth=PARENT, db=db)
    assert read["status"] == "needs_review" and len(read["ask_parent"]) == 2

    with pytest.raises(HTTPException) as exc:
        await practice_router.plan_practice("Alice", read["id"], auth=PARENT, db=db)
    assert exc.value.status_code == 409

    confirmed = await practice_router.confirm_assessment(
        "Alice", read["id"], ConfirmAssessmentRequest(assessment=settled()), auth=PARENT, db=db)
    assert confirmed["status"] == "confirmed"

    planned = await practice_router.plan_practice("Alice", read["id"], auth=PARENT, db=db)
    assert planned["status"] == "draft" and planned["practice_set"]["items"]

    approved = await practice_router.approve_set("Alice", planned["set_id"], ApproveSetRequest(), auth=PARENT, db=db)
    assert approved["status"] == "approved"
    with pytest.raises(HTTPException) as exc:
        await practice_router.discard_set("Alice", planned["set_id"], auth=PARENT, db=db)
    assert exc.value.status_code == 409

    # Nothing in either table holds the pages, raw or decrypted.
    from core.encryption import decrypt_json, student_aad
    from core import student_keys
    key = await student_keys.get_existing(db, "Alice")
    for model, table in ((PracticeAssessment, "practice_assessments"), (PracticeSetRecord, "practice_sets")):
        for row in (await db.execute(select(model))).scalars():
            plain = json.dumps(decrypt_json(row.detail_enc, student_aad(table, "detail_enc", "Alice"), key))
            for page in (PNG, JPEG):
                assert b64(page)[:24] not in plain
                assert page[12:40] not in row.detail_enc
            for media, data in await upload_safety.prepare_pages([b64(PNG), b64(JPEG)]):
                assert data[40:80] not in plain


@pytest.mark.asyncio
async def test_another_childs_records_answer_exactly_like_missing_ones(db):
    made = await practice_router.enter_assessment(
        "Alice", ConfirmAssessmentRequest(assessment=settled()), auth=PARENT, db=db)
    planned = await practice_router.plan_practice("Alice", made["id"], auth=PARENT, db=db)
    for call in (
        lambda: practice_router.plan_practice("Bob", made["id"], auth=PARENT, db=db),
        lambda: practice_router.plan_practice("Alice", 99999, auth=PARENT, db=db),
        lambda: practice_router.approve_set("Bob", planned["set_id"], ApproveSetRequest(), auth=PARENT, db=db),
    ):
        with pytest.raises(HTTPException) as exc:
            await call()
        assert (exc.value.status_code, exc.value.detail) == (404, "Record not found")


@pytest.mark.asyncio
async def test_unknown_students_and_subjects_are_refused(db):
    with pytest.raises(HTTPException) as exc:
        await practice_router.enter_assessment(
            "Nobody", ConfirmAssessmentRequest(assessment=settled()), auth=PARENT, db=db)
    assert exc.value.status_code == 404
    other = settled().model_copy(update={"subject": "chemistry"})
    with pytest.raises(HTTPException) as exc:
        await practice_router.enter_assessment("Alice", ConfirmAssessmentRequest(assessment=other), auth=PARENT, db=db)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_deleting_the_student_deletes_their_practice_records(db):
    from services.student_deletion import delete_all_student_data

    made = await practice_router.enter_assessment(
        "Alice", ConfirmAssessmentRequest(assessment=settled()), auth=PARENT, db=db)
    await practice_router.plan_practice("Alice", made["id"], auth=PARENT, db=db)
    counts = await delete_all_student_data(db, "Alice")
    assert counts["practice_assessments"] == 1 and counts["practice_sets"] == 1
    assert not (await db.execute(select(PracticeAssessment))).scalars().all()


def test_practice_never_reaches_beyond_a_smaller_word_bank():
    data = copy.deepcopy(GOLDEN["assessment"])
    data["sections"][0]["word_bank"] = ["canis", "avis", "anas", "natat", "currit", "volat", "edit", "est"]
    data["sections"] = data["sections"][:1]
    a = GradedAssessment.model_validate(data)
    ps = pipeline.plan(pipeline.diagnose(a), a)
    bank = {normalize(w) for w in a.word_bank()}
    used = {w for i in ps.items for w in normalize(i.expected_answer).split()}
    assert used <= bank, used - bank
