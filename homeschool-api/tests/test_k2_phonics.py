"""K-2 phonics practice: the builder (services/k2_practice/phonics.py) and its
routes (routers/k2_practice.py). Words are authored, answers are checked by
code, nothing a child says or types is kept, and a "Your turn" answer counts
toward the phonics record at the owner's weights (decision 40(b)).
"""
import inspect
import json

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from core import student_keys
from core.config import settings
from core.database import Base, MasteryProfile, SkillActivityLog, StudentConfig
from core.encryption import decrypt_json, encrypt_json, student_aad
from models.practice import ICONS
from models.schemas import SessionConfig
from routers import k2_practice as routes
from routers.pod import _config_aad
from services import ai_service
from services.diagnostic import phonics as phonics_record
from services.k2_practice import phonics
from services.practice.evidence import QUIZ_EVIDENCE_WEIGHT

PARENT = {"role": "parent"}


def _every_task():
    for level in phonics.LEVELS:
        for domain in phonics.DOMAINS:
            for seed in range(60):
                for phase in phonics.PHASES:
                    for index in range(phonics._PHASE_COUNT[phase]):
                        yield level, domain, seed, phase, index, phonics.build_task(level, domain, seed, phase, index)


# ── The builder ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("grade,level,start", [
    ("K", "K", "phonological_awareness"), ("k", "K", "phonological_awareness"),
    ("1", "1", "cvc_blending"), ("2", "2", "blends_digraphs"),
])
def test_each_grade_starts_at_its_own_domain(grade, level, start):
    assert phonics.level_for_grade(grade) == level
    assert phonics.domain_for(level) == start
    assert phonics.domain_for(level, {}) == start


@pytest.mark.parametrize("grade", ["3", "4", "8", "", "Pre-K"])
def test_no_level_above_grade_2(grade):
    assert phonics.level_for_grade(grade) is None


def test_the_next_domain_follows_the_records_developmental_order():
    secure = {"cvc_blending": 0.95, "blends_digraphs": 0.95}
    assert phonics.domain_for("1", secure) == "long_vowel_patterns"
    # A secure later domain never lets a lesson skip an earlier one.
    assert phonics.domain_for("1", {"blends_digraphs": 0.95}) == "cvc_blending"
    # Never earlier than the grade's own start.
    assert phonics.domain_for("2", {"phonological_awareness": 0.1}) == "blends_digraphs"


def test_every_question_is_well_formed_and_has_exactly_one_right_choice():
    for level, domain, seed, phase, index, task in _every_task():
        where = (level, domain, seed, phase, index)
        assert len(task.choices) == phonics.CHOICES_PER_LEVEL[level], where
        assert len(set(task.choices)) == len(task.choices), where
        assert [c for c in task.choices if task.is_right(c)] == [task.accept_choice], where
        if task.choice_kind == "picture":
            assert all(c in ICONS for c in task.choices), where


def test_the_computed_answer_is_the_true_one():
    """Recompute each answer a second way, from the authored lists."""
    rime = {w: i for i, pair in enumerate(phonics.RHYME_PAIRS) for w in pair}
    first = dict(phonics.FIRST_SOUNDS)
    for _level, domain, _seed, _phase, _index, task in _every_task():
        if domain == "phonological_awareness":
            target = task.prompt_args["word"]
            assert [c for c in task.choices if rime[c] == rime[target] and c != target] == [task.accept_choice]
        elif domain == "letter_sound":
            assert task.accept_choice == first[task.prompt_args["word"]]
        elif domain in phonics.DECODING_DOMAINS:
            letters = "".join(g["text"] for g in task.display["graphemes"])
            assert letters == task.accept_choice == task.display["word"]
        else:
            assert task.accept_choice == task.prompt_args["word"]


def test_the_authored_words_are_spelled_by_their_letters_and_all_have_pictures():
    for words in phonics.DECODABLE.values():
        for word, gs in words:
            assert "".join(text for text, _ in gs) == word
            assert word in ICONS
    for pair in phonics.RHYME_PAIRS:
        assert all(w in ICONS for w in pair)
    endings = [pair[0][-2:] for pair in phonics.RHYME_PAIRS]
    assert len(phonics.RHYME_PAIRS) >= 6 and len(phonics.FIRST_SOUNDS) >= 6
    assert len({letter for _, letter in phonics.FIRST_SOUNDS}) == len(phonics.FIRST_SOUNDS)
    assert endings  # each pair is its own rhyme family (checked by the answer test above)


