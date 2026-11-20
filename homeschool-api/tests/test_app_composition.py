"""
Composition tests for the ASSEMBLED application (P11).

Why this file exists, stated precisely because the distinction is the whole
point. Mutation-testing the codebase on 2026-08-03 gave two opposite results:

  * Break a control's own LOGIC — 16 of 16 mutations were caught. The
    controls are genuinely exercised.
  * Break a control's WIRING — 0 of 8 were caught. Every security middleware
    could be unmounted from main.py, the ExfiltrationGuard/GZip ordering bug
    that started this entire engagement could be reintroduced verbatim, and
    guards on real endpoints could be downgraded to weaker ones — and all
    1,603 tests still passed.

That gap is exactly what P11 names. A unit test cannot see it by
construction: the control's code is correct in every case, and only its
position in the assembled system is wrong. The suite tested 125 files' worth
of components and almost nothing about how they are composed.

So these tests assert composition and nothing else. They are deliberately
boring, table-driven, and brittle-by-design: if you change the middleware
order or an endpoint's guard, this file fails and you update the table
consciously. That is the intended workflow — the table is the artifact a
reviewer reads to answer "what protects what", and a diff to it is the
signal that a protection boundary moved.
"""
import pytest
from fastapi.routing import APIRoute, _IncludedRouter

# Outermost first — this is `app.user_middleware` order, which is the REVERSE
# of the add_middleware() call order in main.py (Starlette inserts each new
# entry at the front of the list). GZipMiddleware must stay first here: it is
# added last in main.py precisely so it compresses only after
# ExfiltrationGuard has already scanned the plaintext response. Reversing
# those two is the original inert-guard bug.
EXPECTED_MIDDLEWARE = [
    "GZipMiddleware",
    "LicenseGateMiddleware",
    "CORSMiddleware",
    "RateLimitMiddleware",
    "ExfiltrationGuard",
    "InstanceIdHeaderMiddleware",
    "SecurityHeadersMiddleware",
]

# Dependencies that are plumbing rather than protection.
_NOT_A_GUARD = {"get_db", "bind_request"}

