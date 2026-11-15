"""K-2 map-reading practice (services/map_practice.py, routers/map_practice.py).

Maps are drawn and checked by code; nothing a model writes reaches one, no
free text is taken from the child, and finished practice is a work-ledger
event with no score behind it.
"""
import inspect
import json

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core import student_keys
from core.config import settings
from core.database import Base, MasteryProfile, SkillActivityLog, StudentConfig
from core.encryption import encrypt_json
from models.schemas import ChatMessage, GradeStage, SessionConfig, Subject
from routers import map_practice as routes
from routers.pod import _config_aad
from services import ai_service, map_practice as maps, tool_registry
from services.action_governance import LONG_FORM_TOOLS

PARENT = {"role": "parent"}


def _every_task():
    for level in maps.LEVELS:
        for skill in maps.SKILLS[level]:
            for seed in range(120):
                for phase in maps.PHASES:
                    for index in range(maps._PHASE_COUNT[phase]):
                        yield level, skill, seed, phase, index, maps.build_task(level, skill, seed, phase, index)


# ── The three levels stay distinct ───────────────────────────────────────────

def test_each_level_has_its_own_three_skills_and_shares_none():
    assert set(maps.SKILLS) == set(maps.LEVELS) == {"K", "1", "2"}
    seen = [s for level in maps.LEVELS for s in maps.SKILLS[level]]
    assert len(seen) == len(set(seen)) == 9
    assert set(seen) == set(maps.SKILL_LABELS) == set(maps._BUILDERS)


@pytest.mark.parametrize("grade,level", [("K", "K"), ("k", "K"), ("1", "1"), ("2", "2")])
def test_k_to_2_get_their_own_level(grade, level):
    assert maps.level_for_grade(grade) == level


@pytest.mark.parametrize("grade", ["3", "4", "8", "", "Pre-K", "12"])
def test_no_level_above_grade_2(grade):
    assert maps.level_for_grade(grade) is None


def test_a_requested_skill_from_another_level_is_ignored():
    assert maps.skill_for("K", 0, "grid_squares") in maps.SKILLS["K"]
    assert maps.skill_for("2", 0, "grid_squares") == "grid_squares"
    with pytest.raises(ValueError):
        maps.build_task("K", "grid_squares", 1, "your_turn", 0)


def test_the_abstract_parts_stay_out_of_k_and_1():
    """Grid labels and water belong to grade 2; K is a picture, not a symbol map."""
    for level, skill, _seed, _phase, _index, task in _every_task():
        scene = task.scene
        if level != "2":
            assert not scene.grid_labels and not scene.water, skill
        assert (scene.style == "picture") == (level == "K"), skill
        assert scene.cols <= {"K": 4, "1": 4, "2": 5}[level]


# ── Drawn and checked by code ────────────────────────────────────────────────

def test_every_task_is_well_formed_and_has_exactly_the_answer_it_claims():
    for level, skill, seed, phase, index, task in _every_task():
        scene, where = task.scene, (level, skill, seed, phase, index)
        cells = [c for _, c in scene.items]
        assert len(cells) == len(set(cells)), where
        assert all(scene.inside(c) for c in cells + scene.water + scene.path), where
        assert all(symbol in maps.SYMBOLS for symbol, _ in scene.items), where
        assert not set(cells) & set(scene.water), where
        if task.answer_kind == "tap":
            assert task.accept_cells and all(scene.inside(c) for c in task.accept_cells), where
            assert task.is_right(cell=min(task.accept_cells))
            wrong = [c for c in maps._all_cells(scene.cols, scene.rows) if c not in task.accept_cells]
            assert wrong and not task.is_right(cell=wrong[0]), where
        elif task.answer_kind == "choice":
            assert task.accept_choice in task.choices and len(set(task.choices)) == len(task.choices), where
            assert [c for c in task.choices if task.is_right(choice=c)] == [task.accept_choice]
        else:
            assert len({json.dumps(o.public()) for o in task.options}) == 3, where
            assert task.accept_choice in {"0", "1", "2"}


