"""A teacher-confirmed classroom quiz, saved against one roster learner
(routers/pilot_journey.py's /quiz-results routes,
services/teacher_quiz_records.py).

Sample campuses, teachers and learners only. Every case drives the real
route functions on a real database, the pattern
tests/test_valor_pilot_g2_journey.py uses.
"""
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from core.database import Base
from core.pilot_assessment_models import LEARNER_SCOPED_TABLES
from core.pilot_journey_models import (
    PilotEvidence, PilotQuizResult, PilotRecommendation,
)
from models.practice import SettledScore, TeacherQuestion, TeacherQuiz
from routers.pilot_campuses import CampusInput, LearnerInput, create_campus, create_learner, \
    approve_educator_membership, approve_roster_grant, revoke_roster_grant
from routers.pilot_journey import (
    QuizResultSave, list_quiz_results, quiz_mastery, save_quiz_result,
)
from services import pilot_learner_deletion, teacher_quiz_records
from tests.test_valor_pilot_g2_journey import ADMIN, db, token, two_campuses  # noqa: F401

PROMPTS = ["7 + 5", "36 - 19", "12 x 4", "Name a shape with four equal sides."]


def quiz(subject="mathematics", grade="3", approved=True, prompts=PROMPTS) -> TeacherQuiz:
    return TeacherQuiz(
        title="Sample week 3 check", subject=subject, grade=grade, approved=approved,
        questions=[TeacherQuestion(number=i + 1, type="short_answer", prompt=p, answer="x",
                                   points=1, key_approved=True)
                   for i, p in enumerate(prompts)],
    )


def save(points=(1, 0, 1, 1), submission=None, supersedes=None, q=None) -> QuizResultSave:
    return QuizResultSave(
        submission_id=submission or f"save-{uuid.uuid4().hex[:12]}",
        confirmed=True, quiz=q or quiz(), supersedes=supersedes,
        results=[SettledScore(number=i + 1, points=p) for i, p in enumerate(points)],
    )


async def _count(db, model, learner=None) -> int:
    query = select(func.count()).select_from(model)
    if learner:
        query = query.where(model.learner_id == learner)
    return (await db.execute(query)).scalar_one()


# ── Saving ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_confirmed_quiz_is_saved_against_the_selected_learner(db):
    ta, _, a, _, la, _ = await two_campuses(db)
    out = await save_quiz_result(la, save(), auth=await token(db, ta), db=db)
    assert out["status"] == "current" and out["replayed"] is False
    assert (out["total"], out["possible"]) == (3.0, 4)
    assert out["source"] == "teacher_confirmed_classroom_quiz"
    row = await db.get(PilotQuizResult, out["result_id"])
    assert (row.campus_id, row.learner_id, row.recorded_by) == (a, la, ta["id"])


@pytest.mark.asyncio
async def test_a_retry_returns_the_original_and_stores_one_row(db):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok = await token(db, ta)
    body = save(submission="retry-save-0001")
    first = await save_quiz_result(la, body, auth=tok, db=db)
    again = await save_quiz_result(la, body, auth=tok, db=db)
    assert again["result_id"] == first["result_id"] and again["replayed"] is True
    assert await _count(db, PilotQuizResult, la) == 1
    assert (await quiz_mastery(la, auth=tok, db=db))["observations"] == 3


@pytest.mark.asyncio
async def test_a_reused_save_id_with_different_marks_is_refused(db):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok = await token(db, ta)
    await save_quiz_result(la, save(submission="reused-save-01"), auth=tok, db=db)
    with pytest.raises(HTTPException) as err:
        await save_quiz_result(la, save(points=(0, 0, 0, 0), submission="reused-save-01"), auth=tok, db=db)
    assert err.value.status_code == 422
    assert await _count(db, PilotQuizResult, la) == 1


@pytest.mark.asyncio
async def test_nothing_is_saved_until_the_teacher_has_confirmed_everything(db):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok = await token(db, ta)
    with pytest.raises(ValidationError):
        QuizResultSave(submission_id="unconfirmed-1", confirmed=False, quiz=quiz(),
                       results=[SettledScore(number=1, points=1)])
    with pytest.raises(HTTPException) as unsettled:
        await save_quiz_result(la, QuizResultSave(
            submission_id="unsettled-01", confirmed=True, quiz=quiz(),
            results=[SettledScore(number=1, points=1), SettledScore(number=2, points=None)],
        ), auth=tok, db=db)
    assert unsettled.value.status_code == 409
    with pytest.raises(HTTPException) as unapproved:
        await save_quiz_result(la, save(q=quiz(approved=False)), auth=tok, db=db)
    assert unapproved.value.status_code == 422
    assert await _count(db, PilotQuizResult) == 0


