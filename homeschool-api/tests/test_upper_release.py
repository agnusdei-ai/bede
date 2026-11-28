"""Reviewed Grades 9-12 source wiring; no model calls or real learner records."""
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
from services import upper_curriculum_service as release

FORBIDDEN = {"key_rubric", "prompt_rescue_record", "assessor_role", "worked_example", "worked_model",
             "misconceptions", "key", "private_model", "review_bound_sha256"}


def set_activation(monkeypatch, value):
    from core.config import settings
    monkeypatch.setattr(settings, "bede_upper_curriculum_enabled", value)


def config(grade="9", **updates):
    data = dict(student_name="Example learner", grade=grade, grade_stage="6-8",
                subjects=[Subject.mathematics], upper_curriculum={"week": 1})
    data.update(updates)
    return SessionConfig(**data)


def walk(value):
    if isinstance(value, dict):
        assert not FORBIDDEN.intersection(value)
        for item in value.values():
            walk(item)
    elif isinstance(value, list):
        for item in value:
            walk(item)


def test_operator_flag_defaults_on_without_institutional_ingestion(monkeypatch):
    from core.config import Settings
    monkeypatch.delenv("BEDE_UPPER_CURRICULUM_ENABLED", raising=False)
    monkeypatch.delenv("CURRICULUM_ENGINE_ENABLED", raising=False)
    settings = Settings(_env_file=None)
    assert settings.bede_upper_curriculum_enabled is True
    assert settings.curriculum_engine_enabled is False
    monkeypatch.setenv("BEDE_UPPER_CURRICULUM_ENABLED", "false")
    assert Settings(_env_file=None).bede_upper_curriculum_enabled is False


def test_published_source_is_complete_and_has_no_adult_fields():
    data = release.load()
    assert len(data["lessons"]) == 1728
    assert data["pilot_evaluated"] is False
    assert data["institutionally_promoted"] is False
    assert data["review"]["human_accepted"] is False
    walk(data)
    for lesson in data["lessons"].values():
        assert all(step["mode"] != "worked_example" for step in lesson["steps"])
        assert [a["kind"] for a in lesson["assessments"]] == ["guided", "independent", "delayed", "transfer"]
        assert "Adult: think aloud" not in json.dumps(lesson)


@pytest.mark.parametrize("grade", release.GRADES)
@pytest.mark.parametrize("week", [1, 18, 36])
def test_beginning_middle_and_end_route_every_subject(grade, week, monkeypatch):
    set_activation(monkeypatch, True)
    lessons = release.week_lessons(grade, week)
    assert [x["strand"] for x in lessons] == list(release.STRAND_SUBJECT)
    assert all(x["grade"] == int(grade) and x["week"] == week for x in lessons)
    for subject in {Subject(x["subject"]) for x in lessons}:
        cfg = config(grade=grade, subjects=[subject], upper_curriculum={"week": week})
        text = release.context(cfg, subject)
        payload = json.loads(text[text.index("\n{") + 1:text.rfind("\n</")])
        assert payload["lesson"]["id"] == f"g{grade}-year-{_strand(subject)}-w{week:02d}"
        assert "Never solve the active" in text
        walk(payload)


def _strand(subject):
    return next(s for s, v in release.STRAND_SUBJECT.items() if v == subject.value)


def test_grades_are_distinct_not_repackaged():
    teaching = {g: {x["steps"][0]["instruction"] for w in range(1, 37) for x in release.week_lessons(g, w)}
                for g in release.GRADES}
    for a in release.GRADES:
        assert len(teaching[a]) == 432
        for b in release.GRADES:
            if a != b:
                assert not teaching[a] & teaching[b]


@pytest.mark.parametrize("selection,grade", [
    ({"week": 0}, "9"), ({"week": 37}, "9"), ({"week": True}, "9"), ({"week": "1"}, "9"),
    ({"week": 1, "approved": True}, "9"), ({"week": 1, "release_id": "unreviewed"}, "9"),
    ({"week": 1, "lesson_id": "../../private"}, "9"),
    ({"week": 1, "lesson_id": "g10-year-mathematics-w01"}, "9"),
    ({"week": 1, "lesson_id": "g9-year-mathematics-w02"}, "9"),
    ({"week": 1}, "8"),
])
def test_invalid_scope_never_selects_other_content(selection, grade):
    with pytest.raises(ValidationError):
        config(grade=grade, upper_curriculum=selection)


def test_one_release_per_plan_and_lesson_subject_must_be_enabled():
    with pytest.raises(ValidationError, match="one curriculum release"):
        config(grade="9", grade8_curriculum={"week": 1, "pathway": "foundations"})
    with pytest.raises(ValidationError, match="Enable the selected lesson"):
        config(upper_curriculum={"week": 1, "lesson_id": "g9-year-spanish-w01"})
    chosen = config(grade="12", subjects=[Subject.spanish],
                    upper_curriculum={"week": 36, "lesson_id": "g12-year-spanish-w36"})
    restored = SessionConfig.model_validate_json(chosen.model_dump_json())
    assert '"id": "g12-year-spanish-w36"' in release.context(restored, Subject.spanish)


def test_disabled_runtime_keeps_saved_plan_but_refuses_teaching(monkeypatch):
    set_activation(monkeypatch, False)
    saved = config()
    assert SessionConfig.model_validate_json(saved.model_dump_json()).upper_curriculum is not None
    with pytest.raises(ValueError, match="not enabled"):
        release.context(saved, Subject.mathematics)


def test_posted_positions_cannot_replace_the_adult_plan():
    from services.grade8_curriculum_service import authoritative_config
    saved = config()
    forged = config(upper_curriculum={"week": 30})
    with pytest.raises(ValueError, match="Grades 9-12 plan changed"):
        authoritative_config(forged, saved, Subject.mathematics)
    assert authoritative_config(config(upper_curriculum=None), saved, Subject.mathematics) is saved
    with pytest.raises(PermissionError):
        authoritative_config(config(subjects=[Subject.history]), saved, Subject.history)


