"""What Bede proposes from one finalized official record, case by case.

Pilot content review 2026-11-15 found two proposals that said more than the
report did: a composite printed "Well Below Benchmark" was answered with
"continue current instruction", and so was a record with no printed label
at all. Both are pinned here, with the cases that were already right.
"""
from services.canonical_assessment import POLICY_VERSION, propose


def _score(measure, benchmark=None, support=None, composite=False, status="scored"):
    return {"measure": measure, "administration_status": status,
            "benchmark_label": benchmark, "support_label": support, "is_composite": composite}


def test_a_flagged_composite_alone_is_never_answered_with_continue():
    for label in ("Well Below Benchmark", "Below Benchmark"):
        p = propose([_score("Composite", label, composite=True)], None)
        assert not p.abstained
        assert "continue current instruction" not in p.text
        assert "composite" in p.text and "teacher" in p.text
    p = propose([_score("Composite", support="Most Support", composite=True),
                 _score("PSF", "At Benchmark")], None)
    assert "continue current instruction" not in p.text


def test_no_printed_label_suggests_no_focus_and_never_says_continue():
    p = propose([_score("PSF"), _score("ORF")], None)
    # Still a proposal, so the teacher can record a decision and a plan.
    assert not p.abstained
    assert "no focus is suggested" in p.text and "teacher" in p.text
    assert "continue current instruction" not in p.text
    assert "No benchmark or support label was entered for any measure." in p.rationale


def test_a_flagged_measure_is_named_and_the_composite_is_not():
    p = propose([_score("PSF", support="Most Support"),
                 _score("Composite", "Below Benchmark", composite=True),
                 _score("NWF-CLS", "At Benchmark")], None)
    assert "targeted practice on PSF " in p.text
    assert "Composite" not in p.text and "NWF-CLS" not in p.text
    assert "PSF: printed label Most Support" in p.rationale


def test_continue_is_proposed_only_when_every_printed_label_is_on_track():
    p = propose([_score("PSF", "At Benchmark"), _score("Composite", "Above Benchmark", composite=True)], None)
    assert p.text.startswith("Proposed: continue current instruction")


def test_nothing_scored_abstains_and_a_skipped_measure_is_never_flagged():
    assert propose([_score("PSF", "Well Below Benchmark", status="not_administered_by_rule")], None).abstained


def test_the_proposal_describes_instruction_never_the_child():
    cases = [[_score("PSF", "Well Below Benchmark")], [_score("Composite", "Below Benchmark", composite=True)],
             [_score("PSF", "At Benchmark")]]
    for scores in cases:
        text = propose(scores, None).text.lower()
        for word in ("struggl", "behind", "weak", "deficit", "diagnos", "at risk", "low ", "poor"):
            assert word not in text, (word, text)


def test_the_policy_version_moved_with_the_wording():
    assert POLICY_VERSION == "canonical-review-2026-11-15"
