"""PR 6: offline reciprocal-rank fusion and exact-source citation projection.

No router, network, learner profile, or lesson generation. This function
consumes ONLY trusted, already policy-filtered ChunkHit records from PR 5 and
independently human-reviewed annotations supplied by a future authorized
service boundary. It cannot authenticate those inputs by itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from services.curriculum.flag import curriculum_engine_enabled
from services.curriculum.local_hybrid_index import ChunkHit

_RRF_K = 60
_RRF_WEIGHT = 0.65
_POLICY_WEIGHT = 0.35
_MAX_HITS = 1000
_MAX_PASSAGES = 30
_MAX_QUOTE = 4000


class CitationRetrievalDenied(ValueError):
    """Invalid, unverified, or unscoped citation request."""


@dataclass(frozen=True)
class ReviewedAnnotation:
    """Source and classical-alignment ratings from a separately verified reviewer.

    Ratings are NOT generated or inferred here. The caller must obtain them
    from an authenticated, campus-scoped and review-controlled record.
    """
    chunk_id: str
    version: int
    source_reliability: float
    classical_alignment: float
    objective_ids: tuple[str, ...]
    review_ref: str
    source_kind: str = "unknown"
    grade_min: int | None = None
    grade_max: int | None = None
    standards: tuple[str, ...] = ()
    perspective: str = ""
    modular: bool = False

    def __post_init__(self) -> None:
        if self.source_kind not in ("unknown", "primary", "secondary"):
            raise CitationRetrievalDenied("Invalid reviewed source kind")
        if ((self.grade_min is None) != (self.grade_max is None)
                or (self.grade_min is not None and (
                    type(self.grade_min) is not int or type(self.grade_max) is not int
                    or not 0 <= self.grade_min <= self.grade_max <= 8))):
            raise CitationRetrievalDenied("Reviewed grade range must be K–8")
        if (not isinstance(self.standards, tuple)
                or any(not isinstance(s, str) or not s.strip() for s in self.standards)
                or not isinstance(self.perspective, str)
                or type(self.modular) is not bool):
            raise CitationRetrievalDenied("Invalid reviewed teaching metadata")
        if (not isinstance(self.chunk_id, str) or not self.chunk_id.strip()
                or type(self.version) is not int or self.version < 1
                or not isinstance(self.review_ref, str)
                or not self.review_ref.startswith("review:")
                or len(self.review_ref) <= len("review:")
                or not isinstance(self.objective_ids, tuple)
                or not self.objective_ids
                or any(not isinstance(x, str) or not x.strip()
                       for x in self.objective_ids)):
            raise CitationRetrievalDenied("Invalid reviewed annotation identity")
        for value in (self.source_reliability, self.classical_alignment):
            if type(value) not in (float, int) or not isfinite(value) or not 0 <= value <= 1:
                raise CitationRetrievalDenied("Reviewed policy ratings must be finite in [0,1]")


@dataclass(frozen=True)
class RankedCitation:
    hit: ChunkHit
    review_ref: str
    objective_id: str
    rrf_score: float
    reliability_score: float
    alignment_score: float
    objective_score: float
    effectiveness_score: float
    score: float
    primary_source_score: float = 0.0
    standards_score: float = 0.0
    modular_score: float = 0.0
    perspective: str = ""

    @property
    def citation_id(self) -> str:
        return f"{self.hit.chunk_id}@{self.hit.version}"


@dataclass(frozen=True)
class ExactPassage:
    citation_id: str
    source_id: str
    source_edition: str
    locator: str
    quote: str
    review_ref: str


@dataclass(frozen=True)
class PedagogicalProfile:
    """Server-selected grade and reviewed standards; never a student identity.

    Standards are exact identifiers, such as TEKS/CCSS catalog IDs, not
    model-invented mappings. Grade 0 denotes kindergarten.
    """
    grade: int
    standards: tuple[str, ...] = ()
    diverse_perspectives: bool = True

    def __post_init__(self) -> None:
        if (type(self.grade) is not int or not 0 <= self.grade <= 8
                or not isinstance(self.standards, tuple)
                or any(not isinstance(s, str) or not s.strip() for s in self.standards)
                or type(self.diverse_perspectives) is not bool):
            raise CitationRetrievalDenied("Invalid K–8 pedagogical profile")


def _require_enabled() -> None:
    if not curriculum_engine_enabled():
        raise CitationRetrievalDenied("Curriculum engine disabled")


def rank_citations(
    hits: tuple[ChunkHit, ...] | list[ChunkHit],
    annotations: tuple[ReviewedAnnotation, ...] | list[ReviewedAnnotation],
    *, authorized_objective_id: str,
    limit: int = 10,
    profile: PedagogicalProfile | None = None,
) -> tuple[RankedCitation, ...]:
    """RRF(BM25, signed local vectors) then transparent R/A/O policy scoring.

    The authorized objective must come from an independently verified teacher
    instruction, never an untrusted client query. P/L are deferred and E is
    fixed to zero. Missing/mismatched annotations fail closed rather than
    fabricating provenance or alignment scores.
    """
    _require_enabled()
    if profile is not None and not isinstance(profile, PedagogicalProfile):
        raise CitationRetrievalDenied("Invalid pedagogical profile")
    if (not isinstance(authorized_objective_id, str)
            or not authorized_objective_id.strip()
            or type(limit) is not int or not 1 <= limit <= 20
            or not isinstance(hits, (tuple, list))
            or not isinstance(annotations, (tuple, list))
            or len(hits) > _MAX_HITS or len(annotations) > _MAX_HITS):
        raise CitationRetrievalDenied("Invalid authorized retrieval request")
    if any(not isinstance(hit, ChunkHit) for hit in hits):
        raise CitationRetrievalDenied("Invalid retrieval hit")
    if any(not isinstance(a, ReviewedAnnotation) for a in annotations):
        raise CitationRetrievalDenied("Unverified ranking annotation")
    by_key = {(a.chunk_id, a.version): a for a in annotations}
    hit_keys = [(h.chunk_id, h.version) for h in hits]
    if (len(by_key) != len(annotations) or len(hit_keys) != len(set(hit_keys))
            or any(k not in by_key for k in hit_keys)):
        raise CitationRetrievalDenied("Duplicate or missing reviewed annotation")
    for h in hits:
        if (not h.source_id or not h.source_edition.strip() or not h.locator.strip()
                or not h.text.strip() or any(
                    type(v) not in (int, float) or not isfinite(v) or v < 0
                    for v in (h.score, h.bm25_score, h.vector_score)
                )):
            raise CitationRetrievalDenied("Invalid citable source or retrieval score")
    # Objective authorization is a HARD filter, not a soft preference.
    eligible = [h for h in hits if authorized_objective_id in
                by_key[(h.chunk_id, h.version)].objective_ids and h.bm25_score > 0]
    if profile is not None:
        # Missing age review is not permission to show material to a child.
        eligible = [h for h in eligible if (
            (a := by_key[(h.chunk_id, h.version)]).grade_min is not None
            and a.grade_min <= profile.grade <= a.grade_max
        )]
    if not eligible:
        return ()
    lexical = sorted(eligible, key=lambda h: (-h.bm25_score, h.chunk_id, h.version))
    vector = sorted(eligible, key=lambda h: (-h.vector_score, h.chunk_id, h.version))
    lexical_rank = {(h.chunk_id, h.version): i + 1 for i, h in enumerate(lexical)}
    vector_rank = {(h.chunk_id, h.version): i + 1 for i, h in enumerate(vector)}
    maximum_rrf = 2 / (_RRF_K + 1)
    ranked = []
    for h in eligible:
        key = (h.chunk_id, h.version)
        a = by_key[key]
        rrf = (1 / (_RRF_K + lexical_rank[key]) +
               1 / (_RRF_K + vector_rank[key])) / maximum_rrf
        # R = independently reviewed source reliability, A = independently
        # reviewed classical alignment, O = exact authorized objective match.
        # E (independent effectiveness evidence) is locked to zero.
        r, alignment, objective = a.source_reliability, a.classical_alignment, 1.0
        policy = 0.4 * r + 0.2 * alignment + 0.4 * objective
        base_score = _RRF_WEIGHT * rrf + _POLICY_WEIGHT * policy
        primary = float(a.source_kind == "primary") if profile else 0.0
        standards = float(bool(set(a.standards) & set(profile.standards))) if profile else 0.0
        modular = float(a.modular) if profile else 0.0
        score = (0.6 * base_score + 0.2 * primary + 0.15 * standards + 0.05 * modular
                 if profile else base_score)
        ranked.append(RankedCitation(
            hit=h, review_ref=a.review_ref,
            objective_id=authorized_objective_id,
            rrf_score=round(rrf, 8), reliability_score=r,
            alignment_score=alignment, objective_score=objective,
            effectiveness_score=0.0,
            score=round(score, 8),
            primary_source_score=primary, standards_score=standards,
            modular_score=modular, perspective=a.perspective,
        ))
    ordered = sorted(
        ranked, key=lambda item: (-item.score, item.hit.chunk_id, item.hit.version),
    )
    if profile and profile.diverse_perspectives:
        # Prefer distinct reviewed perspectives without selecting irrelevant,
        # unreviewed, out-of-grade, or unauthorized material for "balance."
        selected, remaining = ordered[:1], []
        seen = {ordered[0].perspective} if ordered else set()
        for item in ordered[1:]:
            if item.perspective and item.perspective not in seen:
                selected.append(item)
                seen.add(item.perspective)
            else:
                remaining.append(item)
        ordered = selected + remaining
    return tuple(ordered[:limit])


def project_exact_passages(
    ranked: tuple[RankedCitation, ...] | list[RankedCitation],
    requests: tuple[tuple[str, str], ...] | list[tuple[str, str]],
) -> tuple[ExactPassage, ...]:
    """Only project literal excerpts from authorized ranked citations.

    Input pairs are (citation_id, exact_quote). Uncited, altered, fabricated,
    or unapproved excerpts are silently dropped; the caller must separately
    disclose missing evidence rather than invent a citation or paraphrase.
    """
    _require_enabled()
    if (not isinstance(ranked, (tuple, list)) or len(ranked) > _MAX_HITS
            or not isinstance(requests, (tuple, list)) or len(requests) > _MAX_PASSAGES):
        raise CitationRetrievalDenied("Invalid passage projection request")
    if any(not isinstance(item, RankedCitation) for item in ranked):
        raise CitationRetrievalDenied("Invalid ranked citation")
    by_id = {item.citation_id: item for item in ranked}
    if len(by_id) != len(ranked):
        raise CitationRetrievalDenied("Duplicate ranked citation")
    projected = []
    seen = set()
    for request in requests:
        if (not isinstance(request, tuple) or len(request) != 2
                or not all(isinstance(x, str) for x in request)):
            raise CitationRetrievalDenied("Invalid passage request")
        citation_id, quote = request
        item = by_id.get(citation_id)
        if (item is None or not quote.strip() or len(quote) > _MAX_QUOTE
                or quote not in item.hit.text or (citation_id, quote) in seen):
            continue
        seen.add((citation_id, quote))
        projected.append(ExactPassage(
            citation_id=citation_id, source_id=item.hit.source_id,
            source_edition=item.hit.source_edition, locator=item.hit.locator,
            quote=quote, review_ref=item.review_ref,
        ))
    return tuple(projected)
