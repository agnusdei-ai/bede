"""Canonical DIBELS / assessment model over real HTTP through the real app.

Every test runs twice: once on SQLite and once on Postgres (as a
NON-superuser role, mirroring production). Set ``BEDE_CANON_PG_URL`` to point
elsewhere; set ``BEDE_REQUIRE_PG=1`` to turn an unreachable Postgres into a
failure instead of a skip, so a CI run cannot report a pass for a backend
that never ran.

Synthetic data only (tests/canonical_assessment_fixtures.py).
"""
from __future__ import annotations

import asyncio
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import settings
from core.database import Base, ClassicalEducator, get_db
import core.pilot_assessment_models as models
from canonical_assessment_fixtures import (
    FORM, PM_FORM, SHARED_DISPLAY_NAME, World, boy_vendor_report, responses_with_errors,
    scored, skipped,
)

PG_URL = os.environ.get(
    "BEDE_CANON_PG_URL",
    "postgresql+asyncpg://bede_canon_app:synthetic-only@127.0.0.1:5433/canon_assess",
)
API = Path(__file__).resolve().parents[1]


def _pg_available() -> bool:
    async def probe():
        eng = create_async_engine(PG_URL, poolclass=NullPool)
        try:
            async with eng.connect() as conn:
                await conn.execute(text("select 1"))
            return True
        except Exception:
            return False
        finally:
            await eng.dispose()
    return asyncio.run(probe())


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from core.middleware import reset_rate_limiter
    reset_rate_limiter()
    yield
    reset_rate_limiter()


@pytest.fixture(params=["sqlite", "postgres"])
def client(request, monkeypatch, test_client_with_database_context):
    import main
    import core.database as database_module
    import core.encryption as encryption_module

    if request.param == "postgres":
        if not _pg_available():
            if os.environ.get("BEDE_REQUIRE_PG") == "1":
                pytest.fail("Postgres required (BEDE_REQUIRE_PG=1) but unreachable")
            pytest.skip("Postgres not reachable")
        url = PG_URL
    else:
        url = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/canon.sqlite"

    async def _reset():
        eng = create_async_engine(url, poolclass=NullPool)
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await eng.dispose()

    asyncio.run(_reset())
    monkeypatch.setattr(settings, "educator_pilot_enabled", True)
    monkeypatch.setattr(settings, "demo_pin", "")
    monkeypatch.setattr(settings, "elevation_enforced", False)
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database_module, "AsyncSessionLocal", factory)
    monkeypatch.setattr(database_module, "engine", engine)
    if encryption_module._DATA_KEY is None:
        from Crypto.Random import get_random_bytes
        monkeypatch.setattr(encryption_module, "_DATA_KEY", get_random_bytes(32))

    async def _override():
        async with factory() as session:
            yield session

    main.app.dependency_overrides[get_db] = _override
    with test_client_with_database_context(main.app, engine) as test_client:
        test_client.db_factory = factory
        test_client.backend = request.param
        yield test_client
    main.app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def world(client):
    return World(client).seed()


def _count(client, model) -> int:
    async def run():
        async with client.db_factory() as s:
            return (await s.execute(select(func.count()).select_from(model))).scalar_one()
    return client.portal.call(run)


def _all_counts(client) -> dict:
    return {m.__tablename__: _count(client, m) for m in (
        models.PilotAssessmentAdministration, models.PilotAssessmentScore,
        models.PilotAssessmentResponse, models.PilotAssessmentTransition,
        models.PilotAssessmentEvidence, models.PilotAssessmentProposal,
        models.PilotAssessmentDecision, models.PilotAssessmentPlan,
        models.PilotProgressMonitoringSchedule)}


def full_journey(w: World, scores=None, responses=()):
    adm = w.administer()
    w.finalize_with(adm["assessment_id"], scores or boy_vendor_report(), responses)
    w.evidence(adm["assessment_id"])
    prop = w.proposal(adm["assessment_id"])
    return adm["assessment_id"], prop


# ── Same campus works; isolation ────────────────────────────────────────────