# ── Corrections ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_correction_replaces_the_earlier_result_everywhere(db):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok = await token(db, ta)
    first = await save_quiz_result(la, save(points=(0, 0, 0, 0)), auth=tok, db=db)
    fixed = await save_quiz_result(la, save(points=(1, 1, 1, 1), supersedes=first["result_id"]),
                                   auth=tok, db=db)
    history = {r["result_id"]: r for r in await list_quiz_results(la, auth=tok, db=db)}
    assert history[first["result_id"]]["status"] == "superseded"
    assert history[first["result_id"]]["superseded_by"] == fixed["result_id"]
    assert history[fixed["result_id"]]["supersedes"] == first["result_id"]

    mastery = await quiz_mastery(la, auth=tok, db=db)
    assert mastery["observations"] == 3
    sources = {s["result_id"] for skill in mastery["skills"] for s in skill["sources"]}
    assert sources == {fixed["result_id"]}
    assert all(s["outcome"] == "correct" for skill in mastery["skills"] for s in skill["sources"])


@pytest.mark.asyncio
async def test_a_result_can_be_corrected_once(db):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok = await token(db, ta)
    first = await save_quiz_result(la, save(), auth=tok, db=db)
    await save_quiz_result(la, save(supersedes=first["result_id"]), auth=tok, db=db)
    with pytest.raises(HTTPException) as err:
        await save_quiz_result(la, save(supersedes=first["result_id"]), auth=tok, db=db)
    assert err.value.status_code == 409
    assert await _count(db, PilotQuizResult, la) == 2


@pytest.mark.asyncio
async def test_a_correction_cannot_reach_another_learners_result(db):
    ta, tb, _, _, la, lb = await two_campuses(db)
    other = await save_quiz_result(lb, save(), auth=await token(db, tb), db=db)
    with pytest.raises(HTTPException) as err:
        await save_quiz_result(la, save(supersedes=other["result_id"]), auth=await token(db, ta), db=db)
    assert err.value.status_code == 404
    assert (await db.get(PilotQuizResult, other["result_id"])).status == "current"


# ── Progress ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mapped_questions_feed_the_estimate_and_unmapped_ones_stay_in_history(db):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok = await token(db, ta)
    out = await save_quiz_result(la, save(points=(1, 0, 1, 1)), auth=tok, db=db)
    assert [q["skill_id"] for q in out["questions"]] == [
        "oa.add_within_20", "nbt.subtract_within_100", "oa.multiplication_facts", None]
    mastery = await quiz_mastery(la, auth=tok, db=db)
    assert mastery["computed_on_read"] is True and mastery["stored"] is False
    assert mastery["unmapped_questions"] == 1 and mastery["observations"] == 3
    assert mastery["weight"] == teacher_quiz_records.QUIZ_EVIDENCE_WEIGHT
    by_skill = {s["skill_id"]: s for s in mastery["skills"]}
    assert by_skill["nbt.subtract_within_100"]["sources"] == [
        {"result_id": out["result_id"], "question": 2, "outcome": "incorrect"}]


@pytest.mark.asyncio
async def test_a_subject_with_no_engine_records_history_only(db):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok = await token(db, ta)
    await save_quiz_result(la, save(q=quiz(subject="history")), auth=tok, db=db)
    mastery = await quiz_mastery(la, auth=tok, db=db)
    assert mastery["skills"] == [] and mastery["unmapped_questions"] == 4
    assert len(await list_quiz_results(la, auth=tok, db=db)) == 1


@pytest.mark.asyncio
async def test_the_estimate_is_never_stored(db):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok = await token(db, ta)
    await save_quiz_result(la, save(), auth=tok, db=db)
    await quiz_mastery(la, auth=tok, db=db)
    for table in Base.metadata.sorted_tables:
        if "mastery" in table.name or "evidence_log" in table.name:
            assert (await db.execute(select(func.count()).select_from(table))).scalar_one() == 0, table.name


