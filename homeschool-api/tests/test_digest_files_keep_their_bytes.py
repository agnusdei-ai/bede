"""Files whose SHA-256 is checked at runtime must be checked out byte for byte.

On Windows, git's core.autocrlf rewrites LF to CRLF on checkout. For the
constitution that changes the digest core/constitution.py pins, and Bede
refuses to start; for the consent and school-data notices it changes the
hash recorded as the parent's or school's acknowledgement. The first real
windows-2022 run of the cross-platform journeys failed exactly this way.
.gitattributes marks these files -text; this test fails if one loses it.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

DIGEST_FILES = [
    "homeschool-api/constitution/bede.constitution.json",
    "homeschool-api/data/consent_notice.txt",
    "homeschool-api/data/school_data_notice.txt",
]


@pytest.mark.parametrize("rel", DIGEST_FILES)
def test_git_never_rewrites_line_endings(rel):
    assert (ROOT / rel).is_file(), rel
    out = subprocess.run(
        ["git", "check-attr", "text", "--", rel],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert out.endswith(": text: unset"), out


@pytest.mark.parametrize("rel", DIGEST_FILES)
def test_committed_bytes_have_no_carriage_returns(rel):
    """The pinned digests are of LF files; a CRLF copy committed by mistake
    would be just as broken as one converted on checkout."""
    assert b"\r" not in (ROOT / rel).read_bytes(), rel