# (method, path) -> the guard chain protecting it, or "PUBLIC".
#
# "PUBLIC" is a claim, not an oversight: each is reachable without a token by
# design — logging in, asking which locales exist, minting a demo code,
# entering account recovery, validating a token you already hold, and asking
# whether the feedback form is switched on. A new PUBLIC row appearing in a
# diff is the thing to challenge in review.
GUARDS = {
    # Public readiness probe, registered directly on the app.
    ('GET', '/health'): 'PUBLIC',
    # Public intake and passkey ceremonies authenticate their own tickets or
    # challenges; invitation and recovery issuance require elevated parent.
    ('POST', '/inquiries'): 'PUBLIC',
    ('POST', '/auth/educator-passkey/invite'): 'require_elevated_parent',
    ('POST', '/auth/educator-passkey/recovery/{educator_id}'): 'require_elevated_parent',
    ('POST', '/auth/educator-passkey/register/options'): 'PUBLIC',
    ('POST', '/auth/educator-passkey/register/verify'): 'PUBLIC',
    ('POST', '/auth/educator-passkey/login/options'): 'PUBLIC',
    ('POST', '/auth/educator-passkey/login/verify'): 'PUBLIC',
    ('GET', '/auth/educator-passkey/credentials'): 'require_educator',
    ('POST', '/auth/educator-passkey/credentials/{credential_id}/revoke'): 'require_educator',
    # Practice routes combine their audience guard with the feature switch.
    ('GET', '/practice/status'): 'require_auth',
    ('GET', '/practice/packs'): 'require_parent+require_practice_coach_enabled',
    ('GET', '/practice/quiz-options'): 'require_parent+require_practice_coach_enabled',
    ('POST', '/practice/{student_name}/quizzes/source'): 'require_parent+require_practice_coach_enabled',
    ('GET', '/practice/progress/{progress_id}'): 'require_parent+require_practice_coach_enabled',
    ('GET', '/practice/educator/progress/{progress_id}'): 'require_educator+require_practice_coach_enabled',
    ('POST', '/practice/educator/quiz/source'): 'require_educator+require_practice_coach_enabled',
    ('POST', '/practice/{student_name}/quizzes/generate'): 'require_parent+require_practice_coach_enabled',
    ('GET', '/practice/educator/quiz-options'): 'require_educator+require_practice_coach_enabled',
    ('POST', '/practice/educator/quiz/generate'): 'require_educator+require_practice_coach_enabled',
    ('POST', '/practice/educator/teacher-quiz/review'): 'require_educator+require_practice_coach_enabled',
    ('POST', '/practice/educator/teacher-quiz/approve'): 'require_educator+require_practice_coach_enabled',
    ('POST', '/practice/educator/teacher-quiz/extract'): 'require_educator+require_practice_coach_enabled',
    ('POST', '/practice/educator/teacher-quiz/score'): 'require_educator+require_practice_coach_enabled',
    ('POST', '/practice/educator/teacher-quiz/finalize'): 'require_educator+require_practice_coach_enabled',
    ('GET', '/practice/reading-route'): 'require_parent+require_practice_coach_enabled',
    ('POST', '/practice/{student_name}/assessments/read'): 'require_parent+require_practice_coach_enabled',
    ('POST', '/practice/{student_name}/assessments'): 'require_parent+require_practice_coach_enabled',
    ('PUT', '/practice/{student_name}/assessments/{record_id}'): 'require_parent+require_practice_coach_enabled',
    ('POST', '/practice/{student_name}/assessments/{record_id}/plan'): 'require_parent+require_practice_coach_enabled',
    ('GET', '/practice/{student_name}/sets'): 'require_parent+require_practice_coach_enabled',
    ('GET', '/practice/{student_name}/delivery'): 'require_practice_coach_enabled+require_real_user',
    ('POST', '/practice/{student_name}/sets/{set_id}/outcomes'): 'require_family_data_write+require_practice_coach_enabled',
    ('GET', '/practice/demo/packs'): 'require_demo_practice_preview+require_practice_coach_enabled',
    ('GET', '/practice/demo/reading-route'): 'require_demo_practice_preview+require_practice_coach_enabled',
    ('GET', '/practice/demo/quiz-options'): 'require_demo_practice_preview+require_practice_coach_enabled',
    ('POST', '/practice/demo/quiz/generate'): 'require_demo_practice_preview+require_practice_coach_enabled',
    ('POST', '/practice/demo/quiz/source'): 'require_demo_practice_preview+require_practice_coach_enabled',
    ('GET', '/practice/demo/progress/{progress_id}'): 'require_demo_practice_preview+require_practice_coach_enabled',
    ('POST', '/practice/demo/read'): 'require_demo_practice_preview+require_practice_coach_enabled',
    ('POST', '/practice/demo/plan'): 'require_demo_practice_preview+require_practice_coach_enabled',
    ('POST', '/practice/demo/approve'): 'require_demo_practice_preview+require_practice_coach_enabled',
    ('POST', '/practice/{student_name}/sets/{set_id}/approve'): 'require_parent+require_practice_coach_enabled',
    ('POST', '/practice/{student_name}/sets/{set_id}/discard'): 'require_parent+require_practice_coach_enabled',
    # Campus administration is elevated; educators additionally resolve a
    # learner's current assignment inside the route.
    ('POST', '/pilot/campuses'): 'require_elevated_parent',
    ('POST', '/pilot/campuses/{campus_id}/learners'): 'require_elevated_parent',
    ('POST', '/pilot/campuses/{campus_id}/educators/{educator_id}'): 'require_elevated_parent',
    ('POST', '/pilot/campuses/{campus_id}/educators/{educator_id}/learners/{learner_id}'): 'require_elevated_parent',
    ('DELETE', '/pilot/campuses/{campus_id}/educators/{educator_id}/learners/{learner_id}'): 'require_elevated_parent',
    ('POST', '/pilot/campuses/{campus_id}/educators/{educator_id}/disable'): 'require_elevated_parent',
    ('GET', '/pilot/me/learners'): 'require_educator',
    ('POST', '/pilot/me/learners/search'): 'require_educator',
    ('GET', '/pilot/me/learners/{learner_id}'): 'require_educator',
    ('GET', '/pilot/campuses/{campus_id}/data-authorization'): '_admin_or_educator',
    ('POST', '/pilot/campuses/{campus_id}/data-authorization'): '_admin_or_educator',
    ('POST', '/pilot/campuses/{campus_id}/data-authorization/revoke'): 'require_elevated_parent',
    ('PUT', '/pilot/campuses/{campus_id}/calendar'): 'require_elevated_parent',
    ('GET', '/pilot/campuses/{campus_id}/calendar'): 'require_elevated_parent',
    ('POST', '/pilot/campuses/{campus_id}/benchmark-authorizations'): 'require_elevated_parent',
    ('POST', '/pilot/campuses/{campus_id}/learners/{learner_id}/assessments'): 'require_educator',
    ('GET', '/pilot/campuses/{campus_id}/learners/{learner_id}/assessments'): 'require_educator',
    ('GET', '/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}'): 'require_educator',
    ('PUT', '/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/scores'): 'require_educator',
    ('POST', '/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/transitions'): 'require_educator',
    ('POST', '/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/supersede'): 'require_educator',
    ('GET', '/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/audit'): 'require_educator',
    ('POST', '/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/evidence'): 'require_educator',
    ('POST', '/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/proposal'): 'require_educator',
    ('POST', '/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/proposals/{proposal_id}/decision'): 'require_educator',
    ('POST', '/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/plan'): 'require_educator',
    ('POST', '/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/progress-monitoring'): 'require_educator',
    ('GET', '/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/plans/{plan_id}/artifact'): 'require_educator',
    ('POST', '/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/plans/{plan_id}/follow-ups'): 'require_educator',
    ('GET', '/pilot/campuses/{campus_id}/learners/{learner_id}/assessments/{assessment_id}/plans/{plan_id}/follow-ups'): 'require_educator',
    ('GET', '/pilot/campuses/{campus_id}/learners/{learner_id}/data-day'): 'require_educator',
    # K-2 map practice: the learner's own session (or the parent). Each route
    # then checks require_learner_access and consent itself.
    ('GET', '/map-practice/{student_name}/lesson'): 'require_real_user',
    ('POST', '/map-practice/{student_name}/lessons/{lesson_id}/answers'): 'require_family_data_write',
    # K-2 phonics practice: the same guards as map practice, for the same reason.
    ('GET', '/k2-practice/{student_name}/phonics/lesson'): 'require_real_user',
    ('POST', '/k2-practice/{student_name}/phonics/lessons/{lesson_id}/answers'): 'require_family_data_write',
    # K-2 practical math: the same boundary as phonics, chosen deliberately.
    # Any real (non-demo) learner session may load a lesson; recording an
    # answer writes family data, so it needs the family-data write guard.
    ('GET', '/k2-practice/{student_name}/math/lesson'): 'require_real_user',
    ('POST', '/k2-practice/{student_name}/math/lessons/{lesson_id}/answers'): 'require_family_data_write',
    # Public-demo Number Time uses the demo identity and remains temporary.
    ('GET', '/k2-practice/demo/math/lesson'): 'require_demo_practice_preview',
    ('POST', '/k2-practice/demo/math/lessons/{lesson_id}/answers'): 'require_demo_practice_preview',
    ('GET', '/k2-practice/demo/phonics/lesson'): 'require_demo_practice_preview',
    ('POST', '/k2-practice/demo/phonics/lessons/{lesson_id}/answers'): 'require_demo_practice_preview',
    ('GET', '/k2-practice/demo/maps/lesson'): 'require_demo_practice_preview',
    ('POST', '/k2-practice/demo/maps/lessons/{lesson_id}/answers'): 'require_demo_practice_preview',
    ('POST', '/pilot/me/learners/{learner_id}/tutoring/chat'): 'require_educator',
    ('GET', '/pilot/me/learners/{learner_id}/tutoring/history'): 'require_educator',
    ('POST', '/pilot/me/learners/{learner_id}/evidence'): 'require_educator',
    ('GET', '/pilot/me/learners/{learner_id}/evidence'): 'require_educator',
    # Teacher-confirmed quiz results: the educator's grant (resolved inside the
    # route through _assigned) plus the Practice Coach switch, since they are
    # the teacher-quiz feature's own records.
    ('POST', '/pilot/me/learners/{learner_id}/quiz-results'): 'require_educator+require_practice_coach_enabled',
    ('GET', '/pilot/me/learners/{learner_id}/quiz-results'): 'require_educator+require_practice_coach_enabled',
    ('GET', '/pilot/me/learners/{learner_id}/quiz-mastery'): 'require_educator+require_practice_coach_enabled',
    ('POST', '/pilot/me/learners/{learner_id}/recommendations'): 'require_educator',
    ('GET', '/pilot/me/learners/{learner_id}/recommendations'): 'require_educator',
    ('POST', '/pilot/me/learners/{learner_id}/recommendations/{recommendation_id}/decision'): 'require_educator',
    ('GET', '/pilot/me/learners/{learner_id}/decisions'): 'require_educator',
    ('GET', '/pilot/me/learners/{learner_id}/instruction'): 'require_educator',
    ('GET', '/pilot/owner/campuses'): 'require_elevated_parent',
    ('GET', '/pilot/owner/campuses/{campus_id}/learners'): 'require_elevated_parent',
    ('POST', '/pilot/owner/campuses/{campus_id}/disable'): 'require_elevated_parent',
    ('POST', '/pilot/owner/campuses/{campus_id}/learners/{learner_id}/delete'): 'require_elevated_parent',
    ('GET', '/pilot/owner/deletion-receipts'): 'require_elevated_parent',
    ('GET', '/pilot/me/learners/{learner_id}/diagnostic'): 'require_educator',
    ('GET', '/admin/agentic-loop-stats'): 'require_parent',
    ('GET', '/admin/ai-provider'): 'require_parent',
    ('POST', '/admin/ai-provider'): 'require_elevated_parent',
    ('POST', '/admin/ai-provider/secondary'): 'require_elevated_parent',
    ('GET', '/admin/audit'): 'require_elevated_parent',
    ('GET', '/admin/devices'): 'require_parent',
    ('POST', '/admin/devices/{device_id}/revoke'): 'require_elevated_parent',
    ('GET', '/admin/license'): 'require_parent',
    ('POST', '/admin/license'): 'require_elevated_parent',
    ('GET', '/admin/status'): 'require_parent',
    ('GET', '/admin/usage/{student_name}'): 'require_parent',
    ('POST', '/auth/demo-code'): 'PUBLIC',
    # The demo's own Parent Setup. Its own policy action, deliberately NOT
    # a third use of require_demo_preview: this one WRITES, and an action
    # that changes what the model is told should not ride on a guard whose
    # name says "preview". Demo domain only — a family session has
    # ParentSetup.tsx and must never reach it.
    ('POST', '/auth/demo-code/config'): 'require_demo_parent_config',
    ('DELETE', '/auth/elevate'): 'require_parent',
    ('GET', '/auth/elevate'): 'require_parent',
    ('POST', '/auth/elevate'): 'require_parent',
    ('GET', '/auth/locales'): 'PUBLIC',
    ('POST', '/auth/login'): 'PUBLIC',
    ('POST', '/auth/logout'): 'require_auth',
    ('GET', '/auth/recovery/methods'): 'PUBLIC',
    ('POST', '/auth/educator-login'): 'PUBLIC',
    ('GET', '/auth/educator-mode'): 'PUBLIC',
    ('POST', '/auth/recovery/reset-password'): 'require_parent_recovery',
    ('POST', '/auth/recovery/verify'): 'PUBLIC',
    ('POST', '/auth/recovery/webauthn/options'): 'PUBLIC',
    ('GET', '/auth/validate'): 'PUBLIC',
    ('GET', '/catalog/book/{book_id}'): 'require_real_user',
    ('GET', '/catalog/search'): 'require_real_user',
    ('GET', '/catalog/years'): 'require_real_user',
    ('GET', '/catalog/{year}/books'): 'require_real_user',
    ('GET', '/catalog/{year}/books/{subject}'): 'require_real_user',
    ('POST', '/diagnostic/chat'): '_require_diagnostic_quota',
    # The demo's own work ledger. require_demo_preview, NOT
    # _require_diagnostic_quota like /diagnostic/summary beside it: the
    # quota protects a mastery estimate, which is the demo's expensive
    # asset. This aggregates what the visitor themselves completed minutes
    # ago and is worthless to anyone else, so spending a preview use on it
    # would be charging for the receipt.
    ('GET', '/diagnostic/demo/activity'): 'require_demo_preview',
    ('GET', '/diagnostic/pod/activity'): 'require_parent',
    ('GET', '/diagnostic/summary'): '_require_diagnostic_quota',
    ('GET', '/diagnostic/{student_name}/activity'): 'require_parent',
    # A child's instructional recommendation history is parent-confidential,
    # just like the work ledger it references. Never widen to require_auth.
    ('GET', '/diagnostic/{student_name}/adaptive-learning'): 'require_parent',
    # Assessment results are confidential even when supplied by a parent:
    # never widen these to a child or demo role.
    ('GET', '/diagnostic/assessment-frameworks'): 'require_parent',
    ('GET', '/diagnostic/{student_name}/assessment-records'): 'require_parent',
    ('POST', '/diagnostic/{student_name}/assessment-records'): 'require_parent',
    ('DELETE', '/diagnostic/{student_name}/assessment-records/{record_id}'): 'require_parent',
    # Which scheduled subjects are actually getting taught. Parent-only
    # for the same reason the ledger is: a child shown "you have not done
    # History in three weeks" has been handed a reproach.
    ('GET', '/diagnostic/{student_name}/coverage'): 'require_parent',
    # Parent-only, and deliberately not merely by convention: the plan's
    # reasons say things like "this hasn't come up in a while", which is a
    # statement about the schedule that a CHILD would read as a statement
    # about themselves. See services/lesson_planner.py.
    ('GET', '/diagnostic/{student_name}/plan'): 'require_parent',
    ('GET', '/diagnostic/{student_name}/summary'): 'require_parent',
    # Distinct educator role: no administrator rights, and every child
    # read/write also verifies a parent-approved SQL roster assignment.
    ('GET', '/educators/accounts'): 'require_parent',
    ('POST', '/educators/accounts'): 'require_elevated_parent',
    ('PUT', '/educators/accounts/{educator_id}/roster'): 'require_elevated_parent',
    ('POST', '/educators/accounts/{educator_id}/disable'): 'require_elevated_parent',
    ('GET', '/educators/me/assessment-frameworks'): 'require_educator',
    ('GET', '/educators/me/roster'): 'require_educator',
    ('GET', '/educators/me/locuto-capacity'): 'require_educator',
    ('GET', '/educators/me/students/{student_name}/config'): 'require_educator',
    ('GET', '/educators/me/students/{student_name}/assessments'): 'require_educator',
    ('POST', '/educators/me/students/{student_name}/assessments'): 'require_educator',
    ('GET', '/educators/me/students/{student_name}/activity'): 'require_educator',
    ('GET', '/educators/me/students/{student_name}/diagnostic'): 'require_educator',
    ('GET', '/educators/me/students/{student_name}/dibels-progress'): 'require_educator',
    ('POST', '/feedback'): 'require_auth',
    ('GET', '/feedback/enabled'): 'PUBLIC',
    ('POST', '/mfa/change-password'): 'require_parent',
    ('DELETE', '/mfa/recovery-code'): 'require_elevated_parent',
    ('POST', '/mfa/recovery-code/enroll'): 'require_elevated_parent',
    ('DELETE', '/mfa/recovery-pin'): 'require_elevated_parent',
    ('POST', '/mfa/recovery-pin/enroll'): 'require_elevated_parent',
    ('GET', '/mfa/status'): 'require_parent',
    ('DELETE', '/mfa/totp'): 'require_elevated_parent',
    ('POST', '/mfa/totp/authenticate/verify'): 'require_mfa_pending',
    ('POST', '/mfa/totp/confirm'): 'require_enrollment_or_elevated_parent',
    ('POST', '/mfa/totp/enroll'): 'require_enrollment_or_elevated_parent',
    ('POST', '/mfa/webauthn/authenticate/options'): 'require_mfa_pending',
    ('POST', '/mfa/webauthn/authenticate/verify'): 'require_mfa_pending',
    ('POST', '/mfa/webauthn/register/options'): 'require_enrollment_or_elevated_parent',
    ('POST', '/mfa/webauthn/register/verify'): 'require_enrollment_or_elevated_parent',
    # C-22/C-23 (hosted profile): the enrollment routes also accept the
    # enrollment-only token issued on a refused password sign-in, while no
    # factor is enrolled. Every other route keeps its guard.
    ('GET', '/auth/child-devices'): 'require_parent',
    ('POST', '/auth/child-devices/{device_id}/approve'): 'require_parent',
    ('POST', '/auth/child-devices/{device_id}/learner'): 'require_parent',
    ('POST', '/auth/child-devices/{device_id}/revoke'): 'require_parent',
    ('DELETE', '/mfa/webauthn/{key_id}'): 'require_elevated_parent',
    ('GET', '/narration/{student_name}/assessments'): 'require_parent',
    ('GET', '/narration/{student_name}/behavior-check'): 'require_parent',
    ('GET', '/narration/{student_name}/profile'): 'require_real_user',
    ('POST', '/narration/{student_name}/profile'): 'require_real_user',
    ('GET', '/pod/roster-capacity'): 'require_parent',
    # Per-child PINs: status is ordinary parent reading; setting, changing
    # or clearing changes an authentication factor, so it needs elevation.
    ('GET', '/pod/child-pins'): 'require_parent',
    ('PUT', '/pod/child-pins/{student_name}'): 'require_elevated_parent',
    ('DELETE', '/pod/child-pins/{student_name}'): 'require_elevated_parent',
    ('GET', '/pod/configs'): 'require_parent',
    ('POST', '/pod/configs'): 'require_parent',
    ('DELETE', '/pod/configs/{student_name}'): 'require_elevated_parent',
    ('GET', '/pod/configs/{student_name}'): 'require_real_user',
    ('PATCH', '/pod/configs/{student_name}/voice-narration'): 'require_real_user',
    ('POST', '/sandbox/chat'): 'require_parent',
    ('POST', '/sandbox/educator-chat'): 'require_educator',
    ('POST', '/sandbox/demo-chat'): 'require_demo_preview',
    ('GET', '/transcripts/{student_name}'): 'require_parent',
    ('POST', '/transcripts/{student_name}'): 'require_real_user',
    ('GET', '/transcripts/{student_name}/{transcript_id}'): 'require_parent',
    ('POST', '/tutor/chat'): 'require_auth',
    ('GET', '/tutor/demo-config'): 'require_auth',
    ('POST', '/tutor/email-summary'): 'require_email_summary',
    ('POST', '/tutor/extract-narration'): 'require_auth',
    ('POST', '/tutor/speak'): 'require_auth',
    ('POST', '/tutor/summary'): 'require_parent',
    # Legacy name-keyed biometric profiles are unsafe on institutional hosts.
    # Preserve BOTH the role guard and fail-closed household-only scope gate.
    ('POST', '/voice/enroll'): '_require_household_biometric_scope+require_parent',
    ('POST', '/voice/override'): '_require_household_biometric_scope+require_parent',
    ('GET', '/voice/profiles'): '_require_household_biometric_scope+require_parent',
    ('DELETE', '/voice/profiles/{student_name}'): '_require_household_biometric_scope+require_parent',
    ('POST', '/voice/stream/start'): 'require_auth',
    ('POST', '/voice/stream/{session_id}/chunk'): 'require_auth',
    ('GET', '/voice/stream/{session_id}/events'): 'require_auth',
    ('POST', '/voice/stream/{session_id}/finish'): 'require_auth',
    ('POST', '/voice/transcribe'): 'require_auth',
    ('POST', '/voice/verify'): '_require_household_biometric_scope+require_real_user',
    # routers/consent.py: every route is parent-only. These carry a child's
    # consent ledger, pause state, full data export and the adult's own
    # greeting name, so a downgrade to require_auth (which admits a child)
    # must fail this table rather than pass silently. The assembled-app walk
    # ensures these routes are included in the comparison.
    ('GET', '/household/consent'): 'require_parent',
    ('POST', '/household/consent'): 'require_parent',
    ('GET', '/household/profile'): 'require_parent',
    ('PUT', '/household/profile'): 'require_parent',
    ('DELETE', '/household/profile'): 'require_parent',
    ('GET', '/consent/notice'): 'require_parent',
    ('GET', '/consent/{student_name}'): 'require_parent',
    ('POST', '/consent/{student_name}'): 'require_parent',
    ('POST', '/consent/{student_name}/revoke'): 'require_parent',
    ('POST', '/consent/{student_name}/pause'): 'require_parent',
    ('POST', '/consent/{student_name}/resume'): 'require_parent',
    ('GET', '/pod/students/{student_name}/review'): 'require_parent',
}


