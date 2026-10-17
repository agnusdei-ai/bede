"""Owner Decision 7: delivering teacher-approved instruction into a learner's
tutoring session is UNAVAILABLE until #585 is decided, and that is tested
rather than assumed.

The approved text is reachable only by the educator who recorded it
(GET .../instruction). The tutoring turn has no path that reads it into a
prompt, and the tutor request carries no pilot-session handle. If someone
adds either, these fail and the decision has to be made on purpose.
"""
from pathlib import Path

API = Path(__file__).resolve().parents[1]


def test_the_tutoring_turn_never_reads_authorized_instruction():
    for rel in ("routers/tutor.py", "services/ai_service.py"):
        src = (API / rel).read_text(encoding="utf-8")
        assert "authorized_instruction" not in src, rel
        assert "pilot_session" not in src, rel


def test_the_tutor_request_carries_no_pilot_session_handle():
    from models.schemas import TutorRequest
    assert not [f for f in TutorRequest.model_fields if "pilot" in f]
