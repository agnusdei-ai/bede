"""
Regression test for core/database.py's connection-string normalization.

Managed providers (Render, Railway, Heroku-style) commonly hand out a plain
postgres:// or postgresql:// URL, but SQLAlchemy's async engine needs the
+asyncpg driver suffix explicit in the scheme or it tries to load psycopg2
instead and fails. This is exactly the kind of silent first-deploy footgun
that's easy to reintroduce accidentally in a future refactor, so it's
pinned down here rather than only being a comment in the code.
"""
import pytest

from core.database import normalize_database_url


@pytest.mark.parametrize("raw,expected", [
    ("postgres://user:pass@host/db", "postgresql+asyncpg://user:pass@host/db"),
    ("postgresql://user:pass@host/db", "postgresql+asyncpg://user:pass@host/db"),
    (
        "postgresql+asyncpg://user:pass@host/db?ssl=require",
        "postgresql+asyncpg://user:pass@host/db?ssl=require",
    ),
    (
        "postgresql+asyncpg://sage:abc123@db:5432/bede",
        "postgresql+asyncpg://sage:abc123@db:5432/bede",
    ),
])
def test_normalize_database_url(raw, expected):
    assert normalize_database_url(raw) == expected
