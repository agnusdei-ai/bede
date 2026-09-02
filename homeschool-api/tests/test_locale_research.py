"""Structural guard for docs/LOCALE_RESEARCH.md, the third-locale evidence base.

The sibling of `test_research_citations.py`, and deliberately not a
generalisation of it. That file guards a corpus of academic papers, where
"resolvable" means a DOI and "editorial notice" means a retraction. This
document's evidence is statutes, a supreme-court ruling, institutional
statistics and vendor documentation — sources for which a DOI mostly does not
exist and for which the equivalent integrity question is whether the law has
been superseded. Forcing this corpus into an author-year/DOI shape would have
meant citing `Republic Act 12027` as though it were a paper, which is the kind
of tidy misrepresentation the research standard exists to prevent.

What is shared is the standard itself — CLAUDE.md's seven rules — and these
tests enforce the four of them that are mechanically checkable:

* every source in the corpus table is in the reference list and vice versa
  (rule 1: no claim without a named source);
* every source states an evidence class from a closed vocabulary (rule 2);
* the supersession/editorial check is reported (rule 3);
* every reference carries a resolvable link, and the one source that was
  *looked for and not retrieved* is still listed, classed `Absent`, so the gap
  is visible rather than inferred (rule 4).

Rules 5-7 (contrary findings get their own section, weak evidence labelled
weak, limits stated with the finding) are checked structurally where a section
is required and not at all where they are matters of prose judgement. No test
can rule on whether a finding is correct.
"""
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_RESEARCH = _ROOT / "docs" / "LOCALE_RESEARCH.md"
_REGISTER = _ROOT / "docs" / "DECISIONS.md"

# Closed vocabulary. A statute and a vendor's language-count claim must not read
# as the same kind of thing, which is exactly the failure §5.2 of the document
# is written to prevent. `Absent` is the load-bearing one: it is how a source
# that was searched for and not found stays in the corpus instead of vanishing.
VALID_EVIDENCE_CLASSES = {
    "Legal",
    "Institutional",
    "Empirical",
    "Documentary",
    "Absent",
}

_CORPUS_ROW = re.compile(r"^\| ([A-Z][^|(]*?) \((\d{4})\) \|")
_REFERENCE = re.compile(r"^\*\*([A-Z][^*]*?) \((\d{4})\)\.\*\*", re.MULTILINE)


def _split() -> tuple[str, str]:
    text = _RESEARCH.read_text()
    marker = "\n## References\n"
    assert marker in text, (
        f"{_RESEARCH} has no '## References' section. Either it was renamed or "
        "removed; this test needs updating rather than deleting."
    )
    head, _, tail = text.partition(marker)
    return head, tail


def _corpus() -> dict[tuple[str, str], list[str]]:
    body, _ = _split()
    out = {}
    for line in body.splitlines():
        m = _CORPUS_ROW.match(line)
        if m:
            out[(m.group(1).strip(), m.group(2))] = [
                c.strip() for c in line.split("|")
            ]
    return out


def _references() -> dict[tuple[str, str], str]:
    _, refs = _split()
    out = {}
    for m in _REFERENCE.finditer(refs):
        end = refs.find("\n\n**", m.end())
        out[(m.group(1).strip(), m.group(2))] = refs[m.start(): end if end != -1 else None]
    return out


def test_the_document_parses_and_has_a_real_corpus():
    """The canary. Without it every test below passes vacuously the moment a
    table or reference format changes — the vacuous-pass failure this repo has
    shipped more than once."""
    corpus, refs = _corpus(), _references()
    assert len(corpus) >= 10, (
        f"Parsed only {len(corpus)} corpus rows from {_RESEARCH}. Either the "
        "table format changed or the corpus was gutted; both need a human."
    )
    assert len(refs) >= 10, (
        f"Parsed only {len(refs)} references from {_RESEARCH}."
    )


def test_the_corpus_table_and_reference_list_agree():
    """Two copies of one fact, checked rather than trusted. A source in the
    table but not the references cannot be looked up; one in the references but
    not the table has no stated evidence class, which is rule 2."""
    corpus, refs = set(_corpus()), set(_references())
    assert corpus == refs, (
        f"The corpus table and reference list disagree in {_RESEARCH}.\n"
        f"  In table only: {sorted(corpus - refs)}\n"
        f"  In references only: {sorted(refs - corpus)}"
    )


