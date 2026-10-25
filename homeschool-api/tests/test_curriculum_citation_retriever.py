"""Synthetic PR 6 qualification: objective-gated fusion and literal citations."""
from datetime import datetime, timezone
import socket

import pytest

from services.curriculum.citation_retriever import (
    CitationRetrievalDenied, ReviewedAnnotation, project_exact_passages,
    rank_citations,
)
from services.curriculum.local_hybrid_index import (
    IndexedChunk, SearchScope, search_chunks,
)
from services.curriculum.models import (
    ContentChunk, ItemStatus, ReviewDecision, ReviewRecord, RightsStatus,
    Visibility,
)

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def engine_enabled(monkeypatch):
    monkeypatch.setenv("CURRICULUM_ENGINE_ENABLED", "true")


def record(chunk_id, text, *, campus="campus-a", visibility=Visibility.campus,
           rights=RightsStatus.original, status=ItemStatus.approved,
           owner=None):
    review = ReviewRecord(
        review_id="review-" + chunk_id, item_id=chunk_id, item_version=1,
        reviewed_by="verified-educator", reviewed_at=NOW,
        decision=ReviewDecision.approve,
    ) if status == ItemStatus.approved else None
    return IndexedChunk(
        chunk=ContentChunk(
            chunk_id=chunk_id, source_id="source-" + chunk_id,
            locator="chapter 1, paragraph 3",
            text=text, verbatim=False, source_edition="Verified edition",
            rights_status=rights, objective_ids=("history-objective",),
            subject="history", stage="grammar", campus_id=campus,
            visibility=visibility, status=status, version=1, review=review,
        ),
        owner_educator_id=owner,
    )


def annotation(chunk_id, reliability=0.7, alignment=0.8, objectives=("history-objective",)):
    return ReviewedAnnotation(
        chunk_id=chunk_id, version=1, source_reliability=reliability,
        classical_alignment=alignment, objective_ids=objectives,
        review_ref="review:verified-" + chunk_id,
    )


def corpus():
    return [
        record("a", "Roman republic, the Roman senate and republic government."),
        record("b", "Roman republic and civic duties in the senate."),
        record("cross", "Roman republic cross-campus restricted.", campus="campus-b"),
        record("unreviewed", "Roman republic unapproved.", status=ItemStatus.staged),
        record("private", "Roman republic teacher private.",
               visibility=Visibility.teacher_private, owner="teacher-1"),
    ]


def test_rrf_policy_and_objective_terms_are_inspectable():
    hits = search_chunks("Roman republic", corpus(), SearchScope("campus-a"))
    assert {h.chunk_id for h in hits} == {"a", "b"}
    ranked = rank_citations(
        hits, [annotation("a", 0.1, 0.1), annotation("b", 1.0, 1.0)],
        authorized_objective_id="history-objective",
    )
    assert {r.hit.chunk_id for r in ranked} == {"a", "b"}
    assert all(r.rrf_score > 0 and r.objective_score == 1 for r in ranked)
    assert all(r.effectiveness_score == 0.0 for r in ranked)
    assert ranked[0].hit.chunk_id == "b"  # Verified policy terms change ordering.
    assert rank_citations(
        hits, [annotation("a", 0.1, 0.1), annotation("b", 1.0, 1.0)],
        authorized_objective_id="history-objective",
    ) == ranked


def test_missing_or_different_objective_fails_closed():
    hits = search_chunks("Roman republic", corpus(), SearchScope("campus-a"))
    assert rank_citations(
        hits, [annotation("a"), annotation("b")],
        authorized_objective_id="math-objective",
    ) == ()
    result = rank_citations(
        hits, [annotation("a", objectives=("math-objective",)),
               annotation("b", objectives=("history-objective",))],
        authorized_objective_id="history-objective",
    )
    assert [x.hit.chunk_id for x in result] == ["b"]


def test_missing_duplicate_or_unreviewed_annotations_denied():
    hits = search_chunks("Roman republic", corpus(), SearchScope("campus-a"))
    with pytest.raises(CitationRetrievalDenied, match="missing"):
        rank_citations(hits, [annotation("a")], authorized_objective_id="history-objective")
    with pytest.raises(CitationRetrievalDenied, match="Duplicate"):
        rank_citations(hits, [annotation("a"), annotation("a"), annotation("b")],
                       authorized_objective_id="history-objective")
    for invalid in (float("nan"), float("inf"), -0.1, 1.1, True):
        with pytest.raises(CitationRetrievalDenied):
            annotation("a", reliability=invalid)


def test_exact_citations_drop_unsupported_quotes_without_fabrication():
    hits = search_chunks("Roman republic", corpus(), SearchScope("campus-a"))
    ranked = rank_citations(
        hits, [annotation("a"), annotation("b")],
        authorized_objective_id="history-objective",
    )
    citations = project_exact_passages(
        ranked, [
            ("a@1", "Roman senate"),
            ("b@1", "civic duties"),
            ("b@1", "invented quotation"),
            ("cross@1", "cross-campus restricted"),
            ("a@1", "Roman senate"),
            ("a@1", ""),
        ],
    )
    assert [(x.citation_id, x.quote) for x in citations] == [
        ("a@1", "Roman senate"), ("b@1", "civic duties")
    ]
    assert all(x.source_edition == "Verified edition" for x in citations)
    assert all(x.locator == "chapter 1, paragraph 3" for x in citations)
    assert all(x.review_ref.startswith("review:") for x in citations)


def test_scope_and_review_filters_stay_upstream_of_fusion():
    hits = search_chunks(
        "Roman republic", corpus(), SearchScope("campus-a", "teacher-1"),
    )
    assert {h.chunk_id for h in hits} == {"a", "b", "private"}
    ranked = rank_citations(
        hits, [annotation("a"), annotation("b"), annotation("private")],
        authorized_objective_id="history-objective",
    )
    assert {r.hit.chunk_id for r in ranked} == {"a", "b", "private"}
    assert not any("cross" in r.hit.text or "unapproved" in r.hit.text for r in ranked)


def test_flag_off_blocks_fusion_and_projection(monkeypatch):
    hits = search_chunks("Roman republic", corpus(), SearchScope("campus-a"))
    ranked = rank_citations(
        hits, [annotation("a"), annotation("b")],
        authorized_objective_id="history-objective",
    )
    monkeypatch.delenv("CURRICULUM_ENGINE_ENABLED")
    with pytest.raises(CitationRetrievalDenied, match="disabled"):
        rank_citations(hits, [annotation("a"), annotation("b")],
                       authorized_objective_id="history-objective")
    with pytest.raises(CitationRetrievalDenied, match="disabled"):
        project_exact_passages(ranked, [("a@1", "Roman senate")])


def test_offline_only_and_invalid_projection_inputs(monkeypatch):
    hits = search_chunks("Roman republic", corpus(), SearchScope("campus-a"))
    def forbid_network(*args, **kwargs):
        raise AssertionError("No network calls allowed")
    monkeypatch.setattr(socket, "socket", forbid_network)
    ranked = rank_citations(
        hits, [annotation("a"), annotation("b")],
        authorized_objective_id="history-objective",
    )
    assert project_exact_passages(ranked, [("a@1", "Roman senate")])
    with pytest.raises(CitationRetrievalDenied):
        project_exact_passages(ranked, [("a@1", None)])
    with pytest.raises(CitationRetrievalDenied):
        rank_citations(hits, [annotation("a"), annotation("b")],
                       authorized_objective_id="history-objective", limit=True)
