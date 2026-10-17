"""R1 state-transition policy. No API route may bypass this service.

The service is pure and deliberately fails closed on unknown states/events.
Database authorization and compare-and-swap are additional required gates.
"""
from __future__ import annotations

from enum import Enum


class TransitionDenied(PermissionError):
    pass


APPROVAL = {
    "DRAFT": {"submit": "PENDING_TEACHER_REVIEW"},
    "PENDING_TEACHER_REVIEW": {"approve": "APPROVED", "revoke": "REVOKED"},
    "APPROVED": {"supersede": "SUPERSEDED", "revoke": "REVOKED", "expire": "EXPIRED"},
}
ASSIGNMENT = {
    "ASSIGNED": {"authorize_launch": "LAUNCH_AUTHORIZED", "revoke": "REVOKED", "expire": "EXPIRED"},
    "LAUNCH_AUTHORIZED": {"open": "ACTIVE", "revoke": "REVOKED", "expire": "EXPIRED"},
    "ACTIVE": {"pause": "PAUSED", "complete": "COMPLETED", "revoke": "REVOKED", "expire": "EXPIRED"},
    "PAUSED": {"resume": "ACTIVE", "revoke": "REVOKED", "expire": "EXPIRED"},
}
SESSION = {
    "CREATED": {"open": "ACTIVE", "cancel": "CANCELLED", "revoke": "REVOKED", "expire": "EXPIRED"},
    "ACTIVE": {"pause": "PAUSED", "complete": "COMPLETED", "revoke": "REVOKED", "expire": "EXPIRED",
               "invalidate": "AUTHORIZATION_INVALIDATED", "supersede": "APPROVAL_VERSION_SUPERSEDED"},
    "PAUSED": {"resume": "ACTIVE", "revoke": "REVOKED", "expire": "EXPIRED",
               "invalidate": "AUTHORIZATION_INVALIDATED", "supersede": "APPROVAL_VERSION_SUPERSEDED"},
}
PERMITTED_INTERACTIONS = frozenset({
    "OBSERVE", "RECALL", "NARRATE", "SUPPORT_WITH_EVIDENCE",
    "COMPARE", "REVISE", "SUMMARIZE",
})
LADDER = tuple(PERMITTED_INTERACTIONS)  # Membership only; ordered sequence below.
LADDER_ORDER = ("OBSERVE", "RECALL", "NARRATE", "SUPPORT_WITH_EVIDENCE",
                "COMPARE", "REVISE", "SUMMARIZE")


def transition(domain: str, current: str, event: str) -> str:
    policies = {"approval": APPROVAL, "assignment": ASSIGNMENT, "session": SESSION}
    target = policies.get(domain, {}).get(current, {}).get(event)
    if target is None:
        raise TransitionDenied("State transition is not authorized")
    return target


def permitted_ladder_step(current: str | None, requested: str, allowed: frozenset[str]) -> bool:
    if requested not in PERMITTED_INTERACTIONS or requested not in allowed:
        return False
    if current is None:
        return requested == "OBSERVE"
    if current not in LADDER_ORDER:
        return False
    return LADDER_ORDER.index(requested) in (
        LADDER_ORDER.index(current), LADDER_ORDER.index(current) + 1,
    )
