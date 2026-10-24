"""Offline, scoped BM25 + deterministic local-vector curriculum search primitive.

This is NOT an authenticated endpoint or semantic embedding service. An
already-authorized caller supplies the trusted campus and educator scope.
Filters execute before text tokenization, indexing, or scoring. No learner
identity, network client, model download, persistence, or logging is used.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import blake2b
from math import log1p, sqrt
import re

from services.curriculum.flag import curriculum_engine_enabled
from services.curriculum.models import (
    ContentChunk, CurriculumModelError, ItemStatus, RightsStatus, Visibility,
    require_approvable,
)

_WORDS = re.compile(r"[a-z0-9]+")
_DIMENSIONS = 128
_K1 = 1.2
_B = 0.75
_MAX_CHUNKS = 1000
_MAX_TEXT_CHARS = 20000
_MAX_QUERY_CHARS = 500


class LocalIndexDenied(ValueError):
    """The disabled flag, invalid scope, or unsafe search input blocks search."""


@dataclass(frozen=True)
class SearchScope:
    """Must be derived from server-verified campus and educator authorization."""

    campus_id: str
    educator_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.campus_id, str) or not self.campus_id.strip():
            raise LocalIndexDenied("Verified campus scope is required")
        if self.educator_id is not None and (
            not isinstance(self.educator_id, str) or not self.educator_id.strip()
        ):
            raise LocalIndexDenied("Invalid educator scope")


@dataclass(frozen=True)
class IndexedChunk:
    """Provenance wrapper; private content requires a verified owner identity."""

    chunk: ContentChunk
    owner_educator_id: str | None = None


@dataclass(frozen=True)
class ChunkHit:
    """Citable source metadata and inspectable local retrieval components."""

    chunk_id: str
    version: int
    source_id: str
    source_edition: str
    locator: str
    text: str
    score: float
    bm25_score: float
    vector_score: float


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(_WORDS.findall(value.casefold()))


def _vector(tokens: tuple[str, ...]) -> tuple[float, ...]:
    """Signed feature-hashing bag-of-words; local lexical vector, NOT an LLM embedding."""
    vector = [0.0] * _DIMENSIONS
    for term, count in Counter(tokens).items():
        digest = blake2b(term.encode("utf-8"), digest_size=8).digest()
        hashed = int.from_bytes(digest, "big")
        position = hashed % _DIMENSIONS
        vector[position] += (1.0 if (hashed >> 7) & 1 else -1.0) * count
    magnitude = sqrt(sum(value * value for value in vector))
    return tuple(value / magnitude for value in vector) if magnitude else tuple(vector)


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    # Signed hashing may yield negative similarities; never promote them.
    return max(0.0, sum(x * y for x, y in zip(a, b)))


def _eligible(item: IndexedChunk, scope: SearchScope) -> bool:
    if not isinstance(item, IndexedChunk) or not isinstance(item.chunk, ContentChunk):
        return False
    chunk = item.chunk
    if chunk.campus_id != scope.campus_id or chunk.status != ItemStatus.approved:
        return False
    if not isinstance(chunk.source_edition, str) or not chunk.source_edition.strip():
        return False  # Do not return excerpts with an unidentifiable source edition.
    # Licensed reuse requires a separately authenticated license-scope contract.
    # Unknown rights are excluded even if a forged review object is supplied.
    if chunk.rights_status not in (
        RightsStatus.original, RightsStatus.public_domain_verified,
        RightsStatus.teacher_private,
    ):
        return False
    if chunk.rights_status == RightsStatus.teacher_private and chunk.visibility != Visibility.teacher_private:
        return False
    if chunk.visibility == Visibility.teacher_private and (
        scope.educator_id is None or item.owner_educator_id != scope.educator_id
    ):
        return False
    if chunk.visibility not in (Visibility.campus, Visibility.teacher_private):
        return False
    try:
        require_approvable(
            item_id=chunk.chunk_id, version=chunk.version,
            rights=(chunk.rights_status,), review=chunk.review,
        )
    except (CurriculumModelError, TypeError, AttributeError):
        return False
    return True


def search_chunks(
    query: str,
    candidates: tuple[IndexedChunk, ...] | list[IndexedChunk],
    scope: SearchScope,
    *,
    limit: int = 10,
) -> tuple[ChunkHit, ...]:
    """Search only the approved, rights-eligible records in a verified scope.

    No hidden fallback: flag-off denies, private content without a matching
    owner is excluded, and every source returned has a human approval record.
    Scores are computed only after all policy filters. A caller must perform
    live grant/revocation checks before invoking this pure primitive.
    """
    if not curriculum_engine_enabled():
        raise LocalIndexDenied("Curriculum engine disabled")
    if not isinstance(scope, SearchScope):
        raise LocalIndexDenied("Verified search scope is required")
    if not isinstance(query, str) or len(query) > _MAX_QUERY_CHARS:
        raise LocalIndexDenied("Invalid query")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise LocalIndexDenied("Invalid result limit")
    if not isinstance(candidates, (tuple, list)) or len(candidates) > _MAX_CHUNKS:
        raise LocalIndexDenied("Invalid corpus size")

    # CRITICAL: never tokenize, vectorize, score, or cache excluded text.
    allowed = tuple(item.chunk for item in candidates if _eligible(item, scope))
    keys = [(chunk.chunk_id, chunk.version) for chunk in allowed]
    if len(keys) != len(set(keys)):
        raise LocalIndexDenied("Duplicate approved chunk version in search scope")
    if any(len(chunk.text) > _MAX_TEXT_CHARS for chunk in allowed):
        raise LocalIndexDenied("Approved chunk exceeds local search size limit")
    q = _tokens(query)
    if not q or not allowed:
        return ()

    documents = tuple(_tokens(chunk.text) for chunk in allowed)
    lengths = [len(doc) for doc in documents]
    avg_length = sum(lengths) / len(lengths) or 1.0
    query_terms = set(q)
    df = {term: sum(term in doc for doc in documents) for term in query_terms}
    q_vector = _vector(q)
    raw_bm25: list[float] = []
    cosine: list[float] = []
    for doc, doc_length in zip(documents, lengths):
        frequencies = Counter(doc)
        bm25 = 0.0
        for term in query_terms:
            tf = frequencies[term]
            if not tf:
                continue
            idf = log1p((len(documents) - df[term] + 0.5) / (df[term] + 0.5))
            bm25 += idf * tf * (_K1 + 1) / (
                tf + _K1 * (1 - _B + _B * doc_length / avg_length)
            )
        raw_bm25.append(bm25)
        cosine.append(_cosine(q_vector, _vector(doc)))
    peak = max(raw_bm25) or 1.0
    hits = tuple(
        ChunkHit(
            chunk_id=chunk.chunk_id, version=chunk.version,
            source_id=chunk.source_id, source_edition=chunk.source_edition,
            locator=chunk.locator, text=chunk.text,
            score=round(0.65 * (raw_bm25[i] / peak) + 0.35 * cosine[i], 8),
            bm25_score=round(raw_bm25[i], 8),
            vector_score=round(cosine[i], 8),
        )
        for i, chunk in enumerate(allowed)
        if raw_bm25[i] > 0  # No false hits from hash collisions without lexical evidence.
    )
    return tuple(sorted(
        hits, key=lambda hit: (-hit.score, hit.chunk_id, hit.version),
    )[:limit])