_DOC_ROUTES = {
    ("/openapi.json", "openapi"),
    ("/docs", "swagger_ui_html"),
    ("/docs/oauth2-redirect", "swagger_ui_redirect"),
    ("/redoc", "redoc_html"),
}


def _assembled_routes(app=None):
    """Walk the actual app, including FastAPI's lazy router contexts."""
    if app is None:
        import main
        app = main.app

    def walk(routes):
        for route in routes:
            if isinstance(route, _IncludedRouter):
                yield from walk(route.effective_candidates())
            elif isinstance(route, APIRoute):
                yield route
            elif isinstance(getattr(route, "original_route", None), APIRoute):
                yield route
            else:
                # FastAPI's optional API documentation routes are Starlette
                # routes. Unknown non-API routes must not disappear silently.
                assert (getattr(route, "path", None), getattr(route, "name", None)) in _DOC_ROUTES, (
                    f"Unreviewed app route: {route!r}"
                )

    yield from walk(app.routes)


def _guard_chain(route) -> str:
    names = sorted({
        getattr(d.call, "__name__", "")
        for d in route.dependant.dependencies
        if getattr(d, "call", None) is not None
    })
    names = [n for n in names if n and n not in _NOT_A_GUARD]
    return "+".join(names) if names else "PUBLIC"


