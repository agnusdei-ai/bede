"""Structural guard for docs/PRICING_RESEARCH.md, the pricing evidence base.

A research document degrades in a specific, quiet way: a citation loses its
reference, a reference loses its DOI, a claim outlives the study it rested on,
or a corpus table stops matching the reference list. Nothing errors. The
document keeps reading like evidence while having stopped being checkable,
which is worse than having no document, because the next person trusts it.

This repo has hit exactly that failure in the neighbouring case — a compliance
policy that enumerated "exactly four demo-related tables" and omitted the
fifth, caught only when tests/test_coppa_compliance.py was finally written. The
same reasoning applies here: a decision register that cites research is only as
good as the research staying citable.

What is enforced is shape and internal agreement, never whether a finding is
correct or a study is good. No test can rule on that. These tests know whether
a claim is *traceable*: every inline citation reaches a reference, every
reference carries a resolvable DOI, every corpus row matches, and the register
entry that depends on the document actually points at it.

Note .github/workflows/test.yml's change filter names docs/PRICING_RESEARCH.md
directly, for the same reason it names docs/DECISIONS.md. Without it, a pull
request touching only the research document computes `relevant=false`, skips
api-tests, and never runs this file.
"""
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_RESEARCH = _ROOT / "docs" / "PRICING_RESEARCH.md"
_REGISTER = _ROOT / "docs" / "DECISIONS.md"

# Closed vocabulary, deliberately a literal rather than inferred from the file.
# The whole point of section 2's table is that an analytical result and a
# meta-analysis do not carry the same weight; a free-text class column would
# let a new one appear without anyone deciding it should exist.
VALID_EVIDENCE_CLASSES = {
    "Analytical",
    "Computational",
    "Empirical",
    "Meta-analytic",
}

# "Surname, A. B., & Other, C. (2010). Title..." — the leading surname and the
# year are the two fields an inline citation has to match.
_REFERENCE = re.compile(r"^([A-Z][A-Za-zÀ-ÿ'’-]+),.*?\((\d{4})\)\.", re.MULTILINE)

# Narrative "Wu et al. (2008)" and parenthetical "(Wu et al., 2008)" alike.
_INLINE = re.compile(
    r"\b([A-Z][A-Za-zÀ-ÿ'’-]+)"
    r"(?:\s+et\s+al\.|\s+&\s+[A-Z][A-Za-zÀ-ÿ'’-]+)?"
    r"[,]?\s*\((\d{4})\)"
    r"|\(([A-Z][A-Za-zÀ-ÿ'’-]+)"
    r"(?:\s+et\s+al\.|\s+&\s+[A-Z][A-Za-zÀ-ÿ'’-]+)?"
    r",\s*(\d{4})\)"
)

# Surnames that legitimately appear in an author-year shape without being a
# citation of this document's own corpus. Kept explicit so a genuine missing
# reference cannot hide behind a broad regex exclusion.
_NOT_CITATIONS = {("Bakos", "1999b")}


def _split() -> tuple[str, str]:
    """(body, references) — everything before the reference list, and it."""
    text = _RESEARCH.read_text()
    marker = "\n## References\n"
    assert marker in text, (
        f"{_RESEARCH} has no '## References' section. Either it was renamed or "
        "removed; this test needs updating rather than deleting."
    )
    head, _, tail = text.partition(marker)
    return head, tail


def _references() -> dict[tuple[str, str], str]:
    """{(surname, year): full entry text}."""
    _, refs = _split()
    out = {}
    for m in _REFERENCE.finditer(refs):
        end = refs.find("\n\n", m.end())
        out[(m.group(1), m.group(2))] = refs[m.start() : end if end != -1 else None]
    return out


def _inline_citations() -> set[tuple[str, str]]:
    body, _ = _split()
    found = set()
    for m in _INLINE.finditer(body):
        surname = m.group(1) or m.group(3)
        year = m.group(2) or m.group(4)
        found.add((surname, year))
    return found - _NOT_CITATIONS


def test_the_document_parses_and_has_a_real_corpus():
    """A canary. Without it every test below passes vacuously the moment the
    reference format changes — the exact vacuous-pass failure this repo has
    shipped twice (see CLAUDE.md's notes on the indentation-sensitive palette
    parser and the `"site/_headers" in body` header check)."""
    refs = _references()
    assert len(refs) >= 8, (
        f"Only parsed {len(refs)} references from {_RESEARCH}. Either the "
        "reference format changed or the corpus was gutted; both need a human."
    )
    assert _inline_citations(), (
        "Parsed no inline citations at all. The document cannot be making "
        "sourced claims, or the citation format changed."
    )


def test_every_inline_citation_has_a_reference():
    """The failure this exists for: a claim whose study was renamed, reworded,
    or dropped from the reference list, leaving prose that still reads as
    sourced. That is how a research document becomes folklore."""
    missing = sorted(_inline_citations() - set(_references()))
    assert not missing, (
        f"Inline citations in {_RESEARCH} with no matching reference: "
        f"{missing}. Every claim must reach a reference, or it is not sourced."
    )


def test_every_reference_is_actually_used():
    """The mirror failure: a reference list padded with studies the document
    never draws on, which inflates apparent rigour. A reference either supports
    a claim in the body or appears in section 2's corpus table with a stated
    reason for being listed unused."""
    body, _ = _split()
    cited = _inline_citations()
    unused = [
        ref for ref in _references() if ref not in cited and ref[0] not in body
    ]
    assert not unused, (
        f"References in {_RESEARCH} that appear nowhere in the body: {unused}. "
        "Either draw on it or remove it; an unused reference is decoration."
    )


