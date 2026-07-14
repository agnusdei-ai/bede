"""
Regression test for POST /tutor/email-summary's demo-role personalization
bug: the handler called _demo_session_config() with no arguments instead of
_demo_session_config(code), so a demo visitor's personalized student_name/
grade (set once at /auth/demo-code) was silently dropped in favor of the
operator's DEMO_STUDENT_NAME/DEMO_GRADE defaults for every diagnostic email
— the visitor's own child's name never appeared in their own summary email.
See routers/tutor.py's email_summary().
"""
from unittest.mock import AsyncMock, patch

import pytest

import core.demo_code_session as demo_code_session
from models.schemas import ChatMessage, EmailSummaryRequest, Subject
from routers.tutor import email_summary

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


async def test_demo_email_summary_uses_the_visitors_personalized_name_and_grade():
    code = await demo_code_session.generate_code(student_name="Priya", grade="5")

    req = EmailSummaryRequest(
        email="parent@example.com",
        session_config={
            "student_name": "Guest",
            "grade": "4",
            "grade_stage": "3-5",
            "subjects": [Subject.living_books],
        },
        conversation_history=[ChatMessage(role="user", content="Hi")],
        subjects_completed=[],
        duration_minutes=15,
    )

    with (
        patch("routers.tutor.generate_session_summary", new=AsyncMock(return_value="A lovely session.")) as mock_summary,
        patch("routers.tutor.send_email", new=AsyncMock(return_value=True)),
        patch("routers.tutor.log_event", new=AsyncMock()),
        patch("routers.tutor.audit_from_request", return_value={"ip": "test", "user_agent": "test"}),
    ):
        result = await email_summary(req, request=None, auth={"role": "demo_code", "code": code})

    assert result == {"sent": True}
    called_req = mock_summary.call_args.args[0]
    assert called_req.session_config.student_name == "Priya"
    assert called_req.session_config.grade == "5"
