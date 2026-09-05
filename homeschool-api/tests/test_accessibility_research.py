"""Guards for the reading-presentation settings and their evidence base.

Two halves, deliberately in one file because they are two copies of one fact.

**The schema half** pins the three fields for a child whose obstacle is
reading the screen rather than understanding the lesson — `letter_spacing`,
`line_spacing`, `frequent_break_offers`. A fourth, `text_size`, shipped in
#486 and was removed: `TextSizeControl` already offered it in both the app and
the demo, scaling the root font size product-wide, so the new field was a
weaker duplicate. Decision register entry 24, and a guard below. What matters about them
is not that they exist but three properties that regress silently: every one
defaults to today's rendering, the frontend mirror agrees exactly, and **none
of them names a condition**. That last is this app's standing rule (Bede never
names, guesses at, or implies a diagnosis) applied to a settings panel, where
it is easiest to break by accident — `dyslexia_mode` is a shorter, clearer
field name than anything here, which is exactly why someone will propose it.

**The research half** enforces CLAUDE.md's seven-rule standard on
`docs/ACCESSIBILITY_RESEARCH.md`, the sibling of `test_locale_research.py` and
`test_research_citations.py`. Rules 1-4 are mechanically checkable; 5 is
checked as a required section; 6 and 7 are matters of prose judgement and are
not checked at all. No test can rule on whether a finding is correct.
"""
import re
from pathlib import Path

import pytest

from models.schemas import GradeStage, SessionConfig


def _config(**overrides) -> SessionConfig:
    return SessionConfig(
        student_name="Emma",
        grade="3",
        grade_stage=GradeStage.core_mastery,
        subjects=["mathematics"],
        **overrides,
    )


_ROOT = Path(__file__).resolve().parents[2]
_RESEARCH = _ROOT / "docs" / "ACCESSIBILITY_RESEARCH.md"
_REGISTER = _ROOT / "docs" / "DECISIONS.md"
_TYPES = _ROOT / "homeschool-tutor" / "src" / "types" / "index.ts"

# Closed vocabulary, mirroring §1's own table. A professional body's stated
# position and a controlled experiment must not read as the same kind of thing
# — which matters more here than in most corpora, because the negative finding
# about dyslexia fonts rests partly on a Position and the positive finding
# about spacing rests on an experiment.
VALID_EVIDENCE_CLASSES = {
    "RCT/Experimental",
    "Meta-analytic",
    "Position",
    "Design guidance",
    "Absent",
}

_CORPUS_ROW = re.compile(r"^\| ([A-Z][^|(]*?) \(([^)]+)\) \|")
_REFERENCE = re.compile(r"^\*\*([A-Z][^*]*?) \(([^)]+)\)\.\*\*", re.MULTILINE)


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
        if m and m.group(1).strip() != "Source":  # the table's own header row
            out[(m.group(1).strip(), m.group(2))] = [c.strip() for c in line.split("|")]
    return out


def _references() -> dict[tuple[str, str], str]:
    _, refs = _split()
    out = {}
    for m in _REFERENCE.finditer(refs):
        end = refs.find("\n\n**", m.end())
        out[(m.group(1).strip(), m.group(2))] = refs[m.start(): end if end != -1 else None]
    return out


# ── The settings themselves ──────────────────────────────────────────────


READING_PRESENTATION_FIELDS = {
    "letter_spacing": {"normal", "wide", "wider"},
    "line_spacing": {"normal", "relaxed", "loose"},
}


def test_every_new_setting_defaults_to_todays_behaviour():
    """The load-bearing property. These fields land in every existing family's
    stored config the moment the schema ships, so any default other than
    today's rendering silently changes what a child who never asked for a
    change sees on their next lesson."""
    config = _config()
    assert config.letter_spacing == "normal"
    assert config.line_spacing == "normal"
    assert config.frequent_break_offers is False


