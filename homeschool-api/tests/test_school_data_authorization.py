"""School data authorization: a school official opts in before a campus stores
learner data (core/school_authorization.py, routers/pilot_campuses.py).

Drives the assembled app over real HTTP (tests/g1_harness.py). Runs on SQLite
by default and on Postgres when G1_TEST_DATABASE_URL is set. Synthetic
identities only. Readiness, not certification: nothing here asserts that the
wording or the mechanism is legally sufficient.
"""
import hashlib
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from core import school_authorization as sa
from core.database import PilotCampusDataAuthorization as Row
from g1_harness import world  # noqa: F401 (fixture)

NAME = "Synthetic Official Name"
FORBIDDEN_IN_AUDIT = (NAME, "Synthetic", "Learner")


def _url(campus):
    return f"/pilot/campuses/{campus}/data-authorization"


def _hash(w, campus=None):
    return w.client.get(_url(campus or w.campus_one), headers=w.admin()).json()["notice_hash"]


def _post(w, campus, headers, *, role="administrator", notice_hash=None, name=NAME):
    return w.client.post(_url(campus), headers=headers, json={
        "notice_hash": notice_hash or _hash(w, campus), "authorizer_name": name,
        "authorizer_role": role})


def _new_campus(w, *, member=None):
    """A fresh, UNAUTHORIZED campus, optionally with a teacher member."""
    r = w.client.post("/pilot/campuses", json={"title": "Synthetic Campus Three"}, headers=w.admin())
    assert r.status_code == 201, r.text
    campus = r.json()["campus_id"]
    if member:
        assert w.client.post(f"/pilot/campuses/{campus}/educators/{member}",
                             headers=w.admin()).status_code == 204
    return campus


def _rows(w, campus):
    async def count():
        async with w.factory() as s:
            return (await s.execute(select(func.count()).select_from(Row)
                                    .where(Row.campus_id == campus))).scalar_one()
    return w.run(count)


def _learner_count(w, campus):
    r = w.client.get(f"/pilot/owner/campuses/{campus}/learners", headers=w.admin())
    assert r.status_code == 200, r.text
    return len(r.json())


def _create_learner(w, campus):
    return w.client.post(f"/pilot/campuses/{campus}/learners",
                         json={"display_name": "Synthetic Learner"}, headers=w.admin())


def _expect_gate(resp, campus):
    assert resp.status_code == 403, (resp.status_code, resp.text)
    body = resp.json()["detail"]
    assert body["error"] == "school_authorization_required"
    assert body["authorize_path"] == f"/pilot/campuses/{campus}/data-authorization"
    assert isinstance(body["message"], str) and body["message"]
    assert set(body) == {"error", "message", "authorize_path"}


# ── The notice ──────────────────────────────────────────────────────────────

def test_notice_hash_is_the_sha256_of_the_files_exact_bytes():
    path = Path(sa.NOTICE_PATH)
    assert sa.notice_hash() == hashlib.sha256(path.read_bytes()).hexdigest()
    assert path.read_text(encoding="utf-8").splitlines()[0].startswith("Notice version: ")
    assert sa.notice_version() == path.read_text(encoding="utf-8").splitlines()[0].split(": ", 1)[1]


# ── Opt-in ──────────────────────────────────────────────────────────────────

def test_unauthorized_status_shape_and_text(world):
    w = world
    campus = _new_campus(w)
    body = w.client.get(_url(campus), headers=w.admin()).json()
    assert body["authorized"] is False and body["stale"] is False
    assert body["authorized_at"] is None and body["authorized_by"] is None
    assert body["notice_hash"] == sa.notice_hash()
    assert body["notice_version"] == sa.notice_version()
    assert body["notice_text"] == sa.notice_text()


def test_administrator_can_authorize_once_and_it_is_idempotent(world):
    w = world
    campus = _new_campus(w)
    first = _post(w, campus, w.admin())
    assert first.status_code == 201, first.text
    assert first.json()["authorized"] is True and first.json()["authorized_by"] == "administrator"
    again = _post(w, campus, w.admin())
    assert again.status_code == 200 and again.json()["authorized"] is True
    assert _rows(w, campus) == 1


