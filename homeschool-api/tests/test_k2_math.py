"""K-2 practical math practice: the builder (services/k2_practice/practical_math.py),
its three new picture kinds (models/practice.py's PieceDiagram,
services/practice/diagrams.py), and its routes (routers/k2_practice.py).

Every number is chosen by code and every answer is worked out twice (the math
pack's exact evaluator and the picture's own count); nothing a child types is
accepted or kept; and a "Your turn" answer counts toward the math record at
the owner's weights (decision 40(b)), through process_evidence's
`confidence`, without the early-evidence boost and without advancing
evidence_count, while every other caller of that function behaves as before.
"""
import asyncio
import inspect
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core import student_keys
from core.config import settings
from core.database import Base, MasteryProfile, SkillActivityLog, StudentConfig
from core.encryption import decrypt_json, encrypt_json, student_aad
from models.practice import DIAGRAM_KINDS, PIECE_DIAGRAM_KINDS, Diagram
from models.schemas import SessionConfig
from routers import k2_practice as routes
from routers.pod import _config_aad
from services import ai_service
from services import diagnostic as math_record
from services.diagnostic.mastery import calibration_weight_for, new_vector
from services.diagnostic.skill_map import GradeBand, get_skill
from services.k2_practice import phonics
from services.k2_practice import practical_math as pm
from services.practice import diagrams
from services.practice.evidence import QUIZ_EVIDENCE_WEIGHT

PARENT = {"role": "parent"}


def _every_task(seeds=range(60)):
    for level in pm.LEVELS:
        for topic in pm.TOPICS:
            for seed in seeds:
                for phase in pm.PHASES:
                    for index in range(pm._PHASE_COUNT[phase]):
                        yield level, topic, seed, phase, index, pm.build_task(level, topic, seed, phase, index)


# ── The builder ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("grade,level,start", [("K", "K", "count"), ("k", "K", "count"), ("1", "1", "add"),
                                               ("2", "2", "add")])
def test_each_grade_starts_at_its_own_topic(grade, level, start):
    assert pm.level_for_grade(grade) == level
    assert pm.topic_for(level) == start and pm.topic_for(level, {}) == start


@pytest.mark.parametrize("grade", ["3", "4", "8", "", "Pre-K"])
def test_no_level_above_grade_2(grade):
    assert pm.level_for_grade(grade) is None


def test_math_and_phonics_share_one_level_vocabulary():
    # The routes read both areas' level through one helper.
    assert pm.LEVELS == phonics.LEVELS


def test_the_next_topic_follows_the_saved_record_in_a_fixed_order():
    secure = {"oa.add_within_20": 0.95}
    assert pm.topic_for("1", secure) == "subtract"
    # A secure later topic never lets a lesson skip an earlier one.
    assert pm.topic_for("1", {"oa.subtract_within_20": 0.95}) == "add"
    everything = {skill: 0.95 for skill in pm.TOPIC_SKILL.values()}
    assert pm.topic_for("2", everything) == pm.LEVEL_TOPICS["2"][-1]


def test_every_skill_is_an_existing_k2_skill_and_no_new_id_is_made():
    spec_skills = {"cc.count_objects_20", "cc.compare_quantities", "oa.add_within_20",
                   "oa.subtract_within_20", "cc.number_bonds", "oa.fact_fluency_20"}
    for topic, skill in pm.TOPIC_SKILL.items():
        assert get_skill(skill) is not None, skill
        assert get_skill(skill).band == GradeBand.K_2, skill
        assert skill in spec_skills, skill
    for level, topics in pm.LEVEL_TOPICS.items():
        assert set(topics) <= set(pm.TOPICS), level


def test_every_question_is_well_formed_and_has_exactly_one_right_choice():
    for level, topic, seed, phase, index, task in _every_task():
        where = (level, topic, seed, phase, index)
        assert len(set(task.choices)) == len(task.choices), where
        assert [c for c in task.choices if task.is_right(c)] == [task.accept_choice], where
        if task.choice_kind == "number":
            assert len(task.choices) == pm.CHOICES_PER_LEVEL[level], where
            assert [int(c) for c in task.choices] == sorted(int(c) for c in task.choices), where
        elif task.choice_kind == "color":
            assert task.choices == pm.COMPARE_CHOICES, where
        else:
            assert task.choice_kind == "build", where
            assert task.choices == tuple(str(i) for i in range(task.build["capacity"] + 1)), where
        # Every number stays within 20, the K-2 range.
        assert all(int(c) <= 20 for c in task.choices if c.isdigit()), where


def _recount(task) -> str:
    """The answer worked out a third way, from the picture's numbers with
    plain integer arithmetic, sharing no code with the module under test."""
    d = task.diagram
    if task.choice_kind == "build":
        start, b = task.build["start"], task.prompt_args
        if task.topic == "count":
            return b["n"]
        if task.topic == "add":
            return str(int(b["a"]) + int(b["b"]))
        if task.topic == "subtract":
            return str(int(b["a"]) - int(b["b"]))
        assert start == int(b["part"])
        return b["whole"]
    if d["kind"] == "counters":
        if len(d["groups"]) == 1:
            return str(d["groups"][0]["count"])
        a, b = (g["count"] for g in d["groups"])
        return "same" if a == b else "red" if a > b else "yellow"
    if d["kind"] == "ten_frame":
        return str(d.get("red", 0) + d.get("yellow", 0) - d.get("crossed", 0))
    known = next(p for p in d["parts"] if p is not None)
    return str(d["whole"] - known)