def test_no_setting_names_a_condition():
    """Bede never names, guesses at, or implies a diagnosis — the constitution's
    `authority_order`, and `_learning_support_note`'s own stated rule. A field
    called `dyslexia_mode` would make the software itself hold a diagnosis, and
    it is a shorter and clearer name than anything here, so someone will
    propose it. See decision register entry 24 for why it was refused."""
    forbidden = (
        "dyslexi", "adhd", "add_", "autis", "asd", "spectrum", "disorder",
        "disabilit", "impair", "deficit", "sped", "iep", "diagnos",
    )
    # Every field on SessionConfig, not just the four added here — a guard
    # that scans a hardcoded list is one someone satisfies by not adding to
    # the list, which is the same act as adding the field.
    for name in SessionConfig.model_fields:
        for word in forbidden:
            assert word not in name.lower(), (
                f"Setting {name!r} names a condition ({word!r}). Accommodations "
                "here are plain settings any parent may turn on for any child; "
                "naming one after a diagnosis makes this software hold one."
            )


@pytest.mark.parametrize("field,allowed", sorted(READING_PRESENTATION_FIELDS.items()))
def test_the_schema_accepts_exactly_the_stated_values(field, allowed):
    for value in allowed:
        _config(**{field: value})
    with pytest.raises(Exception):
        _config(**{field: "enormous"})


def test_the_frontend_mirror_matches_these_settings_exactly():
    """Two copies of one fact. `types/index.ts` is what the parent's picker is
    built from; if it drifts, the form offers a value the API rejects (a save
    that 422s after the parent filled the panel in) or omits one the API
    accepts (a setting that exists and is unreachable). Nothing type-checks a
    TypeScript union against a pydantic `Literal`."""
    ts = _TYPES.read_text()
    for field, allowed in READING_PRESENTATION_FIELDS.items():
        m = re.search(rf"^\s*{field}\?:\s*(.+)$", ts, re.MULTILINE)
        assert m, f"{field} is missing from {_TYPES} — the parent's picker cannot offer it."
        mirrored = set(re.findall(r"'([^']+)'", m.group(1)))
        assert mirrored == allowed, (
            f"{field} disagrees between models/schemas.py and {_TYPES}.\n"
            f"  Backend only: {sorted(allowed - mirrored)}\n"
            f"  Frontend only: {sorted(mirrored - allowed)}"
        )
    assert re.search(r"^\s*frequent_break_offers\?:\s*boolean", ts, re.MULTILINE), (
        f"frequent_break_offers is missing from {_TYPES}."
    )


def test_the_presentation_settings_never_reach_the_prompt():
    """These change what the SCREEN looks like, and must not become something
    Bede is told about.

    `_learning_support_note`'s standing rule is that the child is never told an
    accommodation is in place and never given a reason for it. A model handed
    "this student reads with wider letter spacing" has been handed exactly the
    fact that rule exists to keep out of the conversation, and the friendly
    thing for it to do with that fact — mentioning it kindly — is the failure.

    Asserted against the whole prompt-building service rather than one
    function, because the failure would arrive as a helpful-looking one-line
    addition to whichever note someone was editing at the time."""
    source = (_ROOT / "homeschool-api" / "services" / "ai_service.py").read_text()
    for field in list(READING_PRESENTATION_FIELDS) + ["frequent_break_offers"]:
        assert field not in source, (
            f"services/ai_service.py mentions {field!r}. These are presentation "
            "settings: they change the screen, never the prompt. Telling Bede "
            "about one hands it the fact _learning_support_note forbids it from "
            "saying to the child."
        )


# ── The evidence base ────────────────────────────────────────────────────


def test_the_document_parses_and_has_a_real_corpus():
    """The canary. Without it every test below passes vacuously the moment a
    table or reference format changes — the vacuous-pass failure this repo has
    shipped more than once."""
    corpus, refs = _corpus(), _references()
    assert len(corpus) >= 7, (
        f"Parsed only {len(corpus)} corpus rows from {_RESEARCH}. Either the "
        "table format changed or the corpus was gutted; both need a human."
    )
    assert len(refs) >= 7, f"Parsed only {len(refs)} references from {_RESEARCH}."


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


def test_every_reference_carries_a_resolvable_link():
    """A claim a reader cannot check is not evidence. The one exception is the
    source that was looked for and not retrieved, which is the point of §6.3
    and is allowed to have no link precisely because it has no source."""
    for (name, year), entry in _references().items():
        if "not retrieved" in entry.lower():
            continue
        assert re.search(r"https://\S+", entry), (
            f"Reference {name} ({year}) in {_RESEARCH} has no link."
        )


