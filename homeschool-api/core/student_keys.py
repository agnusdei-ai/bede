"""
Per-student encryption keys — the mechanism that makes deletion real
(punch-list #6, docs/ARCHITECTURE_PRINCIPLES.md P3).

THE PROBLEM. services/student_deletion.py issues real SQL DELETEs across
every student-scoped table, which is correct as far as the live table goes.
It does not reach: Postgres keeps dead tuples until VACUUM, the delete is
written to WAL, and every `make db-backup` dump taken beforehand still
contains the rows. All three remain decryptable indefinitely, because they
are all encrypted under one global DATA_KEY that by design never changes —
even MASTER_SECRET rotation deliberately preserves it. So "permanently
delete a student's data" was true of the live table and false of the disk.
The standard way an auditor tests an erasure claim is restoring a backup,
which would have shown the record intact.

THE MECHANISM. Each student gets one random 32-byte key, wrapped under
DATA_KEY and stored in `student_keys`. Every encrypted column belonging to
that student is encrypted under THEIR key rather than DATA_KEY directly.
Deleting a student destroys that one row, and every copy of their
ciphertext — live rows, dead tuples, WAL segments, old backups — becomes
permanently unopenable at once, including by this deployment itself.
Deletion stops being a storage-layer promise and becomes a cryptographic
fact.

ONE KEY PER STUDENT, NOT PER TABLE OR PER RECORD. Per-record keys would
allow shredding an individual transcript, which nothing in the product
actually asks for; the erasure unit here is the student. One key per
student means the shred is a single row delete and cannot partially
succeed — a per-table scheme could destroy six of eight keys and leave two
tables readable, which is a worse failure than either extreme.

BACKWARD COMPATIBILITY. Rows written before this existed are encrypted
under DATA_KEY and stay readable forever: core/encryption.py's envelope
carries a version byte, and only v3 means "per-student key". A row
upgrades itself on its next write. Same incremental pattern that made the
AAD migration safe, for the same reason — a botched key migration makes a
family's data permanently unreadable, which is strictly worse than the gap
staying open longer.

REPLICATION (docs/DEPLOYMENT_TOPOLOGY.md). The unwrapped-key cache below is
per-process. That is safe by construction for the normal case, because a
student's key is immutable once created — there is no staleness to
propagate. The one case that could matter: after a shred on replica A,
replica B could still hold the unwrapped key in cache. It has nothing to
decrypt with it (the rows are deleted in the same transaction) and the
entry expires within the TTL, but the cache is cleared explicitly on
destroy for the local replica and bounded by TTL for the others.
"""
import logging
import time
from typing import Optional, Union

from Crypto.Random import get_random_bytes
from sqlalchemy.ext.asyncio import AsyncSession

from core.encryption import aad_for, decrypt, encrypt
from core.learner_scope import LearnerScope, as_scope

log = logging.getLogger(__name__)

# Unwrapping costs an AES-GCM open (~70 us, dominated by cipher
# construction) plus a DB round trip. Both would otherwise be paid on every
# encrypted read and write, on a Raspberry Pi. The cached value is a
# student's immutable key, so this is a cache of something that cannot go
# stale in the ordinary case.
#
# KEYED BY SCOPE, NEVER BY NAME (G1 items 3 and 8). The cache key is
# core/learner_scope.py's five-part key — environment, campus UUID, learner
# UUID, resource type, resource version — so two same-named learners on two
# campuses can never be handed each other's unwrapped key. The persistent
# row and its AAD use LearnerScope.storage_subject, which for a legacy
# household is the name exactly as before (no family's key row or ciphertext
# changes) and for an institutional learner is a campus- and learner-bound
# string, so the two campuses also get distinct rows and distinct AAD.
_CACHE_TTL_SECONDS = 300
_RESOURCE = "student_data_key"
_RESOURCE_VERSION = 1
_cache: dict[tuple, tuple[bytes, float]] = {}