def test_the_answer_is_the_true_one():
    for level, topic, seed, phase, index, task in _every_task():
        assert task.accept_choice == _recount(task), (level, topic, seed, phase, index)


def test_the_math_packs_evaluator_decides_what_is_right():
    """The builder asks the math pack's exact evaluator for every arithmetic
    answer. A wrong evaluator means no question is built at all: the picture's
    own count then disagrees and the question is refused."""
    pm._problems.cache_clear()
    with patch.object(pm, "evaluate", lambda expression: __import__("fractions").Fraction(99)):
        for topic in ("compare", "add", "subtract", "bond"):
            with pytest.raises(ValueError):
                pm.build_task("1", topic, 3, "your_turn", 0)
    pm._problems.cache_clear()
    calls = []
    real = pm.evaluate
    with patch.object(pm, "evaluate", lambda e: calls.append(e) or real(e)):
        task = pm.build_task("1", "add", 3, "your_turn", 0)
    assert calls and task.expression in calls


def test_a_question_whose_picture_disagrees_is_refused():
    good = pm.build_task("K", "add", 1, "your_turn", 0)
    wrong = str(int(good.accept_choice) + 1)
    bad = pm.Task(good.topic, good.prompt_key, good.prompt_args, good.diagram, good.choice_kind,
                  tuple(sorted(set(good.choices) | {wrong}, key=int)), wrong, good.expression)
    with pytest.raises(ValueError):
        pm._checked(bad)


def test_a_lesson_is_the_same_every_time_differs_by_seed_and_never_repeats_a_problem():
    a = pm.build_lesson("1", 5, "add")
    assert a == pm.build_lesson("1", 5, "add")
    assert a != pm.build_lesson("1", 6, "add")
    for level in pm.LEVELS:
        for topic in pm.LEVEL_TOPICS[level]:
            for seed in range(30):
                problems = pm._problems(level, topic, seed)
                assert len(set(problems)) == len(problems), (level, topic, seed)


def test_your_turn_has_no_guide_no_ghost_and_no_answer():
    for level in pm.LEVELS:
        for topic in pm.LEVEL_TOPICS[level]:
            for seed in range(20):
                lesson = pm.build_lesson(level, seed, topic)
                for item in lesson["your_turn"]:
                    assert "answer" not in item and item["display"]["guide"] is False
                    assert "ghost" not in item["display"]
                for item in lesson["together"]:
                    assert "answer" not in item and item["display"]["guide"] is True
                    if item["choice_kind"] == "build":
                        task = pm.build_task(level, topic, seed, "together", item["index"])
                        assert item["display"]["ghost"] == int(task.accept_choice)
                assert lesson["watch"]["answer"]["choice"] in lesson["watch"]["choices"]


def test_every_topic_with_a_frame_builds_by_drag_or_tap_in_together_and_your_turn():
    for level in pm.LEVELS:
        for topic in pm.LEVEL_TOPICS[level]:
            lesson = pm.build_lesson(level, 2, topic)
            kinds = [i["choice_kind"] for i in lesson["together"] + lesson["your_turn"]]
            if topic == "compare":
                assert "build" not in kinds
            else:
                assert kinds.count("build") == 2, (level, topic)
                assert lesson["watch"]["choice_kind"] == "build"


def test_without_audio_a_math_lesson_is_the_same_lesson():
    """No math question works only by ear: the picture carries it."""
    assert pm.AUDIO_ONLY_TOPICS == frozenset()
    for level in pm.LEVELS:
        for topic in pm.LEVEL_TOPICS[level]:
            loud, quiet = pm.build_lesson(level, 9, topic), pm.build_lesson(level, 9, topic, audio=False)
            for key in ("watch", "together", "your_turn"):
                assert quiet[key] == loud[key]
            assert quiet["needs_audio"] is False


def test_nothing_here_calls_a_model():
    source = inspect.getsource(pm) + inspect.getsource(routes)
    for forbidden in ("ai_service", "_client", "anthropic", "openai", "resolve_with_failover"):
        assert forbidden not in source


# ── The three new picture kinds ──────────────────────────────────────────────

def test_every_picture_a_lesson_sends_is_in_the_closed_vocabulary():
    for _level, _topic, _seed, _phase, _index, task in _every_task(range(20)):
        piece = diagrams.parse_piece(task.diagram)
        assert piece.kind in PIECE_DIAGRAM_KINDS


