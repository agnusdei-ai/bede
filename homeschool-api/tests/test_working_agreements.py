"""docs/WORKING_AGREEMENTS.md is the short form of CLAUDE.md's standing
workflows -- the same facts, extracted so they can be re-read before starting
work rather than looked up afterwards.

A summary of a living document is exactly the thing that goes stale silently:
nothing errors, nothing fails to build, it simply describes a repository that
has moved on. That is the failure mode CLAUDE.md's own "Carry Out the
Decision" rule names, and the remedy it prescribes is this -- where the same
fact lives twice, add the assertion that fails when they drift.

This guard checks REPRESENTATION, never wording. No test can know whether a
summary is a good one.
"""

from pathlib import Path
import re

import pytest

REPO = Path(__file__).resolve().parents[2]
CLAUDE_MD = REPO / "CLAUDE.md"
AGREEMENTS = REPO / "docs/WORKING_AGREEMENTS.md"
TEST_WORKFLOW = REPO / ".github/workflows/test.yml"

HEADING = re.compile(r"^## (Standing Workflow: .+)$", re.M)


def _standing_workflows() -> list[str]:
    return HEADING.findall(CLAUDE_MD.read_text(encoding="utf-8"))


def test_the_extraction_exists():
    assert AGREEMENTS.is_file(), (
        "docs/WORKING_AGREEMENTS.md is gone. If it was deliberately retired, "
        "delete this guard in the same change rather than leaving it pointing "
        "at nothing."
    )


def test_claude_md_still_declares_standing_workflows():
    """If this ever returns nothing, the heading convention changed and every
    assertion below would pass vacuously."""
    assert _standing_workflows(), (
        "No '## Standing Workflow:' headings found in CLAUDE.md. The convention "
        "changed, and this guard must be updated with it -- as written it would "
        "now pass no matter what docs/WORKING_AGREEMENTS.md says."
    )


@pytest.mark.parametrize("heading", _standing_workflows())
def test_every_standing_workflow_is_represented(heading):
    text = AGREEMENTS.read_text(encoding="utf-8")
    assert heading in text, (
        f"CLAUDE.md declares {heading!r}, and docs/WORKING_AGREEMENTS.md never "
        f"cites it. Either add a section for it (each one names its source "
        f"heading verbatim) or, if it genuinely does not belong in the short "
        f"form, say so there explicitly."
    )


def test_it_defers_to_claude_md():
    """The summary must never read as the authority. Two documents stating the
    same rule will eventually disagree, and the reader needs to know which one
    loses."""
    text = AGREEMENTS.read_text(encoding="utf-8").lower()
    assert "claude.md" in text and "wins" in text, (
        "docs/WORKING_AGREEMENTS.md no longer states that CLAUDE.md is "
        "authoritative when the two disagree."
    )


def test_it_does_not_quietly_become_the_place_faith_gets_measured():
    """The standing refusal, asserted here too because a condensed restatement
    is exactly where a rule gets softened into a suggestion."""
    text = AGREEMENTS.read_text(encoding="utf-8").lower()
    assert "never measure, score, or quantify a child's spiritual engagement" in text, (
        "The never-measure-faith refusal is missing from the extraction. It is "
        "the one rule in CLAUDE.md that a future change is most likely to reach "
        "for, and a summary that drops it reads as permission."
    )


def test_both_files_are_in_the_ci_change_filter():
    """Without BOTH, the guard never runs for the change it exists to catch:
    test.yml computes relevant=false for a docs-only or CLAUDE.md-only edit and
    skips api-tests entirely. Reads the pattern line itself rather than the
    whole file, since the filename appearing in a nearby comment is a vacuous
    pass -- the same trap test_decision_register.py records falling into."""
    pattern_line = next(
        (l for l in TEST_WORKFLOW.read_text(encoding="utf-8").splitlines()
         if "grep -qE" in l),
        None,
    )
    assert pattern_line is not None, "Could not find test.yml's grep -qE change filter."
    for path in (r"CLAUDE\.md", r"docs/WORKING_AGREEMENTS\.md"):
        assert path in pattern_line, (
            f"{path} is missing from test.yml's change filter, so a PR editing "
            f"only it skips api-tests and never runs this file."
        )
