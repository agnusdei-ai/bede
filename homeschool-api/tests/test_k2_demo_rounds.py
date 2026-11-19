"""Public-demo Sound Time and Map Practice stay temporary, demo-only and unrecorded
(decision 40(g) as amended 2026-11-19; the same boundary as demo Number Time)."""

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
def reset(monkeypatch):
    from core import middleware
    from core.config import settings
    from services.k2_practice import demo_rounds

    middleware.reset_rate_limiter()
    monkeypatch.setattr(settings, "rate_limit_auth_per_minute", 1000)
    demo_rounds.clear_state()
    yield
    demo_rounds.clear_state()
    middleware.reset_rate_limiter()


PATHS = {"phonics": "/k2-practice/demo/phonics", "maps": "/k2-practice/demo/maps"}


def _session(client, grade="K"):
    code = client.post("/auth/demo-code", json={"grade": grade, "student_name": "Sam"})
    assert code.status_code == 200, code.text
    login = client.post("/auth/login", json={"role": "demo_code", "credential": code.json()["code"]})
    assert login.status_code == 200, login.text
    return {"Authorization": "Bearer " + login.json()["access_token"]}


def _task(lesson, phase, index):
    from services.k2_practice import demo_rounds

    return demo_rounds._task(demo_rounds._rounds[lesson["lesson_id"]], phase, index)


def _right(area, task):
    if area == "maps" and task.answer_kind == "tap":
        return {"cell": list(min(task.accept_cells))}
    return {"choice": task.accept_choice}


def _wrong(area, task):
    if area == "maps" and task.answer_kind == "tap":
        cells = [(c, r) for c in range(task.scene.cols) for r in range(task.scene.rows)]
        return {"cell": list(next(c for c in cells if c not in task.accept_cells))}
    if area == "maps" and task.answer_kind == "scene_choice":
        return {"choice": next(str(i) for i in range(len(task.options)) if str(i) != task.accept_choice)}
    return {"choice": next(c for c in task.choices if c != task.accept_choice)}


def _answer(client, headers, area, lesson, phase, index, answer):
    return client.post(
        f"{PATHS[area]}/lessons/{lesson['lesson_id']}/answers",
        headers=headers, json={"phase": phase, "index": index, **answer},
    )


@pytest.mark.parametrize("area", ["phonics", "maps"])
@pytest.mark.parametrize("grade", ["K", "1", "2"])
def test_demo_round_uses_the_sign_ins_grade_and_says_it_is_not_recorded(client, area, grade):
    headers = _session(client, grade)
    response = client.get(f"{PATHS[area]}/lesson", headers=headers)
    assert response.status_code == 200, response.text
    lesson = response.json()
    assert lesson["level"] == grade
    assert lesson["demo"] is True and lesson["recorded"] is False
    assert lesson["together"] and lesson["your_turn"]
    assert all("answer" not in task for task in lesson["your_turn"])

    task = _task(lesson, "your_turn", 0)
    result = _answer(client, headers, area, lesson, "your_turn", 0, _right(area, task))
    assert result.status_code == 200, result.text
    assert result.json() == {"understood": True, "correct": True, "demo": True, "recorded": False}


@pytest.mark.parametrize("area", ["phonics", "maps"])
def test_your_turn_shows_the_answer_after_two_misses_and_then_settles(client, area):
    headers = _session(client, "1")
    lesson = client.get(f"{PATHS[area]}/lesson", headers=headers).json()
    task = _task(lesson, "your_turn", 1)
    first = _answer(client, headers, area, lesson, "your_turn", 1, _wrong(area, task)).json()
    assert first["correct"] is False and first["tries_left"] == 1 and "reveal" not in first
    second = _answer(client, headers, area, lesson, "your_turn", 1, _wrong(area, task)).json()
    assert second["tries_left"] == 0 and second["reveal"] == task.reveal()
    again = _answer(client, headers, area, lesson, "your_turn", 1, _right(area, task))
    assert again.status_code == 409