@pytest.mark.parametrize("raw", [
    {"kind": "ten_frame", "frames": 1, "red": 8, "yellow": 3},            # more than one frame holds
    {"kind": "ten_frame", "red": 3, "crossed": 4},                         # more crossed out than there are
    {"kind": "ten_frame", "frames": 3, "red": 1},                          # at most two frames
    {"kind": "number_bond", "whole": 7, "parts": [3, 4]},                  # nothing blank
    {"kind": "number_bond", "whole": None, "parts": [None, 4]},            # two blanks
    {"kind": "number_bond", "whole": 5, "parts": [7, None]},               # a part larger than the whole
    {"kind": "counters", "groups": [{"color": "blue", "count": 3}]},       # only red and yellow
    {"kind": "counters", "groups": []},
    {"kind": "counters", "groups": [{"color": "red", "count": 21}]},      # within 20
    {"kind": "counters", "groups": [{"color": "red", "count": 3}], "label": "<b>hi</b>"},  # no labels
    {"kind": "svg", "path": "M0 0"},
])
def test_the_new_kinds_refuse_anything_outside_their_vocabulary(raw):
    with pytest.raises(ValidationError):
        diagrams.parse_piece(raw)


def test_the_picture_works_out_its_own_answer():
    p = diagrams.parse_piece
    assert diagrams.answer(p({"kind": "counters", "groups": [{"color": "red", "count": 6}]}),
                           "How many counters are there?") == "6"
    two = {"kind": "counters", "groups": [{"color": "red", "count": 4}, {"color": "yellow", "count": 6}]}
    assert diagrams.answer(p(two), "Which has more?") == "yellow"
    assert diagrams.answer(p({**two, "groups": [two["groups"][0], {"color": "yellow", "count": 4}]}),
                           "Which has more?") == "same"
    assert diagrams.answer(p({"kind": "ten_frame", "frames": 2, "red": 8, "yellow": 5}), "How many in all?") == "13"
    assert diagrams.answer(p({"kind": "ten_frame", "red": 9, "crossed": 4}), "How many are left?") == "5"
    assert diagrams.answer(p({"kind": "number_bond", "whole": 7, "parts": [None, 3]}), "x") == "4"
    assert diagrams.answer(p({"kind": "number_bond", "whole": None, "parts": [8, 5]}), "x") == "13"
    # A question the picture cannot settle is left unsettled.
    assert diagrams.answer(p({"kind": "ten_frame", "red": 3}), "What color is it?") is None


def test_the_new_kinds_are_not_kinds_a_quiz_reader_may_emit():
    """They are a sibling vocabulary: a reader or a drafter cannot put one on
    a quiz page, so Diagram.tsx (which the demo mirrors) never has to draw
    one. Moving them into `Diagram` is a deliberate, owner-reviewed change."""
    assert not set(PIECE_DIAGRAM_KINDS) & set(DIAGRAM_KINDS)
    for raw in ({"kind": "counters", "groups": [{"color": "red", "count": 3}]},
                {"kind": "ten_frame", "red": 3}, {"kind": "number_bond", "whole": 5, "parts": [2, None]}):
        with pytest.raises(ValidationError):
            TypeAdapter(Diagram).validate_python(raw)
        assert diagrams.parse(raw) is None
    for kind in PIECE_DIAGRAM_KINDS:
        assert kind not in diagrams.PROMPT_SCHEMA


# ── Spoken answers ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("said,n", [
    ("seven", 7), ("siete", 7), ("it is 7", 7), ("I think SEVENTEEN", 17), ("diecisiete", 17),
    ("diez y siete", 17), ("dieciséis", 16), ("zero", 0), ("cero", 0), ("twenty", 20), ("veinte", 20),
])
def test_numbers_are_heard_in_english_and_spanish(said, n):
    task = pm.Task("add", "add_how_many", {"a": "1", "b": "1"}, {}, "number",
                   tuple(str(v) for v in (0, 6, 7, 16, 17, 20)), "7")
    assert pm.match_spoken(task, said) == str(n)


@pytest.mark.parametrize("said,choice", [
    ("ten thirty", "10:30"), ("half past ten", "10:30"), ("diez y media", "10:30"),
    ("las diez y media", "10:30"), ("ten o'clock", "10:00"), ("las diez", "10:00"),
    ("diez en punto", "10:00"), ("one o'clock", "1:00"), ("la una", "1:00"),
    ("quarter past two", "2:15"), ("dos y cuarto", "2:15"), ("quarter to three", "2:45"),
])
def test_times_are_heard_and_the_longer_phrase_wins(said, choice):
    """"ten thirty" contains "ten", but it names 10:30, never 10:00."""
    task = pm.Task("count", "count_how_many", {}, {}, "time",
                   ("10:00", "10:30", "1:00", "2:15", "2:45"), choice)
    assert pm.match_spoken(task, said) == choice


def test_quantities_are_heard_for_comparing():
    task = pm.build_task("K", "compare", 1, "your_turn", 0)
    for said, choice in (("the red ones", "red"), ("amarillos", "yellow"), ("they are the same", "same"),
                         ("son iguales", "same")):
        assert pm.match_spoken(task, said) == choice


def test_unmatched_or_ambiguous_speech_names_nothing_and_never_leaves_the_choices():
    task = pm.Task("add", "add_how_many", {"a": "3", "b": "4"}, {}, "number", ("6", "7", "8"), "7")
    for heard in ("", "dragon", "um", "seven or eight", "siete ocho", "twelve", "I live at 12 Elm Street"):
        assert pm.match_spoken(task, heard) is None
    for level, topic, seed, phase, index, t in _every_task(range(5)):
        for heard in ("seven", "red", "same", "twenty", "diez y media", "nine"):
            got = pm.match_spoken(t, heard)
            assert got is None or got in t.choices


