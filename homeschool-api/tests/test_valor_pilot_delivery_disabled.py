"""Owner Decision 7: delivering teacher-approved instruction into a learner's
tutoring session is UNAVAILABLE until #585 is decided, and that is tested
rather than assumed.

The approved text is reachable only by the educator who recorded it
(GET .../instruction). The tutoring turn has no path that reads it into a
prompt, the tutor request carries no pilot-session handle, no route under
``/pilot`` names a session, and the frontend offers no way to start one. If
someone adds any of these, a test here fails and the decision has to be
made on purpose. The conditions any future delivery must meet are recorded
in docs/EDUCATOR_CLASSROOM_PILOT.md.

A second, narrower property travels with it: a teacher's words are never
presented to the model as a parent's. ``services/ai_service.py`` renders
``SessionConfig.lesson_focus`` as "Parent's note for today", so a pilot
module that wrote an educator's instruction into that field would
misattribute it. The held owner-flow work did exactly that, which is why
these guards exist.
"""
import re
from pathlib import Path

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from test_valor_pilot_g2_journey import db, dibels, token, two_campuses  # noqa: F401

API = Path(__file__).resolve().parents[1]
TUTOR = API.parent / "homeschool-tutor" / "src"


def _pilot_backend_modules() -> list[Path]:
    found = sorted(
        p for d in ("routers", "services", "core") for p in (API / d).glob("*.py")
        if "pilot" in p.name
    )
    # Non-vacuity: the scan must actually reach the pilot code.
    names = {p.name for p in found}
    assert {"pilot_campuses.py", "pilot_journey.py", "pilot_owner.py",
            "pilot_recommender.py", "pilot_journey_models.py"} <= names, names
    return found


def _pilot_frontend_files() -> list[Path]:
    found = sorted(p for p in (TUTOR / "components").glob("Pilot*.tsx")
                   if not p.name.endswith(".test.tsx"))
    assert {p.name for p in found} >= {"PilotTeacherJourney.tsx", "PilotOwnerPanel.tsx"}
    return found


def walk_app_routes(routes, prefix: str = ""):
    """Every (path, methods) the REAL assembled app serves.

    FastAPI 0.141 includes routers lazily: ``app.routes`` holds
    ``_IncludedRouter`` wrappers with no ``.path``, whose own routes live on
    ``original_router`` under ``include_context.prefix``. Those wrappers are
    recursed into, so a router nested inside another is still reached.
    """
    for route in routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            yield from walk_app_routes(original.routes, prefix + route.include_context.prefix)
        elif hasattr(route, "routes") and not hasattr(route, "endpoint"):  # Mount
            yield from walk_app_routes(route.routes, prefix + getattr(route, "path", ""))
        elif hasattr(route, "path"):
            yield prefix + route.path, frozenset(getattr(route, "methods", None) or ())


# ── Delivery is unavailable ─────────────────────────────────────────────────

def test_the_tutoring_turn_never_reads_authorized_instruction():
    for rel in ("routers/tutor.py", "services/ai_service.py"):
        src = (API / rel).read_text(encoding="utf-8")
        assert "authorized_instruction" not in src, rel
        assert "pilot_session" not in src, rel


def test_the_tutor_request_carries_no_pilot_session_handle():
    from models.schemas import TutorRequest
    assert not [f for f in TutorRequest.model_fields if "pilot" in f]


def test_no_route_under_pilot_names_a_session():
    import main
    routes = list(walk_app_routes(main.app.routes))
    pilot = [path for path, _ in routes if path.startswith("/pilot")]
    # Non-vacuity: the walk reaches every pilot router, including the owner one.
    assert "/pilot/me/learners/{learner_id}/instruction" in pilot
    assert "/pilot/owner/deletion-receipts" in pilot
    assert len(routes) >= 60
    offending = [path for path in pilot if "session" in path.lower()]
    assert offending == [], offending


def test_no_pilot_session_service_or_launch_table_exists():
    assert not (API / "services" / "pilot_session.py").exists()
    from core.database import Base
    tables = {t.name for t in Base.metadata.sorted_tables}
    assert not [t for t in tables if t.startswith("pilot_") and "session" in t]