def test_a_lesson_is_the_same_every_time_differs_by_seed_and_never_repeats_a_word():
    a = phonics.build_lesson("1", 5, "cvc_blending")
    assert a == phonics.build_lesson("1", 5, "cvc_blending")
    assert a != phonics.build_lesson("1", 6, "cvc_blending")
    for level in phonics.LEVELS:
        for domain in phonics.DOMAINS:
            lesson = phonics.build_lesson(level, 3, domain)
            items = [lesson["watch"]] + lesson["together"] + lesson["your_turn"]
            subjects = [json.dumps(i["display"].get("icon") or i["display"].get("graphemes")
                                   or i["prompt"]["args"]) for i in items]
            assert len(set(subjects)) == len(subjects), (level, domain)


def test_your_turn_never_speaks_the_word_when_reading_it_is_the_skill():
    for level in phonics.LEVELS:
        for domain in phonics.DOMAINS:
            for seed in range(30):
                lesson = phonics.build_lesson(level, seed, domain)
                for item in lesson["your_turn"]:
                    assert "answer" not in item and "choice_sounds" not in item
                    if domain in phonics.DECODING_DOMAINS:
                        assert "word" not in item["display"]
                        assert all("sound" not in g for g in item["display"]["graphemes"])
                        assert item["prompt"]["args"] == {}
                for item in lesson["together"]:
                    assert "answer" not in item
                assert lesson["watch"]["answer"]["choice"] in lesson["watch"]["choices"]


def test_together_letters_carry_their_sounds_for_tapping():
    for seed in range(20):
        lesson = phonics.build_lesson("K", seed, "letter_sound")
        for item in lesson["together"]:
            assert set(item["choice_sounds"]) == set(item["choices"])
        lesson = phonics.build_lesson("1", seed, "cvc_blending")
        for item in lesson["together"]:
            assert all(g.get("sound") or g.get("silent") for g in item["display"]["graphemes"])


def test_a_spoken_word_matches_only_one_of_the_questions_own_choices():
    task = phonics.build_task("1", "cvc_blending", 2, "your_turn", 0)
    right = task.accept_choice
    assert phonics.match_spoken(task, f"um, I think it's {right}!") == right
    others = [c for c in task.choices if c != right]
    assert phonics.match_spoken(task, f"{right} or {others[0]}") is None
    assert phonics.match_spoken(task, "dragon") is None
    assert phonics.match_spoken(task, "") is None
    letters = phonics.build_task("K", "letter_sound", 1, "your_turn", 0)
    assert phonics.match_spoken(letters, letters.accept_choice) == letters.accept_choice
    rhyme = phonics.build_task("K", "phonological_awareness", 1, "your_turn", 0)
    spanish = phonics._PICTURE_SPOKEN.get(rhyme.accept_choice, ())
    if spanish:
        assert phonics.match_spoken(rhyme, spanish[0].upper()) == rhyme.accept_choice


def test_nothing_here_calls_a_model():
    source = inspect.getsource(phonics) + inspect.getsource(routes)
    for forbidden in ("ai_service", "_client", "anthropic", "openai", "resolve_with_failover"):
        assert forbidden not in source


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
            ("Eve", "1", "K-2", "approved_only"),
        ):
            key = await student_keys.get_or_create(session, name)
            config = SessionConfig(student_name=name, grade=grade, grade_stage=stage, practice_offers=offers)
            session.add(StudentConfig(student_name=name, config_enc=encrypt_json(
                config.model_dump(), _config_aad(name), key)))
        await session.commit()
        routes._progress.clear()
        yield session
    await engine.dispose()


async def _ledger_rows(db, name):
    return (await db.execute(select(func.count()).select_from(SkillActivityLog).where(
        SkillActivityLog.student_name == name))).scalar_one()


async def _profile(db, name):
    return (await db.execute(select(MasteryProfile).where(
        MasteryProfile.student_name == name, MasteryProfile.subject_area == "phonics"))).scalar_one_or_none()


async def _vector(db, name):
    row = await _profile(db, name)
    return decrypt_json(row.profile_enc, student_aad("mastery_profiles", "profile_enc", name, "phonics"),
                        await student_keys.get_existing(db, name))


def _task(name, lesson, phase, index):
    level, domain, seed = routes.read_lesson_id(name, lesson["lesson_id"])
    return phonics.build_task(level, domain, seed, phase, index)