def test_an_instruction_that_says_its_own_answer_takes_no_spoken_answer():
    """'Put 7 counters in the frame' says the answer, so saying 'seven' back is
    an echo, not counting. The rule bites exactly where the instruction holds
    the answer."""
    for _level, topic, _seed, _phase, _index, task in _every_task(range(20)):
        echoes = pm.speech_echoes_answer(task)
        assert echoes == (task.accept_choice in task.prompt_args.values())
        if echoes:
            assert pm.match_spoken(task, task.accept_choice) is None
    count_build = pm.build_task("K", "count", 1, "your_turn", 1)
    assert count_build.choice_kind == "build" and pm.speech_echoes_answer(count_build)


# ── The routes ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        from core.encryption import initialize_encryption
        await initialize_encryption(settings.master_secret, session)
        for name, grade, stage, offers in (
            ("Ada", "K", "K-2", "todays_subjects"), ("Ben", "1", "K-2", "todays_subjects"),
            ("Cal", "4", "3-5", "todays_subjects"), ("Dot", "1", "K-2", "off"),
            ("Eve", "1", "K-2", "approved_only"), ("Gus", "2", "K-2", "todays_subjects"),
        ):
            key = await student_keys.get_or_create(session, name)
            config = SessionConfig(student_name=name, grade=grade, grade_stage=stage, practice_offers=offers)
            session.add(StudentConfig(student_name=name, config_enc=encrypt_json(
                config.model_dump(), _config_aad(name), key)))
        await session.commit()
        routes._progress.clear()
        routes._rounds.clear()
        yield session
    await engine.dispose()


async def _ledger_rows(db, name):
    return (await db.execute(select(func.count()).select_from(SkillActivityLog).where(
        SkillActivityLog.student_name == name))).scalar_one()


async def _profile(db, name):
    return (await db.execute(select(MasteryProfile).where(
        MasteryProfile.student_name == name, MasteryProfile.subject_area == "mathematics"))).scalar_one_or_none()


async def _vector(db, name):
    row = await _profile(db, name)
    return decrypt_json(row.profile_enc, student_aad("mastery_profiles", "profile_enc", name, "mathematics"),
                        await student_keys.get_existing(db, name))


def _task(name, lesson, phase, index):
    level, topic, seed, _audio = routes.read_lesson_id(name, lesson["lesson_id"], area="math")
    return pm.build_task(level, topic, seed, phase, index)


def _wrong(task):
    return next(c for c in task.choices if c != task.accept_choice)


async def _send(db, name, lesson, phase, index, auth=PARENT, **answer):
    return await routes.answer_math(name, lesson["lesson_id"],
                                    routes.MathAnswer(phase=phase, index=index, **answer), auth=auth, db=db)


async def _lesson(db, name, auth=PARENT, audio=True):
    return await routes.new_math_lesson(name, audio=audio, auth=auth, db=db)


@pytest.mark.asyncio
async def test_the_level_comes_from_the_saved_grade_and_nothing_in_the_request_chooses_it(db):
    assert ((await _lesson(db, "Ada"))["level"], (await _lesson(db, "Ada"))["topic"]) == ("K", "count")
    assert (await _lesson(db, "Ben"))["level"] == "1"
    assert (await _lesson(db, "Gus"))["level"] == "2"
    assert set(inspect.signature(routes.new_math_lesson).parameters) == {"student_name", "audio", "auth", "db"}
    for name in ("Cal", "Dot", "Eve", "Nobody"):
        with pytest.raises(HTTPException) as exc:
            await _lesson(db, name)
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_the_topic_follows_the_saved_math_record(db):
    for _ in range(12):
        await math_record.process_evidence(db, "Ben", "probe.oa.add_within_20", "correct", 1.0, "K-2")
    assert (await _lesson(db, "Ben"))["topic"] == "subtract"


@pytest.mark.asyncio
async def test_together_shows_the_answer_on_a_miss_and_records_nothing(db):
    lesson = await _lesson(db, "Ben")
    for index in range(pm.TOGETHER_TASKS):
        task = _task("Ben", lesson, "together", index)
        miss = await _send(db, "Ben", lesson, "together", index, choice=_wrong(task))
        assert miss == {"understood": True, "correct": False, "reveal": task.reveal()}
        assert (await _send(db, "Ben", lesson, "together", index, choice=task.accept_choice))["correct"] is True
    assert await _ledger_rows(db, "Ben") == 0 and await _profile(db, "Ben") is None


def _expected(prior_vector, skill, confidence):
    """One step of the real engine at `confidence`, with no early boost."""
    from services.diagnostic.mastery import bayesian_update
    vector, _ = bayesian_update(prior_vector, {"probe_id": f"probe.{skill}", "outcome": "correct",
                                               "confidence": confidence}, calibration_weight=1.0)
    return vector[skill]


def test_the_weights_are_the_owners_product_defaults():
    assert routes.FIRST_TRY_WEIGHT == QUIZ_EVIDENCE_WEIGHT == 0.5
    assert routes.SECOND_TRY_WEIGHT == 0.25


