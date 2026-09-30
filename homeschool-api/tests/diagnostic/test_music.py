"""
Music-knowledge mastery engine — services/diagnostic/music.py.

Structured like tests/diagnostic/test_phonics.py (a fixed developmental
domain walk, not language_exposure's probability sort), plus one section
that has no counterpart in any sibling engine's tests: **the refusals.**

This engine measures what a child KNOWS about the music they listened to.
It must never measure how they RESPONDED to it — whether they liked it,
found it beautiful, or preferred one piece to another. That is the same
refusal CLAUDE.md already makes for a child's spiritual engagement and for
character virtues, and the reason it needs tests rather than a comment is
that it is the easy thing to add later: a "how much did they enjoy it"
field looks like richer data and reads, to a reviewer skimming a diff,
exactly like the fields beside it. So the guards below are written to fail
a build rather than rely on a reviewer noticing.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core import student_keys
from core.config import settings
from core.database import Base, MasteryProfile, SkillActivityLog
from core.encryption import decrypt_json, student_aad
from models.schemas import GradeStage, SessionConfig, Subject
from services import ai_service
from services.diagnostic.music import (
    CALIBRATION_THRESHOLD,
    DOMAIN_CHECKIN_HINTS,
    DOMAIN_LABELS,
    DOMAINS,
    FORBIDDEN_DOMAIN_SUBSTRINGS,
    SUBJECT_AREA,
    apply_evidence,
    build_summary_view,
    get_music_summary,
    new_vector,
    process_evidence,
)


# ── The refusals — the part with no sibling precedent ─────────────────────

def test_no_domain_measures_the_child_s_response_to_the_music():
    """The load-bearing guard. A domain named for enjoyment, preference or
    feeling would make this engine score a child's response to beauty,
    which is not Bede's to score."""
    for domain in DOMAINS:
        lowered = domain.lower()
        for forbidden in FORBIDDEN_DOMAIN_SUBSTRINGS:
            assert forbidden not in lowered, (
                f"domain {domain!r} contains {forbidden!r} — this engine records what a "
                "child knows about the music, never how they responded to it"
            )


def test_the_forbidden_list_actually_covers_the_words_someone_would_reach_for():
    """A guard whose vocabulary is too narrow passes while the thing it
    forbids walks in under a synonym."""
    for word in ("enjoyment", "enjoyed", "preference", "favourite", "favorite",
                 "emotional_depth", "feelings", "appreciation", "engagement",
                 "love_of_music", "beauty_response", "reaction"):
        assert any(f in word for f in FORBIDDEN_DOMAIN_SUBSTRINGS), word


def test_the_tools_own_description_forbids_recording_a_response():
    """The model reads the tool description, not this module's docstring, so
    the refusal has to be in the description itself."""
    tool = next(t for t in ai_service.TUTOR_TOOLS if t["name"] == "record_music_evidence")
    described = tool["description"].lower()
    assert "never" in described
    for expected in ("enjoy", "beautiful", "preferred", "felt"):
        assert expected in described, f"the tool description does not rule out {expected!r}"


def test_the_tool_offers_no_field_to_put_a_response_in():
    tool = next(t for t in ai_service.TUTOR_TOOLS if t["name"] == "record_music_evidence")
    for field in tool["input_schema"]["properties"]:
        lowered = field.lower()
        for forbidden in FORBIDDEN_DOMAIN_SUBSTRINGS:
            assert forbidden not in lowered, f"{field!r} is a response field"


def test_the_checkin_note_tells_bede_to_delight_without_recording_it():
    """Refusing to score a response must not read as "be cold about it" —
    the note has to keep the warmth and drop only the bookkeeping."""
    note = ai_service._music_checkin_note(_config(), Subject.art_music)
    lowered = note.lower()
    assert "never record anything about how the child responded" in lowered
    assert "delight" in lowered


# ── Pure in-memory unit tests (no DB) ────────────────────────────────────

def test_new_vector_is_flat_half_across_all_domains():
    vector = new_vector()
    assert set(vector) == set(DOMAINS)
    assert all(p == 0.5 for p in vector.values())


def test_every_domain_has_a_label_and_a_checkin_hint():
    for domain in DOMAINS:
        assert DOMAIN_LABELS.get(domain)
        assert DOMAIN_CHECKIN_HINTS.get(domain)