def _wrong(task):
    return next(c for c in task.choices if c != task.accept_choice)


async def _send(db, name, lesson, phase, index, auth=PARENT, **answer):
    return await routes.answer(name, lesson["lesson_id"],
                               routes.PhonicsAnswer(phase=phase, index=index, **answer), auth=auth, db=db)


@pytest.mark.asyncio
async def test_the_level_comes_from_the_saved_grade_and_nothing_in_the_request_chooses_it(db):
    ada = await routes.new_lesson("Ada", auth=PARENT, db=db)
    ben = await routes.new_lesson("Ben", auth=PARENT, db=db)
    assert (ada["level"], ada["domain"]) == ("K", "phonological_awareness")
    assert (ben["level"], ben["domain"]) == ("1", "cvc_blending")
    # The route takes no grade, level or domain at all.
    params = set(inspect.signature(routes.new_lesson).parameters)
    assert params == {"student_name", "auth", "db"}
    for name in ("Cal", "Dot", "Eve", "Nobody"):
        with pytest.raises(HTTPException) as exc:
            await routes.new_lesson(name, auth=PARENT, db=db)
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_the_domain_follows_the_saved_phonics_record(db):
    for _ in range(12):
        await phonics_record.process_evidence(db, "Ben", "cvc_blending", "correct")
    assert (await routes.new_lesson("Ben", auth=PARENT, db=db))["domain"] == "blends_digraphs"


@pytest.mark.asyncio
async def test_together_shows_the_answer_on_a_miss_and_records_nothing(db):
    lesson = await routes.new_lesson("Ben", auth=PARENT, db=db)
    task = _task("Ben", lesson, "together", 0)
    miss = await _send(db, "Ben", lesson, "together", 0, choice=_wrong(task))
    assert miss == {"understood": True, "correct": False, "reveal": task.reveal()}
    assert (await _send(db, "Ben", lesson, "together", 0, choice=task.accept_choice))["correct"] is True
    assert await _ledger_rows(db, "Ben") == 0 and await _profile(db, "Ben") is None


# ── The weights (decision 40(b)), through the real submission path ───────────

def test_the_weights_are_the_owners_product_defaults():
    assert routes.FIRST_TRY_WEIGHT == QUIZ_EVIDENCE_WEIGHT == 0.5
    assert routes.SECOND_TRY_WEIGHT == 0.25


@pytest.mark.asyncio
@pytest.mark.parametrize("misses,weight,assistance", [(0, 0.5, "unaided"), (1, 0.25, "with_a_hint")])
async def test_a_right_answer_records_one_row_and_one_observation_at_its_weight(db, misses, weight, assistance):
    seen = []
    real = phonics_record.process_evidence

    async def _spy(db_, name, domain, outcome, weight=1.0, skip_calibration_boost=False):
        seen.append((name, domain, outcome, weight, skip_calibration_boost))
        return await real(db_, name, domain, outcome, weight=weight,
                          skip_calibration_boost=skip_calibration_boost)

    lesson = await routes.new_lesson("Ben", auth=PARENT, db=db)
    task = _task("Ben", lesson, "your_turn", 0)
    with patch.object(routes.phonics_record, "process_evidence", _spy):
        for _ in range(misses):
            assert (await _send(db, "Ben", lesson, "your_turn", 0, choice=_wrong(task)))["tries_left"] == 1
        result = await _send(db, "Ben", lesson, "your_turn", 0, choice=task.accept_choice)
    assert result == {"understood": True, "correct": True, "recorded": True}
    # The route passes the weight AND asks for no early-evidence boost.
    assert seen == [("Ben", lesson["domain"], "correct", weight, True)]
    row = (await db.execute(select(SkillActivityLog))).scalar_one()
    detail = decrypt_json(row.detail_enc, student_aad("skill_activity_log", "detail_enc", "Ben", "phonics",
                                                       lesson["domain"]), await student_keys.get_existing(db, "Ben"))
    assert (row.subject_area, row.skill_id, detail["assistance"]) == ("phonics", lesson["domain"], assistance)
    assert ai_service._work_label("phonics", lesson["domain"]) == phonics.DOMAIN_LABELS[lesson["domain"]]
    # The estimate moved by its weight alone from a cold start, no boost.
    expected = {0.5: 0.75, 0.25: 0.625}[weight]
    assert (await _vector(db, "Ben"))[lesson["domain"]] == pytest.approx(expected)


