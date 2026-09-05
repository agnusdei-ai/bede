"""
The authorization decision table, tested exhaustively.

core/policy.py is pure — no I/O, no FastAPI types, no database — which is
precisely what makes this possible: every (role, action) pair can be
asserted directly rather than inferred by reading 67 `Depends(...)` call
sites. That auditability is the point of the P7 separation, not a side
benefit of it.

Enforcement (does the guard raise the right status, is the session still
live) is covered separately in tests/test_deps_policy_equivalence.py.
"""
import pytest
from core.policy import (
    DOMAIN_DEMO,
    DOMAIN_FAMILY,
    DOMAIN_UNKNOWN,
    Decision,
    Subject,
    decide,
    known_actions,
)

ALL_ROLES = ["parent", "child", "demo_code", "parent_pending", "parent_recovery"]


def _subject(role: str, code: str | None = None) -> Subject:
    return Subject.from_token({"role": role, "code": code})


# The full expected matrix. Written out by hand rather than derived from
# core/policy.py's own table on purpose: a test that imports the table it's
# checking would pass no matter what the table said.
EXPECTED: dict[str, set[str]] = {
    "session.self":              {"parent", "child", "demo_code"},
    "tutor.chat":                {"parent", "child", "demo_code"},
    "tutor.email_summary":       {"parent", "demo_code"},
    "family.data.read":          {"parent", "child"},
    "family.data.write":         {"parent", "child"},
    "admin.manage":              {"parent"},
    "admin.privileged":          {"parent"},
    "sandbox.parent_chat":       {"parent"},
    "sandbox.demo_preview":      {"demo_code"},
    "diagnostic.demo_preview":   {"demo_code"},
    "demo.parent_config":        {"demo_code"},
    "mfa.complete":              {"parent_pending"},
    "recovery.reset_password":   {"parent_recovery"},
}


@pytest.mark.parametrize("action", sorted(EXPECTED))
@pytest.mark.parametrize("role", ALL_ROLES)
def test_decision_matrix(role: str, action: str):
    """Every role against every action — 55 assertions, the whole policy."""
    expected_allowed = role in EXPECTED[action]
    assert decide(_subject(role), action).allowed is expected_allowed


def test_documented_matrix_covers_every_action_in_the_table():
    """If a new action is added to core/policy.py without a row here, this
    fails — so the table can't grow an untested entry."""
    assert known_actions() == frozenset(EXPECTED)


# Written out by hand for the same reason as EXPECTED above: deriving this
# from the module under test would assert nothing.
EXPECTED_ELEVATED = {"admin.privileged"}


def test_which_actions_require_privileged_elevation():
    from core.policy import elevated_actions, requires_elevation

    assert elevated_actions() == frozenset(EXPECTED_ELEVATED)
    for action in EXPECTED:
        assert requires_elevation(action) is (action in EXPECTED_ELEVATED)


def test_an_unknown_action_does_not_ask_for_elevation():
    """It is denied outright by decide(), so reporting True here would turn a
    clear 'unknown action' denial into a re-authenticate prompt for something
    that will be refused anyway."""
    from core.policy import requires_elevation

    assert requires_elevation("nonsense.action") is False
    assert decide(_subject("parent"), "nonsense.action").allowed is False


def test_elevation_does_not_widen_who_may_act():
    """Elevation is a second gate, never a substitute for the role check —
    a child holding an elevation (impossible today, but the table must not
    depend on that) still cannot reach the management plane."""
    for role in ("child", "demo_code", "parent_pending", "parent_recovery"):
        assert decide(_subject(role), "admin.privileged").allowed is False


# ── Fail-closed behavior ────────────────────────────────────────────────────

def test_unknown_action_is_denied_for_every_role():
    """A typo'd action string must never silently authorize. This is the
    failure mode a string-keyed table invites, and the reason deny-by-default
    matters more here than it would elsewhere."""
    for role in ALL_ROLES:
        d = decide(_subject(role), "admin.mange")  # deliberate typo
        assert d.allowed is False
        assert "Unknown action" in d.reason


def test_unknown_role_is_denied_for_every_action():
    for action in EXPECTED:
        assert decide(_subject("superuser"), action).allowed is False


def test_empty_or_missing_role_is_denied():
    assert decide(Subject.from_token({}), "session.self").allowed is False
    assert decide(_subject(""), "tutor.chat").allowed is False


# ── Transient roles ─────────────────────────────────────────────────────────

def test_parent_pending_can_only_complete_mfa():
    subject = _subject("parent_pending")
    assert decide(subject, "mfa.complete").allowed is True
    for action in EXPECTED:
        if action != "mfa.complete":
            assert decide(subject, action).allowed is False


def test_parent_recovery_can_only_reset_its_password():
    """Regression for a real gap the collapsed model had: require_auth
    rejected parent_pending by name and said nothing about parent_recovery,
    so a recovery token — issued after proving 2 of 3 factors, intended for
    exactly one action — passed require_auth and could reach any of the 17
    endpoints behind it. Enumerating transient roles closes it structurally
    rather than one guard at a time."""
    subject = _subject("parent_recovery")
    assert decide(subject, "recovery.reset_password").allowed is True
    assert decide(subject, "session.self").allowed is False
    assert decide(subject, "tutor.chat").allowed is False
    assert decide(subject, "family.data.read").allowed is False
    assert decide(subject, "admin.manage").allowed is False


