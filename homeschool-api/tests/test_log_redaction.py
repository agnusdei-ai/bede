"""
COPPA readiness C-15 / C-16: application logs must not carry a child's
first name, or child-supplied text, in any record.

Three layers, each verified by breaking it:

1. core/log_redaction.py's helpers behave as documented (stable keyed
   pseudonym, scrubbing of exception text, a summary with no message body).
2. A static scan of every production log call: a student identifier passed
   raw, a bare exception object, or exc_info=True alongside one is refused.
   This is the invocation guard. A helper nothing calls protects nothing.
3. A caplog run over representative child-facing code paths, asserting no
   fixture name or child-message fragment appears in any formatted record,
   including tracebacks.
"""
import ast
import logging
import pathlib

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core import log_redaction
from core.config import settings
from core.database import Base

FIXTURE_NAME = "Marisol"
CHILD_FRAGMENT = "my cat Biscuit hid under the porch"
ROOT = pathlib.Path(__file__).resolve().parents[1]


# ── 1. Helper behaviour ─────────────────────────────────────────────────────


def test_learner_ref_is_stable_and_does_not_contain_the_name():
    ref = log_redaction.learner_ref(FIXTURE_NAME)
    assert ref == log_redaction.learner_ref(FIXTURE_NAME)
    assert FIXTURE_NAME.lower() not in ref.lower()
    assert ref.startswith("learner:")


def test_learner_ref_differs_between_learners():
    assert log_redaction.learner_ref("Marisol") != log_redaction.learner_ref("Tomas")


def test_learner_ref_depends_on_the_deployment_secret(monkeypatch):
    before = log_redaction.learner_ref(FIXTURE_NAME)
    monkeypatch.setattr(settings, "secret_key", settings.secret_key + "-rotated")
    assert log_redaction.learner_ref(FIXTURE_NAME) != before


def test_learner_ref_handles_missing_name():
    assert log_redaction.learner_ref(None) == "learner:none"
    assert log_redaction.learner_ref("") == "learner:none"


def test_scrub_replaces_the_name_case_insensitively():
    text = f"lookup failed for {FIXTURE_NAME.upper()} and {FIXTURE_NAME}"
    scrubbed = log_redaction.scrub(text, [FIXTURE_NAME])
    assert FIXTURE_NAME.lower() not in scrubbed.lower()
    assert log_redaction.learner_ref(FIXTURE_NAME) in scrubbed


def test_scrub_ignores_empty_and_one_character_secrets():
    # A one-letter "name" would otherwise mangle every log line it appears in.
    assert log_redaction.scrub("a plain line", [None, "", "a"]) == "a plain line"


def test_exc_text_scrubs_a_name_carried_in_the_exception_message():
    exc = RuntimeError(f"SELECT ... WHERE student_name = '{FIXTURE_NAME}'")
    text = log_redaction.exc_text(exc, FIXTURE_NAME)
    assert FIXTURE_NAME not in text
    assert text.startswith("RuntimeError: ")


def test_exc_summary_carries_type_and_location_never_the_message():
    try:
        raise ValueError(f"model echoed child text: {CHILD_FRAGMENT}")
    except ValueError as exc:
        summary = log_redaction.exc_summary(exc)
    assert summary.startswith("ValueError")
    assert "test_log_redaction.py" in summary
    assert CHILD_FRAGMENT not in summary


# ── 2. Static guard over every production log call ──────────────────────────

_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
_LOG_OBJECTS = {"log", "logger", "_log", "LOG"}
_RAW_IDENTIFIERS = {"student_name", "child_message", "student"}


def _is_raw_student_expr(node: ast.AST) -> bool:
    """True for a bare `student_name`, `x.student_name` (e.g. config.student_name,
    req.session_config.student_name) or `child_message`, un-wrapped."""
    if isinstance(node, ast.Name):
        return node.id in _RAW_IDENTIFIERS
    if isinstance(node, ast.Attribute):
        return node.attr in _RAW_IDENTIFIERS
    return False


