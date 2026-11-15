"""Redaction for anything the loop publishes. The repository is public.

Reuses scripts/qa/runner.py's key=value redaction and
scripts/qualification/qualconfig.py's credential shapes rather than a third
copy of either.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO / "scripts" / "qa", _REPO / "scripts" / "qualification"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import qualconfig  # noqa: E402
from runner import sanitize as _qa_sanitize  # noqa: E402

_SHAPES = [re.compile(p) for p in qualconfig.CREDENTIAL_PATTERNS]
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_HOME = re.compile(r"/(?:Users|home)/[^/\s]+")
MAX_TEXT = 4000


def text(value: str) -> str:
    out = _qa_sanitize(str(value))
    for pat in _SHAPES:
        out = pat.sub("[REDACTED]", out)
    out = _EMAIL.sub("[EMAIL]", out)
    out = _HOME.sub("/~", out)
    return out[:MAX_TEXT]


def obj(value):
    if isinstance(value, str):
        return text(value)
    if isinstance(value, list):
        return [obj(v) for v in value]
    if isinstance(value, dict):
        return {k: obj(v) for k, v in value.items()}
    return value


def findings(blob: str) -> list[str]:
    """Credential shapes still present. Publishing refuses when non-empty."""
    return [p.pattern for p in _SHAPES if p.search(blob)]
