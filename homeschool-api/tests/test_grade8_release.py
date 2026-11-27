"""Actual accepted-source wiring; no model calls or real learner records."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request
from unittest.mock import AsyncMock

from models.schemas import DemoParentConfigRequest, SessionConfig, Subject, TutorRequest
from services import grade8_curriculum_service as release


def set_activation(monkeypatch, value):
    from core.config import settings
    monkeypatch.setattr(settings, "bede_grade8_curriculum_enabled", value)


@pytest.mark.parametrize("value,expected", [("false", False), ("0", False), ("true", True), ("1", True)])
def test_operator_flag_uses_the_existing_environment_contract(monkeypatch, value, expected):
    from core.config import Settings
    monkeypatch.setenv("BEDE_GRADE8_CURRICULUM_ENABLED", value)
    assert Settings(_env_file=None).bede_grade8_curriculum_enabled is expected


def test_accepted_course_is_available_without_enabling_institutional_ingestion(monkeypatch):
    from core.config import Settings
    monkeypatch.delenv("BEDE_GRADE8_CURRICULUM_ENABLED", raising=False)
    monkeypatch.delenv("CURRICULUM_ENGINE_ENABLED", raising=False)
    settings = Settings(_env_file=None)
    assert settings.bede_grade8_curriculum_enabled is True
    assert settings.curriculum_engine_enabled is False
    assert config(grade8_curriculum=None).grade8_curriculum is None


def test_accepted_course_rejects_invalid_operator_flag(monkeypatch):
    from core.config import Settings
    monkeypatch.setenv("BEDE_GRADE8_CURRICULUM_ENABLED", "ture")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def config(**updates):
    data = dict(student_name="Example learner", grade="8", grade_stage="6-8",
                subjects=[Subject.mathematics],
                grade8_curriculum={"week": 1, "pathway": "foundations"})
    data.update(updates)
    return SessionConfig(**data)


def test_published_source_is_complete_and_has_no_private_fields():
    data = release.load()
    assert len(data["lessons"]) == data["reviewed_records"] == 592
    assert data["pilot_evaluated"] is False
    assert data["institutionally_promoted"] is False
    forbidden = {"key_rubric", "prompt_rescue_record", "assessor_role", "worked_example",
                 "private_model", "placement_bridge", "covered_record_hashes"}
    def walk(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(data)
    assert all(step["mode"] != "worked_example" for lesson in data["lessons"].values()
               for step in lesson["steps"])
    for pathway in data["weeks"].values():
        for week in pathway.values():
            assert "key" not in week["geography"]


@pytest.mark.parametrize("pathway", ["foundations", "algebra"])
@pytest.mark.parametrize("week", range(1, 37))
def test_actual_week_assignments_and_new_subject_coverage(week, pathway, monkeypatch):
    set_activation(monkeypatch, True)
    plan, lessons = release.week_plan(week, pathway)
    assert len(plan["lesson_ids"]) == len(set(plan["lesson_ids"])) == 14
    strands = {lesson["strand"] for lesson in lessons}
    assert ("algebra_pathway" in strands) == (pathway == "algebra")
    assert ("mathematics" in strands) == (pathway == "foundations")
    assert {release.STRAND_SUBJECT[x["strand"]] for x in lessons} >= {
        "spanish", "computing", "movement_health", "living_books", "history",
        "science", "nature_study", "art_music", "language_arts", "mathematics",
    }
    for subject in (Subject.spanish, Subject.computing, Subject.movement_health):
        cfg = config(subjects=[subject], grade8_curriculum={"week": week, "pathway": pathway})
        text = release.context(cfg, subject)
        assert "<accepted_grade8_lesson>" in text
        assert "Never solve the active" in text


@pytest.mark.parametrize("subject", [Subject.spanish, Subject.computing, Subject.movement_health])
def test_course_only_subjects_cannot_fall_back_to_legacy_catalog(subject):
    with pytest.raises(ValidationError, match="explicit adult-selected"):
        config(subjects=[subject], grade8_curriculum=None)


@pytest.mark.parametrize("selection", [
    {"week": 0, "pathway": "foundations"}, {"week": 37, "pathway": "foundations"},
    {"week": True, "pathway": "foundations"}, {"week": "1", "pathway": "foundations"},
    {"week": 1, "pathway": "unrecognized"}, {"week": 1, "pathway": "algebra", "approved": True},
    {"week": 1, "pathway": "foundations", "lesson_id": "../../private"},
    {"week": 1, "pathway": "algebra", "lesson_id": "g8-year-mathematics-w01"},
    {"week": 1, "pathway": "foundations", "release_id": "unreviewed"},
])
def test_invalid_scope_never_selects_other_content(selection, monkeypatch):
    set_activation(monkeypatch, True)
    with pytest.raises(ValidationError):
        config(grade8_curriculum=selection)


def test_activation_is_not_inferred_from_publication_or_acceptance(monkeypatch):
    set_activation(monkeypatch, False)
    saved = config()
    assert SessionConfig.model_validate_json(saved.model_dump_json()).grade8_curriculum is not None
    with pytest.raises(ValueError, match="not enabled"):
        release.context(saved, Subject.mathematics)
    assert config(grade8_curriculum=None).grade8_curriculum is None


def test_grade_and_subject_cannot_be_overridden_by_lesson_id(monkeypatch):
    set_activation(monkeypatch, True)
    with pytest.raises(ValidationError, match="only for Grade 8"):
        config(grade="7")
    with pytest.raises(ValidationError, match="Enable the selected lesson"):
        config(grade8_curriculum={"week": 1, "pathway": "foundations",
                                 "lesson_id": "g8-year-spanish-w01"})


def test_selection_survives_session_serialization(monkeypatch):
    set_activation(monkeypatch, True)
    original = config(grade8_curriculum={"week": 24, "pathway": "algebra",
                                       "lesson_id": "g8-year-algebra_practice-w24"})
    restored = SessionConfig.model_validate_json(original.model_dump_json())
    assert restored.grade8_curriculum == original.grade8_curriculum
    assert "g8-year-algebra_practice-w24" in release.context(restored, Subject.mathematics)


def test_posted_positions_cannot_replace_or_remove_the_adult_plan():
    saved = config()
    forged = config(grade8_curriculum={"week": 36, "pathway": "algebra"})
    with pytest.raises(ValueError, match="not saved"):
        release.authoritative_config(forged, saved, Subject.mathematics)
    removed = config(grade8_curriculum=None)
    assert release.authoritative_config(removed, saved, Subject.mathematics) is saved
    changed_subject = config(subjects=[Subject.spanish])
    with pytest.raises(PermissionError, match="approved learner"):
        release.authoritative_config(changed_subject, saved, Subject.spanish)
    legacy = config(grade8_curriculum=None)
    assert release.authoritative_config(legacy, legacy, Subject.mathematics) is legacy


def test_quarter_replaces_only_reviewed_focus_checks(monkeypatch):
    set_activation(monkeypatch, True)
    cfg = config(grade8_curriculum={"week": 9, "pathway": "foundations"})
    text = release.context(cfg, Subject.mathematics)
    payload = json.loads(text[text.index("\n{") + 1:text.rfind("\n</")])
    chosen = payload["lesson"]
    assert chosen["assessment_bank_id"] == "g8-year-quarter_mathematics-w09"
    bank = release.load()["lessons"][chosen["assessment_bank_id"]]
    assert next(a for a in chosen["assessments"] if a["kind"] == "independent") == next(
        a for a in bank["assessments"] if a["kind"] == "independent")
    assert chosen["id"] not in payload["companion_ids"]
    algebra = config(grade8_curriculum={"week": 9, "pathway": "algebra"})
    assert '"assessment_bank_id"' not in release.context(algebra, Subject.mathematics)


def test_public_api_and_visual_sources_do_not_require_learner_records(monkeypatch):
    set_activation(monkeypatch, False)
    from routers.catalog import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/catalog/grade8/release?week=36&pathway=algebra")
        assert response.status_code == 200
        assert response.json()["runtime_enabled"] is False
        assert response.json()["retention_due_week"] == 37
        assert client.get("/catalog/grade8/release?week=37").status_code == 422
        for path in ("atlas", "visual-source"):
            response = client.get(f"/catalog/grade8/{path}")
            assert response.status_code == 200
            assert "default-src 'none'" in response.headers["content-security-policy"]
            assert "<script" not in response.text.lower()


def test_private_field_mutations_cannot_change_exported_student_projection():
    path = Path(__file__).resolve().parents[2] / "scripts/export_grade8_student_release.py"
    spec = importlib.util.spec_from_file_location("student_export", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lesson = {
        "id": "example", "title": "Example", "objective_ids": ["example-objective"],
        "entry_evidence": "Explain an original example.",
        "steps": [{"mode": "worked_example", "instruction": "PRIVATE_MODEL"},
                  {"mode": "guided", "instruction": "Ask a question.", "minutes": 5, "materials": []}],
        "assessments": [{"kind": "independent", "prompt": "Explain a new case.",
                         "supports": [], "success_criteria": "Support your reasoning.",
                         "key_rubric": "PRIVATE_KEY"}],
        "access": {"construct": "Reasoning", "supports": [], "alternative_response": "Spoken"},
        "safety": {"hazards": [], "supervision": "Adult", "stop_escalation": "Pause",
                   "safer_alternative": "Unperformed outcomes remain unassessed."},
        "source_refs": [],
    }
    bundle = {"lessons": [lesson], "objectives": [{"id": "example-objective", "statement": "Reason"}],
              "sources": []}
    baseline = module.student_lesson(bundle)
    changed = deepcopy(bundle)
    changed["lessons"][0]["steps"][0]["instruction"] = "DIFFERENT_PRIVATE_MODEL"
    changed["lessons"][0]["assessments"][0]["key_rubric"] = "DIFFERENT_PRIVATE_KEY"
    assert module.student_lesson(changed) == baseline
    assert "PRIVATE_" not in json.dumps(baseline)


@pytest.mark.asyncio
async def test_real_demo_save_and_reload_preserve_the_selected_lesson(monkeypatch):
    from routers import auth, tutor
    saved = {}
    async def save(code, value):
        saved.update(value)
    monkeypatch.setattr(auth, "get_demo_personalization", AsyncMock(return_value=("Example learner", "8")))
    monkeypatch.setattr(auth, "set_parent_config", save)
    monkeypatch.setattr(tutor, "get_demo_personalization", AsyncMock(return_value=("Example learner", "8")))
    monkeypatch.setattr(tutor, "get_demo_current_unit", AsyncMock(return_value=None))
    monkeypatch.setattr(tutor, "get_demo_faith_tradition", AsyncMock(return_value=None))
    monkeypatch.setattr(tutor, "get_demo_parent_config", AsyncMock(side_effect=lambda code: deepcopy(saved)))
    req = DemoParentConfigRequest(subjects=[Subject.computing],
        grade8_curriculum={"week": 12, "pathway": "foundations", "lesson_id": "g8-year-computing_projects-w12"})
    await auth.set_demo_parent_config(req, auth={"code": "example-code", "role": "demo_code"})
    restored = await tutor._demo_session_config("example-code")
    assert restored.grade8_curriculum.week == 12
    assert restored.grade8_curriculum.lesson_id == "g8-year-computing_projects-w12"
    assert restored.subjects == [Subject.computing]
    await auth.set_demo_parent_config(DemoParentConfigRequest(subjects=[Subject.mathematics],
        grade8_curriculum=None), auth={"code": "example-code", "role": "demo_code"})
    assert (await tutor._demo_session_config("example-code")).grade8_curriculum is None


@pytest.mark.asyncio
@pytest.mark.parametrize("course,subject,status_code", [
    (True, Subject.mathematics, 409), (False, Subject.spanish, 403),
])
async def test_disabled_teaching_is_a_clear_conflict_before_any_model_stream(monkeypatch, course, subject, status_code):
    from routers import tutor
    set_activation(monkeypatch, False)
    selected = config() if course else config(grade8_curriculum=None)
    monkeypatch.setattr(tutor, "_demo_session_config", AsyncMock(return_value=selected))
    req = TutorRequest(session_config=selected, current_subject=subject,
                       child_message="Guide me through the next task.")
    request = Request({"type": "http", "method": "POST", "path": "/tutor/chat", "headers": []})
    with pytest.raises(HTTPException) as caught:
        await tutor.chat(req, request, auth={"code": "example-code", "role": "demo_code"}, db=None)
    assert caught.value.status_code == status_code


def test_missing_or_tampered_source_never_silently_uses_the_old_catalog(monkeypatch, tmp_path):
    original = release.DATA_FILE
    release.load.cache_clear()
    monkeypatch.setattr(release, "DATA_FILE", tmp_path / "missing.json")
    try:
        with pytest.raises(ValueError, match="unavailable or invalid"):
            release.load()
    finally:
        monkeypatch.setattr(release, "DATA_FILE", original)
        release.load.cache_clear()