def test_apply_evidence_moves_a_correct_answer_up_and_an_incorrect_one_down():
    up, updates = apply_evidence(new_vector(), "instrumentation", "correct")
    assert up["instrumentation"] > 0.5
    assert len(updates) == 1 and updates[0].domain == "instrumentation"
    down, _ = apply_evidence(new_vector(), "instrumentation", "incorrect")
    assert down["instrumentation"] < 0.5


def test_apply_evidence_only_touches_the_one_domain_evidenced():
    updated, _ = apply_evidence(new_vector(), "form", "correct")
    for domain in DOMAINS:
        if domain != "form":
            assert updated[domain] == 0.5


@pytest.mark.parametrize("domain,outcome", [
    ("enjoyment", "correct"),        # a forbidden domain is simply unknown
    ("instrumentation", "loved_it"),
    ("not_a_domain", "correct"),
])
def test_apply_evidence_is_a_true_no_op_for_anything_unrecognized(domain, outcome):
    vector = new_vector()
    updated, updates = apply_evidence(vector, domain, outcome)
    assert updates == []
    assert updated == vector


def test_next_steps_walks_the_developmental_order_rather_than_sorting_by_score():
    """A child still learning to hear fast from slow is not helped by being
    pointed at historical connection, however low that number is. This is
    phonics' rule, not language_exposure's."""
    vector = {d: 0.5 for d in DOMAINS}
    # Make the LAST domain look like the weakest. A probability sort would
    # promote it to first; a developmental walk must not.
    vector[DOMAINS[-1]] = 0.01
    view = build_summary_view(vector, "Sam", 10, "2026-01-01T00:00:00")
    assert view["next_steps"][0]["skill_id"] == f"{SUBJECT_AREA}.{DOMAINS[0]}"


def test_summary_view_has_the_shared_shape_and_reports_calibration_honestly():
    view = build_summary_view(new_vector(), "Sam", 1, "2026-01-01T00:00:00")
    assert view["subject_area"] == SUBJECT_AREA
    assert view["calibration"] is True, "one observation is not a settled read"
    assert {"student_name", "evidence_count", "domains", "gaps", "next_steps", "updated_at"} <= set(view)
    assert len(view["domains"]) == len(DOMAINS)
    settled = build_summary_view(new_vector(), "Sam", CALIBRATION_THRESHOLD, "2026-01-01T00:00:00")
    assert settled["calibration"] is False


def test_the_summary_emits_no_measure_of_the_child_s_response():
    """A consuming model can reintroduce a judgment the data does not carry
    just by summarizing it, so the payload itself must be clean."""
    view = build_summary_view(new_vector(), "Sam", 9, "2026-01-01T00:00:00")
    blob = repr(view).lower()
    for forbidden in ("enjoy", "prefer", "favourite", "favorite", "beautiful"):
        assert forbidden not in blob, forbidden


# ── DB-backed ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    # _load_music_vector_readonly caches per student at module level with a
    # 5-minute TTL, so without this a later test reads an earlier test's
    # vector for the same student name and the database it was given looks
    # like it already had history.
    ai_service._music_vector_cache.clear()
    async with session_factory() as session:
        from core.encryption import initialize_encryption
        await initialize_encryption(settings.master_secret, session)
        yield session
    ai_service._music_vector_cache.clear()
    await engine.dispose()


def _config(**kw) -> SessionConfig:
    base = dict(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery)
    base.update(kw)
    return SessionConfig(**base)


@pytest.mark.asyncio
async def test_process_evidence_persists_under_its_own_subject_area(db_session):
    vector = await process_evidence(db_session, "Sam", "instrumentation", "correct")
    assert vector is not None and vector["instrumentation"] > 0.5

    from sqlalchemy import select
    row = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.subject_area == SUBJECT_AREA)
    )).scalar_one()
    assert row.evidence_count == 1
    stored = decrypt_json(
        row.profile_enc,
        student_aad("mastery_profiles", "profile_enc", "Sam", SUBJECT_AREA),
        await student_keys.get_existing(db_session, "Sam"),
    )
    assert stored["instrumentation"] > 0.5


@pytest.mark.asyncio
async def test_music_evidence_never_lands_in_another_subject_areas_profile(db_session):
    from services.diagnostic.language_exposure import process_evidence as lang_evidence

    await process_evidence(db_session, "Sam", "form", "correct")
    await lang_evidence(db_session, "Sam", "italian", "correct")

    from sqlalchemy import select
    rows = (await db_session.execute(select(MasteryProfile))).scalars().all()
    assert {r.subject_area for r in rows} == {SUBJECT_AREA, "language_exposure"}
    assert all(r.evidence_count == 1 for r in rows)