def test_same_campus_teacher_can_run_the_whole_lifecycle(world):
    aid, prop = full_journey(world, responses=responses_with_errors())
    assert prop["abstained"] is False and prop["is_approval"] is False
    assert prop["status"] == "pending"
    d = world.decide(aid, prop["proposal_id"], {
        "action": "approve", "expected_version": 1,
        "confirmed_review_on": prop["proposed_review_on"], "rationale": "Synthetic rationale"})
    assert d["action"] == "approve" and d["teacher_id"] == world.teacher_one.id
    plan = world.client.post(f"{world.base()}/assessments/{aid}/plan",
                             json={"plan_text": "Synthetic teacher plan"},
                             headers=world.teacher_one.headers)
    assert plan.status_code == 201, plan.text
    assert plan.json()["status"] == "recorded"
    assert plan.json()["delivery_state"] == "NOT_REQUESTED"
    pm = world.client.post(f"{world.base()}/assessments/{aid}/progress-monitoring",
                           json={"measure": "PSF", "planned_dates": ["2031-09-08", "2031-09-22"]},
                           headers=world.teacher_one.headers)
    assert pm.status_code == 201, pm.text
    detail = world.client.get(f"{world.base()}/assessments/{aid}", headers=world.teacher_one.headers).json()
    assert detail["state"] == "PROGRESS_MONITORING_SCHEDULED"
    assert detail["snapshot_verified"] is True
    audit = world.client.get(f"{world.base()}/assessments/{aid}/audit",
                             headers=world.teacher_one.headers).json()
    assert audit["chain_valid"] is True
    assert [e["to_state"] for e in audit["entries"]] == [
        "DRAFT", "READY_FOR_ADMINISTRATION", "IN_PROGRESS", "COMPLETED_PENDING_REVIEW",
        "FINALIZED", "EVIDENCE_AVAILABLE", "TEACHER_DECISION_PENDING",
        "TEACHER_DECISION_RECORDED", "INSTRUCTIONAL_PLAN_READY", "PROGRESS_MONITORING_SCHEDULED"]
    assert all(e["actor_id"] == world.teacher_one.id for e in audit["entries"])
    # Scheduling progress monitoring creates NO administration.
    assert _count(world.client, models.PilotAssessmentAdministration) == 1


def _protected_requests(w: World, aid: str, pid: str | None):
    """Every learner-scoped route, read and write, with a valid body."""
    b = w.base()
    reqs = [
        ("GET", f"{b}/assessments", None),
        ("GET", f"{b}/assessments/{aid}", None),
        ("GET", f"{b}/assessments/{aid}/audit", None),
        ("GET", f"{b}/data-day?cycle=valor_q1", None),
        ("POST", f"{b}/assessments", {
            "instrument": "dibels8", "edition": "8th", "measure": "PSF", "grade": "1",
            "form_id": PM_FORM, "administration_purpose": "progress_monitoring",
            "instructional_cycle": "valor_q1", "administered_at": "2031-08-21T09:00:00+00:00",
            "report_source": "teacher_administered", "official_benchmark_window": "none"}),
        ("PUT", f"{b}/assessments/{aid}/scores", {"scores": [scored("PSF", 1)]}),
        ("POST", f"{b}/assessments/{aid}/transitions",
         {"action": "void", "expected_state": "FINALIZED", "resolution": "x"}),
        ("POST", f"{b}/assessments/{aid}/evidence", {"summary": "x"}),
        ("POST", f"{b}/assessments/{aid}/proposal", None),
        ("POST", f"{b}/assessments/{aid}/supersede", {"reason": "cross-campus attempt"}),
        ("POST", f"{b}/assessments/{aid}/plan", {"plan_text": "cross-campus"}),
        ("POST", f"{b}/assessments/{aid}/progress-monitoring",
         {"measure": "PSF", "planned_dates": ["2031-09-01"]}),
    ]
    if pid:
        reqs.append(("POST", f"{b}/assessments/{aid}/proposals/{pid}/decision",
                     {"action": "approve", "expected_version": 1}))
    return reqs


def _send(client, method, url, body, headers):
    return client.request(method, url, json=body, headers=headers)


def test_cross_campus_read_and_write_are_denied_identically_and_change_nothing(world):
    aid, prop = full_journey(world)
    before = _all_counts(world.client)
    reference = None
    for method, url, body in _protected_requests(world, aid, prop["proposal_id"]):
        r = _send(world.client, method, url, body, world.teacher_two.headers)
        assert r.status_code == 404, (method, url, r.status_code, r.text)
        if reference is None:
            reference = r.content
        assert r.content == reference  # byte-identical: no metadata disclosed
    assert _all_counts(world.client) == before


def test_substituted_campus_in_path_is_the_same_404(world):
    """Teacher One, own learner, but Campus Two's UUID in the path."""
    aid, _ = full_journey(world)
    bad = f"/pilot/campuses/{world.campus_two}/learners/{world.learner_one}/assessments/{aid}"
    r = world.client.get(bad, headers=world.teacher_one.headers)
    assert r.status_code == 404 and r.json() == {"detail": "Record not found"}
    # And Teacher Two cannot reach Learner One through their own campus.
    bad2 = f"/pilot/campuses/{world.campus_two}/learners/{world.learner_one}/assessments"
    assert world.client.get(bad2, headers=world.teacher_two.headers).json() == {"detail": "Record not found"}


