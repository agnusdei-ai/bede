"""Valor pilot G2: one complete teacher journey on real routes and a real DB.

authorized evidence -> source-linked recommendation -> approve/edit/reject
-> durable, hash-chained decision -> authorized instruction for follow-up.

Synthetic campuses and learners only (#598 fixtures). Every negative case
#588 names for G2 is here: unauthorized learner, cross-campus same-name
learner, revoked grant, replayed decision, stale version, and a grant
revoked between request start and the decision itself.
"""
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, ClassicalEducator
from core.encryption import initialize_encryption
from core.pilot_journey_models import PilotDecision, PilotRecommendation
import routers.pilot_journey as journey
from routers.pilot_campuses import (
    CampusInput, LearnerInput, approve_educator_membership,
    approve_roster_grant, create_campus, create_learner, revoke_roster_grant,
)
from routers.pilot_journey import (
    DecisionInput, authorized_instruction, decide, decision_ledger,
    list_evidence, list_recommendations, record_evidence,
    request_recommendation, verify_chain,
)
from services.assessment_interop import EducatorAssessmentSubmission
from services.educator_access import provision_educator
from services.pilot_recommender import EvidenceRecord, recommend
from valor_synthetic_fixture import assert_synthetic_fixture, two_campus_fixture

ADMIN = {"role": "parent", "auth_method": "webauthn_uv"}
ASSESSED = date.today() - timedelta(days=3)


@pytest_asyncio.fixture
async def db(monkeypatch):
    monkeypatch.setattr(settings, "educator_pilot_enabled", True)
    monkeypatch.setattr(settings, "demo_pin", "")
    # G2_GAP_DB_URL (a postgresql+asyncpg URL to a scratch database) runs
    # every test on this fixture against Postgres, the same switch
    # test_valor_pilot_g2_gaps.py uses. Default: in-memory SQLite.
    pg_url = os.environ.get("G2_GAP_DB_URL")
    engine = (create_async_engine(pg_url) if pg_url else create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    ))
    async with engine.begin() as conn:
        if pg_url:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await initialize_encryption(settings.master_secret, session)
        yield session
    await engine.dispose()


async def token(db, account):
    row = await db.get(ClassicalEducator, account["id"])
    return {"role": "educator", "auth_method": "webauthn_uv",
            "sub": account["id"], "ev": row.credential_version}


async def two_campuses(db):
    assert_synthetic_fixture()
    alpha, beta = two_campus_fixture()
    ta = await provision_educator(db, "valor.g2.teacher.a", "synthetic-passphrase-a-strong")
    tb = await provision_educator(db, "valor.g2.teacher.b", "synthetic-passphrase-b-strong")
    a = (await create_campus(CampusInput(title=alpha.label), auth=ADMIN, db=db))["campus_id"]
    b = (await create_campus(CampusInput(title=beta.label), auth=ADMIN, db=db))["campus_id"]
    # Same display name on both campuses, on purpose.
    la = (await create_learner(a, LearnerInput(display_name=alpha.learners[0].display_name), auth=ADMIN, db=db))["learner_id"]
    lb = (await create_learner(b, LearnerInput(display_name=beta.learners[0].display_name), auth=ADMIN, db=db))["learner_id"]
    await approve_educator_membership(a, ta["id"], auth=ADMIN, db=db)
    await approve_educator_membership(b, tb["id"], auth=ADMIN, db=db)
    await approve_roster_grant(a, ta["id"], la, auth=ADMIN, db=db)
    await approve_roster_grant(b, tb["id"], lb, auth=ADMIN, db=db)
    return ta, tb, a, b, la, lb


def dibels(measure="PSF", band="strategic_some_risk", score=22.0, unit="correct_per_minute"):
    return EducatorAssessmentSubmission(
        framework="dibels8", measure=measure, assessed_on=ASSESSED,
        source_name="Synthetic DIBELS 8 report", score=score, score_unit=unit,
        reported_band=band, assessed_grade="1", assessment_window="middle_of_year",
    )


async def evidence_and_recommendation(db, teacher, learner):
    tok = await token(db, teacher)
    ev = await record_evidence(learner, dibels(), auth=tok, db=db)
    rec = await request_recommendation(learner, auth=tok, db=db)
    return tok, ev, rec


