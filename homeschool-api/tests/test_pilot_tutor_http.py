"""Real-HTTP denials for the synthetic-only learner tutoring route.

No mock external model invocation: rejected requests must be refused before
the model client is resolved. Covers absent educator approval and two-campus
non-enumeration on the actual mounted FastAPI router.
"""
import uuid

from test_canonical_assessment_api import _reset_rate_limiter, client, world


def _path(learner):
    return f"/pilot/me/learners/{learner}/tutoring/chat"


PAYLOAD = {"child_message": "[START]", "subject": "reading"}


def test_missing_teacher_approval_fails_without_starting_local_model(world):
    r = world.client.post(_path(world.learner_one), json=PAYLOAD,
                          headers=world.teacher_one.headers)
    assert r.status_code == 409, r.text
    assert r.json() == {"detail": "Teacher approval is required before tutoring"}
    assert r.headers.get("content-type", "").startswith("application/json")


def test_cross_campus_and_missing_uuid_are_identical_denials(world):
    missing = world.client.post(_path(str(uuid.uuid4())), json=PAYLOAD,
                                headers=world.teacher_two.headers)
    foreign = world.client.post(_path(world.learner_one), json=PAYLOAD,
                                headers=world.teacher_two.headers)
    assert missing.status_code == foreign.status_code == 404
    assert missing.content == foreign.content
    own = world.client.post(_path(world.learner_two), json=PAYLOAD,
                            headers=world.teacher_two.headers)
    assert own.status_code == 409
    assert "Teacher approval" in own.text


def test_invalid_uuid_and_cross_campus_are_uniform(world):
    missing = world.client.post(_path(str(uuid.uuid4())), json=PAYLOAD,
                                headers=world.teacher_two.headers)
    for invalid in ("not-a-uuid", world.learner_one.upper(),
                    "00000000-0000-0000-0000-000000000000"):
        r = world.client.post(_path(invalid), json=PAYLOAD,
                              headers=world.teacher_two.headers)
        assert r.status_code == missing.status_code == 404
        assert r.content == missing.content
