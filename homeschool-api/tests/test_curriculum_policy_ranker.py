"""PR 7 synthetic qualification: no network, fixed labels, or learner actions."""
from datetime import datetime, timezone
import socket

import pytest

from services.curriculum.citation_retriever import RankedCitation
from services.curriculum.learner_evolution import (
    LearnerEvolutionProfile, LearningEvidence, summarize_skill,
)
from services.curriculum.local_hybrid_index import ChunkHit
from services.curriculum.policy_ranker import (
    PolicyContext, PolicyRankingDenied, PolicyWeights, ScopedObservation,
    rerank_for_learner,
)

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)
CAMPUS = "synthetic-campus"
LEARNER = "opaque_learner_1234"
OBJECTIVE = "history-objective"


@pytest.fixture(autouse=True)
def enable_synthetic_only(monkeypatch):
    monkeypatch.setenv("CURRICULUM_ENGINE_ENABLED", "true")


def evidence(ref, skill, signal, response="not_observed", kind="diagnostic"):
    return LearningEvidence(
        evidence_ref="evidence:" + ref, skill_id=skill, kind=kind,
        observed_at=NOW, mastery_signal=signal,
        instructional_response=response,
    )


def profile(*records):
    skills = tuple(summarize_skill(skill, tuple(records))
                   for skill in sorted({r.skill_id for r in records}))
    return LearnerEvolutionProfile(CAMPUS, LEARNER, 1, NOW, skills)


def citation(chunk_id, *, rrf=0.5):
    hit = ChunkHit(
        chunk_id=chunk_id, version=1, source_id="source-" + chunk_id,
        source_edition="Verified edition", locator="chapter 1, paragraph 1",
        text="Roman history", score=0.5, bm25_score=0.5,
        vector_score=0.5,
    )
    return RankedCitation(
        hit=hit, review_ref="review:" + chunk_id,
        objective_id=OBJECTIVE, rrf_score=rrf,
        reliability_score=0.5, alignment_score=0.5,
        objective_score=1.0, effectiveness_score=0.0, score=0.5,
    )


def context(chunk_id, *, prereqs=(), target=("history",), scaffold=0.5):
    return PolicyContext(
        campus_id=CAMPUS, chunk_id=chunk_id, version=1,
        review_ref="review:" + chunk_id, objective_id=OBJECTIVE,
        prerequisite_skill_ids=prereqs, target_skill_ids=target,
        scaffolding_intensity=scaffold,
    )


def rank(citations, contexts, p, observations=(), **kwargs):
    return rerank_for_learner(
        citations, contexts, p, observations, campus_id=CAMPUS,
        learner_ref=LEARNER, objective_id=OBJECTIVE, **kwargs,
    )


def weights_for(term):
    values = dict(rrf=0.0, reliability=0.0, alignment=0.0,
                  objective=0.0, prerequisite=0.0, learner_fit=0.0)
    values[term] = 1.0
    return PolicyWeights(version="ablation-" + term, **values)


def test_prerequisite_term_changes_ordering_with_versioned_weights():
    high = evidence("high-001", "ready", 1.0)
    low = evidence("low-001", "unready", 0.0)
    p = profile(high, low)
    hits = [citation("a", rrf=0.3), citation("b", rrf=0.7)]
    contexts = [context("a", prereqs=("ready",)),
                context("b", prereqs=("unready",))]
    by_p = rank(hits, contexts, p, weights=weights_for("prerequisite"))
    by_rrf = rank(hits, contexts, p, weights=weights_for("rrf"))
    assert [x.citation.hit.chunk_id for x in by_p] == ["a", "b"]
    assert [x.citation.hit.chunk_id for x in by_rrf] == ["b", "a"]
    assert by_p[0].prerequisite_score > by_p[1].prerequisite_score
    assert by_p[0].prerequisite_evidence_refs == ("evidence:high-001",)
    assert by_p[0].weight_version == "ablation-prerequisite"
    assert by_p[0].effectiveness_score == 0.0
    assert dict(by_p[0].terms)["effectiveness"] == 0.0


