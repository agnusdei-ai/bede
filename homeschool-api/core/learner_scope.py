"""Learner scope: the one identity every per-learner cache key is built from.

WHY THIS EXISTS (G1 items 3, 7, 8). Every per-learner cache in this process
used to be keyed by the learner's display name: the unwrapped data-key cache
in core/student_keys.py and the four read-only prompt caches in
services/ai_service.py. A display name is not an identity. Two institutional
campuses can each have a learner called the same thing, and a name-keyed
cache would hand one campus's mastery vector, bookmark, learner profile, or
unwrapped encryption key to the other. That is a cross-campus disclosure
reached through a cache rather than through a route, so route authorization
alone cannot prevent it.

THE KEY. The owner fixed the composition and its order:

    (environment, campus_uuid, learner_uuid, resource_type, resource_version)

Five components, in that order, ``resource_version`` its own component. Never
fold one into another: a key that merged type and version could make two
resource versions collide, which is how a stale-format entry gets served
after a format change. ``tests/test_learner_scope.py`` pins the order and the
presence of every component and was verified by removing each in turn.

ENVIRONMENT is derived from configuration (``environment()``), so a process
configured as production can never read an entry written under development or
demo settings, even if a test or an operator flips the setting in-process.

LEGACY HOUSEHOLDS. A single-family deployment has no campus and no learner
UUID; its learners are identified by name, and that is unchanged on disk.
They get an explicit legacy scope: the campus component is the fixed
``LEGACY_CAMPUS`` sentinel and the learner component is a UUIDv5 derived from
the name under a private namespace. So even the legacy path never puts a bare
name in a cache key, and a legacy entry can never equal an institutional one
(the campus components differ by construction).

STORAGE SUBJECT. Persistent per-learner rows (``StudentKey``,
``MasteryProfile`` and friends) are keyed by a ``student_name`` string column.
``storage_subject`` is the string a scope uses there and in AAD. For a legacy
scope it is the name itself, byte-for-byte what it always was, so no existing
family's row or ciphertext changes. For an institutional scope it is
``pilot:<campus_uuid>:<learner_uuid>`` (79 characters), which cannot collide
with a household name because household names are capped at 50 characters by
``SessionConfig.student_name``. That length gap is what gives two same-named
learners on two campuses distinct key rows, distinct AAD, and distinct
unwrapped keys rather than one shared one.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from core.config import settings

LEGACY_CAMPUS = "legacy-household"
# Private namespace for deriving a legacy learner's UUID from its name. Fixed
# forever: changing it would only re-key in-memory caches (nothing persistent
# uses it), but there is no reason to.
_LEGACY_NAMESPACE = uuid.UUID("6f3c2b1e-8d4a-4c7e-9a51-2e0b7d9c4f18")
PILOT_SUBJECT_PREFIX = "pilot:"


def environment() -> str:
    """The deployment environment, derived from configuration rather than
    stated separately so it cannot drift from what the process really is."""
    base = "production" if settings.is_production else "development"
    return f"{base}+demo" if settings.is_demo_deployment else base


def _canonical_uuid4(value: str) -> str:
    parsed = uuid.UUID(value)
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("Learner scope requires canonical UUIDv4 identifiers")
    return value


@dataclass(frozen=True)
class LearnerScope:
    campus_id: str
    learner_id: str
    # Present only for a legacy scope. Never part of a cache key.
    legacy_name: Optional[str] = None

    @classmethod
    def legacy(cls, student_name: str) -> "LearnerScope":
        if not isinstance(student_name, str) or not student_name:
            raise ValueError("A legacy scope needs a learner name")
        return cls(
            campus_id=LEGACY_CAMPUS,
            learner_id=str(uuid.uuid5(_LEGACY_NAMESPACE, student_name)),
            legacy_name=student_name,
        )

    @classmethod
    def institutional(cls, campus_id: str, learner_id: str) -> "LearnerScope":
        return cls(
            campus_id=_canonical_uuid4(campus_id),
            learner_id=_canonical_uuid4(learner_id),
        )

    @property
    def is_legacy(self) -> bool:
        return self.campus_id == LEGACY_CAMPUS

    @property
    def storage_subject(self) -> str:
        if self.is_legacy:
            return self.legacy_name  # type: ignore[return-value]
        return f"{PILOT_SUBJECT_PREFIX}{self.campus_id}:{self.learner_id}"

    def cache_key(self, resource_type: str, resource_version: int) -> tuple:
        """(environment, campus_uuid, learner_uuid, resource_type, resource_version)."""
        if not resource_type:
            raise ValueError("resource_type is required")
        return (environment(), self.campus_id, self.learner_id, resource_type, int(resource_version))

    def owns(self, key: tuple) -> bool:
        """Whether a cache key belongs to this learner, in ANY environment.
        Eviction deliberately ignores environment: removing a superset is
        always safe, and a learner revoked under one setting must not survive
        under another."""
        return len(key) >= 3 and key[1] == self.campus_id and key[2] == self.learner_id


def as_scope(subject: "str | LearnerScope") -> LearnerScope:
    """Accept either a scope or a legacy name. A bare string is ALWAYS
    treated as a legacy household name; an institutional caller must pass a
    scope, because a name alone cannot say which campus it belongs to."""
    if isinstance(subject, LearnerScope):
        return subject
    return LearnerScope.legacy(subject)


def evict_learner(scope: LearnerScope) -> int:
    """The one eviction entry point for revocation AND deletion.

    Drops every cached entry this process holds for the learner — the four
    read-only prompt caches and the unwrapped data key — in every
    environment. Returns how many entries were removed. Safe to call when
    nothing is cached.

    Per-process, like the caches themselves: another replica's entries are
    bounded by their TTL (see core/student_keys.py's REPLICATION note).
    """
    from core import student_keys

    removed = student_keys.evict(scope)
    try:
        from services import ai_service
    except Exception:  # pragma: no cover - ai_service always importable in the app
        return removed
    return removed + ai_service.evict_learner_prompt_caches(scope)
