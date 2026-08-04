"""
Phase 5.2 — measuring the engine against GROUND TRUTH.

WHY THIS EXISTS, GIVEN test_mastery.py ALREADY HAS AN ACCEPTANCE TEST.

Phase 1's acceptance test (`test_synthetic_stream_converges_and_never_leaves_
prerequisites_behind`) feeds all-correct evidence up a prerequisite chain and
asserts the vector rises. That proves DIRECTION. It cannot prove ACCURACY,
because every answer in it is correct — so it can never catch the engine
calling a skill "secure" for a child who does not have it. That is the error
that actually reaches a family, and until this file nothing measured it.

Here the truth is known because we generate it: a synthetic student with a
real knowledge state, prerequisite-closed so it is coherent (knowing a skill
implies knowing what it is built on). Answers are then sampled from the DINA
response model — mastered → correct with P(1-slip), not mastered → correct
with P(guess) — fed through the real engine, and the engine's own verdicts
are scored against the state we started from.

THE ERROR THAT MATTERS IS NOT SYMMETRIC. Telling a parent their child is
secure on something they cannot do sends the family PAST a gap: the next
lesson builds on sand, and nobody knows why it collapsed. Understating a
skill the child does have is cheaper — it costs some review time. So
"false-secure" is bounded tightly here and "false-gap" loosely, on purpose.

HONEST LIMITS, stated because these numbers look more authoritative than
they are:

  1. The simulator generates data from the SAME model the engine assumes.
     That is a friendly world. `test_accuracy_survives_a_world_messier_than
     _the_engine_assumes` deliberately breaks the assumption, and it is the
     more informative test of the two.
  2. Real evidence is not sampled from any distribution — it is Bede's
     judgement of a child's spoken answer, which carries its own error that
     nothing here models.
  3. This measures the ESTIMATOR, not the tutoring. A perfectly calibrated
     vector built from probes a child never really got asked is still wrong.
     That gap closes only with unit 5.1's real session.

The thresholds below are regression floors with headroom, not targets. They
exist so a future change that quietly degrades accuracy fails a test instead
of reaching a family.
"""
import random
from collections import Counter

import pytest

from services.diagnostic.mastery import (
    bayesian_update, calibration_weight_for, new_vector,
)
from services.diagnostic.skill_map import (
    GradeBand, all_skill_ids, get_skill, prerequisites_of,
)

SECURE_CUTOFF = 0.8
DEVELOPING_CUTOFF = 0.4
BAND_ORDER = [GradeBand.K_2.value, GradeBand.THREE_5.value, GradeBand.SIX_8.value]

# Fixed so a failure is reproducible and a pass is not luck. Raising the
# student count narrows the noise band; 40 keeps the suite fast while leaving
# every assertion below comfortably outside sampling error.
SEED = 7
N_STUDENTS = 40
# Roughly a term of opportunistic math evidence. Deliberately not a number
# that flatters the engine — see test_one_sitting_decides_only_a_fraction.
N_EVIDENCE = 30


def _prerequisite_closure(seeds: list[str], known_ids: set[str]) -> set[str]:
    """A knowledge state must be downward-closed over the DAG, or the 'truth'
    we score against is one no real child could hold."""
    known: set[str] = set()
    stack = list(seeds)
    while stack:
        skill = stack.pop()
        if skill in known or skill not in known_ids:
            continue
        known.add(skill)
        stack.extend(prerequisites_of(skill))
    return known


def _make_student(rng: random.Random, band: str, mastery_fraction: float):
    ids = all_skill_ids()
    band_index = BAND_ORDER.index(band)
    reachable = [
        s for s in ids
        if BAND_ORDER.index(get_skill(s).band.value) <= band_index
    ]
    count = max(1, int(len(reachable) * mastery_fraction))
    truth = _prerequisite_closure(rng.sample(reachable, count), set(ids))
    return truth, reachable


def _answer(rng: random.Random, truth: set[str], skill: str,
            slip: float, guess: float) -> str:
    """DINA: conjunctive over the skill and everything it is built on."""
    has_it = skill in truth and all(p in truth for p in prerequisites_of(skill))
    probability_correct = (1.0 - slip) if has_it else guess
    return "correct" if rng.random() < probability_correct else "incorrect"


def _verdicts(truth: set[str], vector: dict, reachable: list[str]) -> Counter:
    """Score what a parent would actually be told against what is true."""
    tally: Counter = Counter()
    for skill in reachable:
        probability = vector.get(skill, 0.5)
        really_has_it = skill in truth
        tally["n"] += 1
        if probability >= SECURE_CUTOFF:
            tally["true_secure" if really_has_it else "false_secure"] += 1
        elif probability < DEVELOPING_CUTOFF:
            tally["false_gap" if really_has_it else "true_gap"] += 1
        else:
            tally["undecided"] += 1  # 'developing' — an honest hedge
    return tally