# ── Middleware composition ──────────────────────────────────────────────────

def test_the_middleware_stack_is_assembled_in_the_expected_order():
    """Catches the reintroduction of the bug this engagement opened with.

    tests/test_middleware.py has an 'assembled stack' test, but it builds a
    hand-maintained REPLICA of main.py's ordering in the test file — its own
    comment says 'Same relative order as main.py'. A comment is not an
    assertion: reorder main.py and that test still passes. This one reads the
    real application object.
    """
    import main

    assert [m.cls.__name__ for m in main.app.user_middleware] == EXPECTED_MIDDLEWARE


def test_gzip_stays_outside_the_exfiltration_guard():
    """The specific invariant, called out separately from the full ordering
    so the failure message names the actual risk rather than showing a list
    diff. If GZip compresses before ExfiltrationGuard scans, the guard sees
    gzip magic bytes and its patterns never match — fully tested, completely
    inert."""
    import main

    order = [m.cls.__name__ for m in main.app.user_middleware]
    assert order.index("GZipMiddleware") < order.index("ExfiltrationGuard"), (
        "GZipMiddleware must be OUTSIDE ExfiltrationGuard (earlier in "
        "user_middleware) so the guard scans uncompressed response bodies"
    )


@pytest.mark.parametrize("name", EXPECTED_MIDDLEWARE)
def test_each_security_middleware_is_actually_mounted(name):
    """Unmounting any of these left all 1,603 tests green before this file
    existed."""
    import main

    assert name in [m.cls.__name__ for m in main.app.user_middleware]


