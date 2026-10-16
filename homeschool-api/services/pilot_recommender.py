"""Evidence-grounded instructional recommendation for the Valor pilot (G2).

A pure function: decrypted evidence records in, one proposal (or an
abstention) out. No I/O, no model call, no clock beyond what the caller
passes — following ``services/policy_engine.py``'s precedent, so a test
states a situation rather than building one and every output is
reproducible from its inputs.

What it deliberately does NOT do, each for a stated reason:

* **It computes no norm, benchmark, or score.** It only reads the support
  category the educator transcribed from the official source report
  (``reported_band``). DIBELS 8 cut points are the publisher's; inventing
  or re-deriving them here would be a claim Bede has no standing to make
  (see ``services/assessment_interop.py`` and
  ``docs/ASSESSMENT_INTEROPERABILITY.md``).
* **It interprets no ``external_other`` framework.** An unregistered
  external score has no agreed meaning, so it is cited as context only and
  can never on its own produce a recommendation.
* **It describes the instruction, never the child.** Wording names a
  practice focus and the evidence it rests on. It never labels, ranks, or
  diagnoses a learner, the same rule ``_WORK_SCORING_NOTE`` gives Bede.
* **It abstains rather than guesses.** No interpretable evidence means no
  recommendation, with the reason stated, because a confident suggestion
  built on nothing is the failure an approval gate cannot catch.

Every proposal is a draft for a teacher. Nothing here reaches a learner
until an educator approves or edits it through the server-enforced
decision route.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

POLICY_VERSION = "pilot-recommender/1"

# Practice focus per DIBELS 8 measure: what to practise, not what the
# child is. Plain, teacher-facing descriptions of the measure's own skill.
_DIBELS_FOCUS = {
    "LNF": "letter-naming practice",
    "PSF": "phoneme segmentation practice (saying the sounds in spoken words)",
    "NWF_CLS": "letter-sound and decoding practice with phonetically regular words",
    "NWF_WRC": "whole-word decoding practice with phonetically regular words",
    "WRF": "word reading practice with grade-level words",
    "ORF_WC": "repeated oral reading of instructional-level text",
    "ORF_ACCURACY": "accuracy-focused oral reading with immediate error correction",
    "MAZE": "sentence-level comprehension practice (choosing words that keep meaning)",
}

# Support categories as transcribed from the official report. Intensive
# first so the most supported need is addressed first.
_SUPPORT_PRIORITY = {
    "intensive_at_risk": 0,
    "well_below_benchmark": 0,
    "strategic_some_risk": 1,
    "below_benchmark": 1,
}
_ON_TRACK = frozenset({
    "core_negligible_risk", "core_minimal_risk", "at_or_above_benchmark",
})

_CLASSICAL_FOCUS = {
    "with_help": "scaffolded, modelled practice in {measure}, then a supported attempt",
    "with_a_hint": "brief guided practice in {measure}, then an independent attempt",
    "unaided": "a more demanding {measure} task that extends what was done independently",
}

MAX_FOCUS_ITEMS = 2


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    framework: str
    measure: str
    assessed_on: date
    reported_band: str | None = None
    assistance: str | None = None
    # When the record was entered. Breaks ties between two results for the
    # same measure on the same assessment date: the later entry is current.
    recorded_at: datetime | None = None


@dataclass(frozen=True)
class Proposal:
    abstained: bool
    reason: str
    text: str = ""
    rationale: tuple[str, ...] = field(default_factory=tuple)
    source_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    policy_version: str = POLICY_VERSION


def _latest_per_measure(records: list[EvidenceRecord]) -> list[EvidenceRecord]:
    """Most recent record per (framework, measure): latest assessment date,
    then latest entry time, then id. The id is only a last resort for exact
    duplicates; it is random, so ordering on it alone would pick an
    arbitrary record whenever two results share a date."""
    latest: dict[tuple[str, str], EvidenceRecord] = {}
    epoch = datetime.min
    for rec in sorted(records, key=lambda r: (
        r.assessed_on,
        (r.recorded_at.replace(tzinfo=None) if r.recorded_at else epoch),
        r.evidence_id,
    )):
        latest[(rec.framework, rec.measure)] = rec
    return list(latest.values())


def recommend(records: list[EvidenceRecord]) -> Proposal:
    if not records:
        return Proposal(True, "No evidence has been recorded for this learner yet.")

    current = _latest_per_measure(records)
    support: list[tuple[int, EvidenceRecord, str]] = []
    on_track: list[EvidenceRecord] = []
    classical: list[tuple[EvidenceRecord, str]] = []

    for rec in current:
        if rec.framework == "dibels8":
            focus = _DIBELS_FOCUS.get(rec.measure)
            if rec.reported_band in _SUPPORT_PRIORITY and focus:
                support.append((_SUPPORT_PRIORITY[rec.reported_band], rec, focus))
            elif rec.reported_band in _ON_TRACK:
                on_track.append(rec)
            # COMPOSITE, not_reported, or no band: nothing to act on alone.
        elif rec.framework == "classical" and rec.assistance in _CLASSICAL_FOCUS:
            label = rec.measure.replace("_", " ")
            classical.append((rec, _CLASSICAL_FOCUS[rec.assistance].format(measure=label)))
        # external_other is never interpreted (see module docstring).

    if support:
        support.sort(key=lambda item: (item[0], item[1].measure))
        chosen = support[:MAX_FOCUS_ITEMS]
        focuses = [focus for _, _, focus in chosen]
        text = "Suggested focus for the next lessons: " + "; ".join(focuses) + "."
        rationale = tuple(
            f"{rec.measure} ({rec.assessed_on.isoformat()}): the source report lists "
            f"'{rec.reported_band}', so this measure's skill is suggested for practice."
            for _, rec, _ in chosen
        )
        ids = tuple(rec.evidence_id for _, rec, _ in chosen)
        return Proposal(False, "Report support categories indicate a practice focus.",
                        text, rationale, ids)

    if classical:
        # Prefer the observation that needed the most help.
        order = {"with_help": 0, "with_a_hint": 1, "unaided": 2}
        classical.sort(key=lambda item: (order[item[0].assistance], item[0].measure))
        chosen_c = classical[:MAX_FOCUS_ITEMS]
        text = "Suggested next step: " + "; ".join(f for _, f in chosen_c) + "."
        rationale = tuple(
            f"{rec.measure.replace('_', ' ')} ({rec.assessed_on.isoformat()}): "
            f"observed {rec.assistance.replace('_', ' ')}."
            for rec, _ in chosen_c
        )
        return Proposal(False, "Recorded classical observations suggest a next step.",
                        text, rationale, tuple(rec.evidence_id for rec, _ in chosen_c))

    if on_track:
        chosen_t = sorted(on_track, key=lambda r: r.measure)[:MAX_FOCUS_ITEMS]
        text = ("Suggested: continue current instruction and re-check these measures "
                "at the next progress-monitoring window.")
        rationale = tuple(
            f"{rec.measure} ({rec.assessed_on.isoformat()}): the source report lists "
            f"'{rec.reported_band}'." for rec in chosen_t
        )
        return Proposal(False, "Report support categories indicate no change is needed.",
                        text, rationale, tuple(r.evidence_id for r in chosen_t))

    return Proposal(
        True,
        "The recorded evidence carries no reported support category or observation "
        "this policy can act on, so no recommendation is made.",
    )