def test_invalid_random_stale_and_substituted_uuids_all_return_the_same_404(world):
    aid, prop = full_journey(world)
    other_aid = world.administer(teacher=world.teacher_two, campus=world.campus_two,
                                 learner=world.learner_two)["assessment_id"]
    import uuid as _uuid
    variants = [
        f"/pilot/campuses/not-a-uuid/learners/{world.learner_one}/assessments",
        f"/pilot/campuses/{world.campus_one}/learners/{_uuid.uuid4()}/assessments",
        f"/pilot/campuses/{world.campus_one}/learners/{world.learner_one.upper()}/assessments",
        f"/pilot/campuses/00000000-0000-0000-0000-000000000000/learners/{world.learner_one}/assessments",
        f"{world.base()}/assessments/{_uuid.uuid4()}",
        f"{world.base()}/assessments/not-a-uuid",
        f"{world.base()}/assessments/{other_aid}",          # substituted: other campus's record
        f"{world.base()}/assessments/{aid}/proposals/{_uuid.uuid4()}/decision",
    ]
    bodies = set()
    for url in variants:
        method = "POST" if url.endswith("/decision") else "GET"
        body = {"action": "approve", "expected_version": 1} if method == "POST" else None
        r = _send(world.client, method, url, body, world.teacher_one.headers)
        assert r.status_code == 404, (url, r.text)
        bodies.add(r.content)
    assert len(bodies) == 1
    # Stale: a revoked grant's teacher (new token after the ev bump) gets the same body.
    world.client.delete(f"/pilot/campuses/{world.campus_one}/educators/{world.teacher_one.id}"
                        f"/learners/{world.learner_one}", headers=_admin())
    world.teacher_one.ev += 1
    r = world.client.get(f"{world.base()}/assessments/{aid}", headers=world.teacher_one.headers)
    assert r.status_code == 404 and r.content in bodies


def _admin():
    from canonical_assessment_fixtures import ADMIN
    return ADMIN


def test_revoked_grant_old_token_is_401_and_nothing_is_written(world):
    aid, prop = full_journey(world)
    old = world.teacher_one.headers
    before = _all_counts(world.client)
    world.client.delete(f"/pilot/campuses/{world.campus_one}/educators/{world.teacher_one.id}"
                        f"/learners/{world.learner_one}", headers=_admin())
    r = world.client.post(f"{world.base()}/assessments/{aid}/proposals/{prop['proposal_id']}/decision",
                          json={"action": "approve", "expected_version": 1}, headers=old)
    assert r.status_code == 401
    assert _all_counts(world.client) == before


def test_grant_revoked_mid_request_is_rechecked_at_write_time(world, monkeypatch):
    aid, prop = full_journey(world)
    import routers.pilot_campuses as g1
    real = g1._assigned
    calls = {"n": 0}

    async def revoking(db, auth, learner_id):
        calls["n"] += 1
        if calls["n"] >= 2:  # first call = request start; second = write-time recheck
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Record not found")
        return await real(db, auth, learner_id)

    before = _all_counts(world.client)
    monkeypatch.setattr(g1, "_assigned", revoking)
    r = world.client.post(f"{world.base()}/assessments/{aid}/proposals/{prop['proposal_id']}/decision",
                          json={"action": "approve", "expected_version": 1},
                          headers=world.teacher_one.headers)
    assert r.status_code == 404 and calls["n"] == 2
    monkeypatch.setattr(g1, "_assigned", real)
    assert _all_counts(world.client) == before
    proposals = world.client.get(f"{world.base()}/data-day?cycle=valor_q1",
                                 headers=world.teacher_one.headers).json()["proposed_next_steps"]
    assert proposals[0]["status"] == "pending"


def test_duplicate_same_name_learners_stay_isolated(world):
    a1 = world.administer()["assessment_id"]
    a2 = world.administer(teacher=world.teacher_two, campus=world.campus_two,
                          learner=world.learner_two)["assessment_id"]
    one = world.client.get(f"{world.base()}/assessments", headers=world.teacher_one.headers).json()
    two = world.client.get(f"{world.base(world.campus_two, world.learner_two)}/assessments",
                           headers=world.teacher_two.headers).json()
    assert [x["assessment_id"] for x in one] == [a1]
    assert [x["assessment_id"] for x in two] == [a2]
    assert one[0]["campus_id"] == world.campus_one and two[0]["campus_id"] == world.campus_two
    # Both learners share a display name; nothing here is keyed by it.
    r = world.client.get(f"/pilot/me/learners", headers=world.teacher_one.headers).json()
    assert [x["display_name"] for x in r] == [SHARED_DISPLAY_NAME]
    # Ciphertext is AAD-bound to campus:learner:row: a blob moved to the
    # other learner's row does not decrypt there.
    async def swap():
        async with world.client.db_factory() as s:
            r1 = await s.get(models.PilotAssessmentAdministration, a1)
            r2 = await s.get(models.PilotAssessmentAdministration, a2)
            return r1.content_enc, r2
    blob, _ = world.client.portal.call(swap)
    from core.encryption import aad_for, decrypt_json
    with pytest.raises(Exception):
        decrypt_json(blob, aad_for("pilot_assessment_administrations", "content_enc",
                                   f"{world.campus_two}:{world.learner_two}:{a2}"))


# ── DIBELS semantics ────────────────────────────────────────────────────────

