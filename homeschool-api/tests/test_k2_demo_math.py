"""Public-demo Number Time stays isolated, temporary, and demo-authenticated."""

import pytest
from sqlalchemy import func, select

pytestmark = pytest.mark.usefixtures("demo_db")


@pytest.fixture
def client(test_client_with_database_context):
    import main
    import core.database as database

    with test_client_with_database_context(main.app, database.engine) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def reset_rate_limiter(monkeypatch):
    from core import middleware
    from core.config import settings

    middleware.reset_rate_limiter()
    monkeypatch.setattr(settings, "rate_limit_auth_per_minute", 1000)
    yield
    middleware.reset_rate_limiter()


def _session(client, grade="K", name="Same Name"):
    code_response = client.post(
        "/auth/demo-code", json={"grade": grade, "student_name": name},
    )
    assert code_response.status_code == 200, code_response.text
    code = code_response.json()["code"]
    login_response = client.post(
        "/auth/login", json={"role": "demo_code", "credential": code},
    )
    assert login_response.status_code == 200, login_response.text
    return code, {"Authorization": "Bearer " + login_response.json().get("access_token", "")}


def _lesson(client, headers, topic=None):
    params = {} if topic is None else {"topic": topic}
    response = client.get("/k2-practice/demo/math/lesson", headers=headers, params=params)
    return response


def _answer(client, headers, lesson_id, *, phase="together", index=0, choice, submission_id="submission_000001"):
    return client.post(
        f"/k2-practice/demo/math/lessons/{lesson_id}/answers",
        headers=headers,
        json={
            "phase": phase,
            "index": index,
            "choice": choice,
            "submission_id": submission_id,
        },
    )


def _lesson_claims(headers, lesson):
    from core.security import decode_token
    from services.k2_practice.demo_math import _decode_id

    auth = decode_token(headers["Authorization"].split(" ", 1)[1])
    assert auth is not None
    claims, _ = _decode_id(auth, lesson["lesson_id"])
    return claims


@pytest.mark.parametrize(("grade", "level"), [("K", "K"), ("1", "1"), ("2", "2")])
def test_demo_lesson_uses_server_resolved_grade_and_closed_topic(client, grade, level):
    import time
    from services.k2_practice.demo_math import LESSON_TTL_SECONDS

    _, headers = _session(client, grade=grade)
    created_at = int(time.time())
    response = _lesson(client, headers, topic="add")
    assert response.status_code == 200, response.text
    lesson = response.json()
    assert lesson["level"] == level
    assert lesson["topic"] == "add"
    assert lesson["demo"] is True
    assert lesson["recorded"] is False
    assert lesson["available_topics"]
    assert "answer" not in lesson["your_turn"][0]
    claims = _lesson_claims(headers, lesson)
    from core.security import decode_token
    auth = decode_token(
        headers["Authorization"].split(" ", 1)[1],
    )
    assert claims["exp"] <= auth["exp"]
    assert claims["exp"] <= created_at + LESSON_TTL_SECONDS


def test_demo_rejects_non_k2_grade_and_unknown_topic(client):
    _, headers = _session(client, grade="4")
    assert _lesson(client, headers).status_code == 404

    _, k_headers = _session(client, grade="K")
    assert _lesson(client, k_headers, topic="not-a-topic").status_code == 422


def test_lesson_is_bound_to_one_demo_sign_in_even_for_same_name(client):
    _, first = _session(client, grade="1")
    _, second = _session(client, grade="1")
    lesson = _lesson(client, first).json()
    answer = lesson["together"][0]["choices"][0]

    response = _answer(client, second, lesson["lesson_id"], choice=answer)
    assert response.status_code == 404


def test_missing_or_forged_demo_math_credentials_are_refused(client):
    assert client.get("/k2-practice/demo/math/lesson").status_code == 401

    _, headers = _session(client, grade="K")
    lesson = _lesson(client, headers).json()
    forged_id = lesson["lesson_id"][:-1] + ("A" if lesson["lesson_id"][-1] != "A" else "B")
    response = _answer(client, headers, forged_id, choice=lesson["together"][0]["choices"][0])
    assert response.status_code == 404