def test_the_instance_id_header_is_actually_exposed_cross_origin():
    """The same lesson as test_the_middleware_stack_is_assembled_in_the_
    expected_order, applied to a second real gap: tests/test_middleware.py
    proves the MECHANISM (CORSMiddleware + expose_headers, wired the way
    main.py wires them, in a throwaway app) but a throwaway app can't prove
    main.py's OWN CORSMiddleware call actually names X-Bede-Instance —
    remove expose_headers from main.py itself and that test keeps passing,
    because it never reads main.py's real configuration. This one does.

    Why it matters: without this, the demo's split-origin fetch()
    (Cloudflare Pages frontend, Render backend) silently drops the header
    before client code ever sees it — the whole diagnostic goes dark with
    no error anywhere, on the one deployment it exists for.
    """
    import main
    from fastapi.middleware.cors import CORSMiddleware

    cors = next(m for m in main.app.user_middleware if m.cls is CORSMiddleware)
    assert "X-Bede-Instance" in cors.kwargs.get("expose_headers", [])


# ── Guard composition ───────────────────────────────────────────────────────

def _guard_drift(app=None):
    actual = {}
    for route in _assembled_routes(app):
        for method in sorted(route.methods):
            key = (method, route.path)
            assert key not in actual, f"Duplicate registered route: {key}"
            actual[key] = _guard_chain(route)
    return {k: (GUARDS.get(k, "<not in table>"), v) for k, v in actual.items() if GUARDS.get(k) != v}


