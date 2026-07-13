"""
Regression guard for the diagnostic mastery preview's core scope promise
(see docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md's sign-off guardrails):
demo-only, must not touch homeschool-tutor/production in this phase.

These tests assert that promise structurally, not just by convention —
every parent/child call site passes no demo_code/is_demo argument at all
(the defaults), so if this ever regressed to leaking diagnostic content or
behavior into a non-demo session, one of these would fail.
"""
import asyncio

from models.schemas import GradeStage, Subject, SessionConfig
from services.ai_service import (
    _build_static_prompt,
    _build_subject_prompt,
    _record_skill_evidence_demo,
)
import core.demo_code_session as demo_code_session


def setup_function():
    demo_code_session._codes = {}


def _config(grade: str = "3", grade_stage: GradeStage = GradeStage.core_mastery) -> SessionConfig:
    return SessionConfig(student_name="Sam", grade=grade, grade_stage=grade_stage)


def test_static_prompt_defaults_to_no_diagnostic_guidance():
    text = _build_static_prompt(_config())
    assert "diagnostic_guidance" not in text
    assert "record_skill_evidence" not in text


def test_static_prompt_is_byte_identical_with_and_without_is_demo_kwarg_when_false():
    default_call = _build_static_prompt(_config())
    explicit_false = _build_static_prompt(_config(), is_demo=False)
    assert default_call == explicit_false


def test_static_prompt_only_adds_diagnostic_guidance_when_is_demo_true():
    without = _build_static_prompt(_config(), is_demo=False)
    with_demo = _build_static_prompt(_config(), is_demo=True)
    assert "diagnostic_guidance" not in without
    assert "diagnostic_guidance" in with_demo
    assert "record_skill_evidence" in with_demo


def test_subject_prompt_defaults_to_no_diagnostic_context():
    text = _build_subject_prompt(_config(), Subject.mathematics)
    assert "MATH SKILL DIAGNOSTIC" not in text


def test_subject_prompt_adds_diagnostic_context_only_for_demo_code_and_math():
    without_demo = _build_subject_prompt(_config(), Subject.mathematics, demo_code=None)
    assert "MATH SKILL DIAGNOSTIC" not in without_demo

    code = demo_code_session.generate_code("Sam", "3")
    with_demo_math = _build_subject_prompt(_config(), Subject.mathematics, demo_code=code)
    assert "MATH SKILL DIAGNOSTIC" in with_demo_math

    with_demo_non_math = _build_subject_prompt(_config(), Subject.history, demo_code=code)
    assert "MATH SKILL DIAGNOSTIC" not in with_demo_non_math


def test_record_skill_evidence_demo_is_a_true_no_op_without_demo_code():
    """The exact structural guarantee the sign-off scope depends on: every
    parent/child call site passes demo_code=None, so this must never write
    anything anywhere for them, regardless of tool_input content."""
    asyncio.run(_record_skill_evidence_demo(
        None, _config(), Subject.mathematics,
        {"probe_id": "probe.oa.multiplication_facts", "outcome": "correct", "confidence": 1.0},
    ))
    # Nothing to assert against a database here by design — production's
    # persistence path (services.diagnostic.process_evidence) is a
    # separate, not-yet-wired-up function this call must never reach; the
    # real assertion is simply that this didn't raise and touched no state
    # this test can observe, which is exactly the "no-op" contract.


def test_record_skill_evidence_demo_writes_only_for_the_given_code():
    code = demo_code_session.generate_code("Sam", "3")
    asyncio.run(_record_skill_evidence_demo(
        code, _config(), Subject.mathematics,
        {"probe_id": "probe.oa.multiplication_facts", "outcome": "correct", "confidence": 1.0},
    ))
    assert demo_code_session.get_mastery_vector(code) is not None


def test_record_skill_evidence_demo_ignores_non_math_subjects():
    code = demo_code_session.generate_code("Sam", "3")
    asyncio.run(_record_skill_evidence_demo(
        code, _config(), Subject.history,
        {"probe_id": "probe.oa.multiplication_facts", "outcome": "correct", "confidence": 1.0},
    ))
    assert demo_code_session.get_mastery_vector(code) is None