def test_a_member_teacher_can_authorize_as_teacher(world):
    w = world
    campus = _new_campus(w, member=w.teacher_one)
    r = _post(w, campus, w.teacher(w.teacher_one), role="teacher")
    assert r.status_code == 201, r.text
    assert r.json()["authorized_by"] == "teacher"
    # The teacher can read the status as well.
    assert w.client.get(_url(campus), headers=w.teacher(w.teacher_one)).json()["authorized"] is True
    assert _post(w, campus, w.teacher(w.teacher_one), role="teacher").status_code == 200
    assert _rows(w, campus) == 1


def test_wrong_role_foreign_teacher_and_non_member_get_the_uniform_404(world):
    w = world
    campus = _new_campus(w, member=w.teacher_one)
    uniform = {"detail": "Record not found"}
    # A teacher claiming to be the administrator, and the reverse.
    r = _post(w, campus, w.teacher(w.teacher_one), role="administrator")
    assert (r.status_code, r.json()) == (404, uniform)
    r = _post(w, campus, w.admin(), role="teacher")
    assert (r.status_code, r.json()) == (404, uniform)
    # A teacher of ANOTHER campus (not a member of this one).
    for call in (lambda: w.client.get(_url(campus), headers=w.teacher(w.teacher_two)),
                 lambda: _post(w, campus, w.teacher(w.teacher_two), role="teacher")):
        r = call()
        assert (r.status_code, r.json()) == (404, uniform)
    # A disabled membership is no longer a member.
    assert w.client.post(f"/pilot/campuses/{campus}/educators/{w.teacher_one}/disable",
                         headers=w.admin()).status_code == 204
    r = w.client.get(_url(campus), headers=w.teacher(w.teacher_one))
    assert r.status_code in (401, 404)
    # Unknown or malformed campus ids are the same 404.
    for bad in (str(uuid.uuid4()), "not-a-uuid"):
        r = w.client.get(_url(bad), headers=w.admin())
        assert (r.status_code, r.json()) == (404, uniform)
    # No token at all.
    assert w.client.get(_url(campus)).status_code in (401, 403)
    assert _rows(w, campus) == 0


def test_a_stale_notice_hash_is_a_409_and_stores_nothing(world):
    w = world
    campus = _new_campus(w)
    r = _post(w, campus, w.admin(), notice_hash="0" * 64)
    assert r.status_code == 409 and r.json()["error"] == "notice_changed"
    assert _rows(w, campus) == 0


def test_the_official_name_is_encrypted_at_rest(world):
    w = world
    campus = _new_campus(w)
    _post(w, campus, w.admin())

    async def raw():
        async with w.factory() as s:
            row = (await s.execute(select(Row).where(Row.campus_id == campus))).scalar_one()
            return row.authorizer_name_enc, sa.authorizer_name(row), row.authorizer_ref
    blob, decrypted, ref = w.run(raw)
    assert NAME.encode() not in blob and decrypted == NAME
    assert ref == "administrator"


# ── The gate ────────────────────────────────────────────────────────────────

def test_an_unauthorized_campus_cannot_store_a_learner_exact_403(world):
    w = world
    campus = _new_campus(w)
    _expect_gate(_create_learner(w, campus), campus)
    assert _learner_count(w, campus) == 0


def test_after_authorizing_writes_succeed(world):
    w = world
    campus = _new_campus(w)
    _post(w, campus, w.admin())
    assert _create_learner(w, campus).status_code == 201
    assert _learner_count(w, campus) == 1


def test_a_stale_record_blocks_new_writes_until_the_notice_is_read_again(world, monkeypatch, tmp_path):
    w = world
    campus = _new_campus(w)
    _post(w, campus, w.admin())
    assert _create_learner(w, campus).status_code == 201
    old_hash = sa.notice_hash()
    changed = tmp_path / "notice.txt"
    changed.write_text(sa.notice_text() + "\nA new sentence.\n", encoding="utf-8")
    monkeypatch.setattr(sa, "NOTICE_PATH", changed)
    assert sa.notice_hash() != old_hash
    status = w.client.get(_url(campus), headers=w.admin()).json()
    assert status["authorized"] is False and status["stale"] is True
    _expect_gate(_create_learner(w, campus), campus)
    # The old hash is now refused; the new one records a NEW row, old kept.
    assert _post(w, campus, w.admin(), notice_hash=old_hash).status_code == 409
    assert _post(w, campus, w.admin()).status_code == 201
    assert _rows(w, campus) == 2
    assert _create_learner(w, campus).status_code == 201


