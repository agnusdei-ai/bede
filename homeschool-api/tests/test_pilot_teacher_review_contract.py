"""Synthetic agent-state combinations for the bounded teacher-review contract."""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from services.pilot_teacher_review_contract import TeacherReviewCycle


CAMPUS = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TEACHER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
LEARNER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
OTHER = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
DECISION = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
ACTION = "11111111-1111-4111-8111-111111111111"
NOW = datetime(2026, 10, 19, tzinfo=timezone.utc).isoformat()


def sample():
    return {
        "schema_version": "1.1.0", "cycle_id": "22222222-2222-4222-8222-222222222222",
        "record_version": 2,
        "tenant_scope": {"campus_id": CAMPUS, "educator_id": TEACHER,
                         "learner_ids": [LEARNER], "subject_area": "phonics"},
        "official_assessment_record": {
            "record_id": "33333333-3333-4333-8333-333333333333",
            "campus_id": CAMPUS, "learner_id": LEARNER,
            "instrument": "DIBELS_8", "measure": "PSF",
            "purpose": "progress_monitoring", "benchmark_window": "not_applicable",
            "administration_status": "finalized", "snapshot_sha256": "a" * 64,
            "finalized_by": TEACHER, "finalized_at": NOW,
            "official_score_fields": {"raw_score": 28, "score_unit": "correct_per_minute"},
        },
        "evidence_review": {"evidence_ids": [], "source_refs": ["synthetic-official-snapshot"]},
        "proposed_actions": [{"action_id": ACTION, "action_type": "generate_printable_practice",
                              "approval_required": True, "status": "proposed"}],
        "teacher_decision": {"decision_id": DECISION, "decision_status": "pending_teacher_review"},
        "generated_artifacts": [],
        "authorization_context": {
            "subject_id": TEACHER, "tenant_id": CAMPUS,
            "resource_ids": [LEARNER], "action": "review",
        },
    }


def approved(data):
    data["teacher_decision"].update(
        decision_status="teacher_approved", reviewed_by=TEACHER,
        reviewed_at=NOW, approved_record_version=2, selected_action_ids=[ACTION],
    )
    data["proposed_actions"][0]["status"] = "approved_for_execution"
    data["authorization_context"]["action"] = "prepare_teacher_artifact"
    data["generated_artifacts"] = [{
        "artifact_id": "44444444-4444-4444-8444-444444444444",
        "action_id": ACTION, "decision_id": DECISION,
        "artifact_type": "tiered_practice_pack", "paper_format": "US_LETTER_BW",
        "local_file_path": "synthetic/teacher-only.pdf", "approval_version": 2,
    }]
    return data


def rejected(path, value):
    data = sample()
    target = data
    keys = path.split(".")
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    with pytest.raises(ValidationError):
        TeacherReviewCycle.model_validate(data)


def test_pending_cycle_is_advisory_and_generates_no_artifacts():
    cycle = TeacherReviewCycle.model_validate(sample())
    assert cycle.generated_artifacts == []
    assert cycle.delivery_state == "NOT_REQUESTED"


def test_teacher_approved_cycle_may_prepare_teacher_only_artifact():
    cycle = TeacherReviewCycle.model_validate(approved(sample()))
    assert cycle.generated_artifacts[0].approval_version == cycle.record_version
    assert cycle.delivery_state == "NOT_REQUESTED"


@pytest.mark.parametrize("field,value", [
    ("tenant_scope.campus_id", OTHER),
    ("official_assessment_record.learner_id", OTHER),
    ("authorization_context.tenant_id", OTHER),
    ("authorization_context.subject_id", OTHER),
    ("authorization_context.resource_ids", [OTHER]),
    ("official_assessment_record.administration_status", "completed_pending_review"),
    ("official_assessment_record.benchmark_window", "MOY"),
    ("proposed_actions", [{"action_id": ACTION, "action_type": "deliver_to_learner",
                           "approval_required": True, "status": "proposed"}]),
    ("delivery_state", "DELIVERED"),
])
def test_scope_unfinalized_benchmark_and_unsafe_action_all_fail_closed(field, value):
    rejected(field, value)


@pytest.mark.parametrize("mutation", [
    lambda x: x["teacher_decision"].update(decision_status="teacher_rejected"),
    lambda x: x["teacher_decision"].update(reviewed_by=OTHER),
    lambda x: x["teacher_decision"].update(approved_record_version=1),
    lambda x: x["teacher_decision"].update(selected_action_ids=[]),
    lambda x: x["proposed_actions"][0].update(status="proposed"),
    lambda x: x["generated_artifacts"][0].update(decision_id=OTHER),
    lambda x: x["generated_artifacts"][0].update(approval_version=1),
])
def test_artifact_cannot_survive_rejection_wrong_actor_stale_version_or_unapproved_action(mutation):
    data = approved(sample())
    mutation(data)
    with pytest.raises(ValidationError):
        TeacherReviewCycle.model_validate(data)


def test_teacher_observation_has_no_official_score_and_no_benchmark_window():
    data = sample()
    data["official_assessment_record"].update(
        instrument="TEACHER_OBSERVATION", measure="OBSERVATION",
        purpose="teacher_observation", official_score_fields={},
    )
    TeacherReviewCycle.model_validate(data)
    data["official_assessment_record"]["official_score_fields"] = {"raw_score": 42}
    with pytest.raises(ValidationError):
        TeacherReviewCycle.model_validate(data)


def test_allows_one_approved_artifact_without_roster_mutation_or_learner_delivery():
    data = approved(sample())
    data["generated_artifacts"].append({
        **deepcopy(data["generated_artifacts"][0]),
        "artifact_id": "55555555-5555-4555-8555-555555555555",
        "artifact_type": "observation_sheet",
    })
    assert len(TeacherReviewCycle.model_validate(data).generated_artifacts) == 2