def test_observed_support_term_changes_order_without_learning_style_labels():
    observed = evidence("practice-001", "history", 0.4,
                        response="reexplained", kind="practice")
    p = profile(observed)
    hits = [citation("a", rrf=0.7), citation("b", rrf=0.3)]
    contexts = [context("a", scaffold=0.0), context("b", scaffold=1.0)]
    by_fit = rank(hits, contexts, p,
                  [ScopedObservation(CAMPUS, LEARNER, observed)],
                  weights=weights_for("learner_fit"))
    by_rrf = rank(hits, contexts, p,
                  [ScopedObservation(CAMPUS, LEARNER, observed)],
                  weights=weights_for("rrf"))
    assert [x.citation.hit.chunk_id for x in by_fit] == ["b", "a"]
    assert [x.citation.hit.chunk_id for x in by_rrf] == ["a", "b"]
    assert by_fit[0].observation_evidence_refs == ("evidence:practice-001",)
    assert by_fit[0].learner_fit_score > by_fit[1].learner_fit_score
    assert all("style" not in str(x.terms).lower() for x in by_fit)


def test_no_observation_or_missing_prerequisite_stays_neutral():
    p = profile(evidence("base-001", "history", 0.8))
    result = rank([citation("a")], [context("a", prereqs=("unknown",))], p)
    assert result[0].prerequisite_score == 0.5
    assert result[0].learner_fit_score == 0.5
    assert result[0].prerequisite_evidence_refs == ()
    assert result[0].observation_evidence_refs == ()


def test_cross_campus_and_cross_learner_profile_denied():
    p = profile(evidence("base-001", "history", 0.8))
    hits, contexts = [citation("a")], [context("a")]
    for bad in (
        LearnerEvolutionProfile("other-campus", LEARNER, 1, NOW, p.skills),
        LearnerEvolutionProfile(CAMPUS, "another_learner_001", 1, NOW, p.skills),
    ):
        with pytest.raises(PolicyRankingDenied):
            rank(hits, contexts, bad)


def test_unbound_cross_learner_observation_denied():
    obs = evidence("practice-001", "history", 0.4, "hinted", "practice")
    p = profile(obs)
    hits, contexts = [citation("a")], [context("a")]
    for bad in (
        ScopedObservation("other-campus", LEARNER, obs),
        ScopedObservation(CAMPUS, "other_learner_001", obs),
        ScopedObservation(CAMPUS, LEARNER,
                          evidence("unverified-001", "history", 0.5, "hinted", "practice")),
    ):
        with pytest.raises(PolicyRankingDenied):
            rank(hits, contexts, p, [bad])


def test_duplicate_missing_or_mismatched_review_metadata_denied():
    p = profile(evidence("base-001", "history", 0.8))
    hits = [citation("a"), citation("b")]
    with pytest.raises(PolicyRankingDenied, match="Duplicate or missing"):
        rank(hits, [context("a")], p)
    with pytest.raises(PolicyRankingDenied, match="Duplicate or missing"):
        rank(hits, [context("a"), context("a")], p)
    with pytest.raises(PolicyRankingDenied, match="Review or objective"):
        rank([citation("a")], [PolicyContext(
            CAMPUS, "a", 1, "review:wrong", OBJECTIVE, (), ("history",), 0.5
        )], p)
    with pytest.raises(PolicyRankingDenied, match="Review or objective"):
        rank([citation("a")], [PolicyContext(
            "other-campus", "a", 1, "review:a", OBJECTIVE, (), ("history",), 0.5
        )], p)


def test_no_effectiveness_weight_or_invalid_scaffold():
    with pytest.raises(PolicyRankingDenied, match="weights"):
        PolicyWeights(effectiveness=0.1)
    with pytest.raises(PolicyRankingDenied, match="weights"):
        PolicyWeights(rrf=float("nan"))
    with pytest.raises(PolicyRankingDenied):
        context("a", scaffold=float("nan"))
    with pytest.raises(PolicyRankingDenied):
        context("a", scaffold=True)


def test_feature_flag_off_and_no_network(monkeypatch):
    p = profile(evidence("base-001", "history", 0.8))
    hits, contexts = [citation("a")], [context("a")]
    def no_network(*args, **kwargs):
        raise AssertionError("Network use prohibited")
    monkeypatch.setattr(socket, "socket", no_network)
    assert rank(hits, contexts, p)[0].score > 0
    monkeypatch.delenv("CURRICULUM_ENGINE_ENABLED")
    with pytest.raises(PolicyRankingDenied, match="disabled"):
        rank(hits, contexts, p)


def test_evidence_replay_denied_and_no_automatic_action():
    obs = evidence("practice-001", "history", 0.4, "hinted", "practice")
    p = profile(obs)
    with pytest.raises(PolicyRankingDenied, match="Observation"):
        rank([citation("a")], [context("a")], p,
             [ScopedObservation(CAMPUS, LEARNER, obs)] * 2)
    result = rank([citation("a")], [context("a")], p)
    assert not hasattr(result[0], "approve")
    assert not hasattr(result[0], "placement")
    assert not hasattr(result[0], "learner_ref")
