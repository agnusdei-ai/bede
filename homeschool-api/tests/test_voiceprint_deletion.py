"""
COPPA readiness, control C-28 (docs/COPPA_READINESS_CHECKLIST.md): a child's
voiceprint is removed by the parent's own delete actions, and nothing that
identifies the voice survives them.

What a voiceprint is here: one encrypted VoiceProfile row per student
(services/voice_auth.py), keyed to the student's own data key. Audio itself
is never written to disk: enrollment and verification audio lives in
request memory and in the in-memory streaming buffers
(services/streaming_transcription.py), and is discarded when the request or
session ends. The guards below prove that for the deletion paths, and a
static scan proves that no voice module opens a file for writing.
"""
import ast
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from core.config import settings
from core.database import Base, StudentKey, VoiceProfile
from routers.voice import remove_profile
from services import voice_auth
from services.student_deletion import delete_all_student_data

REPO = Path(__file__).resolve().parents[1]

VOICE_MODULES = [
    REPO / "routers" / "voice.py",
    REPO / "services" / "voice_auth.py",
    REPO / "services" / "streaming_transcription.py",
    REPO / "services" / "transcription.py",
]


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        from core.encryption import initialize_encryption
        await initialize_encryption(settings.master_secret, session)
        yield session
    await engine.dispose()


def _request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 1), "headers": [(b"user-agent", b"pytest")]})


async def _enrol(db, student: str) -> None:
    # The embedding shape is whatever services/voice_auth.py stores; the
    # test only needs a real encrypted row, not a meaningful voice.
    await voice_auth._save_profile(db, student, {"embedding": [0.1, 0.2, 0.3, 0.4], "version": 1})


async def _voice_rows(db) -> int:
    return (await db.execute(select(func.count()).select_from(VoiceProfile))).scalar_one()


@pytest.mark.asyncio
async def test_parent_delete_removes_the_voiceprint_row_and_its_readable_form(db_session):
    await _enrol(db_session, "Ada")
    assert await voice_auth._get_profile(db_session, "Ada") is not None

    result = await remove_profile("Ada", _request(), db_session, {"role": "parent"})
    assert result == {"deleted": "Ada"}

    assert await _voice_rows(db_session) == 0
    assert await voice_auth._get_profile(db_session, "Ada") is None


@pytest.mark.asyncio
async def test_removing_one_child_leaves_a_sibling_voiceprint_intact(db_session):
    await _enrol(db_session, "Ada")
    await _enrol(db_session, "Ben")
    await remove_profile("Ada", _request(), db_session, {"role": "parent"})

    assert await voice_auth._get_profile(db_session, "Ada") is None
    assert await voice_auth._get_profile(db_session, "Ben") is not None


@pytest.mark.asyncio
async def test_student_deletion_removes_the_voiceprint_and_shreds_its_key(db_session):
    await _enrol(db_session, "Cy")
    counts = await delete_all_student_data(db_session, "Cy")

    assert counts["voice_profile"] == 1
    assert counts["data_key_shredded"] == 1
    assert await _voice_rows(db_session) == 0
    key_rows = (await db_session.execute(
        select(func.count()).select_from(StudentKey).where(StudentKey.student_name == "Cy")
    )).scalar_one()
    assert key_rows == 0


@pytest.mark.asyncio
async def test_deleting_a_student_with_no_voiceprint_is_a_clean_no_op_for_voice(db_session):
    counts = await delete_all_student_data(db_session, "Nobody")
    assert counts["voice_profile"] == 0


@pytest.mark.asyncio
async def test_enrol_and_delete_write_no_file_to_disk(tmp_path, monkeypatch):
    """Runtime half of the no-retained-audio claim: nothing the enrolment
    save or the delete paths do leaves a file behind in the working
    directory or the temp directory."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        from core.encryption import initialize_encryption
        await initialize_encryption(settings.master_secret, session)
        await _enrol(session, "Dee")
        await remove_profile("Dee", _request(), session, {"role": "parent"})
    await engine.dispose()

    leftovers = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert leftovers == []


def _file_writing_calls(path: Path) -> list[str]:
    """Names of calls in a module that open or create files for writing."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_node = node.func
        name = func_node.attr if isinstance(func_node, ast.Attribute) else getattr(func_node, "id", "")
        if name in {"write_bytes", "write_text", "NamedTemporaryFile", "TemporaryFile", "mkstemp", "mkdtemp", "to_file"}:
            hits.append(f"{path.name}:{node.lineno}:{name}")
        if name == "open":
            mode = ""
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                mode = str(node.args[1].value)
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = str(kw.value.value)
            if any(c in mode for c in "wax+"):
                hits.append(f"{path.name}:{node.lineno}:open({mode!r})")
    return hits


@pytest.mark.parametrize("module", VOICE_MODULES, ids=lambda p: p.name)
def test_no_voice_module_opens_a_file_for_writing(module):
    """Static half: the voice modules have no code path that persists
    audio. If one is ever added, this fails and the retention and
    deletion documents (docs/RETENTION_POLICY.md) must be updated with it."""
    assert _file_writing_calls(module) == []


def test_the_static_scan_would_catch_a_file_write(tmp_path):
    """Guard on the guard: the scanner must actually see a write when one
    is present, or the test above passes for the wrong reason."""
    sample = tmp_path / "leaky.py"
    sample.write_text(
        "def keep(audio):\n"
        "    with open('/tmp/x.wav', 'wb') as fh:\n"
        "        fh.write(audio)\n"
        "    Path('y').write_bytes(audio)\n",
        encoding="utf-8",
    )
    hits = _file_writing_calls(sample)
    assert any("open('wb')" in h for h in hits)
    assert any("write_bytes" in h for h in hits)