@pytest.mark.asyncio
@pytest.mark.parametrize("misses,weight,assistance", [(0, 0.5, "unaided"), (1, 0.25, "with_a_hint")])
async def test_a_right_answer_records_one_row_and_one_observation_at_its_weight(db, misses, weight, assistance):
    seen = []
    real = math_record.process_evidence

    async def _spy(db_, name, probe, outcome, confidence, band, *args, **kwargs):
        seen.append((name, probe, outcome, confidence, band, args, kwargs))
        return await real(db_, name, probe, outcome, confidence, band, *args, **kwargs)

    lesson = await _lesson(db, "Ben")
    skill = lesson["skill"]
    task = _task("Ben", lesson, "your_turn", 0)
    with patch.object(routes.math_record, "process_evidence", _spy):
        for _ in range(misses):
            assert (await _send(db, "Ben", lesson, "your_turn", 0, choice=_wrong(task)))["tries_left"] == 1
        result = await _send(db, "Ben", lesson, "your_turn", 0, choice=task.accept_choice)
    assert result == {"understood": True, "correct": True, "recorded": True}
    assert seen == [("Ben", f"probe.{skill}", "correct", weight, "K-2", (),
                     {"skip_calibration_boost": True, "count_toward_calibration": False})]
    row = (await db.execute(select(SkillActivityLog))).scalar_one()
    detail = decrypt_json(row.detail_enc, student_aad("skill_activity_log", "detail_enc", "Ben", "mathematics", skill),
                          await student_keys.get_existing(db, "Ben"))
    assert (row.subject_area, row.skill_id, detail["assistance"], detail["source"]) == (
        "mathematics", skill, assistance, "practice_round")
    assert ai_service._work_label("mathematics", skill) == pm.skill_label(lesson["topic"])
    # Moved by the weight alone from the cold start, no early boost, and the
    # practice answer does not use up the early window.
    profile = await _profile(db, "Ben")
    assert profile.evidence_count == 0
    assert (await _vector(db, "Ben"))[skill] == pytest.approx(_expected(new_vector("K-2"), skill, weight))


@pytest.mark.asyncio
async def test_without_the_boost_a_practice_answer_moves_less_than_a_boosted_one_would(db):
    """Break-check for skip_calibration_boost: the boosted step from the same
    prior lands somewhere else."""
    lesson = await _lesson(db, "Ben")
    skill = lesson["skill"]
    task = _task("Ben", lesson, "your_turn", 0)
    await _send(db, "Ben", lesson, "your_turn", 0, choice=task.accept_choice)
    prior = new_vector("K-2")[skill]
    unboosted = _expected(new_vector("K-2"), skill, 0.5)
    boosted = prior + calibration_weight_for(0) * (unboosted - prior)
    got = (await _vector(db, "Ben"))[skill]
    assert got == pytest.approx(unboosted) and got != pytest.approx(boosted)


@pytest.mark.asyncio
async def test_when_the_answer_is_shown_nothing_is_recorded_at_all(db):
    lesson = await _lesson(db, "Ben")
    task = _task("Ben", lesson, "your_turn", 2)
    called = []
    with patch.object(routes.math_record, "process_evidence", side_effect=lambda *a, **k: called.append(a)):
        assert (await _send(db, "Ben", lesson, "your_turn", 2, choice=_wrong(task)))["tries_left"] == 1
        two = await _send(db, "Ben", lesson, "your_turn", 2, choice=_wrong(task))
        assert two == {"understood": True, "correct": False, "tries_left": 0, "reveal": task.reveal()}
        after = await _send(db, "Ben", lesson, "your_turn", 2, choice=task.accept_choice)
    assert after == {"understood": True, "correct": True, "recorded": False}
    assert called == []
    assert await _ledger_rows(db, "Ben") == 0 and await _profile(db, "Ben") is None


@pytest.mark.asyncio
async def test_a_retried_answer_records_once(db):
    lesson = await _lesson(db, "Ben")
    task = _task("Ben", lesson, "your_turn", 0)
    first = await _send(db, "Ben", lesson, "your_turn", 0, choice=task.accept_choice)
    again = await _send(db, "Ben", lesson, "your_turn", 0, choice=task.accept_choice)
    assert first["recorded"] is True and again["recorded"] is False
    assert await _ledger_rows(db, "Ben") == 1


@pytest.mark.asyncio
async def test_with_mastery_retention_off_only_the_ledger_is_written(db, monkeypatch):
    monkeypatch.setattr(settings, "retain_mastery_profiles", False)
    lesson = await _lesson(db, "Ben")
    task = _task("Ben", lesson, "your_turn", 0)
    assert (await _send(db, "Ben", lesson, "your_turn", 0, choice=task.accept_choice))["recorded"] is True
    assert await _ledger_rows(db, "Ben") == 1 and await _profile(db, "Ben") is None


@pytest.mark.asyncio
async def test_a_built_frame_is_answered_by_its_count_and_checked_like_a_tap(db):
    lesson = await _lesson(db, "Ada")
    task = _task("Ada", lesson, "your_turn", 1)
    assert task.choice_kind == "build"
    over = str(task.build["capacity"] + 1)
    with pytest.raises(HTTPException) as exc:
        await _send(db, "Ada", lesson, "your_turn", 1, choice=over)
    assert exc.value.status_code == 422
    assert (await _send(db, "Ada", lesson, "your_turn", 1, choice=task.accept_choice))["recorded"] is True


