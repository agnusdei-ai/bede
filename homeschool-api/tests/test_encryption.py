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