def test_revoke_blocks_writes_but_not_reads_or_deletion(world):
    w = world
    campus = _new_campus(w, member=w.teacher_one)
    _post(w, campus, w.admin())
    learner = _create_learner(w, campus).json()["learner_id"]
    # Only the administrator may revoke.
    r = w.client.post(f"{_url(campus)}/revoke", json={"reason": None}, headers=w.teacher(w.teacher_one))
    assert r.status_code in (401, 403)
    assert w.client.get(_url(campus), headers=w.admin()).json()["authorized"] is True
    r = w.client.post(f"{_url(campus)}/revoke", json={"reason": "Synthetic reason"}, headers=w.admin())
    assert r.status_code == 200 and r.json()["authorized"] is False and r.json()["stale"] is False
    _expect_gate(_create_learner(w, campus), campus)
    # Reads stay available.
    assert w.client.get(_url(campus), headers=w.admin()).status_code == 200
    assert _learner_count(w, campus) == 1
    # Deletion stays available.
    r = w.client.post(f"/pilot/owner/campuses/{campus}/learners/{learner}/delete", headers=w.admin(),
                      json={"confirm_learner_id": learner, "confirm_display_name": "Synthetic Learner"})
    assert r.status_code == 200, r.text
    assert _learner_count(w, campus) == 0
    # Revoking again changes nothing; a re-grant records a new row.
    assert w.client.post(f"{_url(campus)}/revoke", json={}, headers=w.admin()).status_code == 200
    assert _post(w, campus, w.admin()).status_code == 201
    assert _rows(w, campus) == 2


def test_revoking_after_a_superseded_record_leaves_the_campus_unauthorized(world, monkeypatch, tmp_path):
    """A stale row left behind by a later grant must not resurface as the
    'active' one when the newest is revoked."""
    w = world
    campus = _new_campus(w)
    _post(w, campus, w.admin())
    changed = tmp_path / "notice.txt"
    changed.write_text(sa.notice_text() + "\nChanged.\n", encoding="utf-8")
    monkeypatch.setattr(sa, "NOTICE_PATH", changed)
    _post(w, campus, w.admin())
    w.client.post(f"{_url(campus)}/revoke", json={}, headers=w.admin())
    status = w.client.get(_url(campus), headers=w.admin()).json()
    assert status["authorized"] is False and status["stale"] is False


def test_authorization_is_per_campus(world):
    w = world
    campus = _new_campus(w)
    assert w.client.get(_url(w.campus_one), headers=w.admin()).json()["authorized"] is True
    _expect_gate(_create_learner(w, campus), campus)


def test_audit_events_carry_no_names_or_notice_text(world):
    w = world
    campus = _new_campus(w)
    _post(w, campus, w.admin())
    w.client.post(f"{_url(campus)}/revoke", json={"reason": "Synthetic reason text"}, headers=w.admin())
    events = [e for e in w.audit_events() if "school_data" in str(e.get("event") or e.get("event_type") or e)]
    kinds = {str(e.get("event") or e.get("event_type")) for e in events}
    assert {"pilot.school_data_authorized", "pilot.school_data_authorization_revoked"} <= kinds
    blob = repr(events)
    for needle in (NAME, "Synthetic reason text", "Notice version", sa.notice_hash()):
        assert needle not in blob, needle
    assert campus in blob


# ── Every learner-data write route is gated, by enumeration ─────────────────

