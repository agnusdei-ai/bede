"""The gate every new piece of curriculum content passes before it joins
Bede's library.

## Why this exists

`docs/CONTENT_CONTRIBUTING.md` already states how content is added to this
repo, and states it well: never store copyrighted text, cite a primary source
for every exact claim, match the existing schema. What it could not do is
*enforce* any of that. Every rule in it was a paragraph a reviewer had to
remember, on a repo whose own standing workflow says a decision is not
finished when it is written down — it is finished when the code says the same
thing.

This module turns that prose into a mechanical gate, and adds the two checks
the doc could not have made on its own:

* **The constitution's own rules**, applied to content rather than to
  conversation. Truthful attribution, formation over dilution, physical
  safety, faith scope, and the standing refusal to measure a child's
  spiritual life.
* **Mastery linkage** — the thing that makes a growing library safe.

## Growing the library without diluting mastery

The tension worth naming: Bede's mastery estimates are only meaningful if
what the diagnostic measures is what the library actually teaches. A library
that grows freely while the skill maps stand still produces a system that
teaches one thing and measures another, and the symptom a parent sees is
their child appearing to fail at material Bede never taught — the exact
failure `tests/diagnostic/test_prep_school_scope.py` was written for when the
math scope and the year plans had drifted apart.

So every candidate must say what it exercises, against the skill vocabularies
that already exist (`services/diagnostic/`). Two rules follow:

1. **Declared skills must already exist.** A candidate may not introduce a
   skill id. `MasteryProfile` stores `encrypt_json({skill_id: probability})`
   and this codebase has no `ALTER TABLE` path, so those ids are the only
   link to a family's accumulated history — growing the map is a deliberate,
   separately-reviewed change (see `skill_map.py`'s own strictly-additive
   discipline), never a side effect of adding a poem.
2. **Exercising nothing is allowed, but must be said out loud.** A poem does
   not map to a math skill, and pretending otherwise would be worse than
   admitting it. `exercises_no_tracked_skill` makes that an explicit
   declaration rather than an empty list nobody filled in — the same instinct
   as this codebase's refusal to let a blank score look like a low one.

## What this is not

Not a substitute for review. It catches what a rule can catch — a missing
source, a hazard word, a skill id that does not exist — and it cannot judge
whether a book is any good. `CurationVerdict.accepted` means "nothing
mechanical is wrong with this", never "this belongs in a child's year."
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set

from models.schemas import GradeStage, Subject

# ── The vocabularies a candidate may declare against ─────────────────────


def known_skill_ids() -> Set[str]:
    """Every skill id the diagnostic engine currently recognizes, across all
    subject areas. Read live rather than copied, so this cannot drift from
    the maps it validates against."""
    from services.diagnostic.composition import DOMAINS as COMPOSITION_DOMAINS
    from services.diagnostic.language_exposure import LANGUAGES
    from services.diagnostic.literacy import DOMAINS as LITERACY_DOMAINS
    from services.diagnostic.phonics import DOMAINS as PHONICS_DOMAINS
    from services.diagnostic.skill_map import SKILL_MAP

    ids: Set[str] = set(SKILL_MAP)
    for vocabulary in (
        PHONICS_DOMAINS, LITERACY_DOMAINS, COMPOSITION_DOMAINS, LANGUAGES
    ):
        ids.update(vocabulary)
    return ids


# ── Constitutional checks, as data ───────────────────────────────────────

#: Attributions this repository has already been caught getting wrong, or
#: which are famously wrong. Seeded from a real finding: "Ora et Labora"
#: appears nowhere in St. Benedict's Rule (it is Maurus Wolter, Beuron,
#: 1880), and services/latin_catalog.py says so rather than repeating the
#: pleasant, universally-repeated, false attribution. A misattribution is
#: the constitution's "never fabricate certainty" rule failing in the one
#: place neither child nor parent can catch it.
KNOWN_MISATTRIBUTIONS: Dict[str, str] = {
    "ora et labora": (
        "'Ora et Labora' does not appear in St. Benedict's Rule — it is Maurus "
        "Wolter, Beuron, 1880. See services/latin_catalog.py, which states this "
        "and quotes Rule ch. 48 instead."
    ),
    "preach the gospel at all times": (
        "Not St. Francis of Assisi; unattested in any of his writings."
    ),
    "the only thing necessary for the triumph of evil": (
        "Widely attributed to Burke; not found in his works."
    ),
}

#: Hazards `_physical_safety_guardrails()` (services/ai_service.py) already
#: forbids Bede from suggesting. Content that proposes an activity must not
#: reintroduce them through the library, which would route around that
#: guardrail entirely — it constrains Bede's own free text, not the material
#: it is handed.
PHYSICAL_HAZARD_PATTERNS = (
    r"\bclimb(ing)?\b", r"\bladder\b", r"\bcandle\b", r"\bmatches\b",
    r"\blighter\b", r"\bflame\b", r"\bstove\b", r"\bboiling\b",
    r"\bknife\b", r"\bknives\b", r"\bscissors\b", r"\bblade\b",
    r"\bthrow(ing)?\b", r"\bglass\b", r"\belectric(al|ity)?\b",
    r"\boutlet\b", r"\bswallow(ing)?\b", r"\btaste\b", r"\bpond\b",
    r"\bstream\b", r"\bcreek\b",
)

#: Doctrines distinctive to particular traditions. `scripture` is
#: denomination-neutral by design and its year plans carry that guarantee in
#: their own text; `latin`/`greek` are deliberately usable by a family
#: holding none of these (tests/test_latin_catalog.py asserts it against the
#: rendered prompt). Content for those subjects must not smuggle them in.
DENOMINATION_DISTINCTIVE = (
    "transubstantiation", "purgatory", "immaculate conception",
    "papal infallibility", "the magisterium", "intercession of the saints",
    "assumption of mary", "ave maria", "salve regina", "confiteor",
    "rosary", "indulgence",
)

#: Any hint of quantifying a child's spiritual life. CLAUDE.md: "Never
#: measure, score, or quantify a child's spiritual engagement or growth."
#: A content field is as good a place to introduce one as a database column.
FAITH_METRIC_MARKERS = (
    "faith_score", "faith_level", "faith_engagement", "spiritual_score",
    "spiritual_growth_score", "piety_score", "devotion_level",
    "holiness_rating",
)

#: Subjects whose content must stay usable by any Christian tradition.
_TRADITION_NEUTRAL_SUBJECTS = frozenset({
    Subject.scripture, Subject.latin, Subject.greek,
})


@dataclass(frozen=True)
class ContentCandidate:
    """One proposed addition to the library."""

    id: str
    title: str
    subject: Subject
    #: Where this claim comes from. Required for anything quoted verbatim.
    source: Optional[str] = None
    #: Verbatim text, if this entry stores any. Only legitimate for confirmed
    #: public-domain material — see docs/CONTENT_CONTRIBUTING.md's one hard
    #: rule.
    verbatim_text: Optional[str] = None
    public_domain: bool = False
    #: Charlotte Mason's term. Living-books entries already carry this field
    #: in data/catalog/year*.json.
    anti_twaddle: Optional[bool] = None
    #: Stages this content is offered at. Empty means every stage.
    stages: Sequence[GradeStage] = field(default_factory=tuple)
    #: Prose the child may eventually be taught from — scanned for hazards
    #: and for out-of-scope doctrine.
    body: str = ""
    #: Which existing diagnostic skills this exercises. See the module
    #: docstring: ids must already exist, and an empty list is only valid
    #: alongside exercises_no_tracked_skill.
    skills: Sequence[str] = field(default_factory=tuple)
    exercises_no_tracked_skill: bool = False
    #: Any extra fields a submission carries, checked for smuggled metrics.
    extra_fields: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Finding:
    rule: str
    message: str
    #: "block" prevents acceptance; "warn" is worth a human's eye but does
    #: not by itself stop the content.
    severity: str = "block"


@dataclass(frozen=True)
class CurationVerdict:
    candidate_id: str
    findings: List[Finding]

    @property
    def blocking(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == "block"]

    @property
    def accepted(self) -> bool:
        """Nothing mechanical is wrong with this. NOT "this belongs in a
        child's year" — see the module docstring."""
        return not self.blocking