@pytest.mark.asyncio
async def test_quiz_results_are_not_published_as_official_assessments(db):
    ta, _, _, _, la, _ = await two_campuses(db)
    await save_quiz_result(la, save(), auth=await token(db, ta), db=db)
    for table in (*LEARNER_SCOPED_TABLES, PilotEvidence.__table__, PilotRecommendation.__table__):
        assert (await db.execute(select(func.count()).select_from(table))).scalar_one() == 0, table.name


# ── Authorization ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_teacher_cannot_save_for_a_learner_they_were_not_granted(db):
    ta, _, _, _, _, lb = await two_campuses(db)
    tok = await token(db, ta)
    for call in (save_quiz_result(lb, save(), auth=tok, db=db),
                 list_quiz_results(lb, auth=tok, db=db),
                 quiz_mastery(lb, auth=tok, db=db)):
        with pytest.raises(HTTPException) as err:
            await call
        assert err.value.status_code == 404
    assert await _count(db, PilotQuizResult) == 0


@pytest.mark.asyncio
async def test_a_revoked_grant_ends_access(db):
    ta, _, a, _, la, _ = await two_campuses(db)
    await save_quiz_result(la, save(), auth=await token(db, ta), db=db)
    await revoke_roster_grant(a, ta["id"], la, auth=ADMIN, db=db)
    with pytest.raises(HTTPException) as err:
        await save_quiz_result(la, save(), auth=await token(db, ta), db=db)
    assert err.value.status_code in (401, 404)


@pytest.mark.asyncio
async def test_a_campus_whose_authorization_was_withdrawn_stores_nothing(db):
    from services.educator_access import provision_educator

    teacher = await provision_educator(db, "quiz.unauthorized.teacher", "sample-passphrase-strong")
    from core import school_authorization
    from school_auth_helper import authorize_campus

    campus = (await create_campus(CampusInput(title="Sample withdrawn campus"), auth=ADMIN, db=db))["campus_id"]
    await authorize_campus(db, campus)
    learner = (await create_learner(campus, LearnerInput(display_name="Sample Learner"), auth=ADMIN, db=db))["learner_id"]
    await approve_educator_membership(campus, teacher["id"], auth=ADMIN, db=db)
    await approve_roster_grant(campus, teacher["id"], learner, auth=ADMIN, db=db)
    await school_authorization.revoke(db, campus, reason="sample withdrawal")
    await db.commit()
    with pytest.raises(HTTPException) as err:
        await save_quiz_result(learner, save(), auth=await token(db, teacher), db=db)
    assert err.value.status_code == 403
    assert await _count(db, PilotQuizResult) == 0


def test_the_routes_follow_the_practice_coach_switch():
    from core.deps import require_practice_coach_enabled
    from routers.pilot_journey import router

    paths = {"/pilot/me/learners/{learner_id}/quiz-results", "/pilot/me/learners/{learner_id}/quiz-mastery"}
    found = [r for r in router.routes if r.path in paths]
    assert len(found) == 3
    for route in found:
        assert any(d.dependency is require_practice_coach_enabled for d in route.dependencies), route.path


# ── Storage and deletion ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_stored_result_is_ciphertext_bound_to_its_learner(db):
    from core.encryption import aad_for, decrypt_json

    ta, _, a, _, la, _ = await two_campuses(db)
    out = await save_quiz_result(la, save(), auth=await token(db, ta), db=db)
    row = await db.get(PilotQuizResult, out["result_id"])
    assert b"36 - 19" not in row.detail_enc and b"Sample week 3" not in row.detail_enc
    with pytest.raises(Exception):
        decrypt_json(row.detail_enc, aad_for("pilot_quiz_results", "detail_enc", f"{a}:other:{row.id}"))


@pytest.mark.asyncio
async def test_deleting_the_learner_deletes_their_quiz_results(db):
    ta, _, a, _, la, _ = await two_campuses(db)
    await save_quiz_result(la, save(), auth=await token(db, ta), db=db)
    assert PilotQuizResult.__table__ in pilot_learner_deletion.pilot_cascade()
    await pilot_learner_deletion.delete_pilot_learner(db, a, la)
    assert await _count(db, PilotQuizResult, la) == 0