@pytest.mark.asyncio
async def test_the_second_try_moves_the_estimate_half_as_far_as_the_first(db):
    lesson_a = await routes.new_lesson("Ben", auth=PARENT, db=db)
    task = _task("Ben", lesson_a, "your_turn", 0)
    await _send(db, "Ben", lesson_a, "your_turn", 0, choice=_wrong(task))
    await _send(db, "Ben", lesson_a, "your_turn", 0, choice=task.accept_choice)
    after_hint = (await _vector(db, "Ben"))[lesson_a["domain"]]
    assert after_hint == pytest.approx(0.625)


@pytest.mark.asyncio
async def test_one_right_practice_answer_never_makes_a_domain_secure_but_two_first_tries_do(db):
    """Owner ruling 2026-11-16: practice skips the early-evidence boost. One
    right first try is 0.5 -> 0.75 (developing) and the next lesson stays on
    the same domain; a second right first try is 0.875, secure, and the next
    lesson moves on."""
    from services.diagnostic.mastery import classify_level

    lesson = await routes.new_lesson("Ben", auth=PARENT, db=db)
    domain = lesson["domain"]
    assert domain == "cvc_blending"
    first = _task("Ben", lesson, "your_turn", 0)
    await _send(db, "Ben", lesson, "your_turn", 0, choice=first.accept_choice)
    after_one = (await _vector(db, "Ben"))[domain]
    assert after_one == pytest.approx(0.75) and classify_level(after_one) != "secure"
    assert (await routes.new_lesson("Ben", auth=PARENT, db=db))["domain"] == domain
    second = _task("Ben", lesson, "your_turn", 1)
    await _send(db, "Ben", lesson, "your_turn", 1, choice=second.accept_choice)
    after_two = (await _vector(db, "Ben"))[domain]
    assert after_two == pytest.approx(0.875) and classify_level(after_two) == "secure"
    assert (await routes.new_lesson("Ben", auth=PARENT, db=db))["domain"] == "blends_digraphs"


@pytest.mark.asyncio
async def test_an_in_lesson_caller_without_the_flag_keeps_the_boost(db):
    """Bede's in-lesson check-ins pass no flag and keep the doubled cold-start
    step exactly as before: weight 0.5 from 0.5 lands on 1.0."""
    await phonics_record.process_evidence(db, "Ada", "letter_sound", "correct", weight=0.5)
    assert (await _vector(db, "Ada"))["letter_sound"] == pytest.approx(1.0)
    await phonics_record.process_evidence(db, "Ada", "cvc_blending", "correct", weight=0.5,
                                          skip_calibration_boost=True)
    # The second observation is the profile's second, so its boost would be
    # 2 - 1/3; without it the step is the weight alone.
    assert (await _vector(db, "Ada"))["cvc_blending"] == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_when_the_answer_is_shown_nothing_is_recorded_at_all(db):
    lesson = await routes.new_lesson("Ben", auth=PARENT, db=db)
    task = _task("Ben", lesson, "your_turn", 1)
    called = []
    with patch.object(routes.phonics_record, "process_evidence",
                      side_effect=lambda *a, **k: called.append(a)):
        one = await _send(db, "Ben", lesson, "your_turn", 1, choice=_wrong(task))
        assert one == {"understood": True, "correct": False, "tries_left": 1}
        two = await _send(db, "Ben", lesson, "your_turn", 1, choice=_wrong(task))
        assert two == {"understood": True, "correct": False, "tries_left": 0, "reveal": task.reveal()}
        after = await _send(db, "Ben", lesson, "your_turn", 1, choice=task.accept_choice)
    assert after == {"understood": True, "correct": True, "recorded": False}
    assert called == []
    assert await _ledger_rows(db, "Ben") == 0 and await _profile(db, "Ben") is None


@pytest.mark.asyncio
async def test_a_retried_answer_records_once(db):
    lesson = await routes.new_lesson("Ben", auth=PARENT, db=db)
    task = _task("Ben", lesson, "your_turn", 2)
    first = await _send(db, "Ben", lesson, "your_turn", 2, choice=task.accept_choice)
    again = await _send(db, "Ben", lesson, "your_turn", 2, choice=task.accept_choice)
    spoken = await _send(db, "Ben", lesson, "your_turn", 2, spoken=task.accept_choice)
    assert first["recorded"] is True and again["recorded"] is False and spoken["recorded"] is False
    assert await _ledger_rows(db, "Ben") == 1
    assert (await _profile(db, "Ben")).evidence_count == 1