def _scan(text: str, patterns: Sequence[str]) -> List[str]:
    """The words that actually matched, not the patterns that matched them.

    These strings end up in a message a contributor reads, and `\\bcandle\\b`
    tells them less about their own submission than `candle` does.
    """
    matched: List[str] = []
    for pattern in patterns:
        found = re.search(pattern, text, re.I)
        if found and found.group(0).lower() not in matched:
            matched.append(found.group(0).lower())
    return matched


def curate(candidate: ContentCandidate) -> CurationVerdict:
    """Run every check against one candidate and report all findings.

    Every finding is returned rather than stopping at the first, so a
    contributor fixes one submission once instead of rediscovering the next
    problem on each run.
    """
    findings: List[Finding] = []
    haystack = f"{candidate.title}\n{candidate.body}\n{candidate.verbatim_text or ''}"

    # ── Truth (constitution, non-negotiable rule 1) ──────────────────────
    if candidate.verbatim_text and not (candidate.source or "").strip():
        findings.append(Finding(
            "truth.source_required",
            "Verbatim text must cite the primary source it was checked against. "
            "An LLM's recollection of a text is not a source — see "
            "docs/CONTENT_CONTRIBUTING.md's sourcing standard.",
        ))

    lowered = haystack.lower()
    for phrase, explanation in KNOWN_MISATTRIBUTIONS.items():
        if phrase in lowered:
            findings.append(Finding(
                "truth.known_misattribution",
                f"Contains {phrase!r}, which carries a known attribution problem. "
                f"{explanation} State the real provenance rather than repeating "
                "the familiar version.",
                severity="warn",
            ))

    # ── Copyright (docs/CONTENT_CONTRIBUTING.md's one hard rule) ─────────
    if candidate.verbatim_text and not candidate.public_domain:
        findings.append(Finding(
            "copyright.verbatim_requires_public_domain",
            "Only confirmed public-domain material may be stored verbatim. "
            "For anything else, store metadata and a citation instead.",
        ))

    # ── Formation over dilution ──────────────────────────────────────────
    if candidate.subject == Subject.living_books and candidate.anti_twaddle is not True:
        findings.append(Finding(
            "formation.anti_twaddle",
            "A living-books entry must declare anti_twaddle=True. Charlotte "
            "Mason's whole objection is to diluted, condescending material, and "
            "the catalog schema already records this per entry.",
        ))

    # ── Stage fit ────────────────────────────────────────────────────────
    if candidate.subject == Subject.logic and GradeStage.foundations in candidate.stages:
        findings.append(Finding(
            "stage.logic_is_never_k2",
            "Logic is deliberately not offered before the Logic stage — formal "
            "reasoning at K-2 is the premature abstraction classical education "
            "warns against. Enforced in four places already; do not add a fifth "
            "route around it.",
        ))

    # ── Physical safety ──────────────────────────────────────────────────
    hazards = _scan(candidate.body, PHYSICAL_HAZARD_PATTERNS)
    if hazards:
        findings.append(Finding(
            "safety.physical_hazard",
            "Suggests an activity involving something _physical_safety_guardrails() "
            f"forbids Bede from proposing (matched: {', '.join(hazards)}). That "
            "guardrail constrains Bede's own words, not material handed to it, so "
            "content can route around it entirely. Keep activities to safe, "
            "ordinary items a child already handles, or say plainly that an adult "
            "should be nearby.",
            severity="warn",
        ))

    # ── Faith scope ──────────────────────────────────────────────────────
    if candidate.subject in _TRADITION_NEUTRAL_SUBJECTS:
        found = [d for d in DENOMINATION_DISTINCTIVE if d in lowered]
        if found:
            findings.append(Finding(
                "faith.tradition_neutrality",
                f"{candidate.subject.value} content must stay usable by any "
                f"Christian tradition, and this asserts {', '.join(found)}. "
                "Catholic-distinctive material belongs in the saints module, "
                "which is explicitly Catholic in scope.",
            ))

    metric_fields = [
        key for key in candidate.extra_fields
        if any(marker in key.lower() for marker in FAITH_METRIC_MARKERS)
    ]
    if metric_fields:
        findings.append(Finding(
            "faith.no_engagement_metric",
            f"Introduces {', '.join(metric_fields)}. A child's spiritual life is "
            "governed qualitatively, by rule, and is never tracked as a metric. "
            "This is out of scope by constitutional design — raise it as a "
            "question, do not build it.",
        ))

    # ── Mastery linkage ──────────────────────────────────────────────────
    findings.extend(_check_mastery_linkage(candidate))

    return CurationVerdict(candidate_id=candidate.id, findings=findings)


