"""Deletion of one Valor pilot learner's active application records.

A pilot learner is keyed by an immutable campus UUID and learner UUID, never
by a display name, so this cannot reuse ``services/student_deletion.py`` (the
household, name-keyed cascade). It removes, in ONE transaction:

1. every row of every table in ``core.pilot_assessment_models.LEARNER_SCOPED_TABLES``
   for ``(campus_id, learner_id)``;
2. every household-shaped row stored under the learner's institutional
   storage subject (``LearnerScope.storage_subject``, ``pilot:<campus>:<learner>``)
   in any table with a ``student_name`` column, EXCEPT ``student_keys``;
3. the learner's roster grants and, last, the ``pilot_learners`` row itself
   (the encrypted display name).

It then RE-COUNTS by learner UUID alone, and rolls the whole transaction back
if anything remains, so a partial deletion is never committed. Only after the
commit succeeds does it call ``core.learner_scope.evict_learner`` (the one
cache and unwrapped-key eviction entry point), and only then does it write
the tombstone: one audit event carrying UUIDs and counts, never a name,
score, label, evidence text or note.

WHAT THIS DOES NOT DO, stated so nothing downstream overclaims it:

* It is not secure deletion, permanent erasure, or backup destruction. The
  pilot assessment tables are encrypted under the deployment's DATA_KEY, not
  a per-learner key. Database backups, WAL, and dead tuples taken before the
  deletion may still hold encrypted historical copies, readable by this
  deployment, until a human-approved retention policy exists.
* It does not destroy the learner's ``student_keys`` row, if one exists.
  Per-learner cryptographic erasure (key destruction) is a human-only
  decision (autonomous brief, HUMAN-ONLY BOUNDARY 8). The row is left in
  place and the unwrapped key is evicted from this process's cache.
* Eviction is per-process. Another replica's cache entries are bounded by
  their TTL (core/student_keys.py's REPLICATION note).

Concurrency. The learner row is locked ``FOR UPDATE`` before anything is
counted. The teacher write path's grant re-check
(``routers/pilot_assessments._recheck``) takes ``FOR SHARE`` on the same row,
so a teacher write in flight either commits before the deletion counts (and
is deleted with everything else) or waits and then finds no learner and
rolls back. On SQLite both clauses are no-ops and the database's single
writer lock serializes the two instead.

Integration seam. There is no deletion route on this base. The owner route
(``routers/pilot_owner.py``, draft #609) calls ``delete_pilot_learner`` after
restack and passes its content-free receipt as ``before_commit`` so the
receipt commits atomically with the deletion. See
docs/CANONICAL_ASSESSMENT_MODEL.md, "Deleting a pilot learner".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from sqlalchemy import Table, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit import AuditEvent, log_event
from core.database import Base, ClassicalEducator, PilotLearner, PilotRosterGrant
from core.learner_scope import LearnerScope, evict_learner
from core.pilot_assessment_models import LEARNER_SCOPED_TABLES
from core.pilot_journey_models import PilotDecision, PilotEvidence, PilotRecommendation

log = logging.getLogger(__name__)

TOMBSTONE_EVENT = "pilot_learner_deleted"

#: Tables with a ``student_name`` column that the storage-subject cascade
#: deliberately does NOT touch, each with its reason. Anything else with a
#: ``student_name`` column is included automatically.
STORAGE_SUBJECT_EXEMPT = {
    "student_keys": (
        "Destroying a per-learner key is cryptographic erasure, a human-only "
        "decision (brief boundary 8). The row is retained; the unwrapped key "
        "is evicted from the cache."
    ),
}


class LearnerNotFound(LookupError):
    """No such learner on that campus (or a malformed id). Callers map this
    to the uniform ``404 Record not found``."""


class DeletionIncomplete(RuntimeError):
    """The re-count found rows after the delete. Nothing was committed."""

    def __init__(self, remaining: dict[str, int]):
        self.remaining = remaining
        super().__init__("Deletion did not complete; nothing was removed")


def storage_subject_tables() -> tuple[Table, ...]:
    """Every table keyed by a household ``student_name`` string, minus the
    named exemptions. Derived from the live metadata so a new name-keyed
    table is covered without anyone remembering to add it."""
    return tuple(
        t for t in Base.metadata.sorted_tables
        if "student_name" in t.c and t.name not in STORAGE_SUBJECT_EXEMPT
    )


def pilot_cascade() -> tuple[Table, ...]:
    """The UUID-keyed pilot tables, children first, the learner row last."""
    return (*LEARNER_SCOPED_TABLES, PilotEvidence.__table__, PilotRecommendation.__table__,
            PilotDecision.__table__, PilotRosterGrant.__table__, PilotLearner.__table__)


def _learner_col(table: Table):
    return table.c.id if table is PilotLearner.__table__ else table.c.learner_id


@dataclass(frozen=True)
class DeletionResult:
    campus_id: str
    learner_id: str
    deleted: dict[str, int] = field(default_factory=dict)
    signed_out_educators: int = 0
    evicted_cache_entries: int = 0

    @property
    def total_rows(self) -> int:
        return sum(self.deleted.values())

    def tombstone_detail(self) -> str:
        """The ONLY text that outlives the learner: UUIDs and counts."""
        tables = sum(1 for n in self.deleted.values() if n)
        return (f"{TOMBSTONE_EVENT} campus={self.campus_id} learner={self.learner_id} "
                f"rows={self.total_rows} tables={tables}")


async def _counts(db: AsyncSession, scope: LearnerScope) -> dict[str, int]:
    """Rows remaining for this learner. Pilot tables are counted by learner
    UUID ALONE (stricter than the delete's campus+learner key), so a row
    misattributed to another campus still blocks the commit."""
    out: dict[str, int] = {}
    for table in pilot_cascade():
        out[table.name] = (await db.execute(
            select(func.count()).select_from(table).where(_learner_col(table) == scope.learner_id)
        )).scalar_one()
    subject = scope.storage_subject
    for table in storage_subject_tables():
        out[table.name] = (await db.execute(
            select(func.count()).select_from(table).where(table.c.student_name == subject)
        )).scalar_one()
    return out


async def delete_pilot_learner(
    db: AsyncSession,
    campus_id: str,
    learner_id: str,
    *,
    actor_role: str = "parent",
    audit_context: Optional[dict] = None,
    before_commit: Optional[Callable[[AsyncSession, DeletionResult], Awaitable[None]]] = None,
) -> DeletionResult:
    """Remove one pilot learner's active records. See the module docstring.

    The caller must already have authorized the actor (verified administrator
    passkey plus elevation); this function authorizes nothing itself.
    Raises ``LearnerNotFound`` or ``DeletionIncomplete``; on any exception the
    transaction is rolled back and nothing is evicted or logged.
    """
    try:
        scope = LearnerScope.institutional(campus_id, learner_id)
    except (ValueError, AttributeError, TypeError):
        raise LearnerNotFound()

    try:
        learner = (await db.execute(
            select(PilotLearner)
            .where(PilotLearner.id == scope.learner_id, PilotLearner.campus_id == scope.campus_id)
            .with_for_update()
        )).scalar_one_or_none()
        if learner is None:
            raise LearnerNotFound()

        # Every teacher who held a grant is signed out at once, so no bearer
        # token minted before the deletion outlives it.
        holders = set((await db.execute(
            select(PilotRosterGrant.educator_id).where(
                PilotRosterGrant.campus_id == scope.campus_id,
                PilotRosterGrant.learner_id == scope.learner_id,
            )
        )).scalars().all())
        for educator_id in holders:
            teacher = await db.get(ClassicalEducator, educator_id)
            if teacher is not None:
                teacher.credential_version += 1

        before = await _counts(db, scope)
        for table in pilot_cascade():
            await db.execute(delete(table).where(
                table.c.campus_id == scope.campus_id,
                _learner_col(table) == scope.learner_id,
            ))
        for table in storage_subject_tables():
            await db.execute(delete(table).where(table.c.student_name == scope.storage_subject))
        await db.flush()

        remaining = await _counts(db, scope)
        if any(remaining.values()):
            raise DeletionIncomplete({k: v for k, v in remaining.items() if v})

        result = DeletionResult(
            campus_id=scope.campus_id, learner_id=scope.learner_id,
            deleted={k: v for k, v in before.items() if v},
            signed_out_educators=len(holders),
        )
        if before_commit is not None:
            await before_commit(db, result)
        await db.commit()
    except BaseException:
        await db.rollback()
        raise

    # Only after the commit: evicting first would let a reader repopulate the
    # cache from rows a failed deletion left in place, and evicting on a
    # rolled-back deletion would report success for nothing.
    evicted = evict_learner(scope)
    result = DeletionResult(
        campus_id=result.campus_id, learner_id=result.learner_id,
        deleted=result.deleted, signed_out_educators=result.signed_out_educators,
        evicted_cache_entries=evicted,
    )
    await log_event(
        AuditEvent.STUDENT_DATA_DELETED, role=actor_role, success=True,
        detail=result.tombstone_detail(), **(audit_context or {}),
    )
    log.info("Deleted pilot learner records: %s", result.tombstone_detail())
    return result
