"""DB_POOL_SIZE and DB_MAX_OVERFLOW reach the engine the app actually uses.

core/database.py built its engine with a hard-coded pool of 5 plus 5 overflow.
Both are now settings (core/config.py), so a capacity run (docs/CAPACITY.md)
can compare a raised pool against the shipped one. The defaults must stay
exactly 5 and 5, so no deployment changes, and a setting that never reaches
the engine is worse than none, because a capacity run would then report a
"raised" pool that was never raised.

So these tests read the pool of the REAL module-level engine, built in a fresh
interpreter from the environment, exactly as `uvicorn main:app` builds it.
Checking only `settings.db_pool_size` would pass with the engine still
hard-coded, which is the defect these tests were written against (verified by
restoring the literal 5s: the environment cases fail).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.config import Settings

API_DIR = Path(__file__).resolve().parents[1]

_PROBE = (
    "import json; from core.database import engine; p = engine.sync_engine.pool; "
    "print(json.dumps({'size': p.size(), 'overflow': p._max_overflow, 'cls': type(p).__name__}))"
)


def _engine_pool(tmp_path: Path, **env: str) -> dict:
    child = {k: v for k, v in os.environ.items() if not k.startswith("DB_")}
    child.update(DATABASE_URL="sqlite+aiosqlite:///" + (tmp_path / "pool.db").as_posix(), **env)
    out = subprocess.run([sys.executable, "-c", _PROBE], cwd=API_DIR, env=child,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_defaults_are_unchanged():
    fields = Settings.model_fields
    assert fields["db_pool_size"].default == 5
    assert fields["db_max_overflow"].default == 5


def test_the_engine_gets_the_default_pool(tmp_path):
    assert _engine_pool(tmp_path) == {"size": 5, "overflow": 5, "cls": "AsyncAdaptedQueuePool"}


def test_the_engine_gets_a_configured_pool(tmp_path):
    pool = _engine_pool(tmp_path, DB_POOL_SIZE="9", DB_MAX_OVERFLOW="3")
    assert (pool["size"], pool["overflow"]) == (9, 3)


@pytest.mark.parametrize("name,value", [("db_pool_size", 0), ("db_pool_size", 101), ("db_max_overflow", -1)])
def test_out_of_range_values_are_refused(name, value):
    with pytest.raises(ValueError):
        Settings(**{name: value})
