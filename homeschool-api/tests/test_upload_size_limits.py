"""
Regression coverage for the shared upload-size ceiling (MAX_UPLOAD_BYTES /
MAX_UPLOAD_BASE64_CHARS in models/schemas.py) — the handwriting-canvas
drawing and a narration-file upload must reject an oversized payload before
it ever reaches ai_service.py or document_extraction.py, protecting both
per-turn token/context cost and the nginx proxy's own body-size ceiling.
"""
import pytest
from pydantic import ValidationError

from models.schemas import (
    MAX_UPLOAD_BASE64_CHARS,
    GradeStage,
    NarrationUploadRequest,
    SessionConfig,
    Subject,
    TutorRequest,
)


def _config() -> SessionConfig:
    return SessionConfig(student_name="Guest", grade="4", grade_stage=GradeStage.core_mastery)


def test_drawing_image_at_the_limit_is_accepted():
    req = TutorRequest(
        session_config=_config(),
        current_subject=Subject.living_books,
        child_message="Tell me about the river.",
        drawing_image="A" * MAX_UPLOAD_BASE64_CHARS,
    )
    assert len(req.drawing_image) == MAX_UPLOAD_BASE64_CHARS


def test_drawing_image_over_the_limit_is_rejected():
    with pytest.raises(ValidationError, match="drawing_image"):
        TutorRequest(
            session_config=_config(),
            current_subject=Subject.living_books,
            child_message="Tell me about the river.",
            drawing_image="A" * (MAX_UPLOAD_BASE64_CHARS + 1),
        )


def test_narration_content_base64_at_the_limit_is_accepted():
    req = NarrationUploadRequest(filename="notes.txt", content_base64="A" * MAX_UPLOAD_BASE64_CHARS)
    assert len(req.content_base64) == MAX_UPLOAD_BASE64_CHARS


def test_narration_content_base64_over_the_limit_is_rejected():
    with pytest.raises(ValidationError, match="content_base64"):
        NarrationUploadRequest(filename="notes.txt", content_base64="A" * (MAX_UPLOAD_BASE64_CHARS + 1))


def _max_length_of(model, field_name: str) -> int:
    for constraint in model.model_fields[field_name].metadata:
        if hasattr(constraint, "max_length"):
            return constraint.max_length
    raise AssertionError(f"{field_name} has no max_length constraint")


def test_drawing_image_and_narration_share_the_same_ceiling():
    """Both upload paths should be governed by one documented standard,
    not two independently-chosen magic numbers."""
    drawing_limit = _max_length_of(TutorRequest, "drawing_image")
    narration_limit = _max_length_of(NarrationUploadRequest, "content_base64")
    assert drawing_limit == narration_limit == MAX_UPLOAD_BASE64_CHARS
