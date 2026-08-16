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
import inspect
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


# ── Cold start: a grade is not evidence ──────────────────────────────────
#
# The priors used to seed below-band skills up to 0.9, above the 0.80 secure
# cutoff, so a brand-new 6-8 student's profile reported 24 of 95 skills as
# Mastered before Bede had asked a single question. These pin the rule that
# replaced it — assume the child has probably MET earlier material, never
# that they have mastered it.

@pytest.mark.parametrize("band", ["K-2", "3-5", "6-8"])
def test_no_skill_is_ever_reported_secure_without_evidence(band):
    """
    The hard invariant, and the reason the prior scheme changed. A grade is
    not evidence. Whatever the seeding rule becomes later, a cold-start
    vector must never contain a skill a parent would be shown as Mastered.
    """
    vector = new_vector(band)
    secure = {s: p for s, p in vector.items() if p >= SECURE_CUTOFF}
    assert not secure, (
        f"{band}: {len(secure)} skills would be reported Mastered before the "
        f"child has been asked anything — e.g. {sorted(secure)[:3]}"
    )


@pytest.mark.parametrize("band", ["K-2", "3-5", "6-8"])
def test_the_below_band_prior_stays_inside_its_window(band):
    """
    The other half of the rule, and it is NOT "assume nothing" — the window
    has two live edges and the lower one is easy to forget.

    Above kst.fringe's `prereq_hi`, or every unprobed earlier-band
    prerequisite blocks its dependents and a student's whole "next steps"
    list collapses to the two skills with no prerequisites at all — see
    test_next_steps_band_leak.py, which caught exactly that when this
    change first went too far. Below the secure cutoff, or a grade alone
    reports a skill as Mastered.
    """
    from services.diagnostic.kst import fringe as _fringe

    prereq_hi = inspect.signature(_fringe).parameters["prereq_hi"].default
    vector = new_vector(band)
    band_index = BAND_ORDER.index(band)
    below = [
        s for s in all_skill_ids()
        if BAND_ORDER.index(get_skill(s).band.value) < band_index
    ]
    if not below:
        pytest.skip(f"{band} has no band beneath it")
    assert all(vector[s] > prereq_hi for s in below), (
        "an unprobed earlier-band skill would block its dependents"
    )
    assert all(vector[s] < SECURE_CUTOFF for s in below), (
        "a grade alone would report an earlier-band skill as Mastered"
    )


def test_the_false_secure_collapse_this_bought_stays_bought():
    """
    Measured, not asserted from taste. Band 6-8 is where the old scheme did
    its damage (the only band with two beneath it), and the struggling
    cohort is where it did the most: false-secure ran at 13.1% before this
    change and 1.9% after, with accuracy on committed verdicts RISING from
    70.0% to 92.1% — the coverage that was lost had been largely wrong.

    The floor is set with headroom above the measured 1.9%, not at it.
    """
    result = _cohort(COHORTS["struggling"], band="6-8")
    assert result["false_secure_rate"] < 0.04, (
        f"false-secure at {result['false_secure_rate']:.2%} for a struggling "
        f"6-8 student — the regression this file exists to catch"
    )
    assert result["accuracy_where_decided"] > 0.85, (
        f"only {result['accuracy_where_decided']:.1%} of committed verdicts "
        f"were right for a struggling 6-8 student"
    )


# ── No child is ever restarted by a tuning change ────────────────────────
#
# The question this had to answer before it could ship: does re-tuning the
# engine throw away what a family has already accumulated? It does not, and
# the reason is structural rather than careful — but structural properties
# are exactly the ones that get broken by an unrelated refactor, so they are
# asserted here.

def test_retuning_never_touches_a_vector_a_family_already_has():
    """
    Priors apply at cold start and at ensure_complete's backfill of skills
    that did not exist when the row was written. They are not re-applied to
    a stored probability, so a child who has been assessed keeps every value
    they earned — no reset, no recompute, no re-test.
    """
    from services.diagnostic.mastery import ensure_complete

    earned = {"cc.rote_count_20": 0.93, "fr.divide_fractions": 0.31}
    after = ensure_complete(dict(earned), "6-8")
    for skill_id, probability in earned.items():
        assert after[skill_id] == probability, (
            f"{skill_id} was rewritten from {probability} to {after[skill_id]} "
            f"— a family's accumulated evidence must survive a tuning change"
        )


def test_the_calibration_threshold_is_read_time_and_write_forward_only():
    """
    CALIBRATION_THRESHOLD is used in exactly two ways, neither retroactive:
    build_summary_view reads it on every render to decide whether to show
    the "still getting to know your learner" banner, and
    calibration_weight_for uses it to weight the NEXT piece of evidence.
    Past updates are already folded into the stored probability and are
    never recomputed, so moving the threshold cannot rewrite history.
    """
    stored = 0.72
    for threshold in (3, 5, 20):
        vector, _ = bayesian_update(
            {"fr.divide_fractions": stored},
            {"probe_id": "probe.fr.divide_fractions", "outcome": "correct", "confidence": 1.0},
            calibration_weight=calibration_weight_for(99, threshold),
        )
        # Past the threshold the weight is 1.0 regardless of what the
        # threshold is, so a settled learner's updates are identical.
        assert vector["fr.divide_fractions"] == pytest.approx(
            bayesian_update(
                {"fr.divide_fractions": stored},
                {"probe_id": "probe.fr.divide_fractions", "outcome": "correct", "confidence": 1.0},
                calibration_weight=1.0,
            )[0]["fr.divide_fractions"]
        )
