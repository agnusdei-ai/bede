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