@pytest.mark.parametrize("area", ["phonics", "maps"])
def test_together_miss_shows_the_answer_at_once(client, area):
    headers = _session(client, "2")
    lesson = client.get(f"{PATHS[area]}/lesson", headers=headers).json()
    task = _task(lesson, "together", 0)
    result = _answer(client, headers, area, lesson, "together", 0, _wrong(area, task)).json()
    assert result["correct"] is False and result["reveal"] == task.reveal()


@pytest.mark.parametrize("area", ["phonics", "maps"])
def test_round_belongs_to_one_sign_in_one_area_and_one_process(client, area):
    from services.k2_practice import demo_rounds

    first, second = _session(client, "K"), _session(client, "K")
    lesson = client.get(f"{PATHS[area]}/lesson", headers=first).json()
    answer = _right(area, _task(lesson, "together", 0))
    assert _answer(client, second, area, lesson, "together", 0, answer).status_code == 404
    other = "maps" if area == "phonics" else "phonics"
    assert _answer(client, first, other, lesson, "together", 0, answer).status_code == 404
    demo_rounds.clear_state()  # a restart: the old round is refused, not rebuilt
    assert _answer(client, first, area, lesson, "together", 0, answer).status_code == 404


def test_non_k2_grade_and_non_demo_tokens_are_refused(client):
    from core.security import create_access_token

    headers = _session(client, "4")
    for path in PATHS.values():
        assert client.get(f"{path}/lesson", headers=headers).status_code == 404
        assert client.get(f"{path}/lesson").status_code == 401
        parent = create_access_token({"sub": "parent", "role": "parent"})
        assert client.get(f"{path}/lesson", headers={"Authorization": "Bearer " + parent}).status_code == 403


@pytest.mark.parametrize("body", [
    {"phase": "together", "index": 0},
    {"phase": "together", "index": 0, "choice": "a", "cell": [0, 0]},
    {"phase": "together", "index": 0, "spoken": "cat"},
    {"phase": "watch", "index": 0, "choice": "a"},
])
def test_malformed_demo_answers_are_refused(client, body):
    headers = _session(client, "K")
    lesson = client.get(f"{PATHS['phonics']}/lesson", headers=headers).json()
    response = client.post(f"{PATHS['phonics']}/lessons/{lesson['lesson_id']}/answers", headers=headers, json=body)
    assert response.status_code == 422


def test_demo_rounds_never_write_records_or_call_a_model(client, demo_db, monkeypatch):
    from core.database import (
        DemoCodeActivityLog, DemoCodeParentConfig, MasteryProfile, SkillActivityLog,
        StudentConfig, StudentKey,
    )
    import services.ai_service as ai_service

    def forbidden(*_args, **_kwargs):
        raise AssertionError("demo practice must not call a model")

    monkeypatch.setattr(ai_service, "stream_tutor_response", forbidden)

    async def counts():
        async with demo_db() as db:
            return tuple([
                await db.scalar(select(func.count()).select_from(table))
                for table in (StudentConfig, StudentKey, SkillActivityLog, MasteryProfile,
                              DemoCodeActivityLog, DemoCodeParentConfig)
            ])

    headers = _session(client, "K")
    before = client.portal.call(counts)
    for area in PATHS:
        lesson = client.get(f"{PATHS[area]}/lesson", headers=headers).json()
        for index in range(len(lesson["your_turn"])):
            task = _task(lesson, "your_turn", index)
            assert _answer(client, headers, area, lesson, "your_turn", index, _right(area, task)).json()["recorded"] is False
    assert client.portal.call(counts) == before


def test_temporary_state_is_bounded(client, monkeypatch):
    from services.k2_practice import demo_rounds

    monkeypatch.setattr(demo_rounds, "MAX_LESSONS", 3)
    headers = _session(client, "K")
    for _ in range(5):
        assert client.get(f"{PATHS['maps']}/lesson", headers=headers).status_code == 200
    assert len(demo_rounds._rounds) == 3