def test_progress_monitoring_is_never_a_benchmark(world):
    # A PM record may not carry an official window, whatever Data Day it is on.
    r = world.client.post(f"{world.base()}/assessments", json={
        "instrument": "dibels8", "edition": "8th", "measure": "PSF", "grade": "1",
        "form_id": PM_FORM, "administration_purpose": "progress_monitoring",
        "instructional_cycle": "valor_q2", "administered_at": "2031-10-27T09:00:00+00:00",
        "report_source": "teacher_administered", "official_benchmark_window": "MOY"},
        headers=world.teacher_one.headers)
    assert r.status_code == 422
    pm = world.administer(purpose="progress_monitoring", cycle="valor_q2", measure="PSF",
                          window="none", form=PM_FORM)
    world.finalize_with(pm["assessment_id"], [scored("PSF", 20)])
    bm = world.administer(cycle="valor_q2", window="MOY", measure="PSF")
    world.finalize_with(bm["assessment_id"], [scored("PSF", 25)])
    packet = world.packet("valor_q2")
    g = packet["growth_by_measure"]
    assert set(g) == {"progress_monitoring", "benchmark"}
    assert [p["assessment_id"] for p in g["progress_monitoring"]["PSF"]["points"]] == [pm["assessment_id"]]
    assert [p["assessment_id"] for p in g["benchmark"]["PSF"]["points"]] == [bm["assessment_id"]]
    shown = {a["assessment_id"]: a for a in packet["current_valid_results"]}
    assert shown[pm["assessment_id"]]["administration_purpose"] == "progress_monitoring"
    assert shown[pm["assessment_id"]]["official_benchmark_window"] == "none"
    assert shown[pm["assessment_id"]]["benchmark_authorization_id"] is None


def test_benchmark_without_campus_authorization_is_refused(client):
    w = World(client).seed(benchmark_auth=False)
    before = _all_counts(client)
    r = client.post(f"{w.base()}/assessments", json={
        "instrument": "dibels8", "edition": "8th", "measure": "multiple", "grade": "1",
        "form_id": FORM, "administration_purpose": "benchmark", "instructional_cycle": "valor_q1",
        "administered_at": "2031-08-20T09:00:00+00:00", "report_source": "vendor_report",
        "official_benchmark_window": "BOY"}, headers=w.teacher_one.headers)
    assert r.status_code == 403
    assert _all_counts(client) == before


def test_benchmark_on_an_unapproved_form_is_refused(world):
    world.administer(form="SYN-UNAPPROVED", expect=403)
    ok = world.administer()
    assert ok["benchmark_authorization_id"]


def test_skipped_measure_is_never_zero_and_never_in_growth(world):
    # Zero is refused for a skipped measure.
    adm = world.administer()
    world.step(adm["assessment_id"], "mark_ready", "DRAFT")
    world.step(adm["assessment_id"], "start", "READY_FOR_ADMINISTRATION")
    bad = {**skipped("ORF_WC"), "raw_score": 0, "score_unit": "correct_per_minute"}
    world.scores(adm["assessment_id"], [bad], expect=422)
    world.scores(adm["assessment_id"], boy_vendor_report())
    world.step(adm["assessment_id"], "submit", "IN_PROGRESS")
    world.step(adm["assessment_id"], "finalize", "COMPLETED_PENDING_REVIEW")
    detail = world.client.get(f"{world.base()}/assessments/{adm['assessment_id']}",
                              headers=world.teacher_one.headers).json()
    by = {s["measure"]: s for s in detail["scores"]}
    assert by["ORF_WC"]["raw_score"] is None and by["ORF_WC"]["administration_status"] == "not_administered_by_rule"
    assert by["MAZE"]["raw_score"] is None and by["MAZE"]["reason"]
    packet = world.packet("valor_q1")
    assert "ORF_WC" not in packet["growth_by_measure"].get("benchmark", {})
    assert "MAZE" not in packet["growth_by_measure"].get("benchmark", {})
    assert {s["measure"] for s in packet["skipped_or_invalid_measures"]} == {"ORF_WC", "MAZE"}


def test_boy_vendor_report_shape_is_transcribed_as_printed(world):
    adm = world.administer(window="BOY", vendor_next="2031-12-08",
                           guidance={"support_areas": ["Synthetic support area"],
                                     "home_activities": ["Synthetic home activity"]})
    assert adm["report_source"] == "vendor_report"
    assert adm["official_benchmark_window"] == "BOY"
    assert adm["vendor_next_assessment_date"] == "2031-12-08"
    assert adm["instructional_cycle"] == "valor_q1"
    world.finalize_with(adm["assessment_id"], boy_vendor_report())
    detail = world.client.get(f"{world.base()}/assessments/{adm['assessment_id']}",
                              headers=world.teacher_one.headers).json()
    comp = next(s for s in detail["scores"] if s["measure"] == "COMPOSITE")
    # Both label vocabularies stored exactly as printed; neither computed.
    assert comp["benchmark_label"] == "Below Benchmark" and comp["support_label"] == "Some Support"
    assert comp["is_composite"] is True
    assert comp["printed_cut_points"] == {"provenance": "as printed on the source report",
                                          "values": [{"label": "printed composite cut", "value": 222.0}]}
    # Raw 240 is ABOVE the printed cut 222, yet the printed label stays: no reconciliation.
    assert comp["raw_score"] == 240
    vg = detail["vendor_guidance"]
    assert vg["attribution"].startswith("vendor guidance") and "not a Bede recommendation" in vg["attribution"]
    # Vendor guidance never becomes Bede's proposal or an approved action.
    world.evidence(adm["assessment_id"])
    prop = world.proposal(adm["assessment_id"])
    assert "Synthetic support area" not in prop["proposed_next_step"]
    assert "Synthetic home activity" not in str(prop)