def test_transient_denials_carry_their_own_status_and_message():
    """parent_pending gets a 401 telling them to finish logging in, not a
    generic 403 — the message is the difference between a user who knows
    what to do next and one who doesn't."""
    d = decide(_subject("parent_pending"), "tutor.chat")
    assert d.status_code == 401
    assert "Second-factor verification required" in d.reason

    d = decide(_subject("parent_recovery"), "tutor.chat")
    assert d.status_code == 403
    assert "No account recovery is in progress" in d.reason


# ── Denial messages preserved from the pre-refactor call sites ──────────────

@pytest.mark.parametrize("role,action,expected", [
    ("demo_code", "family.data.read", "Not available in demo mode"),
    ("demo_code", "family.data.write", "Not available in demo mode"),
    ("child", "admin.manage", "This action requires parent authorisation"),
    ("demo_code", "admin.manage", "This action requires parent authorisation"),
    ("child", "tutor.email_summary", "Not authorized for this action"),
    ("parent", "sandbox.demo_preview",
     "This preview is only available through the public demo login"),
    ("child", "diagnostic.demo_preview",
     "This preview is only available through the public demo login"),
])
def test_denial_messages_match_the_original_call_sites(role, action, expected):
    """Behavioral equivalence: this refactor changes where the decision is
    made, not what a user sees when denied."""
    assert decide(_subject(role), action).reason == expected


# ── Identity domain (the P10 seam) ──────────────────────────────────────────

def test_identity_domain_is_derived_from_role():
    assert _subject("parent").identity_domain == DOMAIN_FAMILY
    assert _subject("child").identity_domain == DOMAIN_FAMILY
    assert _subject("parent_pending").identity_domain == DOMAIN_FAMILY
    assert _subject("parent_recovery").identity_domain == DOMAIN_FAMILY
    assert _subject("demo_code").identity_domain == DOMAIN_DEMO
    assert _subject("nonsense").identity_domain == DOMAIN_UNKNOWN


def test_is_demo_reflects_the_domain_not_the_role_string():
    """P10 relies on the domain being a first-class attribute — code that
    asks `subject.is_demo` keeps working when the demo gets its own
    identity domain, whereas `role == "demo_code"` comparisons scattered
    through routers would each need finding and changing."""
    assert _subject("demo_code").is_demo is True
    assert _subject("parent").is_demo is False


def test_no_family_role_may_take_a_demo_only_action_and_vice_versa():
    """The two domains are mutually exclusive for their scoped actions —
    the property P10 would enforce at issuance, asserted here at decision
    time in the meantime."""
    for role in ["parent", "child", "parent_pending", "parent_recovery"]:
        assert decide(_subject(role), "sandbox.demo_preview").allowed is False
        assert decide(_subject(role), "diagnostic.demo_preview").allowed is False
    assert decide(_subject("demo_code"), "family.data.read").allowed is False
    assert decide(_subject("demo_code"), "admin.manage").allowed is False


# ── Purity ──────────────────────────────────────────────────────────────────

def test_subject_and_decision_are_immutable():
    """Frozen so a decision can't be influenced by a caller mutating the
    subject after the fact."""
    with pytest.raises(Exception):
        _subject("child").role = "parent"          # type: ignore[misc]
    with pytest.raises(Exception):
        Decision(allowed=False).allowed = True     # type: ignore[misc]


def test_decide_is_deterministic():
    subject = _subject("child")
    assert [decide(subject, "admin.manage").allowed for _ in range(5)] == [False] * 5


# ── The domain map is duplicated on purpose; keep the copies honest ─────────

def test_policy_and_identity_agree_on_which_domain_each_role_belongs_to():
    """core/policy.py duplicates core/identity.py's role->domain map rather
    than importing it, to keep the policy module free of config imports and
    exhaustively testable. Drift would produce a Subject whose domain
    disagrees with the key that actually signed its token — the policy layer
    would reason about a 'family' subject holding a demo-signed token, or
    the reverse. Pin them equal so that fails here instead."""
    from core import identity
    from core.policy import _DOMAIN_FOR_ROLE, DOMAIN_DEMO, DOMAIN_FAMILY

    assert DOMAIN_FAMILY == identity.FAMILY
    assert DOMAIN_DEMO == identity.DEMO
    assert _DOMAIN_FOR_ROLE == identity._ROLE_DOMAIN


def test_every_role_the_policy_table_mentions_has_a_domain():
    """A role that appears in the decision table but not the domain map gets
    DOMAIN_UNKNOWN, which no policy entry lists — so it would be denied
    everywhere. That is the safe direction, but it is never the intent."""
    from core.policy import _DOMAIN_FOR_ROLE, _POLICY, _TRANSIENT_ROLES

    mentioned = {role for roles in _POLICY.values() for role in roles} | set(_TRANSIENT_ROLES)
    assert mentioned <= set(_DOMAIN_FOR_ROLE), (
        f"roles with no identity domain: {sorted(mentioned - set(_DOMAIN_FOR_ROLE))}"
    )
