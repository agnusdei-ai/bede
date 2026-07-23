"""
services/policy_engine.py — the second stage of the adversarial-resilience
pipeline. Covers decide()'s tiering: policy_override_attempt/
data_exfiltration_attempt redirect on a Tier 1 hit OR a medium+ confidence
Tier 2 flag; jailbreak_intent/social_engineering never redirect alone, no
matter the confidence, mirroring services/moderation.py's own treatment of
prompt_injection.
"""
from services.adversarial_detection import AdversarialSignals
from services.policy_engine import decide, PolicyDecision


def _signals(tier1=None, classifier=None, confidence="low"):
    return AdversarialSignals(
        tier1_categories=set(tier1 or []),
        classifier_categories=list(classifier or []),
        classifier_confidence=confidence,
    )


def test_no_signals_allows_the_turn():
    decision = decide(_signals())
    assert decision == PolicyDecision(should_redirect=False, detected_categories=set(), blocking_categories=set())


def test_tier1_policy_override_redirects_even_at_low_classifier_confidence():
    decision = decide(_signals(tier1=["policy_override_attempt"]))
    assert decision.should_redirect is True
    assert decision.blocking_categories == {"policy_override_attempt"}
    assert decision.detected_categories == {"policy_override_attempt"}


def test_tier1_data_exfiltration_redirects():
    decision = decide(_signals(tier1=["data_exfiltration_attempt"]))
    assert decision.should_redirect is True
    assert decision.blocking_categories == {"data_exfiltration_attempt"}


def test_tier2_policy_override_at_medium_confidence_redirects():
    decision = decide(_signals(classifier=["policy_override_attempt"], confidence="medium"))
    assert decision.should_redirect is True
    assert decision.blocking_categories == {"policy_override_attempt"}


def test_tier2_policy_override_at_low_confidence_does_not_redirect():
    decision = decide(_signals(classifier=["policy_override_attempt"], confidence="low"))
    assert decision.should_redirect is False
    # Still recorded for audit visibility even though it didn't block.
    assert decision.detected_categories == {"policy_override_attempt"}
    assert decision.blocking_categories == set()


def test_jailbreak_intent_never_redirects_alone_even_at_high_confidence():
    decision = decide(_signals(classifier=["jailbreak_intent"], confidence="high"))
    assert decision.should_redirect is False
    assert decision.detected_categories == {"jailbreak_intent"}
    assert decision.blocking_categories == set()


def test_jailbreak_intent_tier1_hit_never_redirects_alone():
    decision = decide(_signals(tier1=["jailbreak_intent"]))
    assert decision.should_redirect is False
    assert decision.detected_categories == {"jailbreak_intent"}


def test_social_engineering_never_redirects_alone():
    decision = decide(_signals(classifier=["social_engineering"], confidence="high"))
    assert decision.should_redirect is False
    assert decision.detected_categories == {"social_engineering"}


def test_jailbreak_and_policy_override_together_redirects_on_the_blocking_category_only():
    decision = decide(_signals(
        tier1=["jailbreak_intent", "policy_override_attempt"],
    ))
    assert decision.should_redirect is True
    assert decision.blocking_categories == {"policy_override_attempt"}
    assert decision.detected_categories == {"jailbreak_intent", "policy_override_attempt"}


def test_unrelated_classifier_categories_are_ignored():
    """self_harm/violence/etc. are the original five, handled entirely by
    routers/tutor.py's own moderation.should_block gate before this module
    is ever reached — decide() must not react to them at all."""
    decision = decide(_signals(classifier=["self_harm", "prompt_injection"], confidence="high"))
    assert decision == PolicyDecision(should_redirect=False, detected_categories=set(), blocking_categories=set())