def _is_bare_exception(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "exc"


def _label(path: pathlib.Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return path.name


def _student_log_violations(path: pathlib.Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    problems = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _LOG_METHODS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in _LOG_OBJECTS
        ):
            continue
        args = list(node.args) + [kw.value for kw in node.keywords]
        touches_learner = any(
            _is_raw_student_expr(sub)
            for arg in args
            for sub in ast.walk(arg)
        )
        if not touches_learner:
            continue
        where = f"{_label(path)}:{node.lineno}"
        for arg in node.args:
            if _is_raw_student_expr(arg):
                problems.append(f"{where}: raw learner identifier passed to a log call")
            if _is_bare_exception(arg):
                problems.append(f"{where}: bare exception object (use exc_text/exc_summary)")
        for kw in node.keywords:
            if kw.arg == "exc_info":
                problems.append(f"{where}: exc_info alongside a learner identifier (traceback text)")
    return problems


def test_no_application_log_call_passes_a_raw_learner_identifier():
    problems = []
    for path in sorted(ROOT.rglob("*.py")):
        if {"tests", "venv", ".venv", "__pycache__"} & set(path.parts):
            continue
        problems.extend(_student_log_violations(path))
    assert problems == [], "\n".join(problems)


def test_the_static_guard_itself_catches_a_raw_name(tmp_path):
    """The guard must be able to fail. A deliberately bad snippet is refused."""
    bad = tmp_path / "bad.py"
    bad.write_text(
        "import logging\nlog = logging.getLogger(__name__)\n"
        "def f(config, exc):\n"
        "    log.warning('failed for %s: %s', config.student_name, exc)\n"
        "    log.warning('x %s', student_name, exc_info=True)\n"
    )
    problems = _student_log_violations(bad)
    assert any("raw learner identifier" in p for p in problems)
    assert any("bare exception" in p for p in problems)
    assert any("exc_info" in p for p in problems)


# ── 3. caplog over representative child-facing paths ───────────────────────


class _ExplodingDB:
    """Stands in for a database session whose query fails with text that
    carries the child's name, as a real driver error can (SQL parameters)."""

    async def execute(self, *_args, **_kwargs):
        raise RuntimeError(f"(sqlite3) no such row: student_name={FIXTURE_NAME!r}")


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    from core.encryption import initialize_encryption
    async with factory() as session:
        await initialize_encryption(settings.master_secret, session)
    yield factory
    await engine.dispose()


def _formatted_records(caplog) -> list[str]:
    formatter = logging.Formatter("%(levelname)s %(name)s %(message)s")
    return [formatter.format(r) for r in caplog.records]


@pytest.mark.asyncio
async def test_representative_child_paths_log_no_name_or_child_text(caplog, session_factory):
    from services.diagnostic import get_mastery_summary
    from services.student_deletion import delete_all_student_data
    from core.config import settings as cfg

    # Production level (main.py's basicConfig is INFO). At DEBUG, aiosqlite
    # echoes every statement with its bound parameters, which include the
    # learner's name; test_production_logging_level_stays_info pins that the
    # production level never drops to DEBUG.
    caplog.set_level(logging.INFO)

    # Path A: a diagnostic read whose driver error carries the child's name.
    result = await get_mastery_summary(_ExplodingDB(), FIXTURE_NAME, "mathematics")
    assert result is None

    # Path B: deleting a child's data, which logs the outcome by learner.
    async with session_factory() as db:
        await delete_all_student_data(db, FIXTURE_NAME)

    # Path C: a tutor-side failure whose exception text includes the child's
    # message. The child-facing path logs exc_summary, which omits the message.
    from core.log_redaction import exc_summary
    try:
        raise ValueError(f"model choked on: {CHILD_FRAGMENT} ({FIXTURE_NAME})")
    except ValueError as exc:
        logging.getLogger("routers.tutor").error(
            "Tutor stream failed mid-turn for %s: %s",
            log_redaction.learner_ref(FIXTURE_NAME),
            exc_summary(exc),
            exc_info=False,
        )

    records = _formatted_records(caplog)
    assert records, "the representative paths should have logged something"
    for text in records:
        assert FIXTURE_NAME not in text, text
        assert CHILD_FRAGMENT not in text, text
    assert cfg.secret_key  # settings intact after the run


def test_production_logging_level_stays_info():
    """Library DEBUG output (aiosqlite statement echo) carries bound SQL
    parameters, including learner names. The production level must stay INFO."""
    main_src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "level=logging.INFO," in main_src
    assert "level=logging.DEBUG" not in main_src


def test_breaking_the_scrub_would_be_caught(monkeypatch):
    """Verification of the guard itself: with scrubbing turned off, the
    exception helper leaks the name, so the caplog assertion above would
    fail. Confirmed here directly so the failure mode stays visible."""
    monkeypatch.setattr(log_redaction, "scrub", lambda text, secrets: text)
    text = log_redaction.exc_text(RuntimeError(f"row {FIXTURE_NAME}"), FIXTURE_NAME)
    assert FIXTURE_NAME in text