def test_public_api_returns_student_fields_only(monkeypatch):
    set_activation(monkeypatch, True)
    from routers.catalog import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/catalog/upper/release?grade=11&week=18")
        assert response.status_code == 200
        body = response.json()
        assert body["runtime_enabled"] is True and body["human_accepted"] is False
        assert len(body["lessons"]) == 12
        walk(body)
        assert client.get("/catalog/upper/release?grade=8&week=1").status_code == 422
        assert client.get("/catalog/upper/release?grade=9&week=37").status_code == 422
        rows = client.get("/catalog/curriculum-availability").json()["grades"]
        for row in rows:
            upper = row["reviewed_full_year"]
            assert (upper is not None) == (row["grade"] in release.GRADES)
            if upper:
                assert upper["reviewed_records"] == 1728 and upper["source_sha256"] == release.MANIFEST_SHA256


def test_export_projection_drops_private_fields():
    path = Path(__file__).resolve().parents[2] / "scripts/export_upper_student_release.py"
    spec = importlib.util.spec_from_file_location("upper_export", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lesson = {
        "id": "example", "title": "Example", "objective_ids": ["o"], "entry_evidence": "Explain.",
        "steps": [{"mode": "worked_example", "instruction": "PRIVATE_MODEL", "minutes": 5, "materials": []},
                  {"mode": "practice", "instruction": "Ask.", "minutes": 5, "materials": []}],
        "assessments": [{"kind": "independent", "prompt": "Explain.", "supports": [],
                         "success_criteria": "Reason.", "key_rubric": "PRIVATE_KEY"}],
        "access": {"construct": "Reasoning", "supports": [], "alternative_response": "Spoken", "privacy": "x"},
        "safety": {"hazards": [], "supervision": "Adult", "stop_escalation": "Pause", "safer_alternative": "Paper"},
        "source_refs": [],
    }
    baseline = module.student_lesson({"lessons": [lesson], "objectives": [{"id": "o", "statement": "R"}], "sources": []})
    assert "PRIVATE_" not in json.dumps(baseline)


def test_tampered_source_fails_explicitly(monkeypatch, tmp_path):
    original = release.DATA_FILE
    release.load.cache_clear()
    monkeypatch.setattr(release, "DATA_FILE", tmp_path / "missing.json")
    try:
        with pytest.raises(ValueError, match="unavailable or invalid"):
            release.load()
    finally:
        monkeypatch.setattr(release, "DATA_FILE", original)
        release.load.cache_clear()


@pytest.mark.asyncio
async def test_demo_save_and_reload_preserve_the_selected_lesson(monkeypatch):
    from routers import auth, tutor
    saved = {}
    async def save(code, value):
        saved.update(value)
    for module in (auth, tutor):
        monkeypatch.setattr(module, "get_demo_personalization", AsyncMock(return_value=("Example learner", "10")))
    monkeypatch.setattr(auth, "set_parent_config", save)
    monkeypatch.setattr(tutor, "get_demo_current_unit", AsyncMock(return_value=None))
    monkeypatch.setattr(tutor, "get_demo_faith_tradition", AsyncMock(return_value=None))
    monkeypatch.setattr(tutor, "get_demo_parent_config", AsyncMock(side_effect=lambda code: deepcopy(saved)))
    req = DemoParentConfigRequest(subjects=[Subject.computing],
                                  upper_curriculum={"week": 20, "lesson_id": "g10-year-computing-w20"})
    await auth.set_demo_parent_config(req, auth={"code": "example-code", "role": "demo_code"})
    restored = await tutor._demo_session_config("example-code")
    assert restored.upper_curriculum.week == 20
    assert restored.upper_curriculum.lesson_id == "g10-year-computing-w20"
    assert restored.subjects == [Subject.computing]


@pytest.mark.asyncio
async def test_disabled_teaching_is_a_conflict_before_any_model_stream(monkeypatch):
    from routers import tutor
    set_activation(monkeypatch, False)
    selected = config()
    monkeypatch.setattr(tutor, "_demo_session_config", AsyncMock(return_value=selected))
    req = TutorRequest(session_config=selected, current_subject=Subject.mathematics,
                       child_message="Guide me through the next task.")
    request = Request({"type": "http", "method": "POST", "path": "/tutor/chat", "headers": []})
    with pytest.raises(HTTPException) as caught:
        await tutor.chat(req, request, auth={"code": "example-code", "role": "demo_code"}, db=None)
    assert caught.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("grade,week", [("9", 1), ("11", 18), ("12", 36)])
async def test_subject_prompt_carries_the_selected_lesson(grade, week, monkeypatch):
    """The upper-grade prompt path must deliver the chosen lesson, not only guidance."""
    from services.ai_service import _build_subject_prompt
    set_activation(monkeypatch, True)
    lesson_id = f"g{grade}-year-mathematics-w{week:02d}"
    cfg = config(grade=grade, upper_curriculum={"week": week, "lesson_id": lesson_id})
    prompt = await _build_subject_prompt(cfg, Subject.mathematics)
    assert f'"id": "{lesson_id}"' in prompt
    assert "sample practice directions" not in prompt
    walk(json.loads(prompt[prompt.index("\n{", prompt.index("<reviewed_upper_school_lesson>")) + 1:
                          prompt.index("\n</reviewed_upper_school_lesson>")]))
    plain = await _build_subject_prompt(config(grade=grade, upper_curriculum=None), Subject.mathematics)
    assert "<reviewed_upper_school_lesson>" not in plain and "sample practice directions" in plain
