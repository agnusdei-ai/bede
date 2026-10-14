from dataclasses import replace

from core.educator_enrollment_policy import (
    EducatorEnrollment, EnrollmentStage, can_activate,
    can_begin_recovery, can_issue_educator_session, can_replace_lost_passkey,
)


def enrolled():
    return EducatorEnrollment(
        stage=EnrollmentStage.PASSKEY_REGISTERED,
        institution_id="valor-campus-1", educator_id="teacher-1",
        institutional_email_verified=True, active_passkey_count=1,
        administrator_approved=True,
    )


def test_no_activation_without_verified_passkey_and_approval():
    assert can_activate(enrolled())
    assert not can_activate(replace(enrolled(), active_passkey_count=0))
    assert not can_activate(replace(enrolled(), administrator_approved=False))
    assert not can_activate(replace(enrolled(), institutional_email_verified=False))


def test_institutional_email_and_pin_never_create_login_session():
    active = replace(enrolled(), stage=EnrollmentStage.ACTIVE)
    assert not can_issue_educator_session(active)
    assert can_issue_educator_session(replace(active, verified_passkey_assertion=True))


def test_recovery_requires_approval_and_never_signs_in_by_email():
    active = replace(enrolled(), stage=EnrollmentStage.ACTIVE)
    assert can_begin_recovery(active)
    assert not can_issue_educator_session(active)
    pending = replace(active, stage=EnrollmentStage.RECOVERY_PENDING)
    assert not can_replace_lost_passkey(pending)
    assert can_replace_lost_passkey(replace(pending, recovery_approval_count=1))
    assert not can_issue_educator_session(replace(pending, recovery_approval_count=1))
    assert not can_replace_lost_passkey(replace(pending, institutional_email_verified=False))