@pytest.mark.asyncio
async def test_summary_is_none_until_there_is_real_evidence(db_session):
    assert await get_music_summary(db_session, "Sam") is None
    await process_evidence(db_session, "Sam", "musical_elements", "partial")
    assert (await get_music_summary(db_session, "Sam"))["subject_area"] == SUBJECT_AREA


# ── Wiring: the gate, the ledger, and the demo/production split ──────────

@pytest.mark.asyncio
async def test_a_listening_lesson_writes_both_the_profile_and_the_work_ledger(db_session):
    await ai_service._record_music_evidence(
        db_session, None, _config(), Subject.art_music,
        {"domain": "composer_knowledge", "outcome": "correct"},
    )
    from sqlalchemy import select
    assert (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.subject_area == SUBJECT_AREA)
    )).scalar_one_or_none() is not None
    ledger = (await db_session.execute(
        select(SkillActivityLog).where(SkillActivityLog.subject_area == SUBJECT_AREA)
    )).scalars().all()
    assert len(ledger) == 1


@pytest.mark.asyncio
async def test_the_recorder_is_gated_to_art_music(db_session):
    """Defensive backstop matching where the prompt guidance is gated — a
    mathematics session must never produce music evidence."""
    for subject in (Subject.mathematics, Subject.history, Subject.morning_time):
        await ai_service._record_music_evidence(
            db_session, None, _config(), subject,
            {"domain": "form", "outcome": "correct"},
        )
    from sqlalchemy import select
    assert (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.subject_area == SUBJECT_AREA)
    )).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_a_demo_session_reaches_the_ledger_and_never_the_mastery_profile(monkeypatch, db_session):
    """The explicit both-surfaces requirement. The ledger records an event,
    so its first entry is as true as its two-hundredth and a demo visitor
    gets the real card; the mastery estimate needs history a fifteen-minute
    demo cannot produce, so it stays real-sessions-only exactly as
    phonics/literacy/language do."""
    recorded = []
    monkeypatch.setattr(
        ai_service, "_record_work_done_demo",
        lambda code, area, skill, outcome, ev=None: recorded.append((code, area, skill, outcome))
        or _noop(),
    )
    await ai_service._record_music_evidence(
        None, "ABC123", _config(), Subject.art_music,
        {"domain": "instrumentation", "outcome": "partial"},
    )
    assert recorded == [("ABC123", SUBJECT_AREA, "instrumentation", "partial")]


async def _noop():
    return None


def test_the_work_ledger_labels_music_domains_in_plain_words():
    """Without a _work_label branch the parent's ledger shows raw domain
    ids, which is the silent fallback that function ends with."""
    for domain in DOMAINS:
        label = ai_service._work_label(SUBJECT_AREA, domain)
        assert label == DOMAIN_LABELS[domain]
        assert label != domain


def test_the_tool_is_registered_silent():
    from services import tool_registry
    assert "record_music_evidence" in tool_registry.SILENT_TOOLS
    assert tool_registry.is_dispatchable_by_tutor("record_music_evidence")


def test_the_checkin_note_only_renders_for_art_music():
    assert ai_service._music_checkin_note(_config(), Subject.art_music) != ""
    for subject in (Subject.mathematics, Subject.history, Subject.saints):
        assert ai_service._music_checkin_note(_config(), subject) == ""


def test_the_checkin_note_renders_for_every_stage():
    """Ungated by stage on purpose: every grade listens, and what changes
    with age is the depth of the question, which each catalogue entry's own
    stage_notes already carries."""
    for stage in GradeStage:
        note = ai_service._music_checkin_note(_config(grade_stage=stage), Subject.art_music)
        assert note != "", stage
        for domain in DOMAINS:
            assert domain in note


def test_the_curation_gate_accepts_a_music_skill_id():
    """Content declaring that it exercises a music domain must validate, or
    the repository cannot be grown without every entry claiming it exercises
    nothing."""
    from services.content_curation import known_skill_ids
    ids = known_skill_ids()
    for domain in DOMAINS:
        assert domain in ids, domain


# ── The adaptability loop: the profile must feed back, not just accumulate ──

