"""G1 items 3, 7, 8: no per-learner cache is keyed by display name.

Two synthetic campuses each hold a learner with the SAME display name. Every
per-learner cache (the unwrapped data key and the four read-only prompt
caches) must keep them apart, and revocation/deletion must evict through one
entry point.

Runs on in-memory SQLite by default. Set G1_CACHE_TEST_DATABASE_URL to a
dedicated, disposable Postgres database to run the same tests there; the
fixture creates and drops every table in it.

Synthetic identities only: Synthetic Campus One/Two, Synthetic Teacher
One/Two, Synthetic Learner One/Two (who deliberately share a display name).
"""
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from anthropic.types import RawContentBlockDeltaEvent, RawContentBlockStartEvent, RawContentBlockStopEvent
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core import learner_scope, student_keys
from core.config import settings
from core.database import (
    Base, LearnerProfile, LessonBookmark, MasteryProfile, StudentKey, normalize_database_url,
)
from core.encryption import aad_for, decrypt, encrypt_json, initialize_encryption, student_aad
from core.learner_scope import LEGACY_CAMPUS, LearnerScope, environment, evict_learner
from models.schemas import GradeStage, SessionConfig, Subject
from routers.pilot_campuses import (
    CampusInput, LearnerInput, approve_educator_membership, approve_roster_grant,
    create_campus, create_learner, disable_campus_membership, revoke_roster_grant,
)
from services import ai_service
from services.diagnostic.music import SUBJECT_AREA as MUSIC_AREA
from services.educator_access import provision_educator

ADMIN = {"role": "parent", "auth_method": "webauthn_uv"}
SAME_NAME = "Synthetic Learner"


@pytest_asyncio.fixture
async def db(monkeypatch):
    monkeypatch.setattr(settings, "educator_pilot_enabled", True)
    monkeypatch.setattr(settings, "demo_pin", "")
    monkeypatch.setattr(settings, "production", "false")
    url = os.environ.get("G1_CACHE_TEST_DATABASE_URL")
    if url:
        engine = create_async_engine(normalize_database_url(url))
    else:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await initialize_encryption(settings.master_secret, session)
        yield session
    if url:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def two_campuses(db):
    """Synthetic Campus One/Two, each with a same-named learner, each with
    its own teacher holding a grant — created through the real route
    handlers so the IDs are the service's own canonical UUIDv4s."""
    t1 = await provision_educator(db, "synthetic.teacher.one", "synthetic-passphrase-one-strong")
    t2 = await provision_educator(db, "synthetic.teacher.two", "synthetic-passphrase-two-strong")
    c1 = (await create_campus(CampusInput(title="Synthetic Campus One"), auth=ADMIN, db=db))["campus_id"]
    c2 = (await create_campus(CampusInput(title="Synthetic Campus Two"), auth=ADMIN, db=db))["campus_id"]
    l1 = (await create_learner(c1, LearnerInput(display_name=SAME_NAME), auth=ADMIN, db=db))["learner_id"]
    l2 = (await create_learner(c2, LearnerInput(display_name=SAME_NAME), auth=ADMIN, db=db))["learner_id"]
    await approve_educator_membership(c1, t1["id"], auth=ADMIN, db=db)
    await approve_educator_membership(c2, t2["id"], auth=ADMIN, db=db)
    await approve_roster_grant(c1, t1["id"], l1, auth=ADMIN, db=db)
    await approve_roster_grant(c2, t2["id"], l2, auth=ADMIN, db=db)
    return {
        "t1": t1, "t2": t2, "c1": c1, "c2": c2,
        "one": LearnerScope.institutional(c1, l1),
        "two": LearnerScope.institutional(c2, l2),
    }


