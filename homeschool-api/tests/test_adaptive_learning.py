"""Regression and invocation tests for the live bounded adaptive-learning policy."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from anthropic.types import RawContentBlockDeltaEvent, RawContentBlockStartEvent, RawContentBlockStopEvent
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, SkillActivityLog
from models.schemas import GradeStage, SessionConfig, Subject
from services import ai_service
from services.adaptive_learning import (
    POLICY_VERSION, WorkObservation, load_recent_math_work,
    render_instruction, select_instruction,
)
from services.diagnostic.activity import record_activity

NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
SKILL = "oa.multiplication_facts"


def event(ident, assistance, *, skill=SKILL, days_ago=0):
    return WorkObservation(
        event_id=ident, skill_id=skill, assistance=assistance,
        completed_at=NOW - timedelta(days=days_ago, minutes=ident),
    )


def move(*events, grade_band="3-5"):
    return select_instruction(events, grade_band, now=NOW)


def test_no_evidence_means_no_personalized_claim():
    assert move() is None
    assert render_instruction(None, parent_focus=False) == ""


def test_two_supported_completions_trigger_a_new_representation():
    selected = move(event(1, "with_help"), event(2, "with_help"))
    assert selected.method == "change_representation"
    assert selected.reason_code == "two_supported_completions"
    assert set(selected.evidence_event_ids) == {1, 2}
    assert selected.policy_version == POLICY_VERSION


def test_supported_completion_requests_smaller_step():
    assert move(event(1, "with_help")).method == "smaller_step"


def test_hint_is_followed_by_fading_help():
    assert move(event(1, "with_a_hint")).method == "fade_hint"


def test_two_independent_completions_invite_transfer_not_mastery_claim():
    selected = move(event(1, "unaided"), event(2, "unaided"))
    assert selected.method == "transfer"
    assert "mastered" not in render_instruction(selected, parent_focus=False).lower()


def test_one_independent_completion_invites_explanation_not_transfer():
    assert move(event(1, "unaided"), event(2, "with_help")).method == "explain_reasoning"


def test_old_record_invites_gentle_retrieval_without_claiming_forgetting():
    selected = move(event(1, "unaided", days_ago=25))
    assert selected.method == "revisit"
    assert "knowledge has been lost" in render_instruction(selected, parent_focus=False)


def test_order_depends_on_event_time_not_input_order():
    a = event(1, "with_a_hint")
    b = event(2, "with_help", days_ago=1)
    assert move(b, a).method == "fade_hint"
    assert move(a, b).method == "fade_hint"


def test_only_known_grade_reachable_and_fresh_events_are_eligible():
    assert move(event(1, "unaided", skill="fictional.skill")) is None
    assert move(event(1, "unaided", skill="fn.slope")) is None
    assert move(event(1, "unaided", days_ago=150)) is None
    assert move(event(1, "unaided"), grade_band="not_a_band") is None
    assert move(event(1, "unsafe")) is None


def test_parent_directed_curriculum_always_out_ranks_strategy():
    selected = move(event(1, "with_help"))
    note = render_instruction(selected, parent_focus=True)
    assert "NEVER redirect" in note
    assert "same skill" in note
    assert "parent-approved lesson" in note
    assert "make the learner feel tested" in note


def test_policy_contains_no_raw_answer_score_or_student_personal_information():
    selected = move(event(1, "unaided"))
    note = render_instruction(selected, parent_focus=False)
    assert "<adaptive_learning_policy>" in note
    assert "oa.multiplication_facts" in note
    assert "Sam" not in note
    assert "probability" not in note.lower()
    assert "faith" not in note.lower()


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        from core.encryption import initialize_encryption
        await initialize_encryption(settings.master_secret, session)
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_real_encrypted_work_is_student_scoped_and_changes_on_next_turn(db_session):
    assert await load_recent_math_work(db_session, "Sam") == []
    assert await record_activity(db_session, "Sam", "mathematics", SKILL, "Multiplication facts", "hint_dependent")
    observed = await load_recent_math_work(db_session, "Sam")
    assert len(observed) == 1
    assert observed[0].assistance == "with_help"
    assert await load_recent_math_work(db_session, "Other Student") == []
    assert await record_activity(db_session, "Sam", "mathematics", SKILL, "Multiplication facts", "hint_dependent")
    fresh = await load_recent_math_work(db_session, "Sam")
    assert len(fresh) == 2
    assert {x.event_id for x in fresh} == {x.event_id for x in observed} | {fresh[0].event_id}
    assert select_instruction(fresh, "3-5").method == "change_representation"


@pytest.mark.asyncio
async def test_corrupt_ciphertext_does_not_influence_tutoring(db_session):
    db_session.add(SkillActivityLog(
        student_name="Tampered", subject_area="mathematics", skill_id=SKILL,
        detail_enc=b"not a valid encrypted record",
    ))
    await db_session.commit()
    assert await load_recent_math_work(db_session, "Tampered") == []


@pytest.mark.asyncio
async def test_other_subject_work_never_enters_math_policy(db_session):
    assert await record_activity(
        db_session, "Sam", "literacy", "recall", "Reading recall", "correct",
    )
    assert await load_recent_math_work(db_session, "Sam") == []


@pytest.mark.asyncio
async def test_subject_prompt_contains_only_supplied_policy_note():
    config = SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery)
    note = render_instruction(move(event(1, "with_a_hint")), parent_focus=False)
    text = await ai_service._build_subject_prompt(
        config, Subject.mathematics, adaptive_instruction_note=note,
    )
    assert "<adaptive_learning_policy>" in text
    assert "fading" not in text  # the hint policy says to use less scaffolding, not a hidden grade
    text_without = await ai_service._build_subject_prompt(config, Subject.mathematics)
    assert "<adaptive_learning_policy>" not in text_without


class _FakeStream:
    def __aiter__(self):
        return self._events()

    async def _events(self):
        yield RawContentBlockStartEvent.model_validate({
            "type": "content_block_start", "index": 0,
            "content_block": {"type": "text", "text": ""},
        })
        yield RawContentBlockDeltaEvent.model_validate({
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": "What do you notice?"},
        })
        yield RawContentBlockStopEvent.model_validate({
            "type": "content_block_stop", "index": 0,
        })


def _capture_stream(captured):
    @asynccontextmanager
    async def fake(**kwargs):
        captured["system"] = kwargs["system"]
        yield _FakeStream()
    return fake


@pytest.mark.asyncio
async def test_real_tutoring_stream_receives_fresh_work_based_instruction(db_session):
    config = SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery)
    for _ in range(2):
        assert await record_activity(
            db_session, "Sam", "mathematics", SKILL, "Multiplication facts", "hint_dependent",
        )
    captured = {}
    with patch.object(ai_service._client.messages, "stream", side_effect=_capture_stream(captured)):
        async for _ in ai_service.stream_tutor_response(
            config=config, subject=Subject.mathematics, history=[],
            child_message="Could we work through the problem?", db=db_session,
        ):
            pass
    assert "<adaptive_learning_policy>" in captured["system"][1]["text"]
    assert "DIFFERENT concrete representation" in captured["system"][1]["text"]


@pytest.mark.asyncio
async def test_demo_does_not_attempt_a_persistent_student_read():
    config = SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery)
    captured = {}
    with patch.object(ai_service._client.messages, "stream", side_effect=_capture_stream(captured)):
        async for _ in ai_service.stream_tutor_response(
            config=config, subject=Subject.mathematics, history=[],
            child_message="Hi Bede", db=None,
        ):
            pass
    assert "<adaptive_learning_policy>" not in captured["system"][1]["text"]