def _check_mastery_linkage(candidate: ContentCandidate) -> List[Finding]:
    """What keeps a growing library and a standing diagnostic in step.

    See the module docstring for why this is the check that matters most.
    """
    findings: List[Finding] = []
    declared = list(candidate.skills)

    if not declared and not candidate.exercises_no_tracked_skill:
        findings.append(Finding(
            "mastery.linkage_undeclared",
            "Declare which existing skills this exercises, or set "
            "exercises_no_tracked_skill=True to say plainly that it exercises "
            "none. An empty list on its own is indistinguishable from a field "
            "nobody filled in, and a library that grows without saying what it "
            "teaches drifts away from what the diagnostic measures.",
        ))
        return findings

    if declared and candidate.exercises_no_tracked_skill:
        findings.append(Finding(
            "mastery.contradictory_linkage",
            "Declares skills AND claims to exercise none. Pick one.",
        ))

    known = known_skill_ids()
    unknown = [skill for skill in declared if skill not in known]
    if unknown:
        findings.append(Finding(
            "mastery.unknown_skill",
            f"References skills the diagnostic engine does not have: "
            f"{', '.join(sorted(unknown))}. Content may only exercise skills "
            "that already exist. Growing a skill map is a separate, deliberately "
            "reviewed change — MasteryProfile stores those ids as the only link "
            "to a family's accumulated history, and this codebase has no "
            "ALTER TABLE path.",
        ))

    return findings


def curate_all(candidates: Sequence[ContentCandidate]) -> List[CurationVerdict]:
    """Curate a batch, and additionally reject duplicate ids.

    Ids are lookup keys across the whole catalog
    (`tests/test_catalog_data_integrity.py` already checks global uniqueness
    of what is committed); catching a collision here means catching it before
    it is committed rather than after.
    """
    verdicts = [curate(candidate) for candidate in candidates]

    seen: Dict[str, int] = {}
    for candidate in candidates:
        seen[candidate.id] = seen.get(candidate.id, 0) + 1

    return [
        CurationVerdict(
            candidate_id=verdict.candidate_id,
            findings=verdict.findings + ([
                Finding(
                    "id.duplicate",
                    f"Id {verdict.candidate_id!r} appears "
                    f"{seen[verdict.candidate_id]} times in this batch. Ids are "
                    "lookup keys and must be unique across the whole catalog.",
                )
            ] if seen[verdict.candidate_id] > 1 else []),
        )
        for verdict in verdicts
    ]