def test_label_vocabularies_are_validated_against_allowed_sets(world):
    adm = world.administer()
    world.step(adm["assessment_id"], "mark_ready", "DRAFT")
    world.step(adm["assessment_id"], "start", "READY_FOR_ADMINISTRATION")
    world.scores(adm["assessment_id"], [scored("COMPOSITE", 200, unit="points",
                                               benchmark_label="Some Support")], expect=422)
    world.scores(adm["assessment_id"], [scored("COMPOSITE", 200, unit="points",
                                               support_label="At Benchmark")], expect=422)
    world.scores(adm["assessment_id"], [scored("COMPOSITE", 200, unit="points",
                                               benchmark_label="Intensive")], expect=422)


def test_vendor_window_is_never_derived_from_the_instructional_cycle(world):
    a = world.administer(cycle="valor_q1", window="none", purpose="benchmark")
    b = world.administer(cycle="valor_q1", window="MOY", purpose="benchmark")
    assert a["official_benchmark_window"] == "none" and b["official_benchmark_window"] == "MOY"
    assert a["vendor_next_assessment_date"] is None


def test_interpretation_never_overwrites_the_canonical_score(world):
    aid, prop = full_journey(world)
    before = world.client.get(f"{world.base()}/assessments/{aid}", headers=world.teacher_one.headers).json()
    world.decide(aid, prop["proposal_id"], {
        "action": "edit", "expected_version": 1, "edited_text": "Synthetic edited step",
        "rationale": "Teacher reads the composite differently"})
    after = world.client.get(f"{world.base()}/assessments/{aid}", headers=world.teacher_one.headers).json()
    assert after["scores"] == before["scores"]
    assert after["snapshot_sha256"] == before["snapshot_sha256"] and after["snapshot_verified"] is True
    # And the finalized row cannot be changed even by direct SQL (DB trigger).
    async def tamper():
        async with world.client.db_factory() as s:
            await s.execute(text("UPDATE pilot_assessment_administrations SET form_id='X' WHERE id=:i"),
                            {"i": aid})
            await s.commit()
    with pytest.raises(Exception, match="immutable"):
        world.client.portal.call(tamper)
    async def tamper_score():
        async with world.client.db_factory() as s:
            await s.execute(text("UPDATE pilot_assessment_scores SET administration_status='scored' "
                                 "WHERE administration_id=:i"), {"i": aid})
            await s.commit()
    with pytest.raises(Exception, match="immutable"):
        world.client.portal.call(tamper_score)


def test_scores_cannot_be_entered_after_finalization(world):
    aid, _ = full_journey(world)
    world.scores(aid, [scored("PSF", 99)], expect=409)


# ── Lifecycle over HTTP ─────────────────────────────────────────────────────

def test_interrupted_cannot_finalize_without_resolution(world):
    aid = world.administer()["assessment_id"]
    world.step(aid, "mark_ready", "DRAFT")
    world.step(aid, "start", "READY_FOR_ADMINISTRATION")
    world.scores(aid, [scored("PSF", 10)])
    world.step(aid, "interrupt", "IN_PROGRESS")
    world.step(aid, "finalize", "INTERRUPTED", expect=409)
    world.step(aid, "submit", "INTERRUPTED", expect=409)
    world.step(aid, "resume", "INTERRUPTED", expect=409)              # no resolution
    world.step(aid, "resume", "INTERRUPTED", resolution="Resumed same form after fire drill")
    world.step(aid, "submit", "IN_PROGRESS")
    out = world.step(aid, "finalize", "COMPLETED_PENDING_REVIEW")
    assert out["fidelity_state"] == "interrupted_resolved" and out["state"] == "FINALIZED"
    notes = [e["note"] for e in world.client.get(f"{world.base()}/assessments/{aid}/audit",
                                                 headers=world.teacher_one.headers).json()["entries"]]
    assert "Resumed same form after fire drill" in notes


