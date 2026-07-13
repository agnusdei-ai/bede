"""
Parent agreement / platform-scope disclaimer — the required, versioned
sign-off gating access to ParentSetup and the rest of the parent-only UI
(see routers/parent_agreement.py). Bede does not diagnose or screen for
ADHD, autism, or any other condition, and does not adapt its teaching
method to accommodate special-needs learning approaches; it is a Socratic,
classical-tradition tutoring supplement designed to run with reduced
parental supervision (sessions up to two hours, with built-in breaks
between subjects).

⚠️ DRAFT — PENDING LEGAL REVIEW. This wording reflects the product's
stated scope as of the day it was written, but has not been reviewed by
counsel. Do not treat it as final, and do not remove this warning until a
lawyer has signed off — especially the "Your Responsibility" section below,
which is explicitly a placeholder for standard waiver/liability language.

CURRENT_VERSION is a plain string, bumped whenever the wording changes
materially. routers/parent_agreement.py compares a parent's
accepted_version against this constant, not just "has anyone ever
accepted" — so bumping it is what forces every parent to re-accept the
next time they open a parent-only page.
"""
from models.schemas import ParentAgreementSection

CURRENT_VERSION = "2026-07-13-draft"


SECTIONS: list[ParentAgreementSection] = [
    ParentAgreementSection(
        heading="Platform Scope",
        body=(
            "Bede is a Socratic, classical-tradition tutoring supplement for "
            "homeschooling families, designed to run with reduced direct "
            "parental supervision — sessions of up to two hours with built-in "
            "breaks between subjects, so you don't need to sit with your "
            "child the entire time. Bede is not designed, tested, or intended "
            "to accommodate ADHD, autism, or other developmental, learning, "
            "or behavioral differences, and does not adapt its teaching "
            "method for those needs. Bede's expertise is Socratic dialogue in "
            "the classical philosophical tradition — nothing more."
        ),
    ),
    ParentAgreementSection(
        heading="No Diagnosis, No Screening",
        body=(
            "Bede does not test, screen, or evaluate for ADHD, autism, or any "
            "medical, psychological, developmental, or behavioral condition. "
            "Any pattern Bede's learner-profile feature surfaces (for "
            "example, a child's attention span or engagement across "
            "sessions) describes only what was observed during tutoring — it "
            "is not a clinical finding, is not reviewed by a qualified "
            "professional, and must never be treated as a diagnosis or a "
            "substitute for one. If Bede surfaces something, or you notice "
            "something yourself, that concerns you, please consult your "
            "child's pediatrician, a licensed psychologist, or your school "
            "district's evaluation services."
        ),
    ),
    ParentAgreementSection(
        heading="Your Responsibility",
        body=(
            "You are solely responsible for deciding whether Bede — "
            "including its reduced-supervision, up-to-two-hour format — is "
            "right for your child, and for providing whatever supervision "
            "your child needs.\n\n"
            "[PLACEHOLDER — PENDING LEGAL REVIEW: standard assumption-of-"
            "risk, no-warranty, limitation-of-liability, and indemnification "
            "language belongs here. Replace this bracketed text with "
            "counsel-approved wording before this agreement is presented to "
            "real users.]"
        ),
    ),
    ParentAgreementSection(
        heading="Acknowledgment",
        body=(
            "By accepting below, you confirm you've read and agree to the "
            "above, and accept full responsibility for your child's use of "
            "the platform accordingly."
        ),
    ),
]