def test_every_corpus_row_states_a_known_evidence_class():
    """A supreme-court ruling and a vendor's 'supports 201 languages' claim must
    not read as equally weighty. A free-text column would let that distinction
    dissolve silently."""
    for (name, year), cells in _corpus().items():
        assert len(cells) > 2, f"Corpus row for {name} ({year}) has too few columns"
        assert cells[2] in VALID_EVIDENCE_CLASSES, (
            f"Corpus row {name} ({year}) states evidence class {cells[2]!r}, "
            f"not one of {sorted(VALID_EVIDENCE_CLASSES)}. Adding a class is a "
            "deliberate act; edit this vocabulary if that is intended."
        )


def test_every_reference_carries_a_resolvable_link():
    """A claim a reader cannot check is not evidence. Not a DOI requirement —
    most of this corpus is statutes and institutional statistics, which do not
    have one."""
    for (name, year), entry in _references().items():
        assert re.search(r"https://\S+", entry), (
            f"Reference {name} ({year}) in {_RESEARCH} has no link. Every "
            "source must be resolvable by the person reading the claim."
        )


def test_the_unretrieved_source_is_still_in_the_corpus():
    """Rule 4, and the single most important guard here. The document reports
    that Whisper's per-language WER table was looked for and NOT retrieved, and
    that a secondary figure was found and deliberately not cited. If that row
    is dropped, the document silently stops disclosing a gap it currently
    discloses — and a missing disclosure reads exactly like an absence of
    risk."""
    absent = [k for k, cells in _corpus().items() if cells[2] == "Absent"]
    assert absent, (
        "No corpus row is classed 'Absent'. The document previously recorded "
        "that Whisper's per-language WER table was not retrieved. If it has "
        "since been retrieved, reclass the row and cite the real figures — do "
        "not simply delete the disclosure."
    )
    body, _ = _split()
    assert "not retrieved" in body.lower(), (
        "The body no longer states that a source was looked for and not found."
    )


def test_the_document_reports_the_integrity_check():
    """The equivalent of the retraction check for a corpus of laws and
    statistics: whether a source has been superseded. Reporting a negative
    result is the point — a document that does not say it looked has not
    looked, as far as any later reader can tell."""
    body, _ = _split()
    assert re.search(r"[Ee]ditorial notices? (were|was) checked", body), (
        f"{_RESEARCH} does not report the editorial/supersession check."
    )


def test_contrary_findings_have_their_own_section():
    """Rule 5. A corpus assembled to support a conclusion is not evidence, and
    a contrary finding demoted to a subordinate clause is how that happens
    without anyone deciding to do it."""
    body, _ = _split()
    assert re.search(r"^## \d+\. Contrary findings", body, re.MULTILINE), (
        f"{_RESEARCH} has no top-level 'Contrary findings' section."
    )


def test_the_recommendation_names_what_would_change_it():
    """A research document whose conclusion is unfalsifiable is advocacy. The
    recommendation must name its conditions and the runner-up's trigger."""
    body, _ = _split()
    for required in ("Portuguese is the runner-up", "Filipino is rejected"):
        assert required in body, (
            f"{_RESEARCH}'s recommendation no longer states {required!r}. The "
            "rejected and deferred alternatives must stay named, or they get "
            "re-proposed by someone who never saw the reason."
        )


def test_the_register_entry_points_at_the_research_document():
    """The register carries state, the document carries the argument. That
    split only works if the entry links across."""
    register = _REGISTER.read_text()
    assert "LOCALE_RESEARCH.md" in register, (
        "No entry in docs/DECISIONS.md references docs/LOCALE_RESEARCH.md, so "
        "the reasoning is unreachable from the decision it supports."
    )
    assert _RESEARCH.exists()


def test_the_research_document_is_named_in_the_ci_change_filter():
    """Without this, a pull request touching only this document computes
    relevant=false, skips api-tests, and never runs this guard — real
    everywhere except on the changes it exists to guard. Reads the `grep -qE`
    pattern line itself, because an earlier version of the sibling test in
    test_decision_register.py passed on a comment beside the filter."""
    workflow = (_ROOT / ".github" / "workflows" / "test.yml").read_text()
    filter_lines = [
        line for line in workflow.splitlines() if "grep -qE" in line and "^(" in line
    ]
    assert filter_lines, "Could not find the change-filter line in test.yml."
    assert any("docs/LOCALE_RESEARCH" in line for line in filter_lines), (
        "docs/LOCALE_RESEARCH.md is not in test.yml's change-filter pattern, "
        "so a research-only change never runs this guard. A comment mentioning "
        "the file does not count."
    )