def test_every_reference_carries_a_resolvable_doi():
    """A citation without a DOI cannot be checked by the person reading it,
    which defeats the purpose of writing the evidence down at all."""
    for (surname, year), entry in _references().items():
        assert "https://doi.org/10." in entry, (
            f"Reference {surname} ({year}) in {_RESEARCH} has no "
            "https://doi.org/ link. Every reference must be resolvable."
        )


def test_no_reference_is_listed_twice():
    """Two entries for one study means the corpus count overstates the
    evidence base, which is the number a reader anchors on."""
    _, refs = _split()
    dois = re.findall(r"https://doi\.org/(\S+)", refs)
    duplicates = {d for d in dois if dois.count(d) > 1}
    assert not duplicates, (
        f"Duplicate DOIs in {_RESEARCH}'s reference list: {sorted(duplicates)}."
    )


def test_the_corpus_table_matches_the_reference_list():
    """Section 2's table states each study's evidence class and citation
    weight. If it drifts from the reference list, a reader weighing the
    evidence is weighing a study that is not there — the same two-copies-of-one
    -fact failure CLAUDE.md's standing workflow exists to prevent."""
    body, _ = _split()
    table = [
        line for line in body.splitlines()
        if line.startswith("| ") and re.match(r"\| [A-Z][A-Za-zÀ-ÿ'’-]+ .*\(\d{4}\)", line)
    ]
    assert len(table) >= 8, (
        f"Parsed only {len(table)} rows from the corpus table in {_RESEARCH}. "
        "The table format likely changed; update this test rather than dropping it."
    )
    in_table = set()
    for line in table:
        m = re.match(r"\| ([A-Z][A-Za-zÀ-ÿ'’-]+)[^|]*?\((\d{4})\)", line)
        assert m, f"Could not parse a study from corpus row: {line!r}"
        in_table.add((m.group(1), m.group(2)))
    refs = set(_references())
    assert in_table == refs, (
        "The corpus table and the reference list disagree in "
        f"{_RESEARCH}.\n  In table only: {sorted(in_table - refs)}\n"
        f"  In references only: {sorted(refs - in_table)}"
    )


def test_every_corpus_row_states_a_known_evidence_class():
    """An analytical model and a meta-analysis do not carry the same weight,
    and the document's own section 1 turns on that distinction. A free-text
    class column would let the distinction quietly dissolve."""
    body, _ = _split()
    rows = [
        line for line in body.splitlines()
        if line.startswith("| ") and re.match(r"\| [A-Z][A-Za-zÀ-ÿ'’-]+ .*\(\d{4}\)", line)
    ]
    for line in rows:
        cells = [c.strip().strip("*") for c in line.split("|")]
        assert len(cells) > 2, f"Corpus row has too few columns: {line!r}"
        assert cells[2] in VALID_EVIDENCE_CLASSES, (
            f"Corpus row {cells[1]!r} states evidence class {cells[2]!r}, which "
            f"is not one of {sorted(VALID_EVIDENCE_CLASSES)}. Adding a class is "
            "a deliberate act; edit this test's vocabulary if that is intended."
        )


def test_the_document_reports_the_editorial_notice_check():
    """Scite exposes retractions, corrections and expressions of concern. A
    document that cites without saying whether it looked has not looked, as far
    as any later reader can tell. Reporting a negative result is the point."""
    body, _ = _split()
    assert re.search(r"[Ee]ditorial notices? (were|was) checked", body), (
        f"{_RESEARCH} does not state that editorial notices (retractions, "
        "corrections, expressions of concern) were checked. The check must be "
        "reported whether or not it found anything."
    )


def test_the_register_entry_points_at_the_research_document():
    """The register carries state and the research document carries the
    argument. That split only works if the entry actually links across; a
    dangling pointer means the reasoning is unreachable from the decision."""
    register = _REGISTER.read_text()
    assert "PRICING_RESEARCH.md" in register, (
        "No entry in docs/DECISIONS.md references docs/PRICING_RESEARCH.md. "
        "Either the pointer was dropped or the research document is orphaned."
    )
    assert _RESEARCH.exists(), f"{_RESEARCH} does not exist."


def test_the_research_document_is_named_in_the_ci_change_filter():
    """Without this, a pull request touching only the research document
    computes relevant=false, skips api-tests, and never runs this guard — real
    everywhere except on the changes it exists to guard. Checks the `grep -qE`
    pattern line itself, not the file as a whole, because an earlier version of
    the sibling test in test_decision_register.py passed on a comment beside
    the filter. Verified by deleting the pattern."""
    workflow = (_ROOT / ".github" / "workflows" / "test.yml").read_text()
    filter_lines = [
        line for line in workflow.splitlines() if "grep -qE" in line and "^(" in line
    ]
    assert filter_lines, (
        "Could not find the change-filter `grep -qE` line in "
        ".github/workflows/test.yml. If that job was restructured, this test "
        "needs updating rather than deleting."
    )
    assert any("docs/PRICING_RESEARCH" in line for line in filter_lines), (
        "docs/PRICING_RESEARCH.md is not in .github/workflows/test.yml's "
        "change-filter pattern, so a research-only change computes "
        "relevant=false, skips api-tests, and never runs this guard. A comment "
        "mentioning the file does not count."
    )