async def seed_learner_one(db, scope: LearnerScope):
    """Write one encrypted row per cached resource for a learner, under its
    own key and its own storage subject — exactly as the real write paths
    would for that scope."""
    key = await student_keys.get_or_create(db, scope)
    subj = scope.storage_subject
    db.add(MasteryProfile(
        student_name=subj, subject_area="mathematics", evidence_count=7,
        profile_enc=encrypt_json({"add_within_10": 0.9}, student_aad("mastery_profiles", "profile_enc", subj, "mathematics"), key),
    ))
    db.add(MasteryProfile(
        student_name=subj, subject_area=MUSIC_AREA, evidence_count=4,
        profile_enc=encrypt_json({"musical_elements": 0.8}, student_aad("mastery_profiles", "profile_enc", subj, MUSIC_AREA), key),
    ))
    db.add(LearnerProfile(
        student_name=subj, session_count=3,
        profile_enc=encrypt_json({"processing_style": "visual"}, student_aad("learner_profiles", "profile_enc", subj), key),
    ))
    db.add(LessonBookmark(
        student_name=subj, subject="history", updated_at=datetime.now(timezone.utc),
        bookmark_enc=encrypt_json({"note": "Synthetic resume point one."}, student_aad("lesson_bookmarks", "bookmark_enc", subj, "history"), key),
    ))
    await db.commit()


async def prime(db, scope: LearnerScope) -> dict:
    return {
        "mastery": await ai_service._load_mastery_vector_readonly(db, SAME_NAME, scope),
        "style": await ai_service._load_processing_style_readonly(db, SAME_NAME, scope),
        "bookmark": await ai_service._load_lesson_bookmark_readonly(db, SAME_NAME, Subject.history, scope),
        "music": await ai_service._load_music_vector_readonly(db, SAME_NAME, scope),
    }


def all_cache_keys() -> list[tuple]:
    keys = list(student_keys._cache)
    for cache in ai_service._PROMPT_CACHES:
        keys.extend(cache)
    return keys


# ── The key itself ────────────────────────────────────────────────────────────

def test_cache_key_is_exactly_the_owner_five_components_in_order():
    scope = LearnerScope.institutional(
        "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222",
    )
    key = scope.cache_key("prompt_mastery_vector", 3)
    assert key == (
        environment(),
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "prompt_mastery_vector",
        3,
    )
    assert len(key) == 5
    # resource_version is its own component, never folded into the type.
    assert key[3] == "prompt_mastery_vector" and key[4] == 3
    assert scope.cache_key("prompt_mastery_vector", 4) != key


def test_environment_is_derived_from_configuration(monkeypatch):
    monkeypatch.setattr(settings, "demo_pin", "")
    monkeypatch.setattr(settings, "production", "false")
    assert environment() == "development"
    monkeypatch.setattr(settings, "production", "true")
    assert environment() == "production"


def test_legacy_scope_is_explicit_and_never_a_bare_name():
    scope = LearnerScope.legacy(SAME_NAME)
    key = scope.cache_key("student_data_key", 1)
    assert key[1] == LEGACY_CAMPUS
    assert SAME_NAME not in key
    assert key[2] != SAME_NAME
    # Same name, same legacy scope: a household's cache stays warm.
    assert LearnerScope.legacy(SAME_NAME).cache_key("student_data_key", 1) == key
    # On disk the legacy subject is the name, unchanged.
    assert scope.storage_subject == SAME_NAME


def test_institutional_scope_rejects_noncanonical_ids():
    for bad in ["", "not-a-uuid", "11111111-1111-1111-8111-111111111111",
                "11111111111141118111111111111111"]:
        with pytest.raises(ValueError):
            LearnerScope.institutional(bad, "22222222-2222-4222-8222-222222222222")


def test_institutional_storage_subject_cannot_collide_with_a_household_name():
    scope = LearnerScope.institutional(
        "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222",
    )
    household_max = SessionConfig.model_fields["student_name"].metadata
    max_len = next(m.max_length for m in household_max if hasattr(m, "max_length"))
    assert len(scope.storage_subject) > max_len


# ── Same-named learners on two campuses ───────────────────────────────────────