Subject = Union[str, LearnerScope]


def _key_aad(storage_subject: str) -> bytes:
    """The wrapped key is itself context-bound, so a wrapped key cannot be
    moved between students — which would otherwise let someone with DB write
    access make student A's rows decrypt under student B's key."""
    return aad_for("student_keys", "wrapped_key", storage_subject)


def _ckey(scope: LearnerScope) -> tuple:
    return scope.cache_key(_RESOURCE, _RESOURCE_VERSION)


def _cache_get(subject: Subject) -> Optional[bytes]:
    k = _ckey(as_scope(subject))
    entry = _cache.get(k)
    if entry is None:
        return None
    key, expires = entry
    if time.monotonic() >= expires:
        _cache.pop(k, None)
        return None
    return key


async def get_or_create(db: AsyncSession, subject: Subject) -> bytes:
    """The student's data key, creating one on first use.

    `subject` is a legacy household name or a LearnerScope. A bare name is
    always the legacy scope; an institutional learner must pass a scope.

    Called on every encrypted read and write for that student, so the cache
    is not optional — it's what keeps this off the hot path."""
    scope = as_scope(subject)
    cached = _cache_get(scope)
    if cached is not None:
        return cached

    from core.database import StudentKey

    stored = scope.storage_subject
    row = await db.get(StudentKey, stored)
    if row is None:
        key = get_random_bytes(32)
        db.add(StudentKey(student_name=stored, wrapped_key=encrypt(key, _key_aad(stored))))
        await db.commit()
        log.info("Created data key for a learner scope")
    else:
        key = decrypt(row.wrapped_key, _key_aad(stored))

    _cache[_ckey(scope)] = (key, time.monotonic() + _CACHE_TTL_SECONDS)
    return key


async def get_existing(db: AsyncSession, subject: Subject) -> Optional[bytes]:
    """The student's key if one exists, else None — never creates.

    For read paths: a student with no key row has no v3 data, so their rows
    (if any) are v1/v2 under DATA_KEY and decrypt without one. Creating a
    key on a read would write to the database on a read path and, worse,
    resurrect a key row for a student who was just shredded."""
    scope = as_scope(subject)
    cached = _cache_get(scope)
    if cached is not None:
        return cached

    from core.database import StudentKey

    stored = scope.storage_subject
    row = await db.get(StudentKey, stored)
    if row is None:
        return None
    key = decrypt(row.wrapped_key, _key_aad(stored))
    _cache[_ckey(scope)] = (key, time.monotonic() + _CACHE_TTL_SECONDS)
    return key


async def destroy(db: AsyncSession, subject: Subject) -> bool:
    """Crypto-shred: destroy the student's key.

    After this, every v3 ciphertext belonging to them is permanently
    unopenable — live rows, dead tuples awaiting VACUUM, WAL segments, and
    every backup taken while the key existed. Irreversible by design, and
    the only form of deletion that means anything once backups are in the
    picture.

    Does NOT commit — the caller commits alongside the row deletions, so a
    partial failure cannot leave the key destroyed but the rows present (or
    the reverse). Returns whether a key existed."""
    from core.database import StudentKey

    scope = as_scope(subject)
    evict(scope)
    row = await db.get(StudentKey, scope.storage_subject)
    if row is None:
        return False
    await db.delete(row)
    log.info("Destroyed data key for a learner scope — its stored data is now unrecoverable")
    return True


def evict(scope: LearnerScope) -> int:
    """Drop this learner's unwrapped key from the local cache, in every
    environment. Called by core.learner_scope.evict_learner (revocation and
    deletion) and by destroy(). Returns how many entries were removed."""
    stale = [k for k in _cache if scope.owns(k)]
    for k in stale:
        del _cache[k]
    return len(stale)


def clear_cache() -> None:
    """For tests, and for any path that needs to force a re-read."""
    _cache.clear()
