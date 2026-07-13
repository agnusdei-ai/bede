"""
Diagnostic prompt-injection tests for _build_static_prompt/_build_subject_prompt
/_diagnostic_context (services/ai_service.py).

Originally a regression guard for the demo mastery preview's "must not
touch homeschool-tutor/production" scope promise (see
docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md's Phase 3 unit 3.1 decisions
log for the reconciliation). That promise changed deliberately once the
real, db-backed persistence path (services.diagnostic.process_evidence)
was wired in alongside the demo's in-memory one: <diagnostic_guidance> is
now unconditional in the static block (it's harmless, subject-agnostic
prose), and the per-turn MATH SKILL DIAGNOSTIC note now renders from
whichever backend is live — demo_code's in-memory vector, or a real,
already-loaded db_vector for a parent/child session. What these tests
guard now: the two backends' *content* never cross-contaminates (a demo
code's evidence never appears in a db_vector-driven prompt or vice versa)
and the routing logic (demo_code vs db_vector, math vs non-math subject)
is exactly right.
"""
from models.schemas import GradeStage, Subject, SessionConfig
from services.ai_service import _build_static_prompt, _build_subject_prompt
import core.demo_code_session as demo_code_session


def setup_function():
    demo_code_session._codes = {}


def _config(grade: str = "3", grade_stage: GradeStage = GradeStage.core_mastery) -> SessionConfig:
    return SessionConfig(student_name="Sam", grade=grade, grade_stage=grade_stage)


def test_static_prompt_always_includes_diagnostic_guidance():
    """No longer demo-gated — both backends need Bede to know the tool
    exists and how to use it."""
    text = _build_static_prompt(_config())
    assert "diagnostic_guidance" in text
    assert "record_skill_evidence" in text


def test_subject_prompt_non_math_subject_never_gets_diagnostic_context():
    """The one real gate on this content — subject == mathematics — not
    whether a backend vector happens to be present."""
    text = _build_subject_prompt(_config(), Subject.history)
    assert "MATH SKILL DIAGNOSTIC" not in text


def test_subject_prompt_math_with_neither_backend_still_gets_cold_start_probe_list():
    """Neither demo_code nor db_vector supplied for a math subject is the
    degenerate case (routers/tutor.py's contract guarantees one is always
    relevant for a real session) — still well-defined: same cold-start
    content as an explicit db_vector=None, not silently nothing."""
    text = _build_subject_prompt(_config(), Subject.mathematics)
    assert "MATH SKILL DIAGNOSTIC" in text
    assert "Probe archetypes available" in text


def test_subject_prompt_adds_diagnostic_context_for_demo_code_and_math():
    code = demo_code_session.generate_code("Sam", "3")
    with_demo_math = _build_subject_prompt(_config(), Subject.mathematics, demo_code=code)
    assert "MATH SKILL DIAGNOSTIC" in with_demo_math

    with_demo_non_math = _build_subject_prompt(_config(), Subject.history, demo_code=code)
    assert "MATH SKILL DIAGNOSTIC" not in with_demo_non_math


def test_subject_prompt_adds_diagnostic_context_for_a_real_db_vector_and_math():
    """The real (parent/child) path: a caller who already loaded a vector
    via _load_mastery_vector_readonly passes it straight through, no I/O
    inside this function."""
    fake_vector = {"cc.rote_count_20": 0.9}
    with_db_math = _build_subject_prompt(_config(), Subject.mathematics, db_vector=fake_vector)
    assert "MATH SKILL DIAGNOSTIC" in with_db_math

    with_db_non_math = _build_subject_prompt(_config(), Subject.history, db_vector=fake_vector)
    assert "MATH SKILL DIAGNOSTIC" not in with_db_non_math


def test_subject_prompt_db_vector_cold_start_gets_the_probe_list_not_a_fabricated_hint():
    """db_vector=None (real session, no MasteryProfile row yet) still gets
    the probe archetype list — the same cold-start UX the demo path
    already had — not silently nothing."""
    text = _build_subject_prompt(_config(), Subject.mathematics, db_vector=None)
    assert "MATH SKILL DIAGNOSTIC" in text
    assert "Probe archetypes available" in text


def test_db_vector_path_never_touches_the_demo_code_store(monkeypatch):
    """When demo_code is None, _diagnostic_context must never read
    core.demo_code_session's in-memory store at all — a db_vector-driven
    (real parent/child) prompt has no legitimate reason to touch it, and
    doing so would be a real leak vector if a stale demo code happened to
    match some derived key."""
    from unittest.mock import MagicMock
    mock_get_vector = MagicMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr("core.demo_code_session.get_mastery_vector", mock_get_vector)

    text = _build_subject_prompt(_config(), Subject.mathematics, db_vector={"oa.add_within_20": 0.95})

    mock_get_vector.assert_not_called()
    assert "MATH SKILL DIAGNOSTIC" in text


def test_demo_code_path_ignores_any_db_vector_passed_alongside_it():
    """demo_code takes precedence over db_vector if a caller somehow
    passed both (shouldn't happen per routers/tutor.py's contract, but
    the demo code's own store must still be the one actually rendered)."""
    code = demo_code_session.generate_code("Sam", "3")
    demo_code_session.set_mastery_vector(code, {"cc.rote_count_20": 0.05}, 1)

    text_with_conflicting_db_vector = _build_subject_prompt(
        _config(), Subject.mathematics, demo_code=code, db_vector={"oa.add_within_20": 0.95},
    )
    text_demo_only = _build_subject_prompt(_config(), Subject.mathematics, demo_code=code)

    assert text_with_conflicting_db_vector == text_demo_only