@pytest.mark.asyncio
async def test_same_name_learners_get_distinct_unwrapped_keys_rows_and_aad(db):
    w = await two_campuses(db)
    one, two = w["one"], w["two"]
    k1 = await student_keys.get_or_create(db, one)
    k2 = await student_keys.get_or_create(db, two)
    assert k1 != k2

    r1 = await db.get(StudentKey, one.storage_subject)
    r2 = await db.get(StudentKey, two.storage_subject)
    assert r1 is not None and r2 is not None
    assert await db.get(StudentKey, SAME_NAME) is None  # never the display name
    # AAD binds each wrapped key to its own learner: one's AAD cannot open two's.
    with pytest.raises(Exception):
        decrypt(r2.wrapped_key, aad_for("student_keys", "wrapped_key", one.storage_subject))

    # A cache read for Learner Two after priming Learner One is a miss that
    # returns Learner Two's own key, never Learner One's.
    student_keys.clear_cache()
    assert await student_keys.get_existing(db, one) == k1
    assert await student_keys.get_existing(db, two) == k2
    assert len([k for k in student_keys._cache]) == 2


@pytest.mark.asyncio
async def test_prompt_caches_primed_for_one_campus_miss_for_the_same_name_on_the_other(db):
    w = await two_campuses(db)
    await seed_learner_one(db, w["one"])

    primed = await prime(db, w["one"])
    assert primed["mastery"] == ({"add_within_10": 0.9}, 7)
    assert primed["style"] == "visual"
    assert primed["bookmark"]["note"] == "Synthetic resume point one."
    assert primed["music"] == ({"musical_elements": 0.8}, 4)

    other = await prime(db, w["two"])
    assert other == {"mastery": (None, 0), "style": None, "bookmark": None, "music": (None, 0)}
    # Nor does the legacy household scope for the same name see it.
    legacy = await prime(db, LearnerScope.legacy(SAME_NAME))
    assert legacy == {"mastery": (None, 0), "style": None, "bookmark": None, "music": (None, 0)}

    for key in all_cache_keys():
        assert SAME_NAME not in key, key
        assert len(key) == 5


@pytest.mark.asyncio
async def test_stream_tutor_response_threads_the_learner_scope_to_the_caches(db):
    """Invocation, not just the loader: the real stream path must key its
    caches and row lookups by the scope it is handed."""
    w = await two_campuses(db)
    await seed_learner_one(db, w["one"])
    config = SessionConfig(
        student_name=SAME_NAME, grade="3", grade_stage=GradeStage.core_mastery,
        subjects=[Subject.history],
    )

    async def run(scope):
        captured: dict = {}
        with patch.object(ai_service._client.messages, "stream", side_effect=_capturing_stream(captured)):
            async for _ in ai_service.stream_tutor_response(
                config=config, subject=Subject.history, history=[],
                child_message="Hello", db=db, learner_scope=scope,
            ):
                pass
        return captured["system"][1]["text"]

    assert "Synthetic resume point one." in await run(w["one"])
    assert "Synthetic resume point one." not in await run(w["two"])
    owned = [k for k in ai_service._lesson_bookmark_cache if w["one"].owns(k)]
    assert owned, "stream_tutor_response did not populate Learner One's scoped entry"


@pytest.mark.asyncio
async def test_environment_change_isolates_cache_entries(db, monkeypatch):
    w = await two_campuses(db)
    await seed_learner_one(db, w["one"])
    one = w["one"]
    await prime(db, one)
    real_key = await student_keys.get_existing(db, one)

    dev_key = one.cache_key("prompt_processing_style", ai_service._PROMPT_CACHE_VERSION)
    ai_service._processing_style_cache[dev_key] = ("SENTINEL", 1e18)
    student_keys._cache[one.cache_key("student_data_key", 1)] = (b"S" * 32, 1e18)

    monkeypatch.setattr(settings, "production", "true")
    assert await ai_service._load_processing_style_readonly(db, SAME_NAME, one) == "visual"
    assert await student_keys.get_existing(db, one) == real_key

    monkeypatch.setattr(settings, "production", "false")
    assert await ai_service._load_processing_style_readonly(db, SAME_NAME, one) == "SENTINEL"
    assert await student_keys.get_existing(db, one) == b"S" * 32


# ── Eviction: one entry point, wired into revocation ─────────────────────────

