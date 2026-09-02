"""Structural guard for docs/DECISIONS.md, the decision register.

A register nobody checks becomes a list of things that were true once. This
repo has hit that failure repeatedly (see CLAUDE.md's "Thirty settings never
reached the container" and the DiagnosticEvidenceLog docstring that contradicted
the design doc for four phases), so the register ships with the check rather
than a promise to keep it current by hand.

What is enforced here is shape, never content. No test can know whether a
decision is correct. These tests know whether an entry is legible: numbered,
uniquely, tagged from a closed vocabulary, and carrying the obligation its own
status creates. The obligations are the point. A `deferred` entry with no
trigger is an `open` entry wearing a calmer word, and that is exactly how a
register stops being trustworthy without anyone noticing.

Note .github/workflows/test.yml's change filter names docs/DECISIONS.md
directly. Without that, a pull request touching only the register would compute
`relevant=false`, skip the api-tests job, and never run this file, which is the
same silent-no-op problem in a different place.
"""
import re
from pathlib import Path

import pytest

_REGISTER = Path(__file__).resolve().parents[2] / "docs" / "DECISIONS.md"

# Closed vocabularies. Adding to either is a deliberate act, which is the point
# of them being literals here rather than inferred from whatever the file says.
VALID_TAGS = {"COMMERCIAL", "PRODUCT", "DESIGN", "LEGAL", "RESEARCH"}
VALID_STATUSES = {"open", "deferred", "closed"}

_ENTRY = re.compile(r"^## (\d+)\. `\[([A-Z]+)\]` (.+)$", re.MULTILINE)
_STATUS = re.compile(r"^\*\*Status:\*\* (\w+)(.*)$", re.MULTILINE)


def _entries() -> list[dict]:
    """Every entry, with the body text running to the next entry heading."""
    text = _REGISTER.read_text()
    found = list(_ENTRY.finditer(text))
    out = []
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        out.append(
            {
                "number": int(m.group(1)),
                "tag": m.group(2),
                "title": m.group(3),
                "body": text[m.end() : end],
            }
        )
    return out


def test_the_register_parses_and_is_not_empty():
    """A canary for the parser. Without it, every test below would pass
    vacuously the moment the heading format changed."""
    entries = _entries()
    assert len(entries) >= 5, (
        f"Only parsed {len(entries)} entries from {_REGISTER}. Either the register "
        "was emptied or the '## N. `[TAG]` Title' heading format changed, which "
        "would make every other test in this file silently check nothing."
    )


def test_entry_numbers_are_unique():
    numbers = [e["number"] for e in _entries()]
    dupes = {n for n in numbers if numbers.count(n) > 1}
    assert not dupes, (
        f"Duplicate entry number(s) {sorted(dupes)}. Entries are referred to by "
        "number from other entries and from design docs, so a reused number "
        "silently redirects a cross-reference."
    )


def test_every_tag_is_from_the_closed_vocabulary():
    bad = {e["number"]: e["tag"] for e in _entries() if e["tag"] not in VALID_TAGS}
    assert not bad, (
        f"Unknown tag(s) {bad}. Valid tags are {sorted(VALID_TAGS)}. The tag names "
        "who resolves an entry, so an invented one points at nobody."
    )


def test_every_entry_has_exactly_one_status():
    for e in _entries():
        found = _STATUS.findall(e["body"])
        assert len(found) == 1, (
            f"Entry {e['number']} has {len(found)} '**Status:**' lines, expected 1."
        )
        assert found[0][0] in VALID_STATUSES, (
            f"Entry {e['number']} has status {found[0][0]!r}. "
            f"Valid statuses are {sorted(VALID_STATUSES)}."
        )


def test_open_entries_name_what_resolves_them():
    """`open` means due now, so it has to say who or what closes it. Without
    this an entry can sit open forever with nobody able to tell what it is
    waiting for."""
    for e in _entries():
        status, rest = _STATUS.findall(e["body"])[0]
        if status == "open":
            assert "needs:" in rest, (
                f"Entry {e['number']} is open but does not say what it needs. "
                'Use "**Status:** open · needs: <who or what resolves it>".'
            )