def test_the_frontend_offers_no_way_to_start_a_pilot_session():
    api = (TUTOR / "services" / "api.ts").read_text(encoding="utf-8")
    store = (TUTOR / "store" / "sessionStore.ts").read_text(encoding="utf-8")
    chat = (TUTOR / "components" / "SocraticChat.tsx").read_text(encoding="utf-8")
    for name, src in (("api.ts", api), ("sessionStore.ts", store), ("SocraticChat.tsx", chat)):
        assert not re.search(r"pilot_?session", src, re.I), name
        assert "startPilot" not in src, name
    for path in _pilot_frontend_files():
        src = path.read_text(encoding="utf-8")
        assert "Teach this with Bede" not in src, path.name
        assert "Session receipts" not in src, path.name
        assert "startPilot" not in src, path.name
        assert "navigate('/session')" not in src, path.name


def test_the_frontend_files_these_guards_read_are_in_the_ci_change_filter():
    """Without these, a frontend-only edit that re-adds a session launch
    computes relevant=false, skips api-tests, and never runs this file."""
    workflow = (API.parent / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    line = next(l for l in workflow.splitlines() if "grep -qE" in l and "^(" in l)
    alternatives = line.split("'^(", 1)[1].split(")'", 1)[0].split("|")
    for entry in (r"homeschool-tutor/src/services/api\.ts",
                  r"homeschool-tutor/src/store/sessionStore\.ts",
                  r"homeschool-tutor/src/components/SocraticChat\.tsx",
                  r"homeschool-tutor/src/components/Pilot"):
        assert entry in alternatives, entry


# ── A teacher's words are never labelled as a parent's ─────────────────────

_PILOT_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+(?:routers|services|core)\.\w*pilot\w*", re.M)
_EDUCATOR_AUTHORED = ("authorized_enc", "proposal_enc", "note_enc", "edited_text",
                      "PilotRecommendation", "PilotDecision", "PilotEvidence")
_PARENT_LABEL = re.compile(
    r"parent'?s\s+(note|instruction|focus|guidance|request)"
    r"|note\s+from\s+(the\s+|your\s+)?parent"
    r"|parent[- ](supplied|authored|written|wrote)", re.I)


def test_no_educator_text_reaches_the_prompt_at_all():
    """After the delivery removal no educator-authored text reaches the
    prompt by any path, so it cannot reach it under a parent's label."""
    for rel in ("services/ai_service.py", "routers/tutor.py"):
        src = (API / rel).read_text(encoding="utf-8")
        assert not _PILOT_IMPORT.search(src), rel
        for name in _EDUCATOR_AUTHORED:
            assert name not in src, (rel, name)


def test_no_pilot_module_builds_a_tutoring_config():
    """``SessionConfig``'s free-text fields are rendered under parent labels
    ("Parent's note for today"). A pilot module that constructs one could
    only put a teacher's words there."""
    for path in _pilot_backend_modules():
        src = path.read_text(encoding="utf-8")
        for name in ("SessionConfig", "TutorRequest", "lesson_focus", "current_unit",
                     "lesson_resume", "ai_service", "stream_tutor_response"):
            assert name not in src, (path.name, name)


def test_no_pilot_code_uses_parent_attribution_wording():
    files = _pilot_backend_modules() + _pilot_frontend_files()
    hits = [(p.name, m.group(0)) for p in files
            for m in _PARENT_LABEL.finditer(p.read_text(encoding="utf-8"))]
    assert hits == [], hits


def test_the_parent_label_scan_would_catch_the_wording_it_forbids():
    for sample in ("Parent's note for today: ...", "parents note", "a note from the parent",
                   "parent-supplied focus"):
        assert _PARENT_LABEL.search(sample), sample
    assert not _PARENT_LABEL.search("require_elevated_parent")


# ── Every recorded plan's delivery state is NOT_REQUESTED, and stays so ─────

def test_not_requested_is_the_only_delivery_state():
    from core.pilot_journey_models import (
        DELIVERY_NOT_REQUESTED, DELIVERY_STATES, PilotRecommendation,
    )
    assert DELIVERY_NOT_REQUESTED == "NOT_REQUESTED"
    assert DELIVERY_STATES == ("NOT_REQUESTED",)
    col = PilotRecommendation.__table__.c.delivery_state
    assert col.nullable is False and col.default.arg == "NOT_REQUESTED"
    checks = [str(c.sqltext) for c in PilotRecommendation.__table__.constraints
              if c.__class__.__name__ == "CheckConstraint"]
    assert "delivery_state = 'NOT_REQUESTED'" in checks, checks


@pytest.mark.asyncio
async def test_every_decision_path_leaves_delivery_not_requested(db):
    from core.pilot_journey_models import PilotRecommendation
    from routers.pilot_journey import (
        DecisionInput, authorized_instruction, decide, list_recommendations,
        record_evidence, request_recommendation,
    )
    ta, _, _, _, la, _ = await two_campuses(db)
    tok = await token(db, ta)
    for action, band in (("approve", "strategic_some_risk"), ("edit", "intensive_at_risk"),
                         ("reject", "core_minimal_risk")):
        await record_evidence(la, dibels(band=band), auth=tok, db=db)
        rec = await request_recommendation(la, auth=tok, db=db)
        assert rec["delivery_state"] == "NOT_REQUESTED", rec
        body = DecisionInput(action=action, expected_version=1,
                             **({"edited_text": "Synthetic edited plan."} if action == "edit" else {}))
        out = await decide(la, rec["recommendation_id"], body, auth=tok, db=db)
        assert out["status"] in ("approved", "edited", "rejected")
        assert out["delivery_state"] == "NOT_REQUESTED", out
    listed = await list_recommendations(la, auth=tok, db=db)
    assert {r["delivery_state"] for r in listed} == {"NOT_REQUESTED"}
    assert (await authorized_instruction(la, auth=tok, db=db))["delivery_state"] == "NOT_REQUESTED"
    rows = (await db.execute(select(PilotRecommendation))).scalars().all()
    assert len(rows) == 3 and {r.delivery_state for r in rows} == {"NOT_REQUESTED"}


@pytest.mark.asyncio
async def test_the_database_refuses_any_other_delivery_state(db):
    from core.pilot_journey_models import PilotRecommendation
    from routers.pilot_journey import record_evidence, request_recommendation
    ta, _, _, _, la, _ = await two_campuses(db)
    tok = await token(db, ta)
    await record_evidence(la, dibels(), auth=tok, db=db)
    rec = await request_recommendation(la, auth=tok, db=db)
    for state in ("REQUESTED", "CONFIRMED", "QUEUED", "DELIVERED", "CANCELLED"):
        with pytest.raises(IntegrityError):
            await db.execute(update(PilotRecommendation)
                             .where(PilotRecommendation.id == rec["recommendation_id"])
                             .values(delivery_state=state))
            await db.flush()
        await db.rollback()


# Assignment, keyword argument, setattr, or a dict entry (e.g. an UPDATE's
# values dict) whose value is anything other than a read of the row itself.
_STATE_WRITE = re.compile(
    r"""delivery_state\s*=(?!=)"""
    r"""|["']delivery_state["']\s*[,)]"""
    r"""|["']delivery_state["']\s*:(?!\s*row\.delivery_state\b)""")


def test_no_code_path_writes_a_delivery_state():
    """The column is set once, by its default, at insert. Any assignment,
    UPDATE ... values(delivery_state=...) or setattr in shipped code is a
    path off NOT_REQUESTED, so it fails here first."""
    allowed = {("core/pilot_journey_models.py",
                "CheckConstraint(f\"delivery_state = '{DELIVERY_NOT_REQUESTED}'\",")}
    hits = []
    for path in sorted(API.rglob("*.py")):
        rel = path.relative_to(API).as_posix()
        if rel.startswith(("tests/", ".venv", "venv")):
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if _STATE_WRITE.search(line) and (rel, line.strip()) not in allowed:
                hits.append((rel, line.strip()))
    assert hits == [], hits


def test_the_state_write_scan_would_catch_a_write():
    for sample in ("row.delivery_state = 'QUEUED'", ".values(delivery_state=\"QUEUED\")",
                   "setattr(row, 'delivery_state', x)", 'values = {"delivery_state": "QUEUED"}',
                   '"delivery_state": state,'):
        assert _STATE_WRITE.search(sample), sample
    assert not _STATE_WRITE.search('"delivery_state": row.delivery_state,')
