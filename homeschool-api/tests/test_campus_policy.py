from core.campus_policy import CampusSubject, campus_allowed


def subject(**kwargs):
    data = dict(actor_id="t1", role="educator", identity_domain="campus",
                campus_id="c1", approved_pod_ids=frozenset({"p1"}),
                mfa_verified=True)
    data.update(kwargs)
    return CampusSubject(**data)


def test_assigned_pod_teacher_allowed():
    assert campus_allowed(subject(), "campus.lesson.draft",
                          resource_campus_id="c1", pod_id="p1")


def test_cross_campus_and_unassigned_pods_denied():
    for campus, pod in [("c2", "p1"), ("c1", "p2"), ("c1", None)]:
        assert not campus_allowed(subject(), "campus.progress.read",
                                  resource_campus_id=campus, pod_id=pod)


def test_unknown_role_domain_and_action_fail_closed():
    assert not campus_allowed(subject(identity_domain="family"),
                              "campus.pod.read", resource_campus_id="c1", pod_id="p1")
    assert not campus_allowed(subject(role="superuser"),
                              "campus.pod.read", resource_campus_id="c1", pod_id="p1")
    assert not campus_allowed(subject(), "admin.privileged",
                              resource_campus_id="c1", pod_id="p1")


def test_mfa_and_sensitive_step_up():
    assert not campus_allowed(subject(mfa_verified=False), "campus.lesson.approve",
                              resource_campus_id="c1", pod_id="p1")
    admin = subject(role="campus_admin")
    assert not campus_allowed(admin, "campus.report.export",
                              resource_campus_id="c1", pod_id="p1")
    assert campus_allowed(subject(role="campus_admin", step_up_verified=True),
                          "campus.report.export", resource_campus_id="c1", pod_id="p1")


def test_guardian_and_service_operator_cannot_read_teacher_records():
    for role in ("guardian", "service_operator", "campus_learner"):
        assert not campus_allowed(subject(role=role), "campus.progress.read",
                                  resource_campus_id="c1", pod_id="p1")


def test_empty_identity_and_missing_mfa_denied_for_admin():
    for field in ('actor_id', 'campus_id'):
        assert not campus_allowed(subject(role="campus_admin", **{field: ''}),
                                  "campus.roster.manage", resource_campus_id="c1")
    assert not campus_allowed(subject(role="campus_admin", mfa_verified=False,
                                      step_up_verified=True), "campus.settings.manage",
                              resource_campus_id="c1")


def test_admin_step_up_never_crosses_campus_boundary():
    assert not campus_allowed(subject(role="campus_admin", step_up_verified=True),
                              "campus.report.export", resource_campus_id="c2", pod_id="p1")
