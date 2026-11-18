"""Structural guard for docs/K2_PRACTICE_RESEARCH.md, the evidence behind the
K-2 practice evidence weights (docs/DECISIONS.md entry 40, ruling (b)).

The sibling of test_research_citations.py, test_locale_research.py and
test_accessibility_research.py, enforcing CLAUDE.md's seven-rule standard for a
decision backed by research. What is enforced is shape and internal agreement,
never whether a finding is correct: no test can rule on that.

Two things here are specific to this document and worth a guard of their own:

- **The weights are product defaults, not research values.** 0.5, 0.25 and the
  rest were chosen by the owner, and no study tested them. The likeliest way
  this document goes wrong is a later edit that lets one of those numbers read
  as sourced, so the statement that they are product defaults is pinned.
- **The guess-rate table is arithmetic, so it is recomputed here.** It is the
  document's main argument for open decision 40(h), and a number in a table is
  the sentence nobody re-checks when the weights change. The two copies of one
  fact are checked against each other rather than trusted.

Note .github/workflows/test.yml's change filter names this document, for the
reason the siblings document: without it a research-only edit computes
relevant=false, skips api-tests, and never runs this file.
"""
import re
from fractions import Fraction
from itertools import product
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_RESEARCH = _ROOT / "docs" / "K2_PRACTICE_RESEARCH.md"

# Closed vocabulary, mirroring the document's own evidence-class table. A
# review, a correlational study and an experiment must not read as the same
# kind of thing.
VALID_EVIDENCE_CLASSES = {"Experimental", "Review", "Correlational", "Analytical"}

# The product defaults the guess-rate table is computed from. If entry 40's
# weights change, this test fails until the table is recomputed.
FIRST_TRY_WEIGHT = Fraction(1, 2)
SECOND_TRY_WEIGHT = Fraction(1, 4)
SECURE = Fraction(4, 5)  # services/diagnostic/mastery.py's "secure" threshold
ITEMS_PER_ROUND = 3  # map practice's YOUR_TURN_TASKS, which K-2 practice keeps

_CORPUS_ROW = re.compile(r"^\| ([A-Z][^|(]*?) \((\d{4})\) \|")
_REFERENCE = re.compile(r"^\*\*([A-Z][^*]*?) \((\d{4})\)\.\*\*", re.MULTILINE)
_GUESS_ROW = re.compile(
    r"^\| (\d) \| (Yes|No) \| (\d+)% \| (\d+)% \| (0\.\d+) \| (\d+)% \|$", re.MULTILINE
)


def _split() -> tuple[str, str]:
    text = _RESEARCH.read_text()
    marker = "\n## References\n"
    assert marker in text, (
        f"{_RESEARCH} has no '## References' section. Either it was renamed or "
        "removed; this test needs updating rather than deleting."
    )
    head, _, tail = text.partition(marker)
    return head, tail


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _corpus() -> dict[tuple[str, str], list[str]]:
    body, _ = _split()
    out = {}
    for line in body.splitlines():
        m = _CORPUS_ROW.match(line)
        if m:
            out[(m.group(1).strip(), m.group(2))] = [c.strip() for c in line.split("|")]
    return out


def _references() -> dict[tuple[str, str], str]:
    _, refs = _split()
    out = {}
    for m in _REFERENCE.finditer(refs):
        end = refs.find("\n\n**", m.end())
        out[(m.group(1).strip(), m.group(2))] = refs[m.start(): end if end != -1 else None]
    return out


def test_the_document_parses_and_has_a_real_corpus():
    """The canary: without it every test below passes vacuously the moment a
    table or reference format changes."""
    corpus, refs = _corpus(), _references()
    assert len(corpus) >= 6, f"Parsed only {len(corpus)} corpus rows from {_RESEARCH}."
    assert len(refs) >= 6, f"Parsed only {len(refs)} references from {_RESEARCH}."
    assert len(_GUESS_ROW.findall(_split()[0])) == 4, (
        f"Expected the four-row guess-rate table in {_RESEARCH}; its format "
        "changed. Update this test rather than dropping it."
    )


def test_the_corpus_table_and_reference_list_agree():
    corpus, refs = set(_corpus()), set(_references())
    assert corpus == refs, (
        f"The corpus table and reference list disagree in {_RESEARCH}.\n"
        f"  In table only: {sorted(corpus - refs)}\n"
        f"  In references only: {sorted(refs - corpus)}"
    )


def test_every_corpus_row_states_a_known_evidence_class():
    for (name, year), cells in _corpus().items():
        assert len(cells) > 2, f"Corpus row for {name} ({year}) has too few columns"
        assert cells[2] in VALID_EVIDENCE_CLASSES, (
            f"Corpus row {name} ({year}) states evidence class {cells[2]!r}, "
            f"not one of {sorted(VALID_EVIDENCE_CLASSES)}."
        )


def test_every_corpus_row_records_who_read_it_and_the_notice_check():
    """Rules 3 and 4. Each row must say what the owner's reading found, what
    this document's own retrieval achieved, and the editorial-notice result.
    A blank cell there reads as a check that was done."""
    for (name, year), cells in _corpus().items():
        # | Study | Class | Population | Owner | Retrieval | Notices | Used for |
        assert len(cells) >= 9, f"Corpus row for {name} ({year}) is missing columns."
        for index, label in ((4, "owner's reading"), (5, "retrieval"), (6, "editorial notices")):
            assert cells[index], f"Corpus row {name} ({year}) has no {label} entry."


