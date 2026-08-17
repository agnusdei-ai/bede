"""Tier 1 detection: free, instant, deterministic, no dependencies.

    user input -> [Tier 1 regex] + [Tier 2 classifier] -> policy engine -> agent

Tier 1 exists for two reasons a classifier-only design cannot cover:

  1. It still works during a classifier outage. Your classifier must fail open
     (see G12), which means a timeout is a window with no Tier-2 signal at all.
     Tier 1 is what is left.
  2. It is instant and free for the phrasings blunt enough to enumerate safely.

It is deliberately NARROW. Every pattern here is curated for very low
false-positive risk against ordinary legitimate traffic. A classifier reasons
about ambiguous intent; a regex cannot, so a regex should only be asked about
phrasings with no legitimate use.

Note what is NOT here: social engineering has no Tier 1 pattern at all.
Manipulation framing is too context-dependent to enumerate safely -- a free-text
pattern would misfire constantly on ordinary impatience ("can we hurry up").
Some categories are classifier-only, and that is a design decision rather than
an omission.

This module emits FACTS. What they mean is policy_engine.decide()'s job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence

# Blunt "unrestricted alter-ego" framing. Deliberately does NOT match
# jailbreak-FLAVORED creative writing -- "pretend you're a dragon with no rules
# *in the story*" is legitimate work in many domains.
JAILBREAK_PATTERN = re.compile(
    r"(\bdan\s+mode\b"
    r"|\bjailbreak(ing)?\b"
    r"|\bdeveloper\s+mode\b"
    r"|\bunrestricted\s+mode\b"
    r"|\bdo\s+anything\s+now\b"
    r"|\byou\s+have\s+no\s+(rules|restrictions|filters|guidelines)\b"
    r"|\bact\s+as\s+(if\s+you\s+(had|have)\s+)?no\s+(rules|restrictions)\b"
    r"|\bpretend\s+(you\s+are\s+)?an?\s+ai\s+(with\s+)?no\s+(rules|restrictions|guidelines)\b)",
    re.IGNORECASE,
)

# Claimed false authority, or an explicit demand to bypass rules on that
# authority. Someone REPORTING what a real authority said ("my manager approved
# this") does not match -- there is no bypass/override/admin-mode language.
POLICY_OVERRIDE_PATTERN = re.compile(
    r"(\bi\s*(['’])?m\s+(the\s+|your\s+)?(parent|admin|administrator|the\s+developer|the\s+owner)\b"
    r"|\bi\s+am\s+(the\s+|your\s+)?(parent|admin|administrator|the\s+developer|the\s+owner)\b"
    r"|\b(enable|activate|turn\s+on)\s+(admin|developer|debug)\s+mode\b"
    r"|\b(unlock|bypass|override|disable)\s+(the\s+|your\s+)?"
    r"(rules?|restrictions?|safety|filters?|guardrails?|parental\s+controls?)\b"
    r"|\bgive\s+me\s+(admin|root|full)\s+access\b)",
    re.IGNORECASE,
)

# Asking the agent to disclose its own prompt, repeat prior context verbatim, or
# reveal other users, servers, or credentials.
EXFILTRATION_PATTERN = re.compile(
    r"(\bsystem\s+prompt\b"
    r"|\brepeat\s+(everything|the\s+text|what\s+was\s+said)\s+above\b"
    r"|\bprint\s+(your\s+)?(instructions|system\s+prompt|everything\s+above)\b"
    r"|\bwhat\s+(is|are)\s+your\s+(instructions|system\s+prompt|api\s+key|secret)\b"
    r"|\bshow\s+me\s+(the\s+)?(database|other\s+users?|api\s+key)\b"
    r"|\blist\s+all\s+(users?|accounts?|passwords?)\b)",
    re.IGNORECASE,
)

TIER1_DETECTORS: tuple[tuple[str, re.Pattern], ...] = (
    ("jailbreak_intent", JAILBREAK_PATTERN),
    ("policy_override_attempt", POLICY_OVERRIDE_PATTERN),
    ("data_exfiltration_attempt", EXFILTRATION_PATTERN),
)

#: The categories this tier and the policy engine act on. Kept separate from
#: your classifier's general content categories (self_harm, violence, ...),
#: which have their own, unchanged handling.
ADVERSARIAL_CATEGORIES = frozenset(
    {
        "jailbreak_intent",
        "policy_override_attempt",
        "data_exfiltration_attempt",
        "social_engineering",
    }
)


@dataclass
class AdversarialSignals:
    """Everything detection found for one turn. Facts only."""

    tier1_categories: set = field(default_factory=set)
    #: The classifier's full category list for this turn, reused as-is rather
    #: than re-fetched -- you already made that call.
    classifier_categories: list = field(default_factory=list)
    classifier_confidence: str = "low"


def detect_tier1(message: str) -> set:
    """Return the set of categories any pattern matched. Empty is the
    overwhelmingly common case."""
    if not message:
        return set()
    return {category for category, pattern in TIER1_DETECTORS if pattern.search(message)}


def build_signals(message: str, classification: Mapping) -> AdversarialSignals:
    """Combine this turn's Tier 1 pass with the classification you already have.

    No second classifier call. `classification` is trusted to be fail-open-safe
    already (empty categories on any failure), so this needs no try/except.
    """
    categories: Sequence = classification.get("categories") or []
    return AdversarialSignals(
        tier1_categories=detect_tier1(message),
        classifier_categories=list(categories),
        classifier_confidence=classification.get("confidence", "low"),
    )
