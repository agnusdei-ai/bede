"""Essay Studio (docs/ESSAY_STUDIO.md): eligibility, the routes, authorship,
persistence, routing, and Bede's invitation through the real tutor loop.

Sample learners only. Every guard here was verified by breaking the code it
guards (see the PR's test plan)."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core import student_keys
from core.config import settings
from core.database import Base, EssayDraft, MasteryProfile, SkillActivityLog, StudentConfig
from core.encryption import encrypt_json
from models.schemas import ChatMessage, SessionConfig, Subject
from routers import essay_studio as routes
from routers.pod import _config_aad
from services import ai_service, essay_studio as es, k2_practice, tool_registry
from services.action_governance import LONG_FORM_TOOLS, MIN_SECONDS_FOR_LONG_FORM_TASK

PARENT = {"role": "parent"}
LA = Subject.language_arts


def _cfg(name="Ada", grade="7", **kw):
    from models.schemas import grade_to_stage

    base = dict(student_name=name, grade=grade, grade_stage=grade_to_stage(grade),
                subjects=[Subject.morning_time, LA, Subject.living_books])
    base.update(kw)
    return SessionConfig(**base)


# ── Eligibility and stage ────────────────────────────────────────────────────

@pytest.mark.parametrize("grade,band", [("5", None), ("2", None), ("K", None), ("6", "logic"), ("8", "logic"),
                                        ("9", "rhetoric"), ("12", "rhetoric")])
def test_grades_6_to_12_only_and_rhetoric_begins_at_9_by_default(grade, band):
    assert es.stage_band(_cfg(grade=grade)) == band


def test_the_stage_line_is_a_setting_not_a_rule():
    assert es.stage_band(_cfg(grade="7", essay_rhetoric_from_grade=7)) == "rhetoric"
    assert es.stage_band(_cfg(grade="9", essay_rhetoric_from_grade=11)) == "logic"


@pytest.mark.parametrize("value", [5, 13, True, "9", 9.0, None])
def test_an_out_of_range_stage_line_means_not_set(value):
    assert _cfg(essay_rhetoric_from_grade=value).essay_rhetoric_from_grade is None


def test_exercises_follow_the_stage():
    assert es.exercises_for(_cfg(grade="7")) == ("narrative", "refutation")
    assert es.exercises_for(_cfg(grade="10")) == ("narrative", "refutation", "thesis")
    assert es.exercises_for(_cfg(grade="4")) == ()


def test_opposing_view_belongs_to_refutation_and_thesis_only():
    for exercise in es.EXERCISES:
        ids = {c["id"] for c in es.criteria_for(exercise)}
        dialectic = exercise in ("refutation", "thesis")
        assert ("opposing_view" in ids) is dialectic and es.uses_opposing_view(exercise) is dialectic
        assert any("other side" in q for q in es.reflect_questions(exercise)) is dialectic


def test_audience_comes_last_in_the_coaching_order():
    for stage in es.STAGES:
        ids = {c["id"] for c in es.criteria_for("thesis", stage)}
        assert ("audience" in ids) is (stage in ("examine", "revise"))


def test_the_first_five_criteria_are_the_composition_dimensions():
    from services.diagnostic.composition import DOMAINS

    assert set(DOMAINS) <= {c[0] for c in es.CRITERIA}


# ── The authorship gate ──────────────────────────────────────────────────────

_DRAFT = {"exercise": "refutation", "prompt": "Was the wall worth building?", "text": "The wall was too costly.",
          "position": "", "opposing_view": "", "plan": []}


def _clean(data, stage="draft", draft=_DRAFT):
    return es.clean_coaching(data, draft=draft, stage=stage, draft_version=3)


def test_one_note_and_one_question_pass():
    c = _clean({"criterion": "opposing_view", "note": "You answer a view you have not stated yet.",
                "question": "How would someone who wanted the wall put their case?"})
    assert (c["criterion"], c["tier"], c["formative"], c["draft_version"]) == ("opposing_view", "reasoning", True, 3)
    assert c["analysis"]["word_count"] == 5


@pytest.mark.parametrize("data", [
    {"criterion": "grade", "note": "B+", "question": "Why?"},                         # not a criterion
    {"criterion": "detail", "note": "Add evidence.", "question": "Add evidence."},     # no question
    {"criterion": "audience", "note": "Think of readers.", "question": "Who reads it?"},  # audience too early
    {"criterion": "detail", "note": 'Try: "The wall cost more than the empire could pay."',
     "question": "Does that fit?"},                                                   # writes for them
    {"criterion": "detail", "note": "Use the source.",
     "question": 'Could you quote "the wall was never finished by anyone" here?'},    # invented quotation
])
def test_anything_else_is_refused(data):
    with pytest.raises(es.CoachingUnusable):
        _clean(data)


def test_quoting_the_students_own_words_is_allowed():
    c = _clean({"criterion": "detail", "note": 'You say "the wall was too costly."',
                "question": "What shows how costly it was?"})
    assert c["criterion"] == "detail"


def test_narrative_coaching_may_not_name_an_opposing_view():
    with pytest.raises(es.CoachingUnusable):
        _clean({"criterion": "opposing_view", "note": "x", "question": "y?"},
               draft={**_DRAFT, "exercise": "narrative"})


def test_the_coaching_prompt_forbids_writing_for_the_student_and_carries_the_dialectic_rule():
    with patch("services.ai_service._constitution_preamble", return_value=""):
        thesis = es.coaching_system_prompt("thesis", "draft", "rhetoric")
        narrative = es.coaching_system_prompt("narrative", "draft", "logic")
    for p in (thesis, narrative):
        assert "Never write any part of their essay" in p and "Never invent a quotation" in p
        assert "Never give a grade" in p
    assert "Never argue the opposing side" in thesis and "Never argue the opposing side" not in narrative


# ── The routes ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db(monkeypatch):
    monkeypatch.setattr(settings, "essay_studio_save_drafts", True)
    routes._session_drafts.clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        from core.encryption import initialize_encryption
        await initialize_encryption(settings.master_secret, session)
        for config in (_cfg("Ada", "7"), _cfg("Ben", "10"), _cfg("Cal", "4"), _cfg("Dee", "11")):
            key = await student_keys.get_or_create(session, config.student_name)
            session.add(StudentConfig(student_name=config.student_name, config_enc=encrypt_json(
                config.model_dump(), _config_aad(config.student_name), key)))
        await session.commit()
        yield session
    await engine.dispose()


async def _start(db, name="Ada", auth=PARENT, **kw):
    body = routes.StartRequest(**{"subject": LA, "exercise": "narrative", "prompt": "Tell the day the river rose.",
                                  **kw})
    return await routes.start(name, body, auth=auth, db=db)


async def _save(db, draft, name="Ada", auth=PARENT, **kw):
    return await routes.save(name, draft["id"], routes.SaveRequest(version=draft["version"], **kw), auth=auth, db=db)


async def _code(coro):
    with pytest.raises(HTTPException) as exc:
        await coro
    return exc.value.status_code, exc.value.detail


@pytest.mark.asyncio
async def test_status_reports_eligibility_from_the_saved_grade(db):
    ada = await routes.status("Ada", subject=LA, auth=PARENT, db=db)
    assert ada["available"] and ada["stage_band"] == "logic" and ada["persistence"] == "saved"
    assert [e["id"] for e in ada["exercises"]] == ["narrative", "refutation"]
    assert [e["id"] for e in (await routes.status("Ben", subject=LA, auth=PARENT, db=db))["exercises"]] == list(
        es.EXERCISES)
    assert (await routes.status("Cal", subject=LA, auth=PARENT, db=db))["reason"] == "grade"
    assert (await routes.status("Ada", subject=Subject.history, auth=PARENT, db=db))["reason"] == "subject"


@pytest.mark.asyncio
async def test_start_is_refused_outside_its_grades_subjects_exercises_and_time(db):
    assert (await _code(_start(db, "Cal")))[0] == 404
    assert (await _code(_start(db, subject=Subject.history)))[0] == 404
    assert (await _code(_start(db, exercise="thesis")))[0] == 422  # thesis is rhetoric-stage
    status, detail = await _code(_start(db, time_remaining_seconds=MIN_SECONDS_FOR_LONG_FORM_TASK - 1))
    assert status == 409 and detail["code"] == "not_enough_time"
    assert (await _start(db, time_remaining_seconds=MIN_SECONDS_FOR_LONG_FORM_TASK))["stage"] == "task"


@pytest.mark.asyncio
async def test_one_unfinished_draft_and_replacing_it_needs_a_confirmed_replace(db):
    first = await _start(db)
    status, detail = await _code(_start(db, exercise="refutation"))
    assert status == 409 and detail["code"] == "active_draft_exists" and detail["active"]["id"] == first["id"]
    second = await _start(db, exercise="refutation", replace=True)
    assert (await routes.active_draft("Ada", auth=PARENT, db=db))["id"] == second["id"]
    assert (await _code(routes.get_draft("Ada", first["id"], auth=PARENT, db=db)))[0] == 404


@pytest.mark.asyncio
async def test_a_save_must_carry_the_current_version(db):
    draft = await _start(db)
    ack = await _save(db, draft, text="The river rose in the night.", typed_chars=28, stage="draft")
    assert ack["version"] == 2 and ack["persistence"] == "saved"
    status, detail = await _code(_save(db, draft, text="older tab"))  # still version 1
    assert status == 409 and detail == {"code": "version_conflict", "current_version": 2}
    again = await routes.get_draft("Ada", draft["id"], auth=PARENT, db=db)
    assert again["text"] == "The river rose in the night." and again["stage"] == "draft"
    assert (again["typed_chars"], again["pasted_chars"]) == (28, 0)


@pytest.mark.asyncio
async def test_two_saves_of_one_version_cannot_both_land(db):
    draft = await _start(db)
    await _save(db, draft, text="first")
    row = await db.get(EssayDraft, draft["id"])
    await db.refresh(row)
    assert row.version == 2
    assert (await _code(_save(db, draft, text="second")))[0] == 409


@pytest.mark.asyncio
async def test_drafts_are_encrypted_at_rest(db):
    draft = await _start(db)
    await _save(db, draft, text="A sentence only the student wrote.")
    raw = (await db.execute(select(EssayDraft.detail_enc))).scalar_one()
    assert b"only the student wrote" not in raw and b"river" not in raw


@pytest.mark.asyncio
async def test_a_narrative_has_no_opposing_view(db):
    draft = await _start(db)
    await _save(db, draft, opposing_view="Someone might say otherwise.")
    full = await routes.get_draft("Ada", draft["id"], auth=PARENT, db=db)
    assert full["opposing_view"] == "" and not full["uses_opposing_view"]
    refutation = await _start(db, "Ben", exercise="refutation")
    await _save(db, refutation, "Ben", opposing_view="Walls keep people safe.")
    assert (await routes.get_draft("Ben", refutation["id"], auth=PARENT, db=db))["opposing_view"]


@pytest.mark.asyncio
async def test_another_learners_draft_is_refused(db, monkeypatch):
    draft = await _start(db)
    # Bound to Ben's own PIN: Ada's drafts are not his to read or write.
    ben = {"role": "child", "learner": "Ben", "learner_pin_nonce": "n"}
    monkeypatch.setattr("core.child_pin.token_is_live", AsyncMock(return_value=True))
    assert (await _code(routes.get_draft("Ada", draft["id"], auth=ben, db=db)))[0] == 404
    assert (await _code(routes.status("Ada", subject=LA, auth=ben, db=db)))[0] == 404
    assert (await _code(_save(db, draft, auth=ben, text="x")))[0] == 404
    # A draft id belonging to another learner is not found under this one.
    assert (await _code(routes.get_draft("Ben", draft["id"], auth=PARENT, db=db)))[0] == 404
    # Educators (a school) and the demo are refused before anything is read.
    for other in ({"role": "educator"}, {"role": "demo_code"}):
        assert (await _code(routes.status("Ada", subject=LA, auth=other, db=db)))[0] == 404


@pytest.mark.asyncio
async def test_a_finished_essay_is_the_parents_to_see_and_delete(db, monkeypatch):
    draft = await _start(db)
    done = await routes.complete("Ada", draft["id"], auth=PARENT, db=db)
    assert done["status"] == "finished"
    ada = {"role": "child", "learner": "Ada", "learner_pin_nonce": "n"}
    monkeypatch.setattr("core.child_pin.token_is_live", AsyncMock(return_value=True))
    assert (await _code(routes.get_draft("Ada", draft["id"], auth=ada, db=db)))[0] == 404
    listed = await routes.list_drafts("Ada", auth=PARENT, db=db)
    assert listed["drafts"][0]["status"] == "finished"
    # The parent-only routes are guarded by require_parent, not by a role check
    # inside the handler that a refactor could drop.
    from core.deps import require_parent
    for route in routes.router.routes:
        if route.endpoint in (routes.list_drafts, routes.delete_draft):
            assert any(d.call is require_parent for d in route.dependant.dependencies)
    await routes.delete_draft("Ada", draft["id"], auth=PARENT, db=db)
    assert (await db.execute(select(func.count()).select_from(EssayDraft))).scalar_one() == 0


# ── Coaching ─────────────────────────────────────────────────────────────────

def _reply(payload):
    return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload))])


GOOD = {"criterion": "sequence", "note": "The flood comes before the warning.",
        "question": "What happened first that day?"}


@pytest.mark.asyncio
async def test_coaching_goes_through_the_lessons_routed_client_and_never_touches_the_draft(db):
    draft = await _start(db)
    await _save(db, draft, text="The river rose. Then we heard the bell.", stage="draft")
    create = AsyncMock(return_value=_reply(GOOD))
    with patch.object(ai_service._client.messages, "create", create):
        out = await routes.coach("Ada", draft["id"], routes.CoachRequest(version=2), request=None, auth=PARENT, db=db)
    assert out["coaching"]["criterion"] == "sequence" and out["coaching"]["formative"]
    sent = create.await_args.kwargs
    assert "The river rose" in sent["messages"][0]["content"][0]["text"]
    after = await routes.get_draft("Ada", draft["id"], auth=PARENT, db=db)
    assert after["text"] == "The river rose. Then we heard the bell." and after["version"] == 2
    assert after["next_step"] == GOOD["question"] and after["coaching"]["note"] == GOOD["note"]


@pytest.mark.asyncio
async def test_coaching_writes_nothing_to_the_mastery_record_or_the_ledger(db):
    draft = await _start(db)
    with patch.object(ai_service._client.messages, "create", AsyncMock(return_value=_reply(GOOD))):
        await routes.coach("Ada", draft["id"], routes.CoachRequest(version=1), request=None, auth=PARENT, db=db)
    await routes.complete("Ada", draft["id"], auth=PARENT, db=db)
    for model in (MasteryProfile, SkillActivityLog):
        assert (await db.execute(select(func.count()).select_from(model))).scalar_one() == 0


@pytest.mark.asyncio
async def test_a_model_failure_or_an_unusable_reply_keeps_the_draft(db):
    draft = await _start(db)
    await _save(db, draft, text="Kept no matter what.")
    for side_effect in (ConnectionError("down"), None):
        create = AsyncMock(side_effect=side_effect, return_value=_reply({"criterion": "grade", "note": "A"}))
        with patch.object(ai_service._client.messages, "create", create):
            assert (await _code(routes.coach("Ada", draft["id"], routes.CoachRequest(version=2), request=None,
                                             auth=PARENT, db=db)))[0] == 503
    assert (await routes.get_draft("Ada", draft["id"], auth=PARENT, db=db))["text"] == "Kept no matter what."


@pytest.mark.asyncio
async def test_a_safeguarding_draft_gets_the_safe_response_and_no_model_call(db, monkeypatch):
    draft = await _start(db)
    await _save(db, draft, text="Some days I want to hurt myself.")
    monkeypatch.setattr(routes, "log_event", AsyncMock())
    deliver = AsyncMock(return_value="sent")
    monkeypatch.setattr("services.safeguarding_alerts.deliver", deliver)
    create = AsyncMock(return_value=_reply(GOOD))
    with patch.object(ai_service._client.messages, "create", create), \
            patch.object(routes, "audit_from_request", return_value={}):
        out = await routes.coach("Ada", draft["id"], routes.CoachRequest(version=2), request=None, auth=PARENT, db=db)
        import asyncio
        await asyncio.sleep(0)
    assert out["safeguarding"] and out["message"] == ai_service.safeguarding_response("en")
    create.assert_not_awaited()
    deliver.assert_awaited()


@pytest.mark.asyncio
async def test_coaching_is_limited_per_day_and_a_stale_version_is_refused(db, monkeypatch):
    draft = await _start(db)
    monkeypatch.setattr(es, "MAX_COACHING_PER_DAY", 1)
    with patch.object(ai_service._client.messages, "create", AsyncMock(return_value=_reply(GOOD))):
        assert (await _code(routes.coach("Ada", draft["id"], routes.CoachRequest(version=9), request=None,
                                         auth=PARENT, db=db)))[0] == 409
        await routes.coach("Ada", draft["id"], routes.CoachRequest(version=1), request=None, auth=PARENT, db=db)
        assert (await _code(routes.coach("Ada", draft["id"], routes.CoachRequest(version=1), request=None,
                                         auth=PARENT, db=db)))[0] == 429


@pytest.mark.asyncio
async def test_a_local_only_install_never_reaches_a_cloud_adapter(db, monkeypatch):
    """Coaching uses the lesson's routed client. Pinned to local with a cloud
    key also configured, a failing local model is retried and never falls
    back to the cloud adapter, on the first try or on the retry."""
    from services.adapters import router as adapter_router

    monkeypatch.setattr(settings, "bede_force_adapter", "local")
    monkeypatch.setattr(settings, "local_llm_base_url", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(settings, "openai_api_key", "sk-sample")
    calls = []

    def build(name, _settings):
        async def create(**_kw):
            calls.append(name)
            raise ConnectionError("local model is down")
        return SimpleNamespace(messages=SimpleNamespace(create=create))

    monkeypatch.setattr(adapter_router, "_build", build)
    monkeypatch.setattr(ai_service, "_client", adapter_router.resolve_with_failover(settings))
    draft = await _start(db)
    for _attempt in range(2):
        assert (await _code(routes.coach("Ada", draft["id"], routes.CoachRequest(version=1), request=None,
                                         auth=PARENT, db=db)))[0] == 503
    assert calls and set(calls) == {"local"}
    source = open(routes.__file__).read()
    for forbidden in ("AsyncAnthropic", "AsyncOpenAI", "resolve_named", "get_default_client("):
        assert forbidden not in source


@pytest.mark.asyncio
async def test_session_only_drafts_never_reach_the_database_and_belong_to_one_sign_in(db, monkeypatch):
    monkeypatch.setattr(settings, "essay_studio_save_drafts", False)
    sign_in = {"role": "parent", "iat": 1}
    draft = await _start(db, auth=sign_in)
    assert draft["persistence"] == "session"
    await _save(db, draft, auth=sign_in, text="Only for now.")
    # Session-only has no guarded UPDATE behind it, so the version check is the
    # only thing between an older tab and newer text.
    assert (await _code(_save(db, draft, auth=sign_in, text="older tab")))[0] == 409
    assert (await db.execute(select(func.count()).select_from(EssayDraft))).scalar_one() == 0
    assert (await routes.get_draft("Ada", draft["id"], auth=sign_in, db=db))["text"] == "Only for now."
    other = {"role": "parent", "iat": 2}
    assert (await _code(routes.get_draft("Ada", draft["id"], auth=other, db=db)))[0] == 404
    assert (await routes.status("Ada", subject=LA, auth=sign_in, db=db))["persistence"] == "session"


# ── Bede's invitation, through the real loop ────────────────────────────────

@pytest.fixture
def _fresh(monkeypatch):
    k2_practice._offered.clear()
    monkeypatch.setattr(ai_service, "log_event_nowait", lambda *a, **k: None)
    yield
    k2_practice._offered.clear()


def test_the_tool_is_registered_internal_and_long_form():
    assert "invite_essay_studio" in {t["name"] for t in ai_service.TUTOR_TOOLS}
    assert tool_registry.is_dispatchable_by_tutor("invite_essay_studio")
    assert "invite_essay_studio" in LONG_FORM_TOOLS


@pytest.mark.parametrize("locale,title", [("en", "Essay Studio"), ("es", "Estudio de Ensayo")])
def test_the_card_is_server_composed(locale, title):
    card = ai_service._process_tool_use("invite_essay_studio", {"prompt": "Was the wall worth it?"}, locale)
    assert card.startswith(es.CARD_PREFIX) and title in card and "Was the wall worth it?" in card
    empty = ai_service._process_tool_use("invite_essay_studio", {"prompt": ""}, locale)
    assert ai_service.card_phrases(locale)["essay_body"] in empty


def test_the_gate(_fresh):
    ok = _cfg(grade="7")
    allowed = ai_service._essay_studio_allowed
    assert allowed(ok, LA, None, [], session_id="s")
    assert not allowed(_cfg(grade="5"), LA, None, [], session_id="s")
    assert not allowed(ok, Subject.history, None, [], session_id="s")
    assert not allowed(_cfg(grade="7", subjects=[Subject.living_books]), LA, None, [], session_id="s")
    assert not allowed(ok, LA, "DEMO1", [], session_id="s")
    assert not allowed(ok, LA, None, [], time_remaining_seconds=MIN_SECONDS_FOR_LONG_FORM_TASK - 1, session_id="s")
    card = ChatMessage(role="assistant", content=es.CARD_PREFIX + "*Essay Studio* — x")
    assert not allowed(ok, LA, None, [card], session_id="s")


async def _dispatch(config, subject, tool_input, session_id="s"):
    from tests.test_agentic_tool_loop import _multi_round_stream, _tool_use_events

    fake, _ = _multi_round_stream([(list(_tool_use_events("t0", "invite_essay_studio", tool_input)), "end_turn")])
    seen = {}

    def spy(**kw):
        seen["system"] = kw.get("system")
        return fake(**kw)

    chunks = []
    with patch.object(ai_service._client.messages, "stream", side_effect=spy):
        async for chunk in ai_service.stream_tutor_response(
            config=config, subject=subject, history=[], child_message="hello", session_id=session_id,
        ):
            chunks.append(json.loads(chunk))
    system = " ".join(b.get("text", "") for b in seen.get("system") or [] if isinstance(b, dict))
    return [c for c in chunks if c["type"] == "tool"], system


@pytest.mark.asyncio
async def test_the_invitation_reaches_the_child_with_its_question_and_only_once(_fresh):
    tools, system = await _dispatch(_cfg(grade="7"), LA, {"prompt": "Was the flood anyone's fault?",
                                                          "exercise": "refutation"})
    assert "<essay_studio>" in system
    assert len(tools) == 1 and tools[0]["tool"] == "invite_essay_studio"
    assert tools[0]["essay_prompt"] == "Was the flood anyone's fault?" and tools[0]["exercise"] == "refutation"
    again, system = await _dispatch(_cfg(grade="7"), LA, {"prompt": "Another?"})
    assert again == [] and "<essay_studio>" not in system


@pytest.mark.asyncio
@pytest.mark.parametrize("config,subject,tool_input", [
    (_cfg(grade="5"), LA, {"prompt": "x?"}),                                   # grade
    (_cfg(grade="7"), Subject.morning_time, {"prompt": "x?"}),                 # subject
    (_cfg(grade="7"), LA, {"prompt": "x?", "exercise": "thesis"}),             # not at this stage
])
async def test_an_invitation_the_gate_refuses_is_dropped(_fresh, config, subject, tool_input):
    tools, system = await _dispatch(config, subject, tool_input)
    assert tools == []
    if tool_input.get("exercise") != "thesis":
        assert "<essay_studio>" not in system