@pytest.mark.asyncio
async def test_unmatched_speech_is_neither_a_miss_nor_an_answer_and_a_match_counts_like_a_tap(db):
    lesson = await _lesson(db, "Ben")
    task = _task("Ben", lesson, "your_turn", 0)
    for heard in ("um, my house is on Elm Street", " ".join(task.choices)):
        assert await _send(db, "Ben", lesson, "your_turn", 0, spoken=heard) == {"understood": False, "correct": False}
    assert routes._progress.get(("Ben", lesson["lesson_id"]), {"misses": {}})["misses"] == {}
    words = pm.number_forms(int(task.accept_choice))[2]  # the Spanish word
    assert (await _send(db, "Ben", lesson, "your_turn", 0, spoken=f"es {words}"))["recorded"] is True


@pytest.mark.asyncio
async def test_a_spoken_echo_of_the_instruction_counts_as_nothing(db):
    lesson = await _lesson(db, "Ada")
    task = _task("Ada", lesson, "your_turn", 1)
    assert task.prompt_key == "count_build" and pm.speech_echoes_answer(task)
    heard = await _send(db, "Ada", lesson, "your_turn", 1, spoken=task.accept_choice)
    assert heard == {"understood": False, "correct": False}
    assert await _ledger_rows(db, "Ada") == 0


@pytest.mark.asyncio
async def test_free_text_and_answers_off_the_choices_are_refused(db):
    lesson = await _lesson(db, "Ben")
    with pytest.raises(HTTPException) as exc:
        await _send(db, "Ben", lesson, "your_turn", 0, choice="a lot")
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await _send(db, "Ben", lesson, "your_turn", 9, choice="3")
    assert exc.value.status_code == 404
    for body in ({}, {"choice": "3", "spoken": "three"}, {"text": "twelve", "choice": "3"},
                 {"typed": "12"}, {"choice": "3", "note": "12 Elm Street"}):
        with pytest.raises(ValueError):
            routes.MathAnswer(phase="your_turn", index=0, **body)
    assert await _ledger_rows(db, "Ben") == 0


@pytest.mark.asyncio
async def test_a_forged_expired_other_learners_or_phonics_lesson_id_is_404(db):
    lesson = await _lesson(db, "Ben")
    task = _task("Ben", lesson, "your_turn", 0)
    level, topic, seed, _audio = routes.read_lesson_id("Ben", lesson["lesson_id"], area="math")
    forged = lesson["lesson_id"].rsplit("-", 1)[0] + "-" + "0" * 20
    body = f"{level}-{pm.TOPICS.index(topic)}-{seed}-20200101-1"
    expired = f"{body}-{routes._mac('Ben', body, 'math')}"
    # The same numbers signed for phonics are not a math lesson.
    as_phonics = routes.mint_lesson_id("Ben", "1", phonics.DOMAINS[pm.TOPICS.index(topic)], seed)
    for name, lesson_id in (("Ada", lesson["lesson_id"]), ("Ben", forged), ("Ben", expired),
                            ("Ben", as_phonics), ("Ben", "junk")):
        with pytest.raises(HTTPException) as exc:
            await routes.answer_math(name, lesson_id, routes.MathAnswer(
                phase="your_turn", index=0, choice=task.accept_choice), auth=PARENT, db=db)
        assert exc.value.status_code == 404, lesson_id
    # And a math id is not a phonics lesson.
    with pytest.raises(HTTPException):
        routes.read_lesson_id("Ben", lesson["lesson_id"])
    assert await _ledger_rows(db, "Ben") == 0


async def _save_offers(db, name, offers, grade="1"):
    key = await student_keys.get_existing(db, name)
    row = await db.get(StudentConfig, name)
    row.config_enc = encrypt_json(SessionConfig(student_name=name, grade=grade, grade_stage="K-2",
                                                practice_offers=offers).model_dump(), _config_aad(name), key)
    await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("offers", ["off", "approved_only"])
async def test_answers_stop_when_the_parent_switches_away_from_todays_subjects(db, offers):
    lesson = await _lesson(db, "Ben")
    await _save_offers(db, "Ben", offers)
    task = _task("Ben", lesson, "your_turn", 0)
    with pytest.raises(HTTPException) as exc:
        await _send(db, "Ben", lesson, "your_turn", 0, choice=task.accept_choice)
    assert exc.value.status_code == 404
    assert await _ledger_rows(db, "Ben") == 0


@pytest.mark.asyncio
async def test_a_siblings_session_cannot_reach_either_math_route(db, monkeypatch):
    from core import child_pin

    async def _live(_db, _auth):
        return True

    monkeypatch.setattr(child_pin, "token_is_live", _live)
    ada = {"role": "child", "learner": "Ada"}
    lesson = await _lesson(db, "Ben")
    task = _task("Ben", lesson, "your_turn", 0)
    with pytest.raises(HTTPException) as exc:
        await _lesson(db, "Ben", auth=ada)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await _send(db, "Ben", lesson, "your_turn", 0, auth=ada, choice=task.accept_choice)
    assert exc.value.status_code == 404
    assert await _ledger_rows(db, "Ben") == 0
    assert (await _lesson(db, "Ada", auth=ada))["level"] == "K"


