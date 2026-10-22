from services.classical_source_intelligence import (
    ClassicalSource, SkillEvidence, eligible, search, propose_follow_up,
)


def source(rights="US_PUBLIC_DOMAIN_VERIFIED", approved=True, verified=True):
    return ClassicalSource("book-1", "Practical Fractions", "fractions and ratios",
                           "mathematics", ("fraction_comparison",), rights,
                           verified, approved, "Book 1, section 2", "1")


def test_only_approved_and_verified_commercially_compatible_sources():
    assert eligible(source())
    assert not eligible(source("CC_BY_NC_SA"))
    assert not eligible(source(approved=False))
    assert not eligible(source(verified=False))
    assert search([source("CC_BY_NC_SA"), source()], subject="mathematics",
                  skill_id="fraction_comparison", query="fractions") == [source()]


def test_insufficient_evidence_never_asserts_gap():
    proposal = propose_follow_up(sources=[source()], subject="mathematics",
        skill_id="fraction_comparison", evidence=[
            SkillEvidence("fraction_comparison", 0, 2, True, "session-1")],
        query="fractions")
    assert proposal.reason.startswith("insufficient_")
    assert proposal.source_ids == ()


def test_repeated_difficulty_proposes_only_teacher_reviewed_source():
    proposal = propose_follow_up(sources=[source()], subject="mathematics",
        skill_id="fraction_comparison", evidence=[
            SkillEvidence("fraction_comparison", 1, 3, True, "session-1"),
            SkillEvidence("fraction_comparison", 1, 3, True, "session-2")],
        query="fractions")
    assert proposal.source_ids == ("book-1",)
    assert proposal.requires_educator_approval


def test_missing_verified_source_escalates():
    proposal = propose_follow_up(sources=[source("CC_BY_NC_SA")], subject="mathematics",
        skill_id="fraction_comparison", evidence=[
            SkillEvidence("fraction_comparison", 0, 3, True, "session-1"),
            SkillEvidence("fraction_comparison", 0, 3, True, "session-2")],
        query="fractions")
    assert proposal.source_ids == ()
    assert "escalate" in proposal.reason