def test_every_reference_carries_a_resolvable_link():
    for (name, year), entry in _references().items():
        assert re.search(r"https://\S+", entry), (
            f"Reference {name} ({year}) in {_RESEARCH} has no link."
        )


def test_the_document_reports_the_editorial_notice_check():
    """Rule 3, reported either way. This version could not check notices, and
    must keep saying so until the check is done."""
    body, _ = _split()
    assert re.search(r"[Ee]ditorial notices? (were|was) (not )?checked", body), (
        f"{_RESEARCH} does not report the editorial-notice check."
    )


def test_contrary_findings_have_their_own_section():
    body, _ = _split()
    assert re.search(r"^## \d+\. Contrary and limiting findings", body, re.MULTILINE), (
        f"{_RESEARCH} has no top-level contrary-findings section."
    )


def test_the_weights_are_stated_as_product_defaults_not_research():
    """The refusal this document exists to keep. If it stops being written
    down, the weights start being cited as sourced."""
    body = _flat(_split()[0])
    assert "None of them comes from research." in body, (
        f"{_RESEARCH} no longer states that the weights do not come from research."
    )
    assert "## 4. What the research cannot supply" in _split()[0]
    for value in ("0.5", "0.25"):
        assert value in body


def test_the_guess_rate_table_matches_the_arithmetic():
    """Two copies of one fact. Recomputes each row from the weights above and
    fails when the document's table drifts from them."""
    rows = _GUESS_ROW.findall(_split()[0])
    seen = set()
    for choices, retap, first, within_two, avg_weight, secure in rows:
        n = int(choices)
        p_first = Fraction(1, n)
        p_second = (1 - p_first) * (Fraction(1, n) if retap == "Yes" else Fraction(1, n - 1))
        p = {"F": p_first, "S": p_second, "M": 1 - p_first - p_second}
        w = {"F": FIRST_TRY_WEIGHT, "S": SECOND_TRY_WEIGHT, "M": Fraction(0)}
        p_secure = Fraction(0)
        for outcomes in product("FSM", repeat=ITEMS_PER_ROUND):
            estimate, chance = Fraction(1, 2), Fraction(1)
            for outcome in outcomes:
                chance *= p[outcome]
                estimate += w[outcome] * (1 - estimate)
            if estimate >= SECURE:
                p_secure += chance
        expected = (
            round(float(p_first) * 100),
            round(float(p_first + p_second) * 100),
            round(float(p_first * w["F"] + p_second * w["S"]), 2),
            round(float(p_secure) * 100),
        )
        actual = (int(first), int(within_two), float(avg_weight), int(secure))
        assert actual == expected, (
            f"Guess-rate row ({choices} choices, re-tap {retap}) says {actual}, "
            f"the arithmetic gives {expected}."
        )
        seen.add((n, retap))
    assert seen == {(3, "Yes"), (4, "Yes"), (3, "No"), (4, "No")}


def test_the_document_links_to_the_decision_and_the_spec():
    """The register carries state, this document the argument."""
    body, _ = _split()
    assert "(DECISIONS.md)" in body and "entry 40" in body
    assert "(K2_PRACTICE.md)" in body
    assert "40(h)" in body, f"{_RESEARCH} no longer points at open decision 40(h)."


def _entry_40() -> str:
    register = (_ROOT / "docs" / "DECISIONS.md").read_text()
    match = re.search(r"^## 40\..*?(?=^## 41\.)", register, re.S | re.M)
    assert match, "Could not find entry 40 in docs/DECISIONS.md."
    return match.group(0)


def test_entry_40_points_at_this_document():
    """The other direction: a reader of the register must be able to reach the
    argument behind ruling (b) and open item (h)."""
    assert "(K2_PRACTICE_RESEARCH.md)" in _entry_40(), (
        "docs/DECISIONS.md entry 40 no longer links to K2_PRACTICE_RESEARCH.md."
    )


def test_entry_40_says_the_notice_check_is_outstanding_while_it_is():
    """While this document says editorial notices were not checked, entry 40
    must say so too, so the research is never used to close (h) on an
    unchecked corpus."""
    body, _ = _split()
    if "Editorial notices were not checked" not in body:
        return
    entry = _entry_40()
    assert "editorial-notice check" in entry and "has not been done" in entry, (
        "K2_PRACTICE_RESEARCH.md still says editorial notices were not checked, "
        "but entry 40 no longer says the check is outstanding."
    )


def test_the_research_document_is_named_in_the_ci_change_filter():
    """Reads the `grep -qE` pattern line itself, because an earlier sibling
    test passed on a comment beside the filter."""
    workflow = (_ROOT / ".github" / "workflows" / "test.yml").read_text()
    filter_lines = [
        line for line in workflow.splitlines() if "grep -qE" in line and "^(" in line
    ]
    assert filter_lines, "Could not find the change-filter line in test.yml."
    assert any(r"docs/K2_PRACTICE_RESEARCH\.md" in line for line in filter_lines), (
        "docs/K2_PRACTICE_RESEARCH.md is not in test.yml's change-filter "
        "pattern, so a research-only change never runs this guard."
    )