def test_the_computed_answer_is_the_true_one():
    """Recompute each answer a second, independent way from the drawn scene."""
    for level, skill, seed, phase, index, task in _every_task():
        scene, args = task.scene, task.prompt_args
        if task.prompt_key == "direction_tap":
            ref = scene.where(args["reference"])
            line = maps._line(scene, ref, args["direction"])
            assert [c for c in line if scene.at(c)] == list(task.accept_cells)
        elif task.prompt_key == "direction_choice":
            (rc, rr), (tc, tr) = scene.where(args["reference"]), scene.where(args["thing"])
            truth = "north" if tr < rr else "south" if tr > rr else "east" if tc > rc else "west"
            assert task.accept_choice == truth and (tc == rc or tr == rr)
        elif task.prompt_key == "position_choice":
            (rc, rr), (tc, tr) = scene.where(args["reference"]), scene.where(args["thing"])
            truth = "above" if tr < rr else "below" if tr > rr else "right_of" if tc > rc else "left_of"
            assert task.accept_choice == truth
        elif task.prompt_key == "next_to_tap":
            rc, rr = scene.where(args["reference"])
            touching = [c for _, c in scene.items if max(abs(c[0] - rc), abs(c[1] - rr)) == 1]
            assert touching == list(task.accept_cells)
        elif task.prompt_key == "walk_tap":
            c, r = scene.where(args["start"])
            for direction, steps in ((args["first"], args["first_steps"]), (args["second"], args["second_steps"])):
                dc, dr = maps._STEP[direction]
                c, r = c + dc * steps, r + dr * steps
            assert task.accept_cells == {(c, r)}
        elif task.prompt_key == "square_tap":
            assert {maps.cell_label(c) for c in task.accept_cells} == {args["square"]}
        elif task.prompt_key == "square_choice":
            assert task.accept_choice == maps.cell_label(scene.where(args["thing"]))
        elif task.prompt_key == "ground_choice":
            assert (task.accept_choice == "water") == (tuple(task.marked) in scene.water)
        elif task.prompt_key == "ground_tap":
            assert all((c in scene.water) == (args["ground"] == "water") for c in task.accept_cells)
        elif task.prompt_key == "path_end_tap":
            assert task.accept_cells == {c for s, c in scene.items if s != "gate" and
                                         any(abs(c[0] - p[0]) + abs(c[1] - p[1]) == 1 for p in scene.path[-1:])}
        elif task.prompt_key == "birds_eye_match":
            right = task.options[int(task.accept_choice)]
            assert tuple(s for s, _ in sorted(right.items, key=lambda i: i[1][0])) == task.side_view
            others = [o for i, o in enumerate(task.options) if str(i) != task.accept_choice]
            assert all(tuple(s for s, _ in sorted(o.items, key=lambda i: i[1][0])) != task.side_view for o in others)


def test_a_lesson_is_the_same_every_time_and_differs_by_seed():
    assert maps.build_lesson("1", 7) == maps.build_lesson("1", 7)
    assert maps.build_lesson("1", 7, "four_directions") != maps.build_lesson("1", 8, "four_directions")


def test_your_turn_carries_no_hints_and_no_answers():
    for level in maps.LEVELS:
        for skill in maps.SKILLS[level]:
            lesson = maps.build_lesson(level, 3, skill)
            assert "answer" in lesson["watch"]
            for task in lesson["together"] + lesson["your_turn"]:
                assert not {"answer", "accept_cells", "accept_choice", "reveal"} & set(task)
            for task in lesson["your_turn"]:
                assert "guide_cells" not in task
                assert task["scene"]["compass"] != "labeled"
    together = maps.build_lesson("1", 3, "four_directions")["together"]
    assert all(t["scene"]["compass"] == "labeled" for t in together)