def test_every_endpoint_carries_the_guard_the_table_says_it_does():
    """Catches a guard being downgraded, swapped, or dropped on a real route.

    Downgrading transcript reads, voice enrollment, and the parent sandbox
    from require_parent to require_auth — letting a child reach all three —
    was invisible to the entire suite before this."""
    drifted = _guard_drift()
    assert not drifted, (
        "guard chain changed for:\n"
        + "\n".join(
            f"  {m} {p}: expected {exp!r}, found {got!r}"
            for (m, p), (exp, got) in sorted(drifted.items())
        )
        + "\n\nIf you added an endpoint, add its row to GUARDS above — and decide "
        "its guard deliberately rather than copying the neighbour, which is the "
        "whole point of this failing. If you changed an existing endpoint's guard "
        "on purpose, update its row. This test is brittle by design: a protection "
        "boundary should not move without someone editing this table."
    )


def test_no_endpoint_disappeared_from_the_table():
    """The inverse direction: a route deleted from the app but left in the
    table would let the test above keep passing while coverage silently
    shrinks."""
    actual = {
        (method, route.path)
        for route in _assembled_routes()
        for method in sorted(route.methods)
    }
    assert set(GUARDS) - actual == set(), f"in the table but not served: {sorted(set(GUARDS) - actual)}"