@pytest.mark.asyncio
async def test_a_declined_round_records_nothing(db):
    """Opening a lesson and walking away (or never opening it) is declining."""
    await routes.new_lesson("Ben", auth=PARENT, db=db)
    assert await _ledger_rows(db, "Ben") == 0 and await _profile(db, "Ben") is None


@pytest.mark.asyncio
async def test_with_mastery_retention_off_only_the_ledger_is_written(db, monkeypatch):
    monkeypatch.setattr(settings, "retain_mastery_profiles", False)
    lesson = await routes.new_lesson("Ben", auth=PARENT, db=db)
    task = _task("Ben", lesson, "your_turn", 0)
    assert (await _send(db, "Ben", lesson, "your_turn", 0, choice=task.accept_choice))["recorded"] is True
    assert await _ledger_rows(db, "Ben") == 1 and await _profile(db, "Ben") is None


@pytest.mark.asyncio
async def test_unmatched_speech_is_neither_a_miss_nor_an_answer(db):
    lesson = await routes.new_lesson("Ben", auth=PARENT, db=db)
    task = _task("Ben", lesson, "your_turn", 0)
    for heard in ("um, I like my house on Elm Street", " ".join(task.choices)):
        assert await _send(db, "Ben", lesson, "your_turn", 0, spoken=heard) == {"understood": False, "correct": False}
    assert routes._progress.get(("Ben", lesson["lesson_id"]), {"misses": {}})["misses"] == {}
    # Still two full tries left: the first real miss leaves one.
    assert (await _send(db, "Ben", lesson, "your_turn", 0, choice=_wrong(task)))["tries_left"] == 1
    assert await _ledger_rows(db, "Ben") == 0


def test_only_sight_words_say_their_own_answer_aloud():
    """The echo rule must bite exactly where the spoken prompt holds the answer."""
    for level, domain, _seed, _phase, _index, task in _every_task():
        assert phonics.speech_echoes_answer(task) == (domain == "sight_words"), (level, domain)


@pytest.mark.asyncio
async def test_a_spoken_sight_word_is_an_echo_and_counts_as_nothing(db):
    """'Tap the word said' says the answer; saying it back proves hearing, not
    reading. It is neither a miss nor an answer, through the real route."""
    level, seed = "2", 4
    lesson = phonics.build_lesson(level, seed, "sight_words")
    lesson["lesson_id"] = routes.mint_lesson_id("Ben", level, "sight_words", seed)
    await _save_grade(db, "Ben", "2")
    for index in range(phonics.YOUR_TURN_TASKS):
        task = phonics.build_task(level, "sight_words", seed, "your_turn", index)
        assert task.prompt_args["word"] == task.accept_choice
        heard = await _send(db, "Ben", lesson, "your_turn", index, spoken=f"{task.accept_choice}")
        assert heard == {"understood": False, "correct": False}
    assert routes._progress.get(("Ben", lesson["lesson_id"]), {"misses": {}})["misses"] == {}
    assert await _ledger_rows(db, "Ben") == 0 and await _profile(db, "Ben") is None
    # A tap still counts.
    task = phonics.build_task(level, "sight_words", seed, "your_turn", 0)
    assert (await _send(db, "Ben", lesson, "your_turn", 0, choice=task.accept_choice))["recorded"] is True


async def _save_grade(db, name, grade):
    key = await student_keys.get_existing(db, name)
    row = await db.get(StudentConfig, name)
    row.config_enc = encrypt_json(SessionConfig(student_name=name, grade=grade, grade_stage="K-2").model_dump(),
                                  _config_aad(name), key)
    await db.commit()


@pytest.mark.asyncio
async def test_a_matched_spoken_answer_counts_like_a_tap(db):
    lesson = await routes.new_lesson("Ben", auth=PARENT, db=db)
    task = _task("Ben", lesson, "your_turn", 0)
    assert (await _send(db, "Ben", lesson, "your_turn", 0, spoken=f"it is {task.accept_choice}"))["recorded"] is True


