"""
Guards the AAD migration against silent regression.

Every encrypted column is now bound to its location (P5,
docs/DATA_CLASSIFICATION.md). The failure mode this file exists to catch is
a NEW call site — or a refactor of an existing one — quietly reverting to
the unbound v1 envelope, which would still work, still pass that feature's
own tests, and silently lose the protection.

A source-level check rather than a behavioural one, deliberately: the
property is "no production call site omits the argument", and there is no
runtime observation that distinguishes "wrote v1 on purpose" from "forgot
the argument".
"""
import ast
import pathlib

import pytest

_API_ROOT = pathlib.Path(__file__).resolve().parent.parent
_CRYPTO_FUNCS = {"encrypt", "decrypt", "encrypt_json", "decrypt_json"}

# core/encryption.py defines the primitives; scripts/rotate_master_secret.py
# and initialize_encryption deliberately use the unbound envelope for the
# T0 key-wrapping row (exactly one row, no second location to swap with —
# see docs/DATA_CLASSIFICATION.md's "Where AAD deliberately does not apply").
_EXEMPT = {"core/encryption.py"}


def _production_files():
    for sub in ("core", "services", "routers", "scripts"):
        for path in (_API_ROOT / sub).rglob("*.py"):
            rel = path.relative_to(_API_ROOT).as_posix()
            if rel not in _EXEMPT:
                yield rel, path


def _unbound_calls(path: pathlib.Path):
    """Calls to a crypto function with exactly one positional arg and no
    `aad` keyword — i.e. the context argument was omitted."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        if name not in _CRYPTO_FUNCS:
            continue
        if len(node.args) >= 2 or any(k.arg == "aad" for k in node.keywords):
            continue
        yield name, node.lineno


def test_no_production_call_site_omits_context_binding():
    offenders = [
        f"{rel}:{lineno} — {name}() called without an aad argument"
        for rel, path in _production_files()
        for name, lineno in _unbound_calls(path)
    ]
    assert not offenders, (
        "Encrypted values must be bound to their location (P5). Pass "
        "aad_for(table, column, row_key) or student_aad(...). If a call site "
        "genuinely must write the unbound v1 envelope, add it to _EXEMPT here "
        "with the reason.\n  " + "\n  ".join(offenders)
    )


def test_the_guard_itself_detects_an_unbound_call(tmp_path):
    """A guard that cannot fail is not a guard — prove it fires."""
    sample = tmp_path / "sample.py"
    sample.write_text("from core.encryption import encrypt_json\nencrypt_json({'a': 1})\n")
    assert [n for n, _ in _unbound_calls(sample)] == ["encrypt_json"]


def test_the_guard_accepts_a_correctly_bound_call(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from core.encryption import aad_for, encrypt_json\n"
        "encrypt_json({'a': 1}, aad_for('t', 'c', 'r'))\n"
    )
    assert list(_unbound_calls(sample)) == []
