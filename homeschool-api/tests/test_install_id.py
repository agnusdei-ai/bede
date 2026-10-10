"""
core/encryption.py's install_id — the optional license heartbeat's identity.

The contract (docs/PRODUCTION_SETUP.md#licensing, LICENSE_SERVER_DESIGN.md
§6.4): a random UUID generated at first boot, persisted in the
encryption_config table next to device_salt, and NEVER hardware-derived —
Docker/VM churn makes hardware fingerprinting unreliable, and a legitimate
migration to new hardware must not present as a brand-new install.
"""
import uuid as uuid_module

import pytest

from core import encryption


@pytest.fixture(autouse=True)
def _reset_install_id():
    """_INSTALL_ID is process-global (mirrors _DATA_KEY); give each test a
    clean slate and leave nothing behind for the next test file."""
    encryption._INSTALL_ID = None
    yield
    encryption._INSTALL_ID = None


@pytest.mark.asyncio
async def test_first_boot_generates_and_persists_uuid(demo_db):
    async with demo_db() as db:
        install_id = await encryption.get_or_create_install_id(db)
        assert install_id  # non-empty
        # A real UUID — and specifically v4 (random), not name/MAC-derived:
        # uuid4 is os.urandom-backed, which is the "never hardware-derived"
        # guarantee by construction.
        parsed = uuid_module.UUID(install_id)
        assert parsed.version == 4


@pytest.mark.asyncio
async def test_install_id_persists_across_sessions(demo_db):
    """The load-or-generate pattern: a second call (even against a FRESH
    session, the way a container restart re-opens the database) returns the
    SAME id rather than minting a new one."""
    async with demo_db() as db:
        first = await encryption.get_or_create_install_id(db)
    async with demo_db() as db:
        second = await encryption.get_or_create_install_id(db)
    assert first == second


@pytest.mark.asyncio
async def test_install_id_is_idempotent_within_a_session(demo_db):
    async with demo_db() as db:
        first = await encryption.get_or_create_install_id(db)
        again = await encryption.get_or_create_install_id(db)
        assert first == again
        # Exactly one row — a repeat call never writes a second one.
        from sqlalchemy import select

        from core.database import EncryptionConfig
        rows = (await db.execute(
            select(EncryptionConfig).where(EncryptionConfig.key == "install_id")
        )).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_install_id_survives_process_restart_shape(demo_db):
    """A 'restart' (module cache cleared, DB retained) reads the persisted
    row back instead of generating a new identity — this is what makes the
    server-side (license_key, install_id) activation binding stable."""
    async with demo_db() as db:
        original = await encryption.get_or_create_install_id(db)
    encryption._INSTALL_ID = None  # simulate a fresh process
    async with demo_db() as db:
        reloaded = await encryption.get_or_create_install_id(db)
    assert reloaded == original


@pytest.mark.asyncio
async def test_distinct_installs_get_distinct_ids():
    """Two never-before-seen databases must not collide: the id comes from
    the RNG, not from anything the two installs share (hardware, MAC...)."""
    engines_ids = []
    for _ in range(2):
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            from core.database import Base
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        encryption._INSTALL_ID = None
        async with session_factory() as db:
            engines_ids.append(await encryption.get_or_create_install_id(db))
        await engine.dispose()
    assert engines_ids[0] != engines_ids[1]