def test_invalid_administration_needs_resolution_and_stays_out_of_valid_results(world):
    aid = world.administer()["assessment_id"]
    world.step(aid, "mark_ready", "DRAFT")
    world.step(aid, "start", "READY_FOR_ADMINISTRATION")
    world.scores(aid, [scored("PSF", 10)])
    world.step(aid, "invalidate", "IN_PROGRESS", expect=409)          # needs a reason
    world.step(aid, "invalidate", "IN_PROGRESS", resolution="Wrong form used")
    world.step(aid, "finalize", "INVALID_ADMINISTRATION", expect=409)
    world.step(aid, "resolve_invalid", "INVALID_ADMINISTRATION", resolution="Recorded for the file only")
    world.step(aid, "finalize", "COMPLETED_PENDING_REVIEW")
    packet = world.packet("valor_q1")
    assert [a["assessment_id"] for a in packet["current_valid_results"]] == []
    nv = packet["not_valid_administrations"][0]
    assert nv["assessment_id"] == aid and nv["fidelity_state"] == "invalid_resolved"


def test_voided_administration(world):
    aid = world.administer()["assessment_id"]
    world.step(aid, "void", "DRAFT", expect=409)  # reason required
    out = world.step(aid, "void", "DRAFT", resolution="Entered for the wrong learner")
    assert out["state"] == "VOIDED_BY_TEACHER"
    world.step(aid, "mark_ready", "VOIDED_BY_TEACHER", expect=409)
    packet = world.packet("valor_q1")
    assert packet["not_valid_administrations"][0]["state"] == "VOIDED_BY_TEACHER"


def test_finalized_is_corrected_only_by_supersede_with_audit_link(world):
    aid, _ = full_journey(world)
    world.step(aid, "void", "TEACHER_DECISION_PENDING", resolution="no", expect=409)
    r = world.client.post(f"{world.base()}/assessments/{aid}/supersede",
                          json={"reason": "Transcription error on PSF"}, headers=world.teacher_one.headers)
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["supersedes_id"] == aid and new["state"] == "DRAFT"
    old_audit = world.client.get(f"{world.base()}/assessments/{aid}/audit",
                                 headers=world.teacher_one.headers).json()
    last = old_audit["entries"][-1]
    assert last["to_state"] == "SUPERSEDED_WITH_AUDIT_LINK" and last["link_id"] == new["assessment_id"]
    assert old_audit["chain_valid"] is True
    world.finalize_with(new["assessment_id"], [*boy_vendor_report()[:1], scored("PSF", 14),
                                               *boy_vendor_report()[2:]])
    packet = world.packet("valor_q1")
    assert [a["assessment_id"] for a in packet["current_valid_results"]] == [new["assessment_id"]]
    sup = next(x for x in packet["not_valid_administrations"] if x["assessment_id"] == aid)
    assert sup["state"] == "SUPERSEDED_WITH_AUDIT_LINK" and sup["superseded_by"] == new["assessment_id"]
    # The superseded finalized row is unchanged.
    old = world.client.get(f"{world.base()}/assessments/{aid}", headers=world.teacher_one.headers).json()
    assert old["snapshot_verified"] is True


def test_concurrent_transitions_from_one_head_yield_one_winner(world):
    """Two requests that read the same head race to append the same seq."""
    aid = world.administer()["assessment_id"]
    import routers.pilot_assessments as pa
    real_state = pa._state

    async def run_two():
        import httpx
        from canonical_assessment_fixtures import World as _W  # noqa: F401
        import main
        transport = httpx.ASGITransport(app=main.app, client=("testclient", 50000))
        hdr = {**world.teacher_one.headers, "user-agent": "testclient"}
        body = {"action": "mark_ready", "expected_state": "DRAFT"}
        gate = asyncio.Event()
        waiting = {"n": 0}

        async def slow_state(db, adm_id):
            result = await real_state(db, adm_id)
            waiting["n"] += 1
            if waiting["n"] >= 2:
                gate.set()
            await asyncio.wait_for(gate.wait(), 5)
            return result

        pa._state = slow_state
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                url = f"{world.base()}/assessments/{aid}/transitions"
                return await asyncio.gather(c.post(url, json=body, headers=hdr),
                                            c.post(url, json=body, headers=hdr))
        finally:
            pa._state = real_state

    r1, r2 = world.client.portal.call(run_two)
    assert sorted([r1.status_code, r2.status_code]) == [200, 409], (r1.text, r2.text)
    audit = world.client.get(f"{world.base()}/assessments/{aid}/audit",
                             headers=world.teacher_one.headers).json()
    assert [e["to_state"] for e in audit["entries"]] == ["DRAFT", "READY_FOR_ADMINISTRATION"]
    assert audit["chain_valid"] is True


def test_replayed_decision_is_refused_and_ledger_unchanged(world):
    aid, prop = full_journey(world)
    body = {"action": "approve", "expected_version": 1}
    world.decide(aid, prop["proposal_id"], body)
    world.decide(aid, prop["proposal_id"], body, expect=409)
    world.decide(aid, prop["proposal_id"], {"action": "reject", "expected_version": 2}, expect=409)
    assert _count(world.client, models.PilotAssessmentDecision) == 1