def test_the_walk_finds_the_whole_application():
    """A guard-coverage test that silently enumerates nothing passes forever.
    Pin a floor well below the real count but far above the one route
    `app.routes` yields if the lazy-inclusion detail above is ever missed."""
    assert len(list(_assembled_routes())) >= 60


def test_newly_registered_router_missing_from_table_is_detected():
    from fastapi import APIRouter, FastAPI

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    router = APIRouter()

    @router.get("/unreviewed")
    def endpoint():
        return {}

    app.include_router(router)
    assert _guard_drift(app) == {("GET", "/unreviewed"): ("<not in table>", "PUBLIC")}


def test_duplicate_registration_cannot_hide_a_guard():
    from fastapi import APIRouter, FastAPI

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    router = APIRouter()

    @router.get("/unreviewed")
    def endpoint():
        return {}

    app.include_router(router)
    app.include_router(router)
    with pytest.raises(AssertionError, match="Duplicate registered route"):
        _guard_drift(app)


def test_a_downgraded_parent_guard_is_detected():
    from fastapi import APIRouter, Depends, FastAPI
    from core.deps import require_auth

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    router = APIRouter()

    @router.get("/household/profile", dependencies=[Depends(require_auth)])
    def endpoint():
        return {}

    app.include_router(router)
    assert _guard_drift(app) == {
        ("GET", "/household/profile"): ("require_parent", "require_auth")
    }