@pytest.mark.asyncio
async def test_a_later_lesson_is_calibrated_from_what_the_child_already_showed(db_session):
    """The CALIBRATE step. Without this read-back the engine would be
    write-only — a picture for the parent that never changes Bede's own next
    listening lesson — which for a subject that revisits the same small
    repertoire on purpose defeats the point."""
    for _ in range(CALIBRATION_THRESHOLD):
        await process_evidence(db_session, "Sam", "musical_elements", "correct")

    vector, count = await ai_service._load_music_vector_readonly(db_session, "Sam")
    assert vector is not None and count == CALIBRATION_THRESHOLD

    note = ai_service._music_calibration_note(Subject.art_music, vector, count)
    assert "<music_so_far>" in note
    assert DOMAIN_LABELS["musical_elements"] in note
    assert "ever said to them" in note


def test_the_calibration_note_says_nothing_before_it_honestly_can():
    """Two observations is not a read. A confident note built on it would be
    worse than no note."""
    vector = {d: 0.9 for d in DOMAINS}
    assert ai_service._music_calibration_note(Subject.art_music, vector, CALIBRATION_THRESHOLD - 1) == ""
    assert ai_service._music_calibration_note(Subject.art_music, None, 99) == ""


def test_the_calibration_note_names_what_to_build_on_not_what_the_child_lacks():
    """A note reading "weak at X" invites the sentence _learning_support_note
    forbids Bede from ever saying to a child. Same discipline as
    lesson_planner's reason strings."""
    vector = {d: 0.2 for d in DOMAINS}
    vector["musical_elements"] = 0.9
    note = ai_service._music_calibration_note(Subject.art_music, vector, 10).lower()
    for judgment in ("weak", "poor", "struggl", "behind", "cannot", "fail", "bad at"):
        assert judgment not in note, judgment
    assert "worth reaching for" in note


def test_the_calibration_note_is_scoped_to_art_music():
    vector = {d: 0.9 for d in DOMAINS}
    for subject in (Subject.mathematics, Subject.history, Subject.living_books):
        assert ai_service._music_calibration_note(subject, vector, 10) == ""


@pytest.mark.asyncio
async def test_reading_the_vector_back_never_consumes_or_changes_it(db_session):
    await process_evidence(db_session, "Sam", "form", "correct")
    before = await ai_service._load_music_vector_readonly(db_session, "Sam")
    ai_service._music_vector_cache.clear()
    after = await ai_service._load_music_vector_readonly(db_session, "Sam")
    assert before == after

    from sqlalchemy import select
    row = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.subject_area == SUBJECT_AREA)
    )).scalar_one()
    assert row.evidence_count == 1, "a read must not count as evidence"


@pytest.mark.asyncio
async def test_the_real_turn_actually_puts_the_calibration_into_the_prompt(db_session):
    """Asserts the CALL SITE, not the loader.

    Every test above calls `_load_music_vector_readonly` or
    `_music_calibration_note` directly, so all of them keep passing if
    `stream_tutor_response` stops loading the vector at all — which was
    verified by deleting that load and watching them stay green. That is the
    `bayesian_update`-unpassed-`params` defect shape exactly: a function
    tested in isolation, unreachable from the only path that matters. So this
    one drives the real turn and reads the system block the model was
    actually handed.
    """
    import json as _json
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock, patch

    for _ in range(CALIBRATION_THRESHOLD):
        await process_evidence(db_session, "Sam", "musical_elements", "correct")
    ai_service._music_vector_cache.clear()

    captured = {}

    @asynccontextmanager
    async def _fake(**kwargs):
        captured.update(kwargs)

        class _S:
            def __aiter__(self):
                return self._it()

            async def _it(self):
                if False:
                    yield None

            async def get_final_message(self):
                msg = MagicMock()
                msg.stop_reason = "end_turn"
                msg.content = []
                msg.usage = MagicMock(
                    input_tokens=1, output_tokens=1,
                    cache_creation_input_tokens=0, cache_read_input_tokens=0,
                )
                return msg

        yield _S()

    with patch.object(ai_service._client.messages, "stream", side_effect=_fake):
        async for _ in ai_service.stream_tutor_response(
            config=_config(), subject=Subject.art_music, history=[],
            child_message="ready", db=db_session,
        ):
            pass

    system_text = _json.dumps(captured.get("system", []))
    assert "<music_so_far>" in system_text, (
        "the turn never loaded the child's music vector, so the engine is "
        "write-only and a second listening lesson starts from the grade"
    )
    assert DOMAIN_LABELS["musical_elements"] in system_text
