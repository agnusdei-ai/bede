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
import importlib

import pytest
from fastapi.routing import APIRoute

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
    "SecurityHeadersMiddleware",
]

_ROUTER_MODULES = [
    "auth", "mfa", "recovery", "tutor", "narration", "transcripts", "voice",
    "admin", "pod", "catalog", "sandbox", "feedback", "diagnostic",
]

# Dependencies that are plumbing rather than protection.
_NOT_A_GUARD = {"get_db"}

# (method, path) -> the guard chain protecting it, or "PUBLIC".
#
# "PUBLIC" is a claim, not an oversight: each is reachable without a token by
# design — logging in, asking which locales exist, minting a demo code,
# entering account recovery, validating a token you already hold, and asking
# whether the feedback form is switched on. A new PUBLIC row appearing in a
# diff is the thing to challenge in review.
GUARDS = {
    ('GET', '/admin/agentic-loop-stats'): 'require_parent',
    ('GET', '/admin/ai-provider'): 'require_parent',
    ('POST', '/admin/ai-provider'): 'require_elevated_parent',
    ('POST', '/admin/ai-provider/secondary'): 'require_elevated_parent',
    ('GET', '/admin/audit'): 'require_elevated_parent',
    ('GET', '/admin/license'): 'require_parent',
    ('POST', '/admin/license'): 'require_elevated_parent',
    ('GET', '/admin/status'): 'require_parent',
    ('GET', '/admin/usage/{student_name}'): 'require_parent',
    ('POST', '/auth/demo-code'): 'PUBLIC',
    ('DELETE', '/auth/elevate'): 'require_parent',
    ('GET', '/auth/elevate'): 'require_parent',
    ('POST', '/auth/elevate'): 'require_parent',
    ('GET', '/auth/locales'): 'PUBLIC',
    ('POST', '/auth/login'): 'PUBLIC',
    ('POST', '/auth/logout'): 'require_auth',
    ('GET', '/auth/recovery/methods'): 'PUBLIC',
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
    ('GET', '/diagnostic/pod/activity'): 'require_parent',
    ('GET', '/diagnostic/summary'): '_require_diagnostic_quota',
    ('GET', '/diagnostic/{student_name}/activity'): 'require_parent',
    ('GET', '/diagnostic/{student_name}/summary'): 'require_parent',
    ('POST', '/feedback'): 'require_auth',
    ('GET', '/feedback/enabled'): 'PUBLIC',
    # require_elevated_parent, not require_parent like change-password just
    # above, and the difference is deliberate. change-password re-verifies
    # the CURRENT password inline, which is its own step-up. This endpoint
    # asks for no current PIN at all — the case it exists for is a
    # forgotten one — so a step-up is the only thing standing between an
    # unattended parent session and a changed child credential. It is also
    # a credential change, which is what the other elevated rows in this
    # block have in common.
    ('POST', '/mfa/change-child-pin'): 'require_elevated_parent',
    ('POST', '/mfa/change-password'): 'require_parent',
    ('DELETE', '/mfa/recovery-code'): 'require_elevated_parent',
    ('POST', '/mfa/recovery-code/enroll'): 'require_elevated_parent',
    ('DELETE', '/mfa/recovery-pin'): 'require_elevated_parent',
    ('POST', '/mfa/recovery-pin/enroll'): 'require_elevated_parent',
    ('GET', '/mfa/status'): 'require_parent',
    ('DELETE', '/mfa/totp'): 'require_elevated_parent',
    ('POST', '/mfa/totp/authenticate/verify'): 'require_mfa_pending',
    # require_parent_or_enrolling, not require_elevated_parent, and the
    # widening is deliberate and narrow. MFA is mandatory, so a brand-new
    # deployment has to be able to enrol its FIRST factor from a token that
    # is not yet a session — otherwise enforcing it would lock a family out
    # of the app they just installed. The bootstrap role reaches these two
    # routes and nothing else (core/policy.py's "parent_enrolling"), and a
    # settled parent still needs a step-up here exactly as before.
    ('POST', '/mfa/totp/confirm'): 'require_parent_or_enrolling',
    ('POST', '/mfa/totp/enroll'): 'require_parent_or_enrolling',
    ('POST', '/mfa/webauthn/authenticate/options'): 'require_mfa_pending',
    ('POST', '/mfa/webauthn/authenticate/verify'): 'require_mfa_pending',
    ('POST', '/mfa/webauthn/register/options'): 'require_elevated_parent',
    ('POST', '/mfa/webauthn/register/verify'): 'require_elevated_parent',
    ('DELETE', '/mfa/webauthn/{key_id}'): 'require_elevated_parent',
    ('GET', '/narration/{student_name}/assessments'): 'require_parent',
    ('GET', '/narration/{student_name}/behavior-check'): 'require_parent',
    ('GET', '/narration/{student_name}/profile'): 'require_real_user',
    ('POST', '/narration/{student_name}/profile'): 'require_real_user',
    ('GET', '/pod/configs'): 'require_parent',
    ('POST', '/pod/configs'): 'require_parent',
    ('DELETE', '/pod/configs/{student_name}'): 'require_elevated_parent',
    ('GET', '/pod/configs/{student_name}'): 'require_real_user',
    ('PATCH', '/pod/configs/{student_name}/voice-narration'): 'require_real_user',
    ('POST', '/sandbox/chat'): 'require_parent',
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
    ('POST', '/voice/enroll'): 'require_parent',
    ('POST', '/voice/override'): 'require_parent',
    ('GET', '/voice/profiles'): 'require_parent',
    ('DELETE', '/voice/profiles/{student_name}'): 'require_parent',
    ('POST', '/voice/stream/start'): 'require_auth',
    ('POST', '/voice/stream/{session_id}/chunk'): 'require_auth',
    ('GET', '/voice/stream/{session_id}/events'): 'require_auth',
    ('POST', '/voice/stream/{session_id}/finish'): 'require_auth',
    ('POST', '/voice/transcribe'): 'require_auth',
    ('POST', '/voice/verify'): 'require_real_user',
}


def _assembled_routes():
    """Every APIRoute the app actually serves.

    Walks the router modules rather than `app.routes` because FastAPI 0.141
    includes routers lazily — `app.routes` holds `_IncludedRouter` wrappers,
    so filtering it for APIRoute finds one route out of 75 and a test built
    on it would silently assert almost nothing.
    """
    for name in _ROUTER_MODULES:
        module = importlib.import_module(f"routers.{name}")
        for route in module.router.routes:
            if isinstance(route, APIRoute):
                yield route


def _guard_chain(route: APIRoute) -> str:
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


# ── Guard composition ───────────────────────────────────────────────────────

def test_every_endpoint_carries_the_guard_the_table_says_it_does():
    """Catches a guard being downgraded, swapped, or dropped on a real route.

    Downgrading transcript reads, voice enrollment, and the parent sandbox
    from require_parent to require_auth — letting a child reach all three —
    was invisible to the entire suite before this."""
    actual = {
        (method, route.path): _guard_chain(route)
        for route in _assembled_routes()
        for method in sorted(route.methods)
    }

    drifted = {k: (GUARDS.get(k, "<not in table>"), v) for k, v in actual.items() if GUARDS.get(k) != v}
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
