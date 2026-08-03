"""
Authorization policy — the Policy Decision layer.

Pure, synchronous, no I/O, no FastAPI types, no database. Given a Subject
(who) and an action (what), returns a Decision (may they). That purity is
the whole point: authorization becomes a table you can read and test
exhaustively, rather than a property you have to infer by reading 67
`Depends(...)` call sites plus five inline `role == "..."` branches
scattered through router bodies.

This is the P7 separation from docs/ARCHITECTURE_PRINCIPLES.md
("authentication, authorization, and audit are distinct functions,
independently verifiable"). Before this module, `core/deps.py` performed
identity lookup, authentication verification, AND the authorization
decision in one undifferentiated step, which is why there was nowhere for
privileged-access (P8), device identity (P9), or the family/demo identity
split (P10) to attach. Those remain unbuilt — this is the layer they hang
off, not the features themselves.

  core/security.py   — authentication  (is this token genuine?)
  core/policy.py     — this module     (may this subject do this?)
  core/deps.py       — enforcement     (allow the request, or raise)
  core/audit.py      — audit           (record what happened)

DENY IS THE DEFAULT. An unknown action, an unknown role, or a role not
explicitly listed for an action is denied. The previous model was the
inverse in practice — guards rejected specific known-bad roles and let
everything else through — which is exactly how `parent_recovery` came to
pass `require_auth` (see _TRANSIENT_ROLES below).
"""
from dataclasses import dataclass
from typing import Optional

# ── Identity domains ────────────────────────────────────────────────────────
# The seam for P10 (distinct trust domains get distinct identity domains).
# Today both domains are issued by the same signing key and validated by the
# same path — the gap P10 describes. Modeling the domain as a first-class
# subject attribute now, rather than deriving it from `role == "demo_code"`
# at each use, is what makes that split cheap later: the policy table already
# reasons in terms of domains, so separating the *issuance* becomes a change
# to authentication, not a rewrite of every authorization decision.
DOMAIN_FAMILY = "family"
DOMAIN_DEMO = "demo"
DOMAIN_UNKNOWN = "unknown"

_DOMAIN_FOR_ROLE = {
    "parent": DOMAIN_FAMILY,
    "parent_pending": DOMAIN_FAMILY,
    "parent_recovery": DOMAIN_FAMILY,
    "child": DOMAIN_FAMILY,
    "demo_code": DOMAIN_DEMO,
}

# Roles that exist only to complete one specific flow. Each is valid for
# exactly one action and nothing else. Handled before the main table so the
# denial message can say what's actually wrong ("finish your second factor")
# rather than a generic authorization error.
#
# `parent_recovery` was NOT previously handled this way, and the omission was
# a real gap: `require_auth` explicitly rejected `parent_pending` but said
# nothing about `parent_recovery`, so a recovery token — issued after proving
# 2 of 3 factors and intended for exactly one action — passed `require_auth`
# and could reach any of the 17 endpoints behind it. Enumerating the
# transient roles, rather than rejecting known-bad ones case by case, is what
# makes that structurally impossible rather than a bug waiting to recur.
_TRANSIENT_ROLES = {
    "parent_pending": (
        "mfa.complete",
        401,
        "Second-factor verification required to finish logging in",
    ),
    "parent_recovery": (
        "recovery.reset_password",
        403,
        "No account recovery is in progress",
    ),
}


@dataclass(frozen=True)
class Subject:
    """Who is asking. Built from a validated token — never from raw request
    input. Frozen so a policy decision can't be influenced by a caller
    mutating the subject after the fact."""

    role: str
    identity_domain: str
    code: Optional[str] = None   # demo_code sessions only

    @classmethod
    def from_token(cls, payload: dict) -> "Subject":
        role = payload.get("role") or ""
        return cls(
            role=role,
            identity_domain=_DOMAIN_FOR_ROLE.get(role, DOMAIN_UNKNOWN),
            code=payload.get("code"),
        )

    @property
    def is_demo(self) -> bool:
        return self.identity_domain == DOMAIN_DEMO


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""
    status_code: int = 403


_ALLOW = Decision(allowed=True)