def test_lesson_id_cannot_cross_from_household_math_domain(client):
    from routers.k2_practice import mint_lesson_id

    _, headers = _session(client, grade="K")
    family_id = mint_lesson_id("Same Name", "K", "count", 1, area="math")
    response = _answer(client, headers, family_id, choice="0")
    assert response.status_code == 404


def test_demo_answer_replays_submission_and_rejects_changed_payload(client):
    _, headers = _session(client, grade="K")
    lesson = _lesson(client, headers).json()
    task = lesson["together"][0]
    choice = task["choices"][0]

    first = _answer(client, headers, lesson["lesson_id"], choice=choice)
    replay = _answer(client, headers, lesson["lesson_id"], choice=choice)
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    changed = next(item for item in task["choices"] if item != choice)
    conflict = _answer(
        client, headers, lesson["lesson_id"], choice=changed,
    )
    assert conflict.status_code == 409


def test_demo_your_turn_reveals_after_two_misses_and_settles(client):
    from services.k2_practice.practical_math import build_task

    _, headers = _session(client)
    lesson = _lesson(client, headers, topic="count").json()
    task = lesson["your_turn"][0]
    answer = build_task("K", "count", _lesson_claims(headers, lesson)["seed"], "your_turn", 0).accept_choice
    wrong = next(choice for choice in task["choices"] if choice != answer)

    first = _answer(
        client, headers, lesson["lesson_id"], phase="your_turn", choice=wrong,
        submission_id="submission_first_01",
    )
    assert first.status_code == 200
    assert first.json()["tries_left"] == 1
    assert "reveal" not in first.json()

    second = _answer(
        client, headers, lesson["lesson_id"], phase="your_turn", choice=wrong,
        submission_id="submission_second_02",
    )
    assert second.status_code == 200
    assert second.json()["reveal"]["choice"] == answer
    replay = _answer(
        client, headers, lesson["lesson_id"], phase="your_turn", choice=wrong,
        submission_id="submission_second_02",
    )
    assert replay.json() == second.json()
    settled = _answer(
        client, headers, lesson["lesson_id"], phase="your_turn", choice=answer,
        submission_id="submission_after_003",
    )
    assert settled.status_code == 409


def test_concurrent_identical_submissions_consume_one_transition(client):
    from concurrent.futures import ThreadPoolExecutor

    _, headers = _session(client, grade="K")
    lesson = _lesson(client, headers).json()
    choice = lesson["together"][0]["choices"][0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(
            lambda _: _answer(client, headers, lesson["lesson_id"], choice=choice),
            range(2),
        ))
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()


def test_logout_and_lost_volatile_state_expire_existing_lessons(client, monkeypatch):
    from services.k2_practice import demo_math

    code, headers = _session(client, grade="K")
    lesson = _lesson(client, headers).json()
    choice = lesson["together"][0]["choices"][0]
    assert client.post("/auth/logout", headers=headers).status_code == 200
    assert _answer(client, headers, lesson["lesson_id"], choice=choice).status_code == 401

    _, headers = _session(client, grade="K")
    lesson = _lesson(client, headers).json()
    demo_math.clear_state()  # A process restart has the same fail-closed result.
    assert _answer(client, headers, lesson["lesson_id"], choice=choice).status_code == 404

    _, headers = _session(client, grade="K")
    lesson = _lesson(client, headers).json()
    monkeypatch.setattr(demo_math.time, "monotonic", lambda: 10**12)
    assert _answer(client, headers, lesson["lesson_id"], choice=choice).status_code == 404


def test_expired_demo_code_cannot_use_an_existing_lesson(client, demo_db):
    from datetime import datetime, timedelta, timezone
    from core.database import DemoCodeSession

    code, headers = _session(client)
    lesson = _lesson(client, headers).json()

    async def expire_code():
        async with demo_db() as db:
            row = await db.get(DemoCodeSession, code)
            row.created_at = datetime.now(timezone.utc) - timedelta(hours=7)
            await db.commit()

    client.portal.call(expire_code)
    response = _answer(client, headers, lesson["lesson_id"], choice=lesson["together"][0]["choices"][0])
    assert response.status_code == 401