# ── The journey ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approve_journey_end_to_end(db):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok, ev, rec = await evidence_and_recommendation(db, ta, la)

    assert rec["abstained"] is False and rec["status"] == "pending"
    assert rec["source_evidence_ids"] == [ev["evidence_id"]]
    assert "phoneme segmentation" in rec["proposal"]
    assert rec["authorized_instruction"] is None
    # Nothing is instruction until a teacher decides.
    assert (await authorized_instruction(la, auth=tok, db=db))["authorized_instruction"] is None

    out = await decide(la, rec["recommendation_id"],
                       DecisionInput(action="approve", expected_version=1), auth=tok, db=db)
    assert out["status"] == "approved" and out["version"] == 2
    assert out["authorized_instruction"] == rec["proposal"]

    follow_up = await authorized_instruction(la, auth=tok, db=db)
    assert follow_up["authorized_instruction"] == rec["proposal"]
    assert follow_up["source_evidence_ids"] == [ev["evidence_id"]]

    ledger = await decision_ledger(la, auth=tok, db=db)
    assert ledger["chain_valid"] is True
    assert [e["action"] for e in ledger["entries"]] == ["approve"]
    assert ledger["entries"][0]["educator_id"] == ta["id"]


@pytest.mark.asyncio
async def test_edit_authorizes_the_teachers_text_not_the_draft(db):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok, _, rec = await evidence_and_recommendation(db, ta, la)
    mine = "Ten minutes of oral segmentation with picture cards, three times this week."
    out = await decide(la, rec["recommendation_id"],
                       DecisionInput(action="edit", expected_version=1, edited_text=mine,
                                     note="Matches our phonics scope this term"),
                       auth=tok, db=db)
    assert out["status"] == "edited" and out["authorized_instruction"] == mine
    assert out["proposal"] == rec["proposal"]  # the original draft is kept for audit
    ledger = await decision_ledger(la, auth=tok, db=db)
    entry = ledger["entries"][0]
    assert entry["action"] == "edit" and entry["note"] == "Matches our phonics scope this term"
    assert entry["content_sha256"] == journey._sha(mine)


@pytest.mark.asyncio
async def test_reject_never_becomes_instruction(db):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok, _, rec = await evidence_and_recommendation(db, ta, la)
    out = await decide(la, rec["recommendation_id"],
                       DecisionInput(action="reject", expected_version=1), auth=tok, db=db)
    assert out["status"] == "rejected" and out["authorized_instruction"] is None
    assert (await authorized_instruction(la, auth=tok, db=db))["authorized_instruction"] is None
    ledger = await decision_ledger(la, auth=tok, db=db)
    assert ledger["entries"][0]["content_sha256"] == "" and ledger["chain_valid"]


@pytest.mark.asyncio
async def test_follow_up_loop_new_evidence_new_recommendation_chain_grows(db):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok, _, first = await evidence_and_recommendation(db, ta, la)
    await decide(la, first["recommendation_id"],
                 DecisionInput(action="approve", expected_version=1), auth=tok, db=db)
    await record_evidence(la, dibels(band="core_minimal_risk", score=48.0), auth=tok, db=db)
    second = await request_recommendation(la, auth=tok, db=db)
    assert "continue current instruction" in second["proposal"]
    await decide(la, second["recommendation_id"],
                 DecisionInput(action="reject", expected_version=1), auth=tok, db=db)
    ledger = await decision_ledger(la, auth=tok, db=db)
    assert [e["seq"] for e in ledger["entries"]] == [1, 2]
    assert ledger["entries"][1]["prev_hash"] == ledger["entries"][0]["entry_hash"]
    assert ledger["chain_valid"] is True
    # The latest AUTHORIZED instruction is still the approved one.
    assert (await authorized_instruction(la, auth=tok, db=db))["recommendation_id"] == first["recommendation_id"]


# ── Server-enforced approval: replay, stale, concurrency ────────────────────

@pytest.mark.asyncio
async def test_replayed_decision_is_refused_and_ledger_unchanged(db):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok, _, rec = await evidence_and_recommendation(db, ta, la)
    body = DecisionInput(action="approve", expected_version=1)
    await decide(la, rec["recommendation_id"], body, auth=tok, db=db)
    for replay in (body, DecisionInput(action="reject", expected_version=2)):
        with pytest.raises(HTTPException) as exc:
            await decide(la, rec["recommendation_id"], replay, auth=tok, db=db)
        assert exc.value.status_code == 409
    assert len((await decision_ledger(la, auth=tok, db=db))["entries"]) == 1


