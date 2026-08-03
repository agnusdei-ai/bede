"""
Per-student keys and crypto-shredding (punch-list #6, P3).

The claim under test is the one docs/DATA_RETENTION.md and README.md make
to families: that deleting a student's data actually destroys it. Before
this, that was true of the live table and false of the disk — dead tuples,
WAL, and every prior backup stayed decryptable indefinitely under a
DATA_KEY that never changes.

So the tests that matter here are not "the function returns True". They
are: after a shred, does ciphertext that an attacker already holds — a
backup copy, a dead tuple — still open? It must not.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import core.encryption as encryption_module
from core import student_keys
from core.database import Base, StudentKey
from core.encryption import decrypt_json, encrypt_json, student_aad

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    from Crypto.Random import get_random_bytes
    encryption_module._DATA_KEY = get_random_bytes(32)
    student_keys.clear_cache()

    async with factory() as session:
        yield session

    student_keys.clear_cache()
    encryption_module._DATA_KEY = None
    await engine.dispose()


def _aad(name: str) -> bytes:
    return student_aad("session_transcripts", "transcript_enc", name)


# ── The property that makes deletion real ───────────────────────────────────

async def test_shredding_makes_already_captured_ciphertext_unopenable(db):
    """The scenario the whole mechanism exists for: an attacker (or an old
    backup, or an unvacuumed page) holds a copy of the ciphertext bytes.
    Deleting the row cannot reach those. Destroying the key can."""
    key = await student_keys.get_or_create(db, "Ellie")
    blob = encrypt_json({"messages": ["private"]}, _aad("Ellie"), key)

    # Readable while the key exists.
    assert decrypt_json(blob, _aad("Ellie"), key) == {"messages": ["private"]}

    await student_keys.destroy(db, "Ellie")
    await db.commit()

    # The captured bytes survive; the key does not. Nothing can open them —
    # not an attacker, and not this deployment either.
    assert await student_keys.get_existing(db, "Ellie") is None
    with pytest.raises(ValueError):
        decrypt_json(blob, _aad("Ellie"))


async def test_a_recreated_student_cannot_read_the_shredded_predecessors_data(db):
    """Re-adding a student with the same name must not resurrect their old
    data — a fresh key means the old ciphertext stays dead."""
    old_key = await student_keys.get_or_create(db, "Ellie")
    blob = encrypt_json({"messages": ["before"]}, _aad("Ellie"), old_key)
    await student_keys.destroy(db, "Ellie")
    await db.commit()
    student_keys.clear_cache()

    new_key = await student_keys.get_or_create(db, "Ellie")
    assert new_key != old_key
    with pytest.raises(ValueError):
        decrypt_json(blob, _aad("Ellie"), new_key)


async def test_one_students_shred_does_not_affect_another(db):
    a_key = await student_keys.get_or_create(db, "Ellie")
    b_key = await student_keys.get_or_create(db, "Sam")
    a_blob = encrypt_json({"m": "a"}, _aad("Ellie"), a_key)
    b_blob = encrypt_json({"m": "b"}, _aad("Sam"), b_key)

    await student_keys.destroy(db, "Ellie")
    await db.commit()

    with pytest.raises(ValueError):
        decrypt_json(a_blob, _aad("Ellie"))
    assert decrypt_json(b_blob, _aad("Sam"), await student_keys.get_existing(db, "Sam")) == {"m": "b"}


# ── Key isolation ───────────────────────────────────────────────────────────

async def test_one_students_key_cannot_open_anothers_data(db):
    a_key = await student_keys.get_or_create(db, "Ellie")
    b_key = await student_keys.get_or_create(db, "Sam")
    blob = encrypt_json({"m": "ellie's"}, _aad("Ellie"), a_key)
    with pytest.raises(ValueError):
        decrypt_json(blob, _aad("Ellie"), b_key)


async def test_a_wrapped_key_cannot_be_moved_between_students(db):
    """The wrapped key is itself context-bound, so someone with DB write
    access cannot swap student A's wrapped key onto student B's row to make
    A's data decrypt under B."""
    await student_keys.get_or_create(db, "Ellie")
    await student_keys.get_or_create(db, "Sam")
    student_keys.clear_cache()

    ellie = await db.get(StudentKey, "Ellie")
    sam = await db.get(StudentKey, "Sam")
    sam.wrapped_key = ellie.wrapped_key      # the swap
    await db.commit()
    student_keys.clear_cache()

    with pytest.raises(ValueError):
        await student_keys.get_existing(db, "Sam")


# ── Backward compatibility (the migration-safety property) ──────────────────

async def test_rows_written_before_per_student_keys_still_open(db):
    """v1 and v2 rows predate this mechanism and are encrypted under
    DATA_KEY. They must stay readable indefinitely, including from a call
    site that now holds a student key — otherwise enabling this feature
    would destroy every existing family's data."""
    v1 = encrypt_json({"m": "legacy unbound"})
    v2 = encrypt_json({"m": "legacy bound"}, _aad("Ellie"))
    key = await student_keys.get_or_create(db, "Ellie")

    assert decrypt_json(v1) == {"m": "legacy unbound"}
    assert decrypt_json(v2, _aad("Ellie")) == {"m": "legacy bound"}
    # A migrated read path passing a student key still opens them.
    assert decrypt_json(v1, _aad("Ellie"), key) == {"m": "legacy unbound"}
    assert decrypt_json(v2, _aad("Ellie"), key) == {"m": "legacy bound"}


async def test_v3_is_stamped_only_when_a_student_key_is_used(db):
    key = await student_keys.get_or_create(db, "Ellie")
    assert encrypt_json({"m": 1}, _aad("Ellie"))[4] == encryption_module._VERSION_AAD
    assert encrypt_json({"m": 1}, _aad("Ellie"), key)[4] == encryption_module._VERSION_STUDENT_KEY


async def test_a_student_key_write_requires_context_binding(db):
    """Per-student keys and AAD compose rather than substitute — a bug in
    key resolution must not be able to silently degrade to an unbound
    write."""
    key = await student_keys.get_or_create(db, "Ellie")
    with pytest.raises(ValueError, match="requires an aad"):
        encrypt_json({"m": 1}, None, key)


# ── Lifecycle ───────────────────────────────────────────────────────────────

async def test_get_existing_never_creates(db):
    """A read path must not write, and must never resurrect a key row for a
    student who was just shredded."""
    assert await student_keys.get_existing(db, "Nobody") is None
    assert await db.get(StudentKey, "Nobody") is None


async def test_get_or_create_is_stable_across_calls(db):
    first = await student_keys.get_or_create(db, "Ellie")
    student_keys.clear_cache()
    assert await student_keys.get_or_create(db, "Ellie") == first


async def test_destroy_reports_whether_a_key_existed(db):
    assert await student_keys.destroy(db, "Nobody") is False
    await student_keys.get_or_create(db, "Ellie")
    assert await student_keys.destroy(db, "Ellie") is True


async def test_destroy_clears_the_local_cache(db):
    await student_keys.get_or_create(db, "Ellie")
    await student_keys.destroy(db, "Ellie")
    await db.commit()
    assert student_keys._cache_get("Ellie") is None