def _cohort(mastery_fraction: float, world_slip: float = 0.10,
            world_guess: float = 0.20, n_evidence: int = N_EVIDENCE,
            band: str = "3-5") -> dict:
    rng = random.Random(SEED)
    totals: Counter = Counter()
    for _ in range(N_STUDENTS):
        truth, reachable = _make_student(rng, band, mastery_fraction)
        vector = new_vector(band)
        for i in range(n_evidence):
            skill = rng.choice(reachable)
            vector, _ = bayesian_update(
                vector,
                {
                    "probe_id": f"probe.{skill}",
                    "outcome": _answer(rng, truth, skill, world_slip, world_guess),
                    "confidence": 1.0,
                },
                calibration_weight=calibration_weight_for(i),
            )
        totals += _verdicts(truth, vector, reachable)
    n = totals["n"]
    decided = n - totals["undecided"]
    correct = totals["true_secure"] + totals["true_gap"]
    return {
        "decided_fraction": decided / n,
        "accuracy_where_decided": correct / decided if decided else 0.0,
        "false_secure_rate": totals["false_secure"] / n,
        "false_gap_rate": totals["false_gap"] / n,
    }


COHORTS = {"struggling": 0.15, "middle": 0.50, "advanced": 0.85}


@pytest.mark.parametrize("cohort", sorted(COHORTS))
def test_a_child_is_rarely_called_secure_on_a_skill_they_do_not_have(cohort):
    """The error that sends a family past a gap. Bounded for EVERY cohort,
    not just on average — an engine accurate on aggregate while failing the
    children who need it most would pass a mean and fail a family."""
    result = _cohort(COHORTS[cohort])
    assert result["false_secure_rate"] < 0.07, (
        f"{cohort}: {result['false_secure_rate']:.2%} of skills were called "
        f"secure for a child who does not have them"
    )


@pytest.mark.parametrize("cohort", sorted(COHORTS))
def test_the_verdicts_it_does_commit_to_are_mostly_right(cohort):
    result = _cohort(COHORTS[cohort])
    assert result["accuracy_where_decided"] > 0.80, (
        f"{cohort}: only {result['accuracy_where_decided']:.1%} of committed "
        f"verdicts were correct"
    )


def test_the_struggling_child_is_not_served_far_worse_than_the_advanced_one():
    """The Phase 5.2 headline, pinned so it cannot silently return.

    At the pre-tuning guess of 0.20 this gap was 9.3% vs 0.8% — a struggling
    child was ~12x more likely to be told they were secure on something they
    could not do. `guess` is P(correct | not mastered), so understating it
    mis-credits lucky answers, and a child who has mastered less produces far
    more not-mastered attempts for it to mis-credit. The bias therefore grows
    exactly as true mastery falls, which is backwards from what a diagnostic
    is for. See mastery.TUNED_PARAMS.
    """
    struggling = _cohort(COHORTS["struggling"])["false_secure_rate"]
    advanced = _cohort(COHORTS["advanced"])["false_secure_rate"]
    assert struggling < advanced + 0.06, (
        f"struggling students draw a false-secure verdict at {struggling:.2%} "
        f"vs {advanced:.2%} for advanced ones — the engine is least accurate "
        f"for the children who most need it to be right"
    )


def test_accuracy_survives_a_world_messier_than_the_engine_assumes():
    """The engine assumes slip 0.10 / guess 0.25. Real children are noisier,
    and a Socratic dialogue with hints raises the effective guess rate well
    above anything a written test would show. Degrading gracefully here
    matters more than peak accuracy in the tidy case."""
    for cohort, fraction in COHORTS.items():
        result = _cohort(fraction, world_slip=0.25, world_guess=0.35)
        assert result["accuracy_where_decided"] > 0.70, (
            f"{cohort} collapses to {result['accuracy_where_decided']:.1%} "
            f"when the world is messier than assumed"
        )
        assert result["false_secure_rate"] < 0.12, (
            f"{cohort}: {result['false_secure_rate']:.2%} false-secure under stress"
        )


def test_understating_a_skill_stays_rarer_than_the_hedge():
    """The cheap error should still be rare, and 'developing' — saying
    nothing confident — should absorb the uncertainty instead. An engine that
    resolved its doubt by calling things gaps would read as a child going
    backwards."""
    result = _cohort(COHORTS["middle"])
    assert result["false_gap_rate"] < 0.05
    assert result["decided_fraction"] < 0.95, (
        "the engine committed on almost everything — it is not hedging at all"
    )


def test_one_sitting_decides_only_a_fraction_of_the_map():
    """Not a defect — the honest shape of opportunistic evidence, and the
    thing 'still getting to know your learner' is actually describing.

    A 20-minute math block yields a handful of evidence points, not thirty.
    So a parent opening Progress after one session should see most of the map
    undecided, and the summary should keep saying so. This is pinned because
    a future change that makes one session look confident about the whole map
    would be a regression in honesty, not an improvement in coverage.
    """
    one_sitting = _cohort(COHORTS["middle"], n_evidence=4)
    a_term = _cohort(COHORTS["middle"], n_evidence=60)
    assert one_sitting["decided_fraction"] < 0.35
    assert a_term["decided_fraction"] > one_sitting["decided_fraction"], (
        "more evidence must decide more of the map, or the engine is not learning"
    )


def test_accuracy_does_not_degrade_as_evidence_accumulates():
    """Guards the failure mode where an estimator drifts confidently wrong:
    more evidence must never make the committed verdicts worse."""
    early = _cohort(COHORTS["middle"], n_evidence=10)
    late = _cohort(COHORTS["middle"], n_evidence=60)
    assert late["accuracy_where_decided"] > early["accuracy_where_decided"] - 0.05