def test_rejection_schedules_nothing_and_allows_a_fresh_proposal(world):
    aid, prop = full_journey(world)
    world.decide(aid, prop["proposal_id"], {"action": "reject", "expected_version": 1,
                                            "confirmed_review_on": "2031-10-27"}, expect=422)
    world.decide(aid, prop["proposal_id"], {"action": "reject", "expected_version": 1})
    plan = world.client.post(f"{world.base()}/assessments/{aid}/plan", json={"plan_text": "x plan"},
                             headers=world.teacher_one.headers)
    assert plan.status_code == 409
    again = world.proposal(aid)
    assert again["proposal_id"] != prop["proposal_id"] and again["status"] == "pending"
    assert _count(world.client, models.PilotAssessmentPlan) == 0
    assert _count(world.client, models.PilotProgressMonitoringSchedule) == 0


def test_hash_chain_detects_tampering_with_a_decision(world):
    aid, prop = full_journey(world)
    world.decide(aid, prop["proposal_id"], {"action": "approve", "expected_version": 1})

    async def drop_and_check():
        async with world.client.db_factory() as s:
            rows = list((await s.execute(select(models.PilotAssessmentTransition)
                                         .where(models.PilotAssessmentTransition.administration_id == aid)
                                         .order_by(models.PilotAssessmentTransition.seq))).scalars())
        import routers.pilot_assessments as pa
        assert pa.verify_chain(rows, pa._transition_fields)
        return pa.verify_chain(rows[:3] + rows[4:], pa._transition_fields)
    assert world.client.portal.call(drop_and_check) is False


# ── Calendar ────────────────────────────────────────────────────────────────

def test_calendar_is_per_campus_with_a_valor_default(client):
    w = World(client).seed(calendar=False)
    cal = client.get(f"/pilot/campuses/{w.campus_one}/calendar", headers=_admin()).json()
    assert cal["configured"] is False
    assert [c["cycle_key"] for c in cal["cycles"]] == ["valor_q1", "valor_q2", "valor_q3", "valor_q4"]
    assert all(c["data_day_on"] is None for c in cal["cycles"])  # never invented
    r = client.put(f"/pilot/campuses/{w.campus_one}/calendar",
                   json={"preset": "valor_default", "first_data_day": "2031-08-25"}, headers=_admin())
    days = [c["data_day_on"] for c in r.json()["cycles"]]
    assert days == ["2031-08-25", "2031-10-27", "2031-12-29", "2032-03-01"]  # nine weeks apart
    assert r.json()["cycles"][3]["label"] == "Valor Q4 / year-end Data Day"
    # Campus Two configures its own calendar; Campus One's is untouched.
    client.put(f"/pilot/campuses/{w.campus_two}/calendar", json={"cycles": [
        {"cycle_key": "term_a", "label": "Synthetic Term A review"},
        {"cycle_key": "term_b", "label": "Synthetic Term B review"}]}, headers=_admin())
    two = client.get(f"/pilot/campuses/{w.campus_two}/calendar", headers=_admin()).json()
    assert [c["cycle_key"] for c in two["cycles"]] == ["term_a", "term_b"]
    w.administer(cycle="valor_q1", teacher=w.teacher_two, campus=w.campus_two,
                 learner=w.learner_two, expect=422)
    # Teachers cannot change calendars.
    r = client.put(f"/pilot/campuses/{w.campus_one}/calendar", json={"preset": "valor_default"},
                   headers=w.teacher_one.headers)
    assert r.status_code in (401, 403)


def test_no_fall_winter_spring_schedule_is_hard_coded():
    for rel in ("services/canonical_assessment.py", "routers/pilot_assessments.py",
                "core/pilot_assessment_models.py", "services/assessment_lifecycle.py"):
        src = (API / rel).read_text().lower()
        for season in ("fall", "winter", "spring", "autumn"):
            assert not re.search(rf"\b{season}\b", src), (rel, season)


# ── Data Day packet ─────────────────────────────────────────────────────────