def test_deferred_entries_name_a_trigger():
    """The one that matters most. A deferred entry with no trigger never comes
    back, and reads as a decision when it is an omission."""
    for e in _entries():
        status, rest = _STATUS.findall(e["body"])[0]
        if status == "deferred":
            assert "until:" in rest, (
                f"Entry {e['number']} is deferred with no trigger. A deferral "
                "without an 'until:' is an open entry wearing a calmer word. "
                'Use "**Status:** deferred · until: <the condition>".'
            )


def test_closed_entries_state_what_was_decided():
    for e in _entries():
        status, _ = _STATUS.findall(e["body"])[0]
        if status == "closed":
            assert "**Decided" in e["body"], (
                f"Entry {e['number']} is closed but never states the decision. "
                'Add a "**Decided (date).**" sentence, so the register carries '
                "the outcome rather than pointing at a commit message."
            )


@pytest.mark.parametrize("status", sorted(VALID_STATUSES))
def test_the_how_to_read_table_documents_every_status(status):
    """The register explains its own vocabulary in a table at the top. If a
    status is added to the code above without being explained there, a reader
    meets a word the document never defines."""
    assert f"`{status}`" in _REGISTER.read_text(), (
        f"Status {status!r} is valid per this test file but is not documented in "
        "docs/DECISIONS.md's 'How to read an entry' table."
    )


def test_the_register_is_named_in_the_ci_change_filter():
    """Without this, a pull request touching only the register computes
    relevant=false, skips api-tests, and never runs this file. The guard would
    be real everywhere except on the changes it exists to guard.

    This checks the `grep -qE` pattern line itself, not the file as a whole.
    An earlier version asserted the filename appeared anywhere in the workflow
    and passed on the explanatory comment beside the filter, which meant it
    would have kept passing if the pattern were deleted. Verified by deleting
    it."""
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "test.yml"
    ).read_text()
    filter_lines = [
        line for line in workflow.splitlines() if "grep -qE" in line and "^(" in line
    ]
    assert filter_lines, (
        "Could not find the change-filter `grep -qE` line in "
        ".github/workflows/test.yml. If that job was restructured, this test "
        "needs updating rather than deleting."
    )
    assert any("docs/DECISIONS" in line for line in filter_lines), (
        "docs/DECISIONS.md is not in .github/workflows/test.yml's change-filter "
        "pattern, so a register-only change computes relevant=false, skips "
        "api-tests, and never runs this guard. A comment mentioning the file "
        "does not count."
    )


def test_no_entry_points_at_a_document_that_does_not_exist():
    """A register entry's value is that it reaches the reasoning. A pointer to
    a renamed or deleted document leaves an entry that still *reads* as
    sourced while being unreachable — the same shape as
    test_research_citations.py's dangling-citation guard, and as
    test_release_posture.py's phantom-workflow guard, generalised to every
    document this register names.

    Caught as a real gap: docs/LDC_DEPLOYMENT.md is referenced by three
    entries and, being outside test.yml's change filter, had nothing in CI
    reading it at all. Renaming it would have broken all three silently.
    """
    register = _REGISTER.read_text()

    # A `docs/...` path belonging to ANOTHER repository is not a dangling
    # pointer here. Entry 23 cites `agnusdei-ai/locuto`'s own
    # `docs/bede-ipc-spec.md`, which this guard flagged on its first run — a
    # false positive against a correct register, and the kind that gets a test
    # deleted. Excluded by looking at what precedes the path rather than by
    # loosening the pattern, so a genuinely missing local file cannot hide
    # behind the exemption.
    external = re.compile(r"agnusdei-ai/[a-z-]+`?'?s?\s*\n?[^\n]{0,40}$")
    referenced = sorted({
        m.group(0)
        for m in re.finditer(r"docs/[A-Za-z0-9_/-]+\.md", register)
        if not external.search(register[max(0, m.start() - 120): m.start()])
    })
    assert referenced, (
        "Parsed no document references out of the register at all. Either the "
        "convention changed or this pattern needs updating — both need a human "
        "rather than a vacuous pass."
    )
    root = _REGISTER.parent.parent
    missing = [p for p in referenced if not (root / p).exists()]
    assert not missing, (
        f"docs/DECISIONS.md points at document(s) that do not exist: {missing}. "
        "Either the file was renamed without the register following, or the "
        "entry's reasoning is now unreachable from the decision it supports."
    )