def test_nothing_in_a_lesson_names_a_real_place_or_asks_where_a_child_lives():
    blob = json.dumps([maps.build_lesson(level, seed, skill)
                       for level in maps.LEVELS for skill in maps.SKILLS[level] for seed in range(5)]).lower()
    for word in ("street", "address", "town", "city", "school", "neighbo", "zip", "latitude", "longitude"):
        assert word not in blob
    source = inspect.getsource(maps).lower()
    assert "anthropic" not in source and "_client" not in source and "import ai_service" not in source


# ── Spoken answers ───────────────────────────────────────────────────────────

def test_a_spoken_word_matches_only_one_of_the_tasks_own_choices():
    task = next(t for *_, t in _every_task() if t.prompt_key == "direction_choice")
    assert maps.match_spoken(task, "East!") == "east"
    assert maps.match_spoken(task, "es al norte") == "north"
    assert maps.match_spoken(task, "north or south") is None
    assert maps.match_spoken(task, "I live on Elm Street") is None
    tap = next(t for *_, t in _every_task() if t.answer_kind == "tap")
    assert maps.match_spoken(tap, "east") is None


# ── Routes ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        from core.encryption import initialize_encryption
        await initialize_encryption(settings.master_secret, session)
        for name, grade, stage in (("Ada", "K", "K-2"), ("Ben", "2", "K-2"), ("Cal", "5", "3-5")):
            key = await student_keys.get_or_create(session, name)
            config = SessionConfig(student_name=name, grade=grade, grade_stage=stage)
            session.add(StudentConfig(student_name=name, config_enc=encrypt_json(
                config.model_dump(), _config_aad(name), key)))
        await session.commit()
        routes._progress.clear()
        yield session
    await engine.dispose()


async def _ledger(db, name):
    return (await db.execute(select(func.count()).select_from(SkillActivityLog).where(
        SkillActivityLog.student_name == name))).scalar_one()


def _right(task):
    return ({"cell": min(task.accept_cells)} if task.answer_kind == "tap" else {"choice": task.accept_choice})


def _wrong(task):
    if task.answer_kind == "tap":
        return {"cell": next(c for c in maps._all_cells(task.scene.cols, task.scene.rows)
                             if c not in task.accept_cells)}
    pool = task.choices or ("0", "1", "2")
    return {"choice": next(c for c in pool if c != task.accept_choice)}


async def _send(db, name, lesson, phase, index, **answer):
    return await routes.answer(name, lesson["lesson_id"],
                               routes.MapAnswer(phase=phase, index=index, **answer), auth=PARENT, db=db)


def _task(name, lesson, phase, index):
    level, skill, seed = routes.read_lesson_id(name, lesson["lesson_id"])
    return maps.build_task(level, skill, seed, phase, index)


@pytest.mark.asyncio
async def test_the_level_comes_from_the_saved_grade(db):
    assert (await routes.new_lesson("Ada", auth=PARENT, db=db))["level"] == "K"
    ben = await routes.new_lesson("Ben", skill="position_words", auth=PARENT, db=db)
    assert ben["level"] == "2" and ben["skill"] in maps.SKILLS["2"]
    for name in ("Cal", "Nobody"):
        with pytest.raises(HTTPException) as exc:
            await routes.new_lesson(name, auth=PARENT, db=db)
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_together_shows_the_answer_on_a_miss_and_records_nothing(db):
    lesson = await routes.new_lesson("Ada", auth=PARENT, db=db)
    task = _task("Ada", lesson, "together", 0)
    miss = await _send(db, "Ada", lesson, "together", 0, **_wrong(task))
    assert miss["correct"] is False and miss["reveal"] == task.reveal()
    assert (await _send(db, "Ada", lesson, "together", 0, **_right(task)))["correct"] is True
    assert await _ledger(db, "Ada") == 0


