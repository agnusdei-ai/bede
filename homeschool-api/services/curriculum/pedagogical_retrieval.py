"""Offline search orchestration for an already-authorized curriculum caller.

This is a service primitive, not an endpoint or an authorization mechanism.
Never obtain campus scope, objective authorization, or review metadata from
student-supplied text. No network, model download, persistence, or query logging.
"""
from __future__ import annotations

from services.curriculum.citation_retriever import (
    CitationRetrievalDenied, PedagogicalProfile, RankedCitation,
    ReviewedAnnotation, rank_citations,
)
from services.curriculum.local_hybrid_index import IndexedChunk, SearchScope, search_chunks


def retrieve_for_learning(
    query: str,
    candidates: tuple[IndexedChunk, ...] | list[IndexedChunk],
    annotations: tuple[ReviewedAnnotation, ...] | list[ReviewedAnnotation],
    scope: SearchScope,
    *,
    authorized_objective_id: str,
    profile: PedagogicalProfile,
    limit: int = 10,
) -> tuple[RankedCitation, ...]:
    """Filter reviewed grade/objective BEFORE tokenization or top-k truncation."""
    if (not isinstance(profile, PedagogicalProfile)
            or not isinstance(candidates, (tuple, list)) or len(candidates) > 1000
            or not isinstance(annotations, (tuple, list)) or len(annotations) > 1000
            or any(not isinstance(a, ReviewedAnnotation) for a in annotations)
            or not isinstance(authorized_objective_id, str)
            or not authorized_objective_id.strip()
            or type(limit) is not int or not 1 <= limit <= 20):
        raise CitationRetrievalDenied("Invalid pedagogical retrieval request")
    by_key = {(a.chunk_id, a.version): a for a in annotations}
    if len(by_key) != len(annotations):
        raise CitationRetrievalDenied("Duplicate reviewed annotation")
    filtered = []
    for item in candidates:
        if not isinstance(item, IndexedChunk):
            raise CitationRetrievalDenied("Invalid indexed curriculum record")
        annotation = by_key.get((item.chunk.chunk_id, item.chunk.version))
        if (annotation and annotation.grade_min is not None
                and annotation.grade_min <= profile.grade <= annotation.grade_max
                and authorized_objective_id in annotation.objective_ids):
            filtered.append(item)
    # Existing campus/owner/rights/review gates still run inside search_chunks.
    hits = search_chunks(query, filtered, scope, limit=20)
    return rank_citations(
        hits, annotations, authorized_objective_id=authorized_objective_id,
        profile=profile, limit=limit,
    )