def test_the_math_routes_use_the_learner_and_consent_guards():
    from core.deps import require_family_data_write, require_real_user
    guards = {r.path: {p.default.dependency for p in inspect.signature(r.endpoint).parameters.values()
                       if hasattr(p.default, "dependency")} for r in routes.router.routes}
    assert require_real_user in guards["/k2-practice/{student_name}/math/lesson"]
    assert require_family_data_write in guards["/k2-practice/{student_name}/math/lessons/{lesson_id}/answers"]
    for name in ("new_math_lesson", "answer_math"):
        source = inspect.getsource(getattr(routes, name))
        assert "require_learner_access(auth, student_name, db)" in source
        assert "consent.require_collection(db, student_name)" in source


@pytest.mark.asyncio
async def test_consent_is_required_on_both_math_routes(db, monkeypatch):
    calls = []

    async def _refuse(_db, name):
        calls.append(name)
        raise HTTPException(status_code=403, detail="no consent")

    monkeypatch.setattr(routes.consent, "require_collection", _refuse)
    with pytest.raises(HTTPException):
        await _lesson(db, "Ben")
    with pytest.raises(HTTPException):
        await routes.answer_math("Ben", "x", routes.MathAnswer(phase="your_turn", index=0, choice="3"),
                                 auth=PARENT, db=db)
    assert calls == ["Ben", "Ben"]


@pytest.mark.asyncio
async def test_lessons_build_and_check_with_the_ai_provider_failing(db):
    def _boom(*a, **k):
        raise RuntimeError("provider down")

    with patch.object(ai_service._client.messages, "stream", side_effect=_boom), \
            patch.object(ai_service._client.messages, "create", side_effect=_boom):
        lesson = await _lesson(db, "Ben")
        task = _task("Ben", lesson, "your_turn", 0)
        assert (await _send(db, "Ben", lesson, "your_turn", 0, choice=task.accept_choice))["recorded"] is True


# ── One recorded round per area per sign-in ──────────────────────────────────

async def _answer_right(db, name, lesson, auth, index=0):
    task = _task(name, lesson, "your_turn", index)
    return await _send(db, name, lesson, "your_turn", index, auth=auth, choice=task.accept_choice)


@pytest.mark.asyncio
async def test_one_recorded_math_round_per_sign_in_and_another_is_practice_only(db):
    signed_in = {"role": "parent", "sub": "parent", "iat": 1000, "exp": 9000}
    first = await _lesson(db, "Ben", auth=signed_in)
    assert (await _answer_right(db, "Ben", first, signed_in))["recorded"] is True
    another = await _lesson(db, "Ben", auth=signed_in)
    for index in range(pm.YOUR_TURN_TASKS):
        result = await _answer_right(db, "Ben", another, signed_in, index)
        assert result == {"understood": True, "correct": True, "recorded": False, "practice_only": True}
    assert await _ledger_rows(db, "Ben") == 1
    # A new sign-in gets its own round.
    fresh = dict(signed_in, iat=2000)
    mine = await _lesson(db, "Ben", auth=fresh)
    assert (await _answer_right(db, "Ben", mine, fresh))["recorded"] is True


@pytest.mark.asyncio
async def test_the_phonics_round_and_the_math_round_are_counted_apart(db):
    signed_in = {"role": "parent", "sub": "parent", "iat": 1100, "exp": 9000}
    sound = await routes.new_lesson("Ben", auth=signed_in, db=db)
    level, domain, seed, _ = routes.read_lesson_id("Ben", sound["lesson_id"])
    t = phonics.build_task(level, domain, seed, "your_turn", 0)
    recorded = await routes.answer("Ben", sound["lesson_id"], routes.PhonicsAnswer(
        phase="your_turn", index=0, choice=t.accept_choice), auth=signed_in, db=db)
    assert recorded["recorded"] is True
    numbers = await _lesson(db, "Ben", auth=signed_in)
    assert (await _answer_right(db, "Ben", numbers, signed_in))["recorded"] is True


@pytest.mark.asyncio
async def test_two_math_lessons_answered_at_once_record_only_one_round(db):
    signed_in = {"role": "parent", "sub": "parent", "iat": 5400, "exp": 9000}
    one = await _lesson(db, "Ben", auth=signed_in)
    two = await _lesson(db, "Ben", auth=signed_in)
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as db_one, maker() as db_two:
        results = await asyncio.gather(_answer_right(db_one, "Ben", one, signed_in),
                                       _answer_right(db_two, "Ben", two, signed_in))
    assert sorted(bool(r["recorded"]) for r in results) == [False, True]
    assert await _ledger_rows(db, "Ben") == 1


@pytest.mark.asyncio
async def test_the_recorded_round_stops_at_three_answers(db, monkeypatch):
    assert routes.MAX_RECORDED_ANSWERS == 3 == pm.YOUR_TURN_TASKS
    monkeypatch.setattr(routes, "MAX_RECORDED_ANSWERS", 2)
    signed_in = {"role": "parent", "sub": "parent", "iat": 4000, "exp": 9000}
    lesson = await _lesson(db, "Ben", auth=signed_in)
    results = [await _answer_right(db, "Ben", lesson, signed_in, i) for i in range(pm.YOUR_TURN_TASKS)]
    assert [r["recorded"] for r in results] == [True, True, False]
    assert await _ledger_rows(db, "Ben") == 2