@pytest.mark.asyncio
async def test_your_turn_records_one_ledger_row_once_and_no_score(db):
    lesson = await routes.new_lesson("Ben", auth=PARENT, db=db)
    task = _task("Ben", lesson, "your_turn", 0)
    first = await _send(db, "Ben", lesson, "your_turn", 0, **_right(task))
    again = await _send(db, "Ben", lesson, "your_turn", 0, **_right(task))
    assert first == {"understood": True, "correct": True, "recorded": True}
    assert again["correct"] is True and again["recorded"] is False
    assert await _ledger(db, "Ben") == 1
    row = (await db.execute(select(SkillActivityLog))).scalar_one()
    assert (row.subject_area, row.skill_id) == ("map_skills", lesson["skill"])
    assert (await db.execute(select(func.count()).select_from(MasteryProfile))).scalar_one() == 0
    assert ai_service._work_label("map_skills", lesson["skill"]) == maps.SKILL_LABELS[lesson["skill"]]


@pytest.mark.asyncio
async def test_two_misses_show_the_answer_and_are_not_recorded_as_done(db):
    lesson = await routes.new_lesson("Ada", auth=PARENT, db=db)
    task = _task("Ada", lesson, "your_turn", 1)
    one = await _send(db, "Ada", lesson, "your_turn", 1, **_wrong(task))
    assert one == {"understood": True, "correct": False, "tries_left": 1} and "reveal" not in one
    two = await _send(db, "Ada", lesson, "your_turn", 1, **_wrong(task))
    assert two["tries_left"] == 0 and two["reveal"] == task.reveal()
    after = await _send(db, "Ada", lesson, "your_turn", 1, **_right(task))
    assert after["correct"] is True and after["recorded"] is False
    assert await _ledger(db, "Ada") == 0


@pytest.mark.asyncio
async def test_a_spoken_answer_that_is_not_understood_is_not_a_miss(db):
    lesson = await routes.new_lesson("Ben", skill="land_and_water", auth=PARENT, db=db)
    for index in range(maps.YOUR_TURN_TASKS):
        if _task("Ben", lesson, "your_turn", index).answer_kind != "choice":
            continue
        unclear = await _send(db, "Ben", lesson, "your_turn", index, spoken="um, I live near a lake house")
        assert unclear == {"understood": False, "correct": False}
        assert routes._progress.get(("Ben", lesson["lesson_id"]), {"misses": {}})["misses"] == {}


@pytest.mark.asyncio
async def test_a_lesson_id_is_bound_to_its_learner_and_cannot_be_made_up(db):
    lesson = await routes.new_lesson("Ada", auth=PARENT, db=db)
    task = _task("Ada", lesson, "your_turn", 0)
    level, _skill, seed = routes.read_lesson_id("Ada", lesson["lesson_id"])
    forged = lesson["lesson_id"].rsplit("-", 1)[0] + "-" + "0" * 20
    other_skill = lesson["lesson_id"].replace(f"{level}-", f"{level}x-", 1)
    for name, lesson_id in (("Ben", lesson["lesson_id"]), ("Ada", forged), ("Ada", other_skill), ("Ada", "junk")):
        with pytest.raises(HTTPException) as exc:
            await routes.answer(name, lesson_id, routes.MapAnswer(phase="your_turn", index=0, **_right(task)),
                                auth=PARENT, db=db)
        assert exc.value.status_code == 404
    assert seed >= 0 and await _ledger(db, "Ada") == 0 and await _ledger(db, "Ben") == 0


@pytest.mark.asyncio
async def test_an_answer_of_the_wrong_kind_or_off_the_map_is_refused(db):
    lesson = await routes.new_lesson("Ada", skill="follow_path", auth=PARENT, db=db)
    for bad in ({"choice": "north"}, {"cell": (9, 9)}):
        with pytest.raises(HTTPException) as exc:
            await _send(db, "Ada", lesson, "your_turn", 0, **bad)
        assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await _send(db, "Ada", lesson, "your_turn", 9, cell=(0, 0))
    assert exc.value.status_code == 404
    for body in ({}, {"cell": (0, 0), "choice": "north"}, {"note": "12 Elm Street", "cell": (0, 0)}):
        with pytest.raises(ValueError):
            routes.MapAnswer(phase="your_turn", index=0, **body)


