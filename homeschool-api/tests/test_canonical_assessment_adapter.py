"""The G2 adapter seam validates against G2's REAL input contract."""
from datetime import datetime, timedelta, timezone

import pytest

from services.assessment_interop import EducatorAssessmentSubmission
from services.canonical_assessment_adapter import (
    to_g2_decision_input, to_g2_evidence_submission,
)

PAST = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()


def meta(**kw):
    base = {"assessment_id": "a" * 8, "administration_purpose": "benchmark",
            "official_benchmark_window": "BOY", "administered_at": PAST, "grade": "1"}
    return base | kw


def test_scored_measure_maps_to_a_valid_g2_submission():
    body = to_g2_evidence_submission(meta(), {"measure": "PSF", "administration_status": "scored",
                                              "raw_score": 12.0, "score_unit": "correct_per_minute"},
                                     finalized=True)
    parsed = EducatorAssessmentSubmission.model_validate(body)
    assert parsed.assessment_window == "beginning_of_year" and parsed.reported_band is None


def test_progress_monitoring_maps_to_the_g2_pm_window_not_a_benchmark():
    body = to_g2_evidence_submission(meta(administration_purpose="progress_monitoring",
                                          official_benchmark_window="none"),
                                     {"measure": "PSF", "administration_status": "scored",
                                      "raw_score": 9.0, "score_unit": "correct_per_minute"},
                                     finalized=True)
    assert EducatorAssessmentSubmission.model_validate(body).assessment_window == "progress_monitoring"


@pytest.mark.parametrize("score,finalized,m", [
    ({"measure": "ORF_WC", "administration_status": "not_administered_by_rule",
      "raw_score": None, "score_unit": None}, True, meta()),
    ({"measure": "PSF", "administration_status": "scored", "raw_score": 3.0,
      "score_unit": "correct_per_minute"}, False, meta()),
    ({"measure": "PSF", "administration_status": "scored", "raw_score": 3.0,
      "score_unit": "correct_per_minute"}, True, meta(official_benchmark_window="none")),
    ({"measure": "PSF", "administration_status": "scored", "raw_score": 3.0,
      "score_unit": "correct_per_minute"}, True, meta(administration_purpose="teacher_observation",
                                                      official_benchmark_window="none")),
])
def test_refuses_skipped_unfinalized_or_windowless_records(score, finalized, m):
    assert to_g2_evidence_submission(m, score, finalized=finalized) is None


def test_decision_maps_to_g2_decision_input_shape():
    out = to_g2_decision_input({"action": "edit", "version": 2, "authorized_text": "t",
                                "rationale": "r"})
    assert out == {"action": "edit", "expected_version": 1, "edited_text": "t", "note": "r"}
    assert to_g2_decision_input({"action": "reject", "version": 2, "authorized_text": None,
                                 "rationale": None}) == {"action": "reject", "expected_version": 1}
