"""K–12 routing parity; use static public sources and synthetic configurations."""
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.config import settings
from models.schemas import SessionConfig, Subject, VALID_DEMO_GRADES, VALID_GRADES, grade_to_stage
from routers.catalog import router
from services import curriculum_delivery as delivery
from services import grade8_curriculum_service as accepted
from services.demo_upper_school import upper_school_guidance

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("grade", VALID_GRADES)
def test_grade_selection_and_tutor_mapping_share_the_catalog_contract(grade):
    from services.ai_service import _infer_year
    config = SessionConfig(student_name="Example", grade=grade, grade_stage=grade_to_stage(grade),
                           subjects=[Subject.mathematics])
    assert _infer_year(config) == delivery.catalog_year_for_grade(grade)
    assert VALID_GRADES == VALID_DEMO_GRADES
    assert config.model_dump() == SessionConfig.model_validate_json(config.model_dump_json()).model_dump()


@pytest.mark.parametrize("enabled", [True, False])
def test_shared_public_metadata_tracks_actual_sources_and_operator_state(monkeypatch, enabled):
    monkeypatch.setattr(settings, "bede_grade8_curriculum_enabled", enabled)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        # No identity, role, or learner parameter can choose another curriculum tier.
        demo = client.get("/catalog/curriculum-availability")
        installed = client.get("/catalog/curriculum-availability?role=parent&delivery=installer")
        assert demo.status_code == installed.status_code == 200
        assert demo.json() == installed.json()
    payload = demo.json()
    assert payload["contract_version"] == 1
    assert [row["grade"] for row in payload["grades"]] == VALID_GRADES
    for row in payload["grades"]:
        year = row["catalog_year"]
        if year:
            assert row["catalog_sha256"] == sha256(
                (delivery.CATALOG_DIR / f"year{year}.json").read_bytes()
            ).hexdigest()
            assert row["default_route"] == "catalog_guided"
        else:
            assert row["catalog_sha256"] is None
            assert row["default_route"] == "grade_specific_practice"
        if row["grade"] == "8":
            release = row["accepted_full_year"]
            assert release["release_id"] == accepted.RELEASE_ID
            assert release["runtime_enabled"] is enabled
            assert release["reviewed_records"] == 592
            assert release["source_sha256"] == accepted.MANIFEST_SHA256
        else:
            assert row["accepted_full_year"] is None


def test_public_metadata_does_not_silently_accept_a_broken_release(monkeypatch):
    def broken():
        raise ValueError("Missing or tampered accepted source")
    monkeypatch.setattr(accepted, "load", broken)
    with pytest.raises(ValueError, match="Missing or tampered"):
        delivery.curriculum_availability()


def test_metadata_rechecks_manifest_even_after_adapter_cache_is_warm(monkeypatch, tmp_path):
    accepted.load()
    changed = tmp_path / "changed-manifest.json"
    changed.write_text('{"release_id":"unreviewed"}')
    monkeypatch.setattr(accepted, "DATA_FILE", changed)
    with pytest.raises(ValueError, match="manifest changed"):
        delivery.curriculum_availability()


@pytest.mark.parametrize("grade", ["-1", "13", "high school", "8.0", ""])
def test_invalid_grades_do_not_route_to_other_content(grade):
    with pytest.raises(ValueError):
        delivery.catalog_year_for_grade(grade)


def test_legacy_kindergarten_alias_remains_compatible():
    assert delivery.catalog_year_for_grade(" 0 ") == delivery.catalog_year_for_grade("k") == 1


@pytest.mark.parametrize("grade", ["9", "10", "11", "12"])
def test_upper_school_guidance_is_not_a_demo_only_curriculum(grade):
    config = SessionConfig(student_name="Example", grade=grade, grade_stage="6-8",
                           subjects=[Subject.mathematics])
    note = upper_school_guidance(config)
    assert f"INTERACTIVE GRADE {grade} —" in note
    assert " DEMO" not in note
    assert "not a complete" in note
    assert "Do not report K-8 diagnostic" in note


def test_both_client_displays_use_the_same_contract():
    demo = ROOT / "demo/src/CurriculumAvailability.tsx"
    enrolled = ROOT / "homeschool-tutor/src/components/CurriculumAvailability.tsx"
    assert demo.read_bytes() == enrolled.read_bytes()
    for path in (ROOT / "demo/src/api.ts", ROOT / "homeschool-tutor/src/services/api.ts"):
        assert "/catalog/curriculum-availability" in path.read_text()


@pytest.mark.parametrize("week", [1, 18, 36])
@pytest.mark.parametrize("pathway", ["foundations", "algebra"])
@pytest.mark.parametrize("subject", [Subject.mathematics, Subject.living_books, Subject.science])
def test_saved_course_delivers_identical_accepted_instruction(week, pathway, subject, monkeypatch):
    from services.ai_service import _get_catalog_context
    monkeypatch.setattr(settings, "bede_grade8_curriculum_enabled", True)
    configured = SessionConfig(
        student_name="Example", grade="8", grade_stage="6-8", subjects=[subject],
        grade8_curriculum={"week": week, "pathway": pathway},
    )
    # Both saved client contracts deserialize to the same server-owned model.
    demo = SessionConfig.model_validate_json(configured.model_dump_json())
    installed = SessionConfig.model_validate(configured.model_dump())
    demo_context = _get_catalog_context(demo, subject)
    assert demo_context == _get_catalog_context(installed, subject)
    assert "<accepted_grade8_lesson>" in demo_context


def test_installer_uses_the_same_api_build_context():
    dockerfile = (ROOT / "homeschool-api/Dockerfile").read_text()
    assert "COPY . ." in dockerfile
    workflow = (ROOT / ".github/workflows/build-bede-operator.yml").read_text()
    assert "-f homeschool-api/Dockerfile homeschool-api" in workflow