# ── The early window, and every other caller exactly as before ───────────────

@pytest.mark.asyncio
async def test_practice_does_not_use_up_the_early_window_for_bedes_own_check_ins(db):
    lesson = await _lesson(db, "Ben")
    skill = lesson["skill"]
    for index in range(pm.YOUR_TURN_TASKS):
        assert (await _answer_right(db, "Ben", lesson, PARENT, index))["recorded"] is True
    assert (await _profile(db, "Ben")).evidence_count == 0
    before = await _vector(db, "Ben")
    # Bede's own check-in: no flags, so calibration_weight_for(0) == 2.0.
    await math_record.process_evidence(db, "Ben", f"probe.{skill}", "partial", 1.0, "K-2")
    from services.diagnostic.mastery import bayesian_update
    expected, _ = bayesian_update(before, {"probe_id": f"probe.{skill}", "outcome": "partial", "confidence": 1.0},
                                  calibration_weight=calibration_weight_for(0))
    assert (await _vector(db, "Ben"))[skill] == pytest.approx(expected[skill])
    assert (await _profile(db, "Ben")).evidence_count == 1


@pytest.mark.asyncio
async def test_process_evidence_without_the_flags_behaves_exactly_as_before(db):
    """The two new keyword flags default to the old behaviour, step by step:
    each call blends at calibration_weight_for(count) and advances the count."""
    from services.diagnostic.mastery import bayesian_update
    vector = new_vector("K-2")
    for count, (probe, outcome, confidence) in enumerate([
        ("probe.oa.add_within_20", "correct", 1.0), ("probe.cc.number_bonds", "incorrect", 0.5),
        ("probe.oa.add_within_20", "partial", 0.8),
    ]):
        await math_record.process_evidence(db, "Ada", probe, outcome, confidence, "K-2")
        vector, _ = bayesian_update(vector, {"probe_id": probe, "outcome": outcome, "confidence": confidence},
                                    calibration_weight=calibration_weight_for(count))
        assert await _vector(db, "Ada") == pytest.approx(vector)
        assert (await _profile(db, "Ada")).evidence_count == count + 1


def test_the_other_callers_pass_neither_flag():
    """Bede's record_skill_evidence check-ins and a marked quiz call
    process_evidence exactly as before: neither names the practice flags."""
    from services.practice import evidence
    for source in (inspect.getsource(ai_service._record_skill_evidence), inspect.getsource(evidence.count_quiz)):
        assert "process_evidence(" in source
        assert "skip_calibration_boost" not in source and "count_toward_calibration" not in source
    params = inspect.signature(math_record.process_evidence).parameters
    assert params["skip_calibration_boost"].default is False
    assert params["count_toward_calibration"].default is True
    assert params["skip_calibration_boost"].kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.asyncio
async def test_a_marked_quiz_still_counts_with_the_boost_and_advances_the_count(db, monkeypatch):
    """Invocation check for the marked-quiz path: its observation is boosted
    and counted, the opposite of practice."""
    seen = []
    real = math_record.process_evidence

    async def _spy(*args, **kwargs):
        seen.append(kwargs)
        return await real(*args, **kwargs)

    from models.practice import AssessmentItem, AssessmentSection, GradedAssessment
    from services.practice import evidence
    monkeypatch.setattr(math_record, "process_evidence", _spy)
    assessment = GradedAssessment(subject="math", sections=[AssessmentSection(label="Sums", items=[
        AssessmentItem(number=1, prompt="3 + 4 =", student_response="7", teacher_mark="correct")])])
    assert await evidence.count_quiz(db, "Ben", 1, assessment) == 1
    assert seen == [{}]
    assert (await _profile(db, "Ben")).evidence_count == 1


@pytest.mark.asyncio
async def test_the_math_summary_counts_practice_answers_apart_from_check_ins(db):
    from models.schemas import MasteryProfileSummary
    from routers.diagnostic import _SUMMARY_BUILDERS
    from services.diagnostic.activity import record_activity

    lesson = await _lesson(db, "Ben")
    for index in range(pm.YOUR_TURN_TASKS):
        assert (await _answer_right(db, "Ben", lesson, PARENT, index))["recorded"] is True
    summary = await _SUMMARY_BUILDERS["mathematics"](db, "Ben")
    assert summary["evidence_count"] == 0 and summary["calibration"] is True
    assert summary["practice_answers"] == pm.YOUR_TURN_TASKS
    await math_record.process_evidence(db, "Ben", f"probe.{lesson['skill']}", "correct", 1.0, "K-2")
    await record_activity(db, "Ben", "mathematics", lesson["skill"], "x", "correct")
    await record_activity(db, "Ben", "mathematics", lesson["skill"], "x", "correct", source="marked_quiz")
    summary = await _SUMMARY_BUILDERS["mathematics"](db, "Ben")
    assert summary["evidence_count"] == 1 and summary["practice_answers"] == pm.YOUR_TURN_TASKS
    assert MasteryProfileSummary(**summary).practice_answers == pm.YOUR_TURN_TASKS
    # No record at all still reads as "no data yet".
    assert await _SUMMARY_BUILDERS["mathematics"](db, "Nobody") is None