# (METHOD, route path) of every /pilot route that STORES learner data. Each
# has a behavioural case below that must answer the exact 403.
GATED = {
    ("POST", "/pilot/campuses/{campus_id}/learners"),
    ("POST", "/pilot/campuses/{campus_id}/educators/{educator_id}/learners/{learner_id}"),
    ("POST", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments"),
    ("PUT", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/scores"),
    ("POST", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/transitions"),
    ("POST", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/supersede"),
    ("POST", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/evidence"),
    ("POST", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/proposal"),
    ("POST", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/proposals/{proposal_id}/decision"),
    ("POST", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/plan"),
    ("POST", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/progress-monitoring"),
    ("POST", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/plans/{plan_id}/follow-ups"),
    ("POST", "/pilot/me/learners/{learner_id}/evidence"),
    ("POST", "/pilot/me/learners/{learner_id}/recommendations"),
    ("POST", "/pilot/me/learners/{learner_id}/recommendations/{recommendation_id}/decision"),
    ("POST", "/pilot/me/learners/{learner_id}/tutoring/chat"),
}

# Write routes that store NO learner data, each with the reason.
EXEMPT = {
    ("POST", "/pilot/campuses"): "creates a campus row; no learner data",
    ("PUT", "/pilot/campuses/{campus_id}/calendar"): "campus instructional calendar; no learner data",
    ("POST", "/pilot/campuses/{campus_id}/benchmark-authorizations"): "campus licence record; no learner data",
    ("POST", "/pilot/campuses/{campus_id}/educators/{educator_id}"): "educator-to-campus membership; no learner data",
    ("POST", "/pilot/campuses/{campus_id}/educators/{educator_id}/disable"): "revocation; must stay available",
    ("DELETE", "/pilot/campuses/{campus_id}/educators/{educator_id}/learners/{learner_id}"): "revocation; must stay available",
    ("POST", "/pilot/campuses/{campus_id}/data-authorization"): "records the authorization itself",
    ("POST", "/pilot/campuses/{campus_id}/data-authorization/revoke"): "withdrawal; must stay available",
    ("POST", "/pilot/me/learners/search"): "a read carried in a POST body so a name stays out of a URL",
    ("POST", "/pilot/owner/campuses/{campus_id}/disable"): "emergency stop; must stay available",
    ("POST", "/pilot/owner/campuses/{campus_id}/learners/{learner_id}/delete"): "deletion; must stay available",
}


def _served(routes, prefix=""):
    """(METHOD, path) for every route. FastAPI includes routers lazily, so
    app.routes holds wrappers that must be unwrapped, carrying the prefix
    (the trap tests/test_app_composition.py documents)."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            ctx = getattr(route, "include_context", None)
            yield from _served(inner.routes, prefix + (getattr(ctx, "prefix", "") or ""))
            continue
        path = getattr(route, "path", None)
        for method in (getattr(route, "methods", None) or ()):
            if path is not None:
                yield method, prefix + path


def _pilot_write_routes():
    import main
    return {(m, p) for m, p in _served(main.app.routes)
            if p.startswith("/pilot") and m in {"POST", "PUT", "PATCH", "DELETE"}}


def test_every_pilot_write_route_is_gated_or_named_exempt():
    routes = _pilot_write_routes()
    assert routes, "no /pilot write routes found"
    unclassified = routes - GATED - set(EXEMPT)
    assert not unclassified, (
        "New /pilot write route(s) must call require_authorized (and be added to GATED "
        f"with a behavioural case) or be added to EXEMPT with a reason: {sorted(unclassified)}")
    assert not (GATED - routes), f"GATED names a route that no longer exists: {sorted(GATED - routes)}"
    assert not (set(EXEMPT) - routes), f"EXEMPT names a route that no longer exists: {sorted(set(EXEMPT) - routes)}"
    assert not (GATED & set(EXEMPT))
    assert all(EXEMPT.values())


def _cases(w):
    c, l, t = w.campus_one, w.learner_one, w.teacher_one
    a, p, plan, rec = (str(uuid.uuid4()) for _ in range(4))
    b = f"/pilot/campuses/{c}/learners/{l}/assessments"
    admin, teacher = w.admin(), w.teacher(w.teacher_one)
    dibels = {"framework": "dibels8", "measure": "PSF", "assessed_on": "2026-01-05",
              "source_name": "Synthetic DIBELS report", "score": 22.0,
              "score_unit": "correct_per_minute", "reported_band": "strategic_some_risk",
              "assessed_grade": "1", "assessment_window": "middle_of_year"}
    return {
        ("POST", "/pilot/campuses/{campus_id}/learners"):
            ("POST", f"/pilot/campuses/{c}/learners", {"display_name": "Synthetic Learner"}, admin),
        ("POST", "/pilot/campuses/{campus_id}/educators/{educator_id}/learners/{learner_id}"):
            ("POST", f"/pilot/campuses/{c}/educators/{t}/learners/{l}", None, admin),
        ("POST", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments"):
            ("POST", b, {
                "instrument": "dibels8", "edition": "8th", "measure": "multiple", "grade": "1",
                "form_id": "synthetic-form-a", "administration_purpose": "benchmark",
                "instructional_cycle": "valor_q1", "administered_at": "2031-08-20T09:00:00+00:00",
                "report_source": "vendor_report", "official_benchmark_window": "BOY",
                "accommodations": [], "notes": None, "vendor_guidance": None}, teacher),
        ("PUT", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/scores"):
            ("PUT", f"{b}/{a}/scores", {"scores": [
                {"measure": "PSF", "administration_status": "not_administered_other",
                 "reason": "absent"}], "responses": []}, teacher),
        ("POST", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/transitions"):
            ("POST", f"{b}/{a}/transitions", {"action": "mark_ready", "expected_state": "DRAFT"}, teacher),
        ("POST", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/supersede"):
            ("POST", f"{b}/{a}/supersede", {"reason": "synthetic reason"}, teacher),
        ("POST", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/evidence"):
            ("POST", f"{b}/{a}/evidence", {"summary": "Synthetic evidence"}, teacher),
        ("POST", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/proposal"):
            ("POST", f"{b}/{a}/proposal", None, teacher),
        ("POST", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/proposals/{proposal_id}/decision"):
            ("POST", f"{b}/{a}/proposals/{p}/decision", {"action": "approve", "expected_version": 1}, teacher),
        ("POST", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/plan"):
            ("POST", f"{b}/{a}/plan", {"plan_text": "Synthetic plan"}, teacher),
        ("POST", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/progress-monitoring"):
            ("POST", f"{b}/{a}/progress-monitoring", {"measure": "PSF", "planned_dates": ["2031-09-01"]}, teacher),
        ("POST", "/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/plans/{plan_id}/follow-ups"):
            ("POST", f"{b}/{a}/plans/{plan}/follow-ups", {
                "observed_on": "2026-01-06", "teaching_mode": "in_person",
                "observation": "Synthetic observation"}, teacher),
        ("POST", "/pilot/me/learners/{learner_id}/evidence"):
            ("POST", f"/pilot/me/learners/{l}/evidence", dibels, teacher),
        ("POST", "/pilot/me/learners/{learner_id}/recommendations"):
            ("POST", f"/pilot/me/learners/{l}/recommendations", None, teacher),
        ("POST", "/pilot/me/learners/{learner_id}/recommendations/{recommendation_id}/decision"):
            ("POST", f"/pilot/me/learners/{l}/recommendations/{rec}/decision",
             {"action": "approve", "expected_version": 1}, teacher),
        ("POST", "/pilot/me/learners/{learner_id}/tutoring/chat"):
            ("POST", f"/pilot/me/learners/{l}/tutoring/chat", {"child_message": "[START]"}, teacher),
    }


def test_every_gated_route_answers_the_exact_403_when_the_campus_is_unauthorized(world):
    w = world
    r = w.client.post(f"{_url(w.campus_one)}/revoke", json={}, headers=w.admin())
    assert r.status_code == 200 and r.json()["authorized"] is False
    cases = _cases(w)
    assert set(cases) == GATED, "every GATED route needs a behavioural case, and no more"
    for key, (method, path, body, headers) in cases.items():
        resp = w.client.request(method, path, json=body, headers=headers)
        assert resp.status_code == 403, (key, resp.status_code, resp.text)
        _expect_gate(resp, w.campus_one)


def test_the_commit_backstop_refuses_a_write_that_skipped_the_early_gate(world):
    """A future write route that resolves its learner with a read-style
    _scope and then commits is still refused at _recheck."""
    from fastapi import HTTPException
    import routers.pilot_assessments as pa
    w = world
    w.client.post(f"{_url(w.campus_one)}/revoke", json={}, headers=w.admin())
    claims = {"role": "educator", "sub": w.teacher_one, "auth_method": "webauthn_uv",
              "ev": w.credential_version(w.teacher_one)}

    async def go():
        async with w.factory() as s:
            _, learner = await pa._scope(s, claims, w.campus_one, w.learner_one)  # read-style
            try:
                await pa._commit(s, claims, learner)
            except HTTPException as exc:
                return exc.status_code, exc.detail["error"]
    assert w.run(go) == (403, "school_authorization_required")