@pytest.mark.asyncio
async def test_evict_learner_removes_every_scoped_entry_and_the_unwrapped_key(db):
    w = await two_campuses(db)
    await seed_learner_one(db, w["one"])
    await seed_learner_one(db, w["two"])
    await prime(db, w["one"])
    await prime(db, w["two"])
    before_two = [k for k in all_cache_keys() if w["two"].owns(k)]

    removed = evict_learner(w["one"])
    assert removed == 5  # data key + four prompt caches
    assert not [k for k in all_cache_keys() if w["one"].owns(k)]
    assert [k for k in all_cache_keys() if w["two"].owns(k)] == before_two
    assert evict_learner(w["one"]) == 0


@pytest.mark.asyncio
async def test_evict_learner_reaches_every_environment(db, monkeypatch):
    w = await two_campuses(db)
    await seed_learner_one(db, w["one"])
    await prime(db, w["one"])
    monkeypatch.setattr(settings, "production", "true")
    await prime(db, w["one"])
    assert len([k for k in all_cache_keys() if w["one"].owns(k)]) == 10
    assert evict_learner(w["one"]) == 10


@pytest.mark.asyncio
async def test_grant_revocation_route_evicts_the_learner(db):
    w = await two_campuses(db)
    await seed_learner_one(db, w["one"])
    await seed_learner_one(db, w["two"])
    await prime(db, w["one"])
    await prime(db, w["two"])

    await revoke_roster_grant(w["c1"], w["t1"]["id"], w["one"].learner_id, auth=ADMIN, db=db)

    assert not [k for k in all_cache_keys() if w["one"].owns(k)]
    assert len([k for k in all_cache_keys() if w["two"].owns(k)]) == 5


@pytest.mark.asyncio
async def test_membership_disable_route_evicts_every_granted_learner(db):
    w = await two_campuses(db)
    await seed_learner_one(db, w["one"])
    await seed_learner_one(db, w["two"])
    await prime(db, w["one"])
    await prime(db, w["two"])

    await disable_campus_membership(w["c1"], w["t1"]["id"], auth=ADMIN, db=db)

    assert not [k for k in all_cache_keys() if w["one"].owns(k)]
    assert len([k for k in all_cache_keys() if w["two"].owns(k)]) == 5


@pytest.mark.asyncio
async def test_destroy_evicts_the_scoped_unwrapped_key(db):
    w = await two_campuses(db)
    await student_keys.get_or_create(db, w["one"])
    await student_keys.get_or_create(db, w["two"])
    assert await student_keys.destroy(db, w["one"]) is True
    await db.commit()
    assert student_keys._cache_get(w["one"]) is None
    assert student_keys._cache_get(w["two"]) is not None


# ── Legacy household path unchanged ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_legacy_name_path_keeps_its_row_aad_and_reads(db):
    key = await student_keys.get_or_create(db, SAME_NAME)
    row = await db.get(StudentKey, SAME_NAME)
    assert row is not None
    assert decrypt(row.wrapped_key, aad_for("student_keys", "wrapped_key", SAME_NAME)) == key
    # A bare string and the explicit legacy scope are the same learner.
    assert await student_keys.get_existing(db, LearnerScope.legacy(SAME_NAME)) == key

    db.add(LearnerProfile(
        student_name=SAME_NAME, session_count=3,
        profile_enc=encrypt_json({"processing_style": "auditory"}, student_aad("learner_profiles", "profile_enc", SAME_NAME), key),
    ))
    await db.commit()
    # No scope passed: the household caller, exactly as before.
    assert await ai_service._load_processing_style_readonly(db, SAME_NAME) == "auditory"
    assert learner_scope.evict_learner(LearnerScope.legacy(SAME_NAME)) == 2


# ── helpers ──────────────────────────────────────────────────────────────────

class _FakeStream:
    def __init__(self, events):
        self._events = events

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        for event in self._events:
            yield event


def _text_events():
    yield RawContentBlockStartEvent.model_validate(
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
    )
    yield RawContentBlockDeltaEvent.model_validate(
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}}
    )
    yield RawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": 0})


def _capturing_stream(captured: dict):
    @asynccontextmanager
    async def _fake(**kwargs):
        captured["system"] = kwargs["system"]
        yield _FakeStream(list(_text_events()))
    return _fake
