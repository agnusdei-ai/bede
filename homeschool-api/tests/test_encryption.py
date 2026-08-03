"""
Regression tests for core/encryption.py's rotate_master_secret() — new
alongside scripts/rotate_master_secret.py. Exercises the real
initialize_encryption() / rotate_master_secret() pair against an isolated
in-memory SQLite engine per test, independent of the demo_db fixture in
conftest.py (that fixture deliberately skips the real
initialize_encryption()/encryption_config dance and just sets
core.encryption._DATA_KEY directly, which is exactly the state this file
needs to control itself to prove rotation survives a real "reboot").
"""
import core.encryption as encryption_module
import pytest
import pytest_asyncio
from core.database import Base, EncryptionConfig
from core.encryption import initialize_encryption, rotate_master_secret
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest_asyncio.fixture
async def db_session():
    """A fresh, isolated SQLite engine per test — same shape as conftest.py's
    demo_db fixture, but this file manages core.encryption's module-global
    _DATA_KEY itself instead of the fixture pre-seeding it, since these
    tests are specifically about the initialize_encryption() boot sequence
    and the encryption_config rows it reads/writes."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _reset_data_key():
    """core.encryption._DATA_KEY is a module-global — reset it around every
    test in this file so one test's boot state can't leak into the next."""
    encryption_module._DATA_KEY = None
    yield
    encryption_module._DATA_KEY = None


async def _boot(master_secret: str, db) -> None:
    await initialize_encryption(master_secret, db)


async def _get_row(db, key: str) -> bytes:
    result = await db.execute(select(EncryptionConfig).where(EncryptionConfig.key == key))
    row = result.scalar_one()
    return row.value


@pytest.mark.asyncio
async def test_rotate_master_secret_preserves_data_key_and_existing_ciphertext(db_session):
    # First boot: generates device_salt + DATA_KEY, wraps DATA_KEY under
    # the OLD secret.
    await _boot("old-master-secret-" + "a" * 32, db_session)
    original_data_key = encryption_module._DATA_KEY
    ciphertext = encryption_module.encrypt(b"a student's real data")

    # Rotate to a new secret.
    await rotate_master_secret(
        "old-master-secret-" + "a" * 32,
        "new-master-secret-" + "b" * 32,
        db_session,
    )

    # Simulate a real restart: forget the in-memory DATA_KEY entirely and
    # re-boot as if MASTER_SECRET in .env had just been updated to the new
    # value — this is the actual scenario the script exists for.
    encryption_module._DATA_KEY = None
    await _boot("new-master-secret-" + "b" * 32, db_session)

    # DATA_KEY itself must be byte-identical — rotation re-wraps, it never
    # regenerates.
    assert encryption_module._DATA_KEY == original_data_key
    # Ciphertext encrypted before rotation must still decrypt correctly
    # after the reboot on the new secret, with zero rewriting.
    assert encryption_module.decrypt(ciphertext) == b"a student's real data"


@pytest.mark.asyncio
async def test_rotate_master_secret_old_secret_no_longer_works_after_rotation(db_session):
    await _boot("old-master-secret-" + "a" * 32, db_session)
    await rotate_master_secret(
        "old-master-secret-" + "a" * 32,
        "new-master-secret-" + "b" * 32,
        db_session,
    )
    encryption_module._DATA_KEY = None

    # Booting again with the OLD secret must now fail loudly — the whole
    # point of rotation is that the leaked/old secret stops working.
    with pytest.raises(RuntimeError):
        await _boot("old-master-secret-" + "a" * 32, db_session)


@pytest.mark.asyncio
async def test_rotate_master_secret_rejects_wrong_old_secret_and_writes_nothing(db_session):
    await _boot("old-master-secret-" + "a" * 32, db_session)
    wrapped_before = await _get_row(db_session, "data_key")

    with pytest.raises(ValueError, match="[Cc]ould not unwrap"):
        await rotate_master_secret(
            "totally-wrong-secret-" + "z" * 32,
            "new-master-secret-" + "b" * 32,
            db_session,
        )

    # Nothing was written — the stored wrapper is byte-identical to before
    # the failed attempt, and the real old secret still unwraps it.
    wrapped_after = await _get_row(db_session, "data_key")
    assert wrapped_after == wrapped_before

    encryption_module._DATA_KEY = None
    await _boot("old-master-secret-" + "a" * 32, db_session)  # must not raise


@pytest.mark.asyncio
async def test_rotate_master_secret_rejects_when_nothing_has_been_encrypted_yet(db_session):
    with pytest.raises(ValueError, match="nothing to rotate"):
        await rotate_master_secret(
            "old-master-secret-" + "a" * 32,
            "new-master-secret-" + "b" * 32,
            db_session,
        )


# ── AAD context binding (v2 envelope) ───────────────────────────────────────
# See docs/DATA_CLASSIFICATION.md. The attack these close: with one global
# DATA_KEY and no associated data, a ciphertext proves only "encrypted by
# whoever holds the key" — not where it belongs — so blobs are freely
# interchangeable between rows, columns, and tables by anyone with database
# write access, decrypting cleanly with no tag failure and no signal.

@pytest.mark.asyncio
async def test_ciphertext_cannot_be_moved_between_rows_when_aad_bound(db_session):
    """The actual swap attack, as it would be performed against the DB."""
    await _boot("master-secret-" + "a" * 32, db_session)

    alice = encryption_module.encrypt_json(
        {"note": "alice's private note"},
        encryption_module.aad_for("lesson_bookmarks", "bookmark_enc", "Alice"),
    )

    # Attacker copies Alice's blob into Bob's row. Bob's read path supplies
    # Bob's context, which is not what the blob was sealed with.
    with pytest.raises(ValueError):
        encryption_module.decrypt_json(
            alice, encryption_module.aad_for("lesson_bookmarks", "bookmark_enc", "Bob")
        )

    # Sanity: it still decrypts correctly in the row it belongs to.
    assert encryption_module.decrypt_json(
        alice, encryption_module.aad_for("lesson_bookmarks", "bookmark_enc", "Alice")
    ) == {"note": "alice's private note"}


@pytest.mark.asyncio
async def test_ciphertext_cannot_be_moved_between_columns_or_tables(db_session):
    await _boot("master-secret-" + "a" * 32, db_session)
    blob = encryption_module.encrypt(
        b"x", encryption_module.aad_for("voice_profiles", "profile_enc", "Alice")
    )
    # Same row key, different column.
    with pytest.raises(ValueError):
        encryption_module.decrypt(
            blob, encryption_module.aad_for("voice_profiles", "other_enc", "Alice")
        )
    # Same column name, different table.
    with pytest.raises(ValueError):
        encryption_module.decrypt(
            blob, encryption_module.aad_for("student_configs", "profile_enc", "Alice")
        )


@pytest.mark.asyncio
async def test_v2_blob_cannot_be_read_without_its_aad(db_session):
    """The downgrade that must not be possible: omitting the argument must
    fail loudly, never silently succeed as an unauthenticated read."""
    await _boot("master-secret-" + "a" * 32, db_session)
    blob = encryption_module.encrypt(
        b"secret", encryption_module.aad_for("voice_profiles", "profile_enc", "Alice")
    )
    with pytest.raises(ValueError, match="context binding"):
        encryption_module.decrypt(blob)


@pytest.mark.asyncio
async def test_v1_blobs_written_before_the_migration_still_decrypt(db_session):
    """Migration safety: rows written before AAD existed are still live in
    deployed databases and must keep working, with or without a migrated
    read path passing an aad."""
    await _boot("master-secret-" + "a" * 32, db_session)
    legacy = encryption_module.encrypt(b"written before v2 existed")  # no aad -> v1

    assert legacy[4] == encryption_module._VERSION_LEGACY_NO_AAD
    # Unmigrated read path.
    assert encryption_module.decrypt(legacy) == b"written before v2 existed"
    # Migrated read path, against a not-yet-rewritten row: the aad is ignored
    # because a v1 blob has nothing bound in its tag to check it against.
    assert encryption_module.decrypt(
        legacy, encryption_module.aad_for("voice_profiles", "profile_enc", "Alice")
    ) == b"written before v2 existed"


@pytest.mark.asyncio
async def test_supplying_aad_writes_v2_and_omitting_it_writes_v1(db_session):
    await _boot("master-secret-" + "a" * 32, db_session)
    assert encryption_module.encrypt(b"x")[4] == encryption_module._VERSION_LEGACY_NO_AAD
    assert encryption_module.encrypt(
        b"x", encryption_module.aad_for("t", "c", "r")
    )[4] == encryption_module._VERSION_AAD


@pytest.mark.asyncio
async def test_row_key_stability_is_load_bearing_for_decryptability(db_session):
    """Documents, as an executable fact, the constraint the AAD design rests
    on: the row_key must never change for an existing row.

    docs/DATA_CLASSIFICATION.md's feasibility section verifies that no
    rename path exists today (routers/pod.py's save_pod_configs matches on
    student_name and creates a new row rather than mutating an existing
    one), so this holds by construction. But nothing in the code *says* so,
    and adding a rename later — an UPDATE on student_name — would silently
    render every AAD-bound row for that student permanently unreadable.

    This test is here so that change fails loudly in CI with a pointer to
    why, rather than surfacing as a family's data becoming undecryptable.
    A rename, if ever wanted, must be decrypt-under-old / re-encrypt-under-
    new."""
    await _boot("master-secret-" + "a" * 32, db_session)

    blob = encryption_module.encrypt_json(
        {"grade": "4"},
        encryption_module.aad_for("student_configs", "config_enc", "Ellie"),
    )
    # Renaming the row (same table, same column, new key) makes the stored
    # value unreadable — there is no way back to it without the old name.
    with pytest.raises(ValueError):
        encryption_module.decrypt_json(
            blob, encryption_module.aad_for("student_configs", "config_enc", "Eleanor")
        )
    # The correct migration for a rename: decrypt under the old key,
    # re-encrypt under the new one.
    plaintext = encryption_module.decrypt_json(
        blob, encryption_module.aad_for("student_configs", "config_enc", "Ellie")
    )
    rekeyed = encryption_module.encrypt_json(
        plaintext, encryption_module.aad_for("student_configs", "config_enc", "Eleanor")
    )
    assert encryption_module.decrypt_json(
        rekeyed, encryption_module.aad_for("student_configs", "config_enc", "Eleanor")
    ) == {"grade": "4"}


@pytest.mark.asyncio
async def test_data_key_wrapping_stays_on_the_v1_envelope(db_session):
    """T0 key material is deliberately not AAD-bound — there is exactly one
    encryption_config.data_key row, so there is no second location to swap
    it with and nothing for context binding to defend against. Asserted so
    a well-meaning "migrate everything to v2" pass doesn't touch the boot
    path for no security gain."""
    await _boot("master-secret-" + "a" * 32, db_session)
    wrapped = await _get_row(db_session, "data_key")
    assert wrapped[4] == encryption_module._VERSION_LEGACY_NO_AAD


@pytest.mark.asyncio
async def test_v2_envelope_header_is_tamper_evident(db_session):
    """v1 leaves magic+version outside the authenticated data, so flipping
    the version byte is undetectable until it fails a range check. v2 binds
    the header into the tag, making it a tag failure like any other tamper."""
    await _boot("master-secret-" + "a" * 32, db_session)
    aad = encryption_module.aad_for("voice_profiles", "profile_enc", "Alice")
    blob = bytearray(encryption_module.encrypt(b"secret", aad))
    blob[4] = encryption_module._VERSION_LEGACY_NO_AAD   # claim it's v1
    with pytest.raises(ValueError):
        encryption_module.decrypt(bytes(blob), aad)