def test_normal_q1_to_q4_run_and_the_packet(world):
    ids = {}
    run = [("valor_q1", "BOY", 12, datetime(2031, 8, 20, 9, tzinfo=timezone.utc)),
           ("valor_q2", "MOY", 18, datetime(2031, 10, 20, 9, tzinfo=timezone.utc)),
           ("valor_q3", "none", 23, datetime(2031, 12, 20, 9, tzinfo=timezone.utc)),
           ("valor_q4", "EOY", 30, datetime(2032, 2, 20, 9, tzinfo=timezone.utc))]
    for i, (cycle, window, psf, when) in enumerate(run):
        adm = world.administer(cycle=cycle, window=window, measure="PSF", when=when)
        world.finalize_with(adm["assessment_id"], [scored("PSF", psf)],
                            responses_with_errors() if i == 3 else ())
        world.evidence(adm["assessment_id"])
        ids[cycle] = adm["assessment_id"]
    q4 = ids["valor_q4"]
    prop = world.proposal(q4)
    before = _all_counts(world.client)
    packet = world.packet("valor_q4")
    assert _all_counts(world.client) == before  # reading the packet writes nothing
    assert [a["assessment_id"] for a in packet["current_valid_results"]] == [q4]
    assert [a["assessment_id"] for a in packet["prior_valid_results"]] == [
        ids["valor_q1"], ids["valor_q2"], ids["valor_q3"]]
    changes = packet["growth_by_measure"]["benchmark"]["PSF"]["changes"]
    assert [c["change"] for c in changes] == [6, 5, 7]
    assert packet["observed_error_patterns"] == {"PSF": {"onset_rime_only": 2}}
    assert {e["assessment_id"] for e in packet["cited_evidence"]} == set(ids.values())
    assert packet["proposed_next_steps"][0]["proposal_id"] == prop["proposal_id"]
    assert packet["controls"][0]["actions"] == ["approve", "edit", "reject"]
    assert packet["recommended_next_review"][0]["status"] == "proposed_awaiting_teacher_confirmation"
    assert packet["boundaries"] == {"changes_official_scores": False, "alters_placement": False,
                                    "starts_instruction": False, "delivers_instruction": False}
    assert all(a["chain_valid"] for a in packet["audit_history"]["administrations"])
    # Q1's packet does not see Q2-Q4.
    q1 = world.packet("valor_q1")
    assert [a["assessment_id"] for a in q1["current_valid_results"]] == [ids["valor_q1"]]
    assert q1["prior_valid_results"] == []
    # Exercise approve through the packet's own control path.
    ctl = packet["controls"][0]
    r = world.client.post(ctl["path"], json={"action": "approve",
                                             "expected_version": ctl["expected_version"]},
                          headers=world.teacher_one.headers)
    assert r.status_code == 200
    after = world.packet("valor_q4")
    assert after["prior_teacher_decisions"][0]["outcome"] == {"plan_recorded": False,
                                                              "delivery_state": "NOT_REQUESTED"}
    assert after["audit_history"]["decisions_chain_valid"] is True


def test_progress_monitoring_series_packet(world):
    pm_ids = []
    for day, raw in ((3, 14), (10, 17), (17, 16)):
        adm = world.administer(purpose="progress_monitoring", cycle="valor_q1", measure="PSF",
                               window="none", form=PM_FORM,
                               when=datetime(2031, 9, day, 9, tzinfo=timezone.utc))
        world.finalize_with(adm["assessment_id"], [scored("PSF", raw)])
        pm_ids.append(adm["assessment_id"])
    g = world.packet("valor_q1")["growth_by_measure"]
    assert list(g) == ["progress_monitoring"]
    assert [c["change"] for c in g["progress_monitoring"]["PSF"]["changes"]] == [3, -1]


def test_packet_never_reveals_another_campus(world):
    full_journey(world)
    world.administer(teacher=world.teacher_two, campus=world.campus_two, learner=world.learner_two)
    two = world.packet("valor_q1", teacher=world.teacher_two, campus=world.campus_two,
                       learner=world.learner_two)
    blob = str(two)
    assert world.learner_one not in blob and world.campus_one not in blob
    world.packet("valor_q1", teacher=world.teacher_two, expect=404)


def test_no_route_auto_advances_or_delivers(world):
    """Recommendation creation changes only the proposal; no plan, schedule or delivery."""
    aid, prop = full_journey(world)
    assert _count(world.client, models.PilotAssessmentPlan) == 0
    assert _count(world.client, models.PilotProgressMonitoringSchedule) == 0
    d = world.decide(aid, prop["proposal_id"], {"action": "approve", "expected_version": 1})
    assert d["confirmed_review_on"] is None  # proposed date is not confirmed by approval alone
    assert _count(world.client, models.PilotAssessmentPlan) == 0
    src = (API / "routers/pilot_assessments.py").read_text()
    assert "delivery_state=\"NOT_REQUESTED\"" in src
    assert "DELIVERED" not in src


def test_every_learner_table_is_listed_for_the_deletion_lane():
    scoped = {t.name for t in models.Base.metadata.sorted_tables
              if t.name.startswith("pilot_") and "learner_id" in t.c
              and t.name in {m.__tablename__ for m in vars(models).values()
                             if isinstance(m, type) and hasattr(m, "__tablename__")
                             and m.__module__ == models.__name__}}
    assert scoped == {t.name for t in models.LEARNER_SCOPED_TABLES}
    doc = (API.parent / "docs/CANONICAL_ASSESSMENT_MODEL.md").read_text()
    for name in scoped:
        assert f"`{name}`" in doc, name


def test_the_model_doc_is_in_cis_change_filter():
    """A doc-only edit must still run the guard that reads the doc."""
    wf = (API.parent / ".github/workflows/test.yml").read_text()
    line = next(ln for ln in wf.splitlines() if "grep -qE" in ln)
    alternatives = line.split("'")[1].strip("^()").split("|")
    assert r"docs/CANONICAL_ASSESSMENT_MODEL\.md" in alternatives
