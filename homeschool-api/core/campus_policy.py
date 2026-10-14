"""Pure, fail-closed campus authorization decisions.

This module is not yet wired to the API: enforcement must separately validate
token issuance, assignment freshness, campus boundaries and audit logging.
Family and demo identity domains remain unchanged.
"""
from dataclasses import dataclass
from typing import FrozenSet

CAMPUS_DOMAIN = "campus"
ACTIONS = frozenset({
    "campus.pod.read",
    "campus.lesson.draft",
    "campus.lesson.approve",
    "campus.progress.read",
    "campus.report.export",
    "campus.roster.manage",
    "campus.settings.manage",
})
ROLE_ACTIONS: dict[str, FrozenSet[str]] = {
    "educator": frozenset({
        "campus.pod.read", "campus.lesson.draft", "campus.lesson.approve",
        "campus.progress.read",
    }),
    "campus_admin": frozenset(ACTIONS),
    "campus_learner": frozenset(),
    "guardian": frozenset(),
    "service_operator": frozenset(),
}
SCOPED_ACTIONS = frozenset({
    "campus.pod.read", "campus.lesson.draft", "campus.lesson.approve",
    "campus.progress.read", "campus.report.export",
})
STEP_UP_ACTIONS = frozenset({
    "campus.report.export", "campus.roster.manage", "campus.settings.manage",
})


@dataclass(frozen=True)
class CampusSubject:
    actor_id: str
    role: str
    identity_domain: str
    campus_id: str
    approved_pod_ids: FrozenSet[str] = frozenset()
    mfa_verified: bool = False
    step_up_verified: bool = False


def campus_allowed(subject: CampusSubject, action: str, *,
                   resource_campus_id: str, pod_id: str | None = None) -> bool:
    """Return only a policy decision, never a substitute for enforcement."""
    if subject.identity_domain != CAMPUS_DOMAIN:
        return False
    if not subject.actor_id or not subject.campus_id or not resource_campus_id:
        return False
    if subject.campus_id != resource_campus_id:
        return False
    if subject.role not in ROLE_ACTIONS or action not in ACTIONS:
        return False
    if action not in ROLE_ACTIONS[subject.role]:
        return False
    if subject.role in {"educator", "campus_admin"} and not subject.mfa_verified:
        return False
    if action in STEP_UP_ACTIONS and not subject.step_up_verified:
        return False
    if subject.role == "educator" and action in SCOPED_ACTIONS:
        if pod_id is None or pod_id not in subject.approved_pod_ids:
            return False
    return True
