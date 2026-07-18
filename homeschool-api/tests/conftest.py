"""
Shared pytest fixtures. Sets required env vars before any app module is
imported — core.config.Settings() builds eagerly at import time (module
level `settings = Settings()`), so this has to happen in conftest.py rather
than inside individual test functions.
"""
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key-" + "x" * 32)
os.environ.setdefault("MASTER_SECRET", "test-master-secret-" + "y" * 32)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/testdb")
os.environ.setdefault("DEMO_PIN", "384756")

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest.fixture(autouse=True)
def _clear_readonly_prompt_caches():
    """services/ai_service.py caches _load_mastery_vector_readonly and
    _load_processing_style_readonly per student_name for several minutes
    (a real perf fix — see _READONLY_PROMPT_CACHE_TTL_SECONDS' comment).
    That cache is module-global, so without resetting it here, one test's
    result for a given student_name could silently leak into a later test
    reusing the same name (several test files use "Sam"). Autouse so no
    test file needs to remember to ask for this."""
    import services.ai_service as ai_service_module
    ai_service_module._mastery_vector_cache.clear()
    ai_service_module._processing_style_cache.clear()
    yield
    ai_service_module._mastery_vector_cache.clear()
    ai_service_module._processing_style_cache.clear()


@pytest_asyncio.fixture
async def demo_db(monkeypatch):
    """
    Backs core/demo_code_session.py and core/diagnostic_preview_quota.py
    (and anything else following core/audit.py's self-contained-session
    convention) with a fresh, isolated SQLite engine for the duration of
    one test. Both modules re-import AsyncSessionLocal from core.database
    inside every function call, so patching the module attributes here is
    picked up immediately — no call site elsewhere needs to change.

    Without this, those modules' real target (core.database.engine, built
    from DATABASE_URL at import time) is the fake Postgres URL set above,
    which just fails to connect — the same "swallow it" fire-and-forget
    shape core/audit.py's log_event() intentionally has is NOT what these
    two modules do (a demo code that never actually gets stored would
    silently break the whole public demo), so tests that reach them need a
    real, working database to talk to.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        from core.database import Base
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    import core.database as database_module
    monkeypatch.setattr(database_module, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(database_module, "engine", engine)

    # core.demo_code_session/core.diagnostic_preview_quota encrypt/decrypt
    # via core.encryption's process-global _DATA_KEY, independent of which
    # engine holds the resulting ciphertext — it doesn't need to be
    # "registered" via the real initialize_encryption()/encryption_config
    # dance (that's production durability logic, irrelevant to a throwaway
    # in-memory engine). Only set it if nothing else in this test already
    # has (e.g. a test file's own `db_session` fixture calling the real
    # initialize_encryption) — never overwrite an already-initialized key,
    # since that would leave THAT fixture's already-encrypted rows
    # undecryptable for the rest of the test.
    import core.encryption as encryption_module
    if encryption_module._DATA_KEY is None:
        from Crypto.Random import get_random_bytes
        encryption_module._DATA_KEY = get_random_bytes(32)

    yield session_factory

    await engine.dispose()