# ── The decision table ──────────────────────────────────────────────────────
# Every action Bede authorizes, and the roles permitted to take it. This is
# the artifact docs/AUTHORIZATION_POLICY.md renders for review — a reader can
# answer "what can a child do?" by reading one table instead of grepping.
#
# Actions are deliberately coarse (~12 covering all 67 call sites). Per-
# endpoint permissions would be more precise and vastly more churn without
# separating anything that isn't already separated here.
_POLICY: dict[str, frozenset[str]] = {
    # Anything a fully-authenticated session may do about itself.
    "session.self": frozenset({"parent", "child", "demo_code"}),

    # Tutoring. Every authenticated role may chat; the demo's session config
    # is substituted server-side rather than trusted from the client, which
    # is an input-handling concern in routers/tutor.py, not an authz one.
    "tutor.chat": frozenset({"parent", "child", "demo_code"}),
    # Emailing a session summary is parent-or-demo, NOT child — a child
    # should not be able to send mail to an arbitrary address.
    "tutor.email_summary": frozenset({"parent", "demo_code"}),

    # Real family data: student configs, transcripts, narration, voice
    # profiles, diagnostics. Excludes the demo domain entirely.
    "family.data.read": frozenset({"parent", "child"}),
    "family.data.write": frozenset({"parent", "child"}),

    # Management plane. P4/P8: today "parent" is simultaneously the ordinary
    # account identity and the fully-privileged administrative one, with no
    # step-up between them. Naming this action separately from family.data.*
    # is what gives P8's elevation check somewhere to attach.
    "admin.manage": frozenset({"parent"}),

    # Parent's direct-answer sandbox, additionally gated by SANDBOX_PIN in
    # routers/sandbox.py (a second factor, not an authorization question).
    "sandbox.parent_chat": frozenset({"parent"}),
    # Public-demo previews — demo domain only, deliberately not reachable by
    # a real family session.
    "sandbox.demo_preview": frozenset({"demo_code"}),
    "diagnostic.demo_preview": frozenset({"demo_code"}),

    # Transient-flow completion. Listed so the table is exhaustive; the
    # transient-role check above handles these before the table is consulted.
    "mfa.complete": frozenset({"parent_pending"}),
    "recovery.reset_password": frozenset({"parent_recovery"}),
}

# Denial messages per action, preserving the exact wording each call site
# produced before this layer existed — changing user-visible auth errors is
# not in scope for a refactor whose whole claim is behavioral equivalence.
_DENIAL: dict[str, str] = {
    "family.data.read": "Not available in demo mode",
    "family.data.write": "Not available in demo mode",
    "admin.manage": "This action requires parent authorisation",
    "sandbox.parent_chat": "This action requires parent authorisation",
    "sandbox.demo_preview": "This preview is only available through the public demo login",
    "diagnostic.demo_preview": "This preview is only available through the public demo login",
    "tutor.email_summary": "Not authorized for this action",
    "mfa.complete": "No second-factor verification is pending",
    "recovery.reset_password": "No account recovery is in progress",
}

_DEFAULT_DENIAL = "Not authorized for this action"


def known_actions() -> frozenset[str]:
    """Every action the policy table defines. Used by the test suite to
    assert the table and the documented decision table agree."""
    return frozenset(_POLICY)


def decide(subject: Subject, action: str) -> Decision:
    """
    The single authorization decision point. Pure — same inputs, same output,
    no I/O, safe to call anywhere including from tests.

    Session *liveness* is deliberately NOT decided here: whether a demo code
    still exists server-side requires a database read, so it stays in the
    enforcement layer (core/deps.py). Policy answers "may this subject do
    this"; enforcement additionally answers "is this session still real".
    """
    # Unknown action -> deny. Guards against a typo'd action string silently
    # authorizing everything, which is the failure mode a string-keyed table
    # invites and the reason deny-by-default matters more here than usual.
    if action not in _POLICY:
        return Decision(
            allowed=False,
            reason=f"Unknown action {action!r} — denied by default",
            status_code=403,
        )

    # Transient roles are valid for exactly one action.
    transient = _TRANSIENT_ROLES.get(subject.role)
    if transient is not None:
        permitted_action, status, message = transient
        if action != permitted_action:
            return Decision(allowed=False, reason=message, status_code=status)
        return _ALLOW

    if subject.role in _POLICY[action]:
        return _ALLOW

    return Decision(
        allowed=False,
        reason=_DENIAL.get(action, _DEFAULT_DENIAL),
        status_code=403,
    )