@pytest.mark.asyncio
async def test_stale_version_is_refused(db):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok, _, rec = await evidence_and_recommendation(db, ta, la)
    with pytest.raises(HTTPException) as exc:
        await decide(la, rec["recommendation_id"],
                     DecisionInput(action="approve", expected_version=7), auth=tok, db=db)
    assert exc.value.status_code == 409
    assert (await list_recommendations(la, auth=tok, db=db))[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_compare_and_swap_loses_a_race_without_a_ledger_entry(db, monkeypatch):
    """Simulate a concurrent decision landing between the route's read and
    its write: the CAS must refuse, and no ledger row may be written."""
    ta, _, _, _, la, _ = await two_campuses(db)
    tok, _, rec = await evidence_and_recommendation(db, ta, la)
    real = journey.review_recommendation

    async def racing(*args, **kwargs):
        await db.execute(update(PilotRecommendation)
                         .where(PilotRecommendation.id == rec["recommendation_id"])
                         .values(status="rejected", version=2))
        return await real(*args, **kwargs)

    monkeypatch.setattr(journey, "review_recommendation", racing)
    with pytest.raises(HTTPException) as exc:
        await decide(la, rec["recommendation_id"],
                     DecisionInput(action="approve", expected_version=1), auth=tok, db=db)
    assert exc.value.status_code == 409
    assert (await db.execute(select(PilotDecision))).scalars().all() == []


@pytest.mark.asyncio
async def test_one_pending_recommendation_at_a_time(db):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok, _, _ = await evidence_and_recommendation(db, ta, la)
    with pytest.raises(HTTPException) as exc:
        await request_recommendation(la, auth=tok, db=db)
    assert exc.value.status_code == 409


def test_decision_input_contract():
    with pytest.raises(ValidationError):
        DecisionInput(action="edit", expected_version=1)
    with pytest.raises(ValidationError):
        DecisionInput(action="edit", expected_version=1, edited_text="   ")
    with pytest.raises(ValidationError):
        DecisionInput(action="approve", expected_version=1, edited_text="sneaky")
    with pytest.raises(ValidationError):
        DecisionInput(action="approve", expected_version=0)
    with pytest.raises(ValidationError):
        DecisionInput(action="publish", expected_version=1)
    with pytest.raises(ValidationError):
        DecisionInput(action="approve", expected_version=1, campus_id="forged")


# ── Authorization: cross-campus, same-name, revoked, mid-flight ─────────────

@pytest.mark.asyncio
async def test_cross_campus_same_name_teacher_is_denied_everywhere(db):
    ta, tb, _, _, la, lb = await two_campuses(db)
    tok_a, ev, rec = await evidence_and_recommendation(db, ta, la)
    tok_b = await token(db, tb)
    rid = rec["recommendation_id"]
    attempts = [
        lambda: list_evidence(la, auth=tok_b, db=db),
        lambda: record_evidence(la, dibels(), auth=tok_b, db=db),
        lambda: request_recommendation(la, auth=tok_b, db=db),
        lambda: list_recommendations(la, auth=tok_b, db=db),
        lambda: decide(la, rid, DecisionInput(action="approve", expected_version=1), auth=tok_b, db=db),
        lambda: decision_ledger(la, auth=tok_b, db=db),
        lambda: authorized_instruction(la, auth=tok_b, db=db),
        # Teacher B using HER OWN learner's path with campus A's recommendation id.
        lambda: decide(lb, rid, DecisionInput(action="approve", expected_version=1), auth=tok_b, db=db),
    ]
    for attempt in attempts:
        with pytest.raises(HTTPException) as exc:
            await attempt()
        assert exc.value.status_code == 404
    # Nothing leaked into B's learner, and A's recommendation is untouched.
    assert await list_evidence(lb, auth=tok_b, db=db) == []
    assert (await list_recommendations(la, auth=tok_a, db=db))[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_revoked_grant_ends_access_and_decision(db):
    ta, _, a, _, la, _ = await two_campuses(db)
    tok, _, rec = await evidence_and_recommendation(db, ta, la)
    await revoke_roster_grant(a, ta["id"], la, auth=ADMIN, db=db)
    # The old bearer token is dead (credential version bumped)...
    with pytest.raises(HTTPException) as exc:
        await decide(la, rec["recommendation_id"],
                     DecisionInput(action="approve", expected_version=1), auth=tok, db=db)
    assert exc.value.status_code == 401
    # ...and a fresh session still has no grant.
    fresh = await token(db, ta)
    for call in (
        lambda: decide(la, rec["recommendation_id"],
                       DecisionInput(action="approve", expected_version=1), auth=fresh, db=db),
        lambda: authorized_instruction(la, auth=fresh, db=db),
    ):
        with pytest.raises(HTTPException) as exc:
            await call()
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_grant_revoked_mid_decision_blocks_without_writing(db, monkeypatch):
    """The governed orchestrator re-checks authorization at decision time.
    If the grant disappears after the route's first check, nothing is
    persisted and no ledger entry is written."""
    ta, _, _, _, la, _ = await two_campuses(db)
    tok, _, rec = await evidence_and_recommendation(db, ta, la)
    real = journey._assigned
    calls = {"n": 0}

    async def first_ok_then_revoked(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return await real(*args, **kwargs)
        raise HTTPException(status_code=404, detail="Record not found")

    monkeypatch.setattr(journey, "_assigned", first_ok_then_revoked)
    with pytest.raises(HTTPException) as exc:
        await decide(la, rec["recommendation_id"],
                     DecisionInput(action="approve", expected_version=1), auth=tok, db=db)
    assert exc.value.status_code == 404
    assert calls["n"] == 2  # the in-orchestrator re-check actually ran
    monkeypatch.setattr(journey, "_assigned", real)
    assert (await list_recommendations(la, auth=tok, db=db))[0]["status"] == "pending"
    assert (await db.execute(select(PilotDecision))).scalars().all() == []


@pytest.mark.asyncio
async def test_pilot_disabled_closes_every_route(db, monkeypatch):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok = await token(db, ta)
    monkeypatch.setattr(settings, "educator_pilot_enabled", False)
    with pytest.raises(HTTPException) as exc:
        await list_evidence(la, auth=tok, db=db)
    assert exc.value.status_code in (401, 403)


# ── Abstention ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_abstains_without_evidence_and_persists_nothing(db):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok = await token(db, ta)
    out = await request_recommendation(la, auth=tok, db=db)
    assert out["abstained"] is True and "No evidence" in out["reason"]
    assert await list_recommendations(la, auth=tok, db=db) == []


@pytest.mark.asyncio
async def test_abstains_on_uninterpretable_external_scores(db):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok = await token(db, ta)
    await record_evidence(la, EducatorAssessmentSubmission(
        framework="external_other", measure="District screener", assessed_on=ASSESSED,
        source_name="Synthetic screener", score=71.0, score_unit="points",
    ), auth=tok, db=db)
    out = await request_recommendation(la, auth=tok, db=db)
    assert out["abstained"] is True


# ── Ledger integrity ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tampered_ledger_is_detected(db):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok, _, rec = await evidence_and_recommendation(db, ta, la)
    await decide(la, rec["recommendation_id"],
                 DecisionInput(action="reject", expected_version=1), auth=tok, db=db)
    rows = (await db.execute(select(PilotDecision))).scalars().all()
    assert verify_chain(rows)
    rows[0].action = "approve"  # rewrite history in memory
    assert not verify_chain(rows)
    await db.rollback()


def test_no_route_updates_or_deletes_the_decision_ledger():
    src = Path(journey.__file__).read_text()
    assert "update(PilotDecision" not in src
    assert "delete(PilotDecision" not in src
    assert "db.delete(" not in src


# ── Invocation: the routes are mounted and use the governed review path ─────

def test_g2_routes_are_mounted_on_the_real_app():
    """Reads main.app itself. FastAPI includes routers lazily, so the router
    object must appear as an _IncludedRouter's original_router; a module
    that defines routes nobody mounts would otherwise pass every test above."""
    import main
    mounted = [getattr(r, "original_router", None) for r in main.app.routes]
    assert journey.router in mounted
    paths = {r.path for r in journey.router.routes}
    for suffix in ("evidence", "recommendations",
                   "recommendations/{recommendation_id}/decision",
                   "decisions", "instruction"):
        assert f"/pilot/me/learners/{{learner_id}}/{suffix}" in paths


@pytest.mark.asyncio
async def test_decision_goes_through_the_governed_orchestrator(db, monkeypatch):
    ta, _, _, _, la, _ = await two_campuses(db)
    tok, _, rec = await evidence_and_recommendation(db, ta, la)
    real = journey.review_recommendation
    seen = []

    async def spy(scope, proposal, decision, **kw):
        seen.append((scope, proposal.proposal_id, decision))
        return await real(scope, proposal, decision, **kw)

    monkeypatch.setattr(journey, "review_recommendation", spy)
    await decide(la, rec["recommendation_id"],
                 DecisionInput(action="approve", expected_version=1), auth=tok, db=db)
    assert len(seen) == 1
    scope, pid, decision = seen[0]
    assert pid == rec["recommendation_id"] and decision.value == "approve"
    assert scope.learner_id == la and scope.educator_id == ta["id"]


# ── Recommender policy (pure) ───────────────────────────────────────────────

def _rec(i, measure, band=None, framework="dibels8", assistance=None, days_ago=1):
    return EvidenceRecord(f"e{i}", framework, measure,
                          date.today() - timedelta(days=days_ago), band, assistance)


def test_intensive_need_outranks_strategic_and_caps_at_two():
    p = recommend([_rec(1, "ORF_WC", "strategic_some_risk"),
                   _rec(2, "PSF", "intensive_at_risk"),
                   _rec(3, "LNF", "strategic_some_risk")])
    assert not p.abstained and p.source_evidence_ids[0] == "e2"
    assert len(p.source_evidence_ids) == 2


def test_latest_record_per_measure_wins():
    p = recommend([_rec(1, "PSF", "intensive_at_risk", days_ago=40),
                   _rec(2, "PSF", "core_minimal_risk", days_ago=2)])
    assert "continue current instruction" in p.text and p.source_evidence_ids == ("e2",)


def test_same_day_results_use_the_later_entry_not_a_random_id():
    """Two results for one measure on one date: the later ENTRY is current.
    Ids are random UUIDs, so ordering on them flipped this case at random
    (caught by CI on Python 3.12 after passing locally)."""
    day = date.today() - timedelta(days=1)
    first = EvidenceRecord("ffff", "dibels8", "PSF", day, "intensive_at_risk",
                           recorded_at=datetime(2026, 10, 1, 9, 0))
    later = EvidenceRecord("0000", "dibels8", "PSF", day, "core_minimal_risk",
                           recorded_at=datetime(2026, 10, 1, 15, 0))
    for order in ([first, later], [later, first]):
        p = recommend(order)
        assert "continue current instruction" in p.text and p.source_evidence_ids == ("0000",)


def test_composite_and_unreported_bands_alone_abstain():
    assert recommend([_rec(1, "COMPOSITE", "intensive_at_risk")]).abstained
    assert recommend([_rec(1, "PSF", "not_reported")]).abstained
    assert recommend([_rec(1, "PSF", None)]).abstained


def test_classical_observation_suggests_a_next_step():
    p = recommend([_rec(1, "oral_narration", framework="classical", assistance="with_help")])
    assert not p.abstained and "oral narration" in p.text and p.source_evidence_ids == ("e1",)


def test_recommendations_describe_instruction_never_the_child():
    judgments = ("struggl", "behind", "weak", "poor", "slow", "disabilit",
                 "dyslex", "deficit", "low ability", "at risk child", "lazy")
    cases = [
        [_rec(1, m, "intensive_at_risk")] for m in
        ("LNF", "PSF", "NWF_CLS", "NWF_WRC", "WRF", "ORF_WC", "ORF_ACCURACY", "MAZE")
    ] + [[_rec(1, "composition", framework="classical", assistance=a)]
         for a in ("with_help", "with_a_hint", "unaided")]
    for records in cases:
        p = recommend(records)
        assert not p.abstained
        prose = (p.text + " " + " ".join(p.rationale)).lower()
        for word in judgments:
            assert word not in prose, (word, prose)
