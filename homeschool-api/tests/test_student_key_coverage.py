"""
Structural guard: every student-scoped encrypt/decrypt passes a student key.

The failure this exists to catch is silent in both directions, which is why
it needs a test that reads the source rather than exercises behaviour:

  * A WRITE that builds `student_aad(...)` but forgets the key argument
    stamps a v2 envelope under the global DATA_KEY. Nothing raises. The row
    reads back fine forever. It is simply not crypto-shreddable any more —
    deleting the student destroys their key and this row still opens. The
    erasure guarantee in core/student_keys.py degrades and no test fails.

  * A READ that forgets the key raises, but only on rows written after the
    call site was migrated — so it survives any test suite whose fixtures
    seed rows directly with encrypt_json().

So the invariant is checked where it actually lives: in the shape of the
call. If a call's aad argument is student-scoped — `student_aad(...)`, or a
module-local helper that wraps it — the call must also pass a key. Anything
scoped to something other than a student (audit, demo sessions, parent MFA)
keys its AAD on a code, token, or fixed label instead, and is deliberately
not covered here.
"""
import ast
import pathlib

import pytest

_API_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SCANNED_DIRS = ("core", "services", "routers", "scripts")
_CRYPTO_FUNCS = {"encrypt", "decrypt", "encrypt_json", "decrypt_json"}


# core/student_keys.py is the one legitimate exception, and it has to be: it
# wraps a student's key under DATA_KEY. A key cannot be encrypted under
# itself, so the wrap is student-scoped (it binds the student's name as AAD)
# yet correctly takes no student key. Excluding the module rather than the
# individual lines — everything in it is the mechanism, not a consumer.
_EXEMPT = {"core/student_keys.py"}


def _production_sources() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for d in _SCANNED_DIRS:
        files.extend(sorted((_API_ROOT / d).rglob("*.py")))
    return [f for f in files if str(f.relative_to(_API_ROOT)) not in _EXEMPT]


def _student_aad_helpers(tree: ast.Module) -> set[str]:
    """Names of module-local helpers that build a student-scoped AAD.

    Several call sites don't inline `student_aad(...)` — they go through a
    small wrapper (`_profile_aad(student_name)`, `_config_aad(...)`) that
    calls `aad_for(table, column, student_name)` instead. Those are just as
    student-scoped, so the scan has to follow them or it silently skips
    routers/pod.py, routers/narration.py, routers/transcripts.py and
    services/voice_auth.py entirely.

    The signal is deliberately narrow: a function taking `student_name` that
    returns an AAD. That excludes the genuinely non-student helpers —
    `_totp_aad()` (parent MFA), and the inline `aad_for(..., code)` /
    `aad_for(..., token)` uses in demo-session and interaction-signal code,
    which are correctly keyed on something other than a student.
    """
    helpers = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = {a.arg for a in node.args.args}
        if "student_name" not in params:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id in {"aad_for", "student_aad"}:
                helpers.add(node.name)
                break
    return helpers


def _uses_student_aad(node: ast.AST, helpers: set[str]) -> bool:
    """True if this expression is (or contains) a student-scoped AAD call."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
            if sub.func.id == "student_aad" or sub.func.id in helpers:
                return True
    return False


def _crypto_calls_with_student_aad():
    """Yields (path, lineno, call) for every encrypt*/decrypt* whose aad
    argument is student-scoped."""
    for path in _production_sources():
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError as exc:  # pragma: no cover - would fail the suite anyway
            pytest.fail(f"{path} does not parse: {exc}")
        helpers = _student_aad_helpers(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name not in _CRYPTO_FUNCS:
                continue
            # The aad is the second positional argument, or aad= by keyword.
            aad_arg = node.args[1] if len(node.args) >= 2 else next(
                (kw.value for kw in node.keywords if kw.arg == "aad"), None
            )
            if aad_arg is None or not _uses_student_aad(aad_arg, helpers):
                continue
            yield path.relative_to(_API_ROOT), node.lineno, node


def test_every_student_scoped_crypto_call_passes_a_student_key():
    missing = []
    for rel, lineno, node in _crypto_calls_with_student_aad():
        has_key = len(node.args) >= 3 or any(kw.arg == "key" for kw in node.keywords)
        if not has_key:
            missing.append(f"{rel}:{lineno}")
    assert not missing, (
        "These calls bind a student AAD but pass no per-student key, so they "
        "write/read v2 under the global DATA_KEY and are not crypto-shreddable:\n  "
        + "\n  ".join(missing)
    )


def test_the_guard_actually_finds_the_call_sites():
    """A scanner that silently matches nothing would pass the test above
    forever. Pin a floor so an import rename or a refactor that moves these
    calls out of reach fails here instead of going unnoticed."""
    found = list(_crypto_calls_with_student_aad())
    assert len(found) >= 30, f"expected the student-scoped call sites to be found, got {len(found)}"