def test_malformed_demo_answer_is_refused(client):
    _, headers = _session(client, grade="K")
    lesson = _lesson(client, headers).json()
    response = client.post(
        f"/k2-practice/demo/math/lessons/{lesson['lesson_id']}/answers",
        headers=headers,
        json={
            "phase": "your_turn",
            "index": 0,
            "choice": "not-a-choice",
            "submission_id": "short",
        },
    )
    assert response.status_code == 422


def test_demo_math_never_writes_household_or_progress_records(client, demo_db, monkeypatch):
    from core.database import (
        DemoCodeActivityLog,
        DemoCodeFaithNote,
        DemoCodeParentConfig,
        DemoCodeUnitNote,
        MasteryProfile,
        StudentKey,
        SkillActivityLog,
        StudentConfig,
    )

    _, headers = _session(client, grade="K")
    async def counts():
        async with demo_db() as db:
            return (
                await db.scalar(select(func.count()).select_from(StudentConfig)),
                await db.scalar(select(func.count()).select_from(StudentKey)),
                await db.scalar(select(func.count()).select_from(SkillActivityLog)),
                await db.scalar(select(func.count()).select_from(MasteryProfile)),
                await db.scalar(select(func.count()).select_from(DemoCodeActivityLog)),
                await db.scalar(select(func.count()).select_from(DemoCodeUnitNote)),
                await db.scalar(select(func.count()).select_from(DemoCodeFaithNote)),
                await db.scalar(select(func.count()).select_from(DemoCodeParentConfig)),
            )

    before = client.portal.call(counts)
    import services.ai_service as ai_service

    def forbidden_model_call(*_args, **_kwargs):
        raise AssertionError("demo math must not call a model")

    monkeypatch.setattr(ai_service, "stream_tutor_response", forbidden_model_call)
    lesson = _lesson(client, headers).json()
    from core.security import decode_token
    from services.k2_practice.demo_math import _decode_id
    from services.k2_practice.practical_math import build_task

    # The answer is deliberately absent from the HTTP lesson. Compute it from
    # the deterministic task only inside the test, never through the response.
    auth = decode_token(headers["Authorization"].split(" ", 1)[1])
    assert auth is not None
    claims, _ = _decode_id(
        auth,
        lesson["lesson_id"],
    )
    choice = build_task(
        claims["level"], claims["topic"], claims["seed"], "your_turn", 0,
    ).accept_choice
    response = _answer(
        client,
        headers,
        lesson["lesson_id"],
        phase="your_turn",
        choice=choice,
        submission_id="submission_000002",
    )
    assert response.status_code == 200
    assert response.json()["recorded"] is False
    assert response.json()["demo"] is True

    assert client.portal.call(counts) == before


def test_temporary_lesson_and_submission_state_are_bounded(client, monkeypatch):
    from services.k2_practice import demo_math

    _, headers = _session(client, grade="K")
    monkeypatch.setattr(demo_math, "MAX_LESSONS", 2)
    first = _lesson(client, headers).json()
    _lesson(client, headers)
    _lesson(client, headers)
    assert len(demo_math._lessons) == 2
    assert _answer(
        client, headers, first["lesson_id"],
        choice=first["together"][0]["choices"][0],
    ).status_code == 404

    monkeypatch.setattr(demo_math, "MAX_SUBMISSIONS_PER_LESSON", 1)
    lesson = _lesson(client, headers).json()
    assert _answer(
        client, headers, lesson["lesson_id"],
        choice=lesson["together"][0]["choices"][0],
    ).status_code == 200
    assert _answer(
        client, headers, lesson["lesson_id"],
        phase="your_turn",
        choice=lesson["your_turn"][0]["choices"][0],
        submission_id="submission_over_001",
    ).status_code == 409
