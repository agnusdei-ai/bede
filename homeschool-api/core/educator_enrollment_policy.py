"""Institutional educator enrollment policy; pure security decisions.

Not a WebAuthn verifier. Authentication is disabled until a real RP, challenge
storage, attestation/assertion verification, counters and session issuance
are integrated. Never accept email or a PIN as a substitute for WebAuthn.
"""
from dataclasses import dataclass
from enum import Enum


class EnrollmentStage(str, Enum):
    INVITED = "invited"
    EMAIL_CONFIRMED = "email_confirmed"
    PASSKEY_REGISTERED = "passkey_registered"
    ACTIVE = "active"
    RECOVERY_PENDING = "recovery_pending"
    SUSPENDED = "suspended"


@dataclass(frozen=True)
class EducatorEnrollment:
    stage: EnrollmentStage
    institution_id: str
    educator_id: str
    institutional_email_verified: bool
    active_passkey_count: int
    administrator_approved: bool
    verified_passkey_assertion: bool = False
    recovery_approval_count: int = 0


def can_activate(enrollment: EducatorEnrollment) -> bool:
    return bool(
        enrollment.stage == EnrollmentStage.PASSKEY_REGISTERED
        and enrollment.institution_id
        and enrollment.educator_id
        and enrollment.institutional_email_verified
        and enrollment.administrator_approved
        and enrollment.active_passkey_count >= 1
    )


def can_issue_educator_session(enrollment: EducatorEnrollment) -> bool:
    return bool(
        enrollment.stage == EnrollmentStage.ACTIVE
        and enrollment.administrator_approved
        and enrollment.active_passkey_count >= 1
        and enrollment.verified_passkey_assertion
    )


def can_begin_recovery(enrollment: EducatorEnrollment) -> bool:
    # Confirmation of the mailbox is only a notification/recovery initiation.
    # It never provides access, resets an authenticator or reassigns a roster.
    return bool(
        enrollment.stage in {EnrollmentStage.ACTIVE, EnrollmentStage.RECOVERY_PENDING}
        and enrollment.institutional_email_verified
        and enrollment.institution_id
        and enrollment.educator_id
    )


def can_replace_lost_passkey(enrollment: EducatorEnrollment) -> bool:
    # Recovery requires a distinct authorized administrator's supervised
    # approval plus re-verification of the institution affiliation.
    # Approval-count is a placeholder policy input, NOT an implementation of
    # admin identity or an authorization grant.
    return bool(
        enrollment.stage == EnrollmentStage.RECOVERY_PENDING
        and enrollment.institutional_email_verified
        and enrollment.administrator_approved
        and enrollment.recovery_approval_count >= 1
    )
