"""
Probe archetypes and the Q-matrix mapping them to skill_map.py sub-skills —
runtime-loop steps S5/S6 (see docs/diagnostic/DIAGNOSTIC_LOOP.md). Pure
data + accessors: no DB, no LLM, stdlib only, per
docs/diagnostic/DIAGNOSTIC_BUILD_LOOP.md's Phase 1 hard rules.

There is no item bank of multiple-choice questions in bede — the "items"
are ordinary tutoring interactions Bede classifies in the moment. Each
probe archetype here is one such interaction shape; Bede reports which
archetype an exchange matched via the record_skill_evidence tool (unit
3.1), and this module's q_row() looks up which skill(s) that archetype is
evidence for.

One probe per skill in this skeleton (a 1:1 Q-matrix), matching
skill_map.py's own "representative, extensible skeleton" framing rather
than hand-pairing skills into multi-attribute probes — kept simple so the
CDM baseline (DINA, unit 1.4) reads each observation as evidence for
exactly one attribute. A future revision can add genuinely multi-skill
probes (the design doc's own examples pair 2 related skills) once the
core pipeline is proven; that's a data change here, not an engine change.
"""

from dataclasses import dataclass
from typing import Literal, TypedDict

from services.diagnostic.skill_map import SKILL_MAP


class EvidenceObservation(TypedDict):
    """In-memory only, per design doc §3.4 — never persisted raw. Only the
    derived per-skill probability contribution computed from this survives
    (mastery.bayesian_update, unit 1.7); the observation itself is
    discarded once that update completes."""
    probe_id: str
    outcome: Literal["correct", "partial", "incorrect", "hint_dependent"]
    confidence: float


@dataclass(frozen=True)
class ProbeArchetype:
    id: str
    description: str
    skills: tuple[str, ...]


def _p(id_: str, description: str, skill_id: str) -> ProbeArchetype:
    return ProbeArchetype(id=id_, description=description, skills=(skill_id,))


_PROBES: tuple[ProbeArchetype, ...] = tuple(
    _p(f"probe.{skill_id}", f"Socratic exchange reveals grasp of: {skill.label.lower()}", skill_id)
    for skill_id, skill in SKILL_MAP.items()
)

Q_MATRIX: dict[str, ProbeArchetype] = {p.id: p for p in _PROBES}

_OUTCOME_SCORES: dict[str, float] = {
    "correct": 1.0,
    "partial": 0.65,
    "hint_dependent": 0.35,
    "incorrect": 0.0,
}
# Deliberately not partial=0.5: cdm.update_attribute_posteriors (unit 1.4)
# treats each outcome as a soft Bernoulli-style label, and a score of
# exactly 0.5 is a fixed point of that blend — score*p + (1-score)*(1-p)
# equals 0.5 identically for ANY p when score==0.5, so it would carry zero
# evidential weight regardless of slip/guess. partial/hint_dependent sit
# symmetrically on either side of 0.5 instead, so "some grasp" nudges
# mastery estimates up and "only after heavy scaffolding" nudges them
# down, matching the tool's own description in ai_service.py's eventual
# record_skill_evidence definition (design doc §7.1).


def q_row(probe_id: str) -> list[str]:
    """Skills a probe is evidence for. Empty list for an unknown probe_id —
    never raises, since an invented/hallucinated id from the model must
    resolve to nothing (see design doc §11's prompt-injection defense)."""
    probe = Q_MATRIX.get(probe_id)
    return list(probe.skills) if probe else []


def probes_for_skill(skill_id: str) -> list[str]:
    """Inverse lookup: every probe archetype that exercises this skill."""
    return [p.id for p in _PROBES if skill_id in p.skills]


def outcome_to_score(outcome: str) -> float:
    """correct=1.0, partial=0.5, hint_dependent=0.25, incorrect=0.0.
    Unknown outcome strings score 0.0 rather than raising — mirrors
    q_row's degrade-to-empty contract for untrusted model output."""
    return _OUTCOME_SCORES.get(outcome, 0.0)