def test_the_unretrieved_source_is_still_in_the_corpus():
    """Rule 4. A figure was found in secondary writing during this research and
    deliberately not cited, and line length is consequently not offered as a
    setting at all. If that row is dropped, the document silently stops
    disclosing a gap it currently discloses — and a missing disclosure reads
    exactly like an absence of risk."""
    absent = [k for k, cells in _corpus().items() if cells[2] == "Absent"]
    assert absent, (
        "No corpus row is classed 'Absent'. The document previously recorded "
        "that the line-length figure's primary source was not retrieved. If it "
        "has since been retrieved, reclass the row and cite the real source — "
        "do not simply delete the disclosure."
    )
    body, _ = _split()
    assert "not retrieved" in body.lower()


def test_the_document_reports_the_integrity_check():
    """Rule 3. A document that does not say it looked has not looked, as far as
    any later reader can tell."""
    body, _ = _split()
    assert re.search(r"[Ee]ditorial notices? (were|was) checked", body), (
        f"{_RESEARCH} does not report the editorial-notice check."
    )


def test_contrary_findings_have_their_own_section():
    """Rule 5. A corpus assembled to support a conclusion is not evidence, and
    a contrary finding demoted to a subordinate clause is how that happens
    without anyone deciding to do it."""
    body, _ = _split()
    assert re.search(r"^## \d+\. Contrary findings", body, re.MULTILINE), (
        f"{_RESEARCH} has no top-level 'Contrary findings' section."
    )


def test_the_document_keeps_stating_what_it_declined_to_build():
    """The three refusals are the substance of this research, not a preamble to
    it — a dyslexia font (evidence is negative), a dyslexia mode (would make
    the software hold a diagnosis), and line length (its one supporting figure
    could not be checked). A refusal that stops being written down gets
    re-proposed by someone who never saw the reason, which is the whole failure
    mode a decision register exists to prevent."""
    body = re.sub(r"\s+", " ", _split()[0])
    for required, why in [
        ("**No dyslexia font is offered.**", "the negative font finding"),
        ("**not** offered as a setting at all", "the unverifiable line-length figure"),
        ("Bigger Is Not Always Better", "the text-size reversal"),
    ]:
        assert required in body, (
            f"{_RESEARCH} no longer states {required!r} ({why}). Refusals must "
            "stay named in the document, or they are re-proposed."
        )


def test_the_document_states_what_it_cannot_tell_you():
    """Rule 7, and the sentence that keeps this honest: no setting here was
    tested with a real child using Bede, and adding spacing controls does not
    make Bede a reading intervention."""
    body, _ = _split()
    assert re.search(r"^## \d+\. What this cannot tell you", body, re.MULTILINE)
    assert "not a reading intervention" in re.sub(r"\s+", " ", body), (
        f"{_RESEARCH} no longer states that Bede is not a reading intervention."
    )


def test_the_register_entry_points_at_the_research_document():
    """The register carries state, the document carries the argument. That
    split only works if the entry links across."""
    register = _REGISTER.read_text()
    assert "ACCESSIBILITY_RESEARCH.md" in register, (
        "No entry in docs/DECISIONS.md references docs/ACCESSIBILITY_RESEARCH.md, "
        "so the reasoning is unreachable from the decision it supports."
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
    assert any("docs/ACCESSIBILITY_RESEARCH" in line for line in filter_lines), (
        "docs/ACCESSIBILITY_RESEARCH.md is not in test.yml's change-filter "
        "pattern, so a research-only change never runs this guard."
    )


def test_no_per_student_text_size_field_comes_back():
    """`TextSizeControl`/`useTextScale` already offer text size in BOTH the app
    and the demo — a floating control on every screen scaling the ROOT font
    size 87.5%-175% (WCAG 2.1 SC 1.4.4), which reaches every rem-based size in
    the product. A per-student `SessionConfig` copy shipped in #486 without
    anyone checking for it, and was removed as the weaker of two controls for
    one thing.

    Adding it back is an obvious-sounding request, and the reason it is
    refused lives in a register entry nobody re-reads. This is that reason,
    placed where someone adding the field would trip over it."""
    assert "text_size" not in SessionConfig.model_fields, (
        "SessionConfig has a text_size field again. Text size is "
        "TextSizeControl's job — see docs/DECISIONS.md entry 24. If this is "
        "deliberate, the register entry and both accessibility docs need "
        "changing first, not just this test."
    )
    types = _TYPES.read_text()
    assert "text_size" not in types, f"text_size is back in {_TYPES}."