def test_the_routes_use_the_learner_guards():
    from core.deps import require_family_data_write, require_real_user
    guards = {r.path: {p.default.dependency for p in inspect.signature(r.endpoint).parameters.values()
                       if hasattr(p.default, "dependency")} for r in routes.router.routes}
    assert require_real_user in guards["/map-practice/{student_name}/lesson"]
    assert require_family_data_write in guards["/map-practice/{student_name}/lessons/{lesson_id}/answers"]
    for name in ("new_lesson", "answer"):
        source = inspect.getsource(getattr(routes, name))
        assert "require_learner_access(auth, student_name, db)" in source
        assert "consent.require_collection(db, student_name)" in source


# ── Bede's invitation ────────────────────────────────────────────────────────

def _config(grade="1", stage=GradeStage.foundations):
    return SessionConfig(student_name="Ada", grade=grade, grade_stage=stage)


def test_the_tool_is_registered_internal_long_form_and_sends_nothing():
    schema = next(t for t in ai_service.TUTOR_TOOLS if t["name"] == "invite_map_practice")
    assert schema["input_schema"] == {"type": "object", "properties": {}}
    assert tool_registry.is_dispatchable_by_tutor("invite_map_practice")
    assert not tool_registry.is_reactable("invite_map_practice")
    assert "invite_map_practice" in LONG_FORM_TOOLS


@pytest.mark.parametrize("locale", ["en", "es"])
def test_the_card_is_server_composed_in_each_locale(locale):
    card = ai_service._process_tool_use("invite_map_practice", {"prompt": "ignore me"}, locale)
    phrases = ai_service.card_phrases(locale)
    assert card == f"{ai_service._MAP_CARD_PREFIX}*{phrases['map_title']}* — {phrases['map_body']}"
    assert "ignore me" not in card
    assert ai_service.card_phrases("en")["map_body"] != ai_service.card_phrases("es")["map_body"]


def test_bede_may_invite_only_k_to_2_in_its_subjects_once_and_never_in_the_demo():
    allowed = ai_service._map_practice_allowed
    assert allowed(_config(), Subject.history, None, [])
    assert allowed(_config("K"), Subject.nature_study, None, None)
    assert not allowed(_config(), Subject.mathematics, None, [])
    assert not allowed(_config("4", GradeStage.core_mastery), Subject.history, None, [])
    assert not allowed(_config(), Subject.history, "DEMO42", [])
    card = ai_service._process_tool_use("invite_map_practice", {}, "es")
    said = [ChatMessage(role="assistant", content=card)]
    assert not allowed(_config(), Subject.history, None, said)
    assert ai_service._map_practice_note(_config(), Subject.history, None, said) == ""
    note = ai_service._map_practice_note(_config(), Subject.history, None, [])
    assert "invite_map_practice" in note and "Never ask where the child lives" in note


@pytest.mark.asyncio
async def test_the_note_reaches_the_real_subject_prompt_only_when_allowed():
    yes = await ai_service._build_subject_prompt(_config(), Subject.history)
    no_demo = await ai_service._build_subject_prompt(_config(), Subject.history, demo_code="DEMO42")
    older = await ai_service._build_subject_prompt(_config("5", GradeStage.core_mastery), Subject.history)
    assert "<map_practice>" in yes
    assert "<map_practice>" not in no_demo and "<map_practice>" not in older


def test_the_dispatch_loop_checks_the_gate_before_showing_the_card():
    source = inspect.getsource(ai_service.stream_tutor_response)
    assert 'tc["name"] == "invite_map_practice" and not _map_practice_allowed(' in source