@pytest.mark.asyncio
async def test_a_forged_expired_or_other_learners_lesson_id_is_404(db):
    lesson = await routes.new_lesson("Ben", auth=PARENT, db=db)
    task = _task("Ben", lesson, "your_turn", 0)
    level, domain, seed = routes.read_lesson_id("Ben", lesson["lesson_id"])
    forged = lesson["lesson_id"].rsplit("-", 1)[0] + "-" + "0" * 20
    other_domain = lesson["lesson_id"].replace(f"{level}-", f"{level}x-", 1)
    body = f"{level}-{phonics.DOMAINS.index(domain)}-{seed}-20200101"
    expired = f"{body}-{routes._mac('Ben', body)}"
    for name, lesson_id in (("Ada", lesson["lesson_id"]), ("Ben", forged), ("Ben", other_domain),
                            ("Ben", expired), ("Ben", "junk")):
        with pytest.raises(HTTPException) as exc:
            await routes.answer(name, lesson_id, routes.PhonicsAnswer(
                phase="your_turn", index=0, choice=task.accept_choice), auth=PARENT, db=db)
        assert exc.value.status_code == 404, lesson_id
    assert await _ledger_rows(db, "Ben") == 0 and await _ledger_rows(db, "Ada") == 0


@pytest.mark.asyncio
async def test_an_answer_off_the_choices_or_with_free_text_is_refused(db):
    lesson = await routes.new_lesson("Ben", auth=PARENT, db=db)
    with pytest.raises(HTTPException) as exc:
        await _send(db, "Ben", lesson, "your_turn", 0, choice="dragon")
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await _send(db, "Ben", lesson, "your_turn", 9, choice="cat")
    assert exc.value.status_code == 404
    for body in ({}, {"choice": "cat", "spoken": "cat"}, {"note": "12 Elm Street", "choice": "cat"}):
        with pytest.raises(ValueError):
            routes.PhonicsAnswer(phase="your_turn", index=0, **body)


async def _save_offers(db, name, offers):
    key = await student_keys.get_existing(db, name)
    row = await db.get(StudentConfig, name)
    row.config_enc = encrypt_json(SessionConfig(student_name=name, grade="1", grade_stage="K-2",
                                                practice_offers=offers).model_dump(), _config_aad(name), key)
    await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("offers", ["off", "approved_only"])
async def test_a_lessons_answers_stop_when_the_parent_switches_away_from_todays_subjects(db, offers):
    """Step 1 serves phonics only under "todays_subjects": with "only sets I
    approved" there is no approved phonics set, so no lesson and no evidence."""
    lesson = await routes.new_lesson("Ben", auth=PARENT, db=db)
    await _save_offers(db, "Ben", offers)
    task = _task("Ben", lesson, "your_turn", 0)
    with pytest.raises(HTTPException) as exc:
        await _send(db, "Ben", lesson, "your_turn", 0, choice=task.accept_choice)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await routes.new_lesson("Ben", auth=PARENT, db=db)
    assert exc.value.status_code == 404
    assert await _ledger_rows(db, "Ben") == 0 and await _profile(db, "Ben") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["Dot", "Eve"])
async def test_approved_only_and_off_serve_no_lesson(db, name):
    with pytest.raises(HTTPException) as exc:
        await routes.new_lesson(name, auth=PARENT, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("saved,role", [
    ("off", "child"), ("approved_only", "child"), ("todays_subjects", "child"),
    ("off", "parent"), ("approved_only", "parent"),
])
async def test_the_tutor_turn_uses_the_saved_setting_over_the_tablets_copy(db, monkeypatch, saved, role):
    """A tablet holds the config it loaded at the start of the session. A
    parent's later change to the saved setting must reach the offer gate on
    the next turn; only practice_offers is taken from the saved config."""
    from starlette.requests import Request

    import routers.tutor as tutor_module
    from models.schemas import Subject, TutorRequest

    await _save_offers(db, "Ben", saved)
    seen = []

    async def fake_classify(*args, **kwargs):
        return {"flagged": False, "categories": [], "confidence": "low", "should_block": False}

    async def fake_stream(*args, **kwargs):
        seen.append(kwargs["config"])
        yield '{"type": "done"}'

    async def no_check(*args, **kwargs):
        return None

    monkeypatch.setattr(tutor_module, "classify_child_message", fake_classify)
    monkeypatch.setattr(tutor_module, "stream_tutor_response", fake_stream)
    monkeypatch.setattr(tutor_module, "require_learner_access", no_check)
    stale = SessionConfig(student_name="Ben", grade="1", grade_stage="K-2", practice_offers="todays_subjects",
                          lesson_focus="the tablet's own note")
    req = TutorRequest(session_config=stale, current_subject=Subject.language_arts,
                       conversation_history=[], child_message="hello")
    request = Request({"type": "http", "client": ("127.0.0.1", 1), "headers": [(b"user-agent", b"pytest")]})
    response = await tutor_module.chat(req, request, auth={"role": role}, db=db)
    [c async for c in response.body_iterator]
    assert [c.practice_offers for c in seen] == [saved]
    # Nothing else is taken from the saved config.
    assert seen[0].lesson_focus == "the tablet's own note"


@pytest.mark.asyncio
async def test_a_missing_saved_config_fails_closed_to_off(db):
    assert await routes.saved_practice_offers(db, "Nobody") == "off"
    assert await routes.saved_practice_offers(db, "Ben") == "todays_subjects"


@pytest.mark.asyncio
async def test_a_siblings_session_cannot_reach_either_route(db, monkeypatch):
    from core import child_pin

    async def _live(_db, _auth):
        return True

    monkeypatch.setattr(child_pin, "token_is_live", _live)
    ada = {"role": "child", "learner": "Ada"}
    lesson = await routes.new_lesson("Ben", auth=PARENT, db=db)
    task = _task("Ben", lesson, "your_turn", 0)
    with pytest.raises(HTTPException) as exc:
        await routes.new_lesson("Ben", auth=ada, db=db)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await _send(db, "Ben", lesson, "your_turn", 0, auth=ada, choice=task.accept_choice)
    assert exc.value.status_code == 404
    assert await _ledger_rows(db, "Ben") == 0
    # Her own session reaches her own lesson.
    assert (await routes.new_lesson("Ada", auth=ada, db=db))["level"] == "K"


@pytest.mark.asyncio
async def test_lessons_build_and_check_with_the_ai_provider_failing(db):
    def _boom(*a, **k):
        raise RuntimeError("provider down")

    with patch.object(ai_service._client.messages, "stream", side_effect=_boom), \
            patch.object(ai_service._client.messages, "create", side_effect=_boom):
        lesson = await routes.new_lesson("Ben", auth=PARENT, db=db)
        task = _task("Ben", lesson, "your_turn", 0)
        assert (await _send(db, "Ben", lesson, "your_turn", 0, choice=task.accept_choice))["recorded"] is True


def test_the_routes_use_the_learner_and_consent_guards():
    from core.deps import require_family_data_write, require_real_user
    guards = {r.path: {p.default.dependency for p in inspect.signature(r.endpoint).parameters.values()
                       if hasattr(p.default, "dependency")} for r in routes.router.routes}
    assert require_real_user in guards["/k2-practice/{student_name}/phonics/lesson"]
    assert require_family_data_write in guards["/k2-practice/{student_name}/phonics/lessons/{lesson_id}/answers"]
    for name in ("new_lesson", "answer"):
        source = inspect.getsource(getattr(routes, name))
        assert "require_learner_access(auth, student_name, db)" in source
        assert "consent.require_collection(db, student_name)" in source


@pytest.mark.asyncio
async def test_consent_is_required_on_both_routes(db, monkeypatch):
    calls = []

    async def _refuse(_db, name):
        calls.append(name)
        raise HTTPException(status_code=403, detail="no consent")

    monkeypatch.setattr(routes.consent, "require_collection", _refuse)
    with pytest.raises(HTTPException):
        await routes.new_lesson("Ben", auth=PARENT, db=db)
    with pytest.raises(HTTPException):
        await routes.answer("Ben", "x", routes.PhonicsAnswer(phase="your_turn", index=0, choice="cat"),
                            auth=PARENT, db=db)
    assert calls == ["Ben", "Ben"]


# ── process_evidence's weight ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_process_evidence_without_a_weight_behaves_as_before(db):
    await phonics_record.process_evidence(db, "Ada", "letter_sound", "correct")
    assert (await _vector(db, "Ada"))["letter_sound"] == pytest.approx(1.0)


@pytest.mark.asyncio
@pytest.mark.parametrize("weight", [0, -0.5, 1.5, True, "0.5"])
async def test_process_evidence_refuses_a_malformed_weight(db, weight):
    assert await phonics_record.process_evidence(db, "Ada", "letter_sound", "correct", weight=weight) is None
    assert await _profile(db, "Ada") is None
