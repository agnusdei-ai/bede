"""
Adversarial Detection — the free, deterministic tier of Bede's adversarial-
resilience pipeline:

    User Input -> Adversarial Detection -> Policy Engine -> Tutor State
    Machine -> Action Validator -> Parent/Student

Covers, or documents where else in the codebase covers, each of the six
detection categories that pipeline is meant to catch:

- Prompt injection: `_INJECTION_PATTERN` (services/ai_service.py, parent-
  supplied fields) + the classifier's `prompt_injection` category
  (services/moderation.py) — both pre-date this module, unchanged by it.
- Jailbreak detection: `_JAILBREAK_PATTERN` below (Tier 1, this module) +
  the classifier's `jailbreak_intent` category (Tier 2, moderation.py).
- Policy override attempts: `_POLICY_OVERRIDE_PATTERN` below (Tier 1) +
  the classifier's `policy_override_attempt` category (Tier 2).
- Data exfiltration attempts: `_EXFILTRATION_PATTERN` below (Tier 1) +
  the classifier's `data_exfiltration_attempt` category (Tier 2) — the
  CONVERSATIONAL variant (a child/attacker trying to get Bede to reveal
  secrets via chat). The HTTP/response-body variant is a separate,
  already-existing layer: core/middleware.py's ExfiltrationGuard.
- Tool abuse detection: services/ai_service.py's `_MAX_TOOL_CALLS_PER_TURN`
  cap + `AuditEvent.TOOL_INVOKED`/`TOOL_CALL_SUPPRESSED` — a downstream
  concern (it needs to see actual tool calls, which only exist once the
  Tutor State Machine is already running), not duplicated here.
- Social engineering: the classifier's `social_engineering` category only
  (Tier 2) — deliberately no Tier 1 regex. Manipulation/pressure framing
  is too context-dependent to enumerate safely; a free-text pattern here
  would misfire constantly on ordinary kid impatience ("can we hurry").

Tier 1 (this module) exists for two reasons a Tier-2-only design can't
cover: it still works during a classifier outage (moderation.py fails
open — Tier 1 is the only signal left in that window), and it's instant/
free for the phrasings blunt enough to enumerate safely. It is
deliberately narrow: every pattern here is curated for very low false-
positive risk against ordinary K-8 Socratic dialogue, unlike a classifier
that reasons about ambiguous intent. See services/policy_engine.py for
what actually happens with a Tier 1 or Tier 2 hit — detection and policy
are kept separate so either can change without the other.
"""
import re
from dataclasses import dataclass, field


# Blunt, low-ambiguity "unrestricted alter-ego" framing — near-zero
# legitimate use in a K-8 Socratic-tutor conversation (contrast with
# jailbreak-FLAVORED creative writing, e.g. "pretend you're a dragon with
# no rules *in the story*", which this deliberately does NOT match).
_JAILBREAK_PATTERN = re.compile(
    r'(\bdan\s+mode\b'
    r'|\bjailbreak(ing)?\b'
    r'|\bdeveloper\s+mode\b'
    r'|\bunrestricted\s+mode\b'
    r'|\bdo\s+anything\s+now\b'
    r'|\byou\s+have\s+no\s+(rules|restrictions|filters|guidelines)\b'
    r'|\bact\s+as\s+(if\s+you\s+(had|have)\s+)?no\s+(rules|restrictions)\b'
    r'|\bpretend\s+(you\s+are\s+)?an?\s+ai\s+(with\s+)?no\s+(rules|restrictions|guidelines)\b)',
    re.IGNORECASE,
)

# Claimed false authority ("I am the parent/admin") or an explicit demand
# to bypass/unlock the tutor's own rules on that authority. A child
# reporting something a real parent said ("my mom said I can stop early")
# doesn't match this — there's no bypass/override/admin-mode language.
_POLICY_OVERRIDE_PATTERN = re.compile(
    r'(\bi\s*(\'|’)?m\s+(the\s+|your\s+)?(parent|admin|administrator|the\s+developer)\b'
    r'|\bi\s+am\s+(the\s+|your\s+)?(parent|admin|administrator|the\s+developer)\b'
    r'|\b(enable|activate|turn\s+on)\s+(admin|developer|debug)\s+mode\b'
    r'|\b(unlock|bypass|override|disable)\s+(the\s+|your\s+)?(rules?|restrictions?|safety|filters?|parental\s+controls?)\b'
    r'|\bgive\s+me\s+(admin|parent|full)\s+access\b)',
    re.IGNORECASE,
)

# Asking Bede to disclose its own prompt/instructions, repeat prior
# context verbatim, or reveal information about other students, servers,
# or credentials — Bede has no legitimate reason to do any of these for a
# student. Narration ("tell me back what you remember") is the child
# repeating THEIR OWN understanding, not Bede repeating ITS OWN
# instructions, so it doesn't match this pattern.
_EXFILTRATION_PATTERN = re.compile(
    r'(\bsystem\s+prompt\b'
    r'|\brepeat\s+(everything|the\s+text|what\s+was\s+said)\s+above\b'
    r'|\bprint\s+(your\s+)?(instructions|system\s+prompt|everything\s+above)\b'
    r'|\bwhat\s+(is|are)\s+your\s+(instructions|system\s+prompt|api\s+key|secret)\b'
    r'|\bshow\s+me\s+(the\s+)?(database|other\s+students?|api\s+key)\b'
    r'|\blist\s+all\s+(students?|users?|passwords?)\b)',
    re.IGNORECASE,
)


_TIER1_DETECTORS = (
    ("jailbreak_intent", _JAILBREAK_PATTERN),
    ("policy_override_attempt", _POLICY_OVERRIDE_PATTERN),
    ("data_exfiltration_attempt", _EXFILTRATION_PATTERN),
)


@dataclass
class AdversarialSignals:
    """Everything Adversarial Detection found for one turn, handed to
    services/policy_engine.py's decide() — detection stays fact-only
    (what matched), policy decides what it means."""
    tier1_categories: set = field(default_factory=set)
    # The classifier's full category list for this turn (services/
    # moderation.py's classify_child_message result) — reused as-is, not
    # re-fetched, since routers/tutor.py already makes that one call per
    # turn for the original five categories.
    classifier_categories: list = field(default_factory=list)
    classifier_confidence: str = "low"


# New-category names this module/policy_engine.py act on — kept separate
# from moderation.py's own five (self_harm, violence, sexual_content,
# hate_or_harassment, prompt_injection), which are handled entirely by
# the existing, unchanged pipe in routers/tutor.py.
NEW_CLASSIFIER_CATEGORIES = frozenset({
    "jailbreak_intent", "policy_override_attempt", "data_exfiltration_attempt", "social_engineering",
})


def detect_tier1(message: str) -> set:
    """Free, instant, deterministic pre-classifier pass. Returns the set
    of new-category names any pattern matched — empty when nothing did
    (the overwhelmingly common case)."""
    if not message:
        return set()
    return {category for category, pattern in _TIER1_DETECTORS if pattern.search(message)}


def build_signals(message: str, moderation_result: dict) -> AdversarialSignals:
    """Combines this turn's Tier 1 regex pass with the classifier result
    routers/tutor.py already computed (services/moderation.py's
    classify_child_message) — no second classifier call. moderation_result
    is trusted to already be fail-open-safe (empty categories on any
    classifier failure), so this never needs its own try/except."""
    return AdversarialSignals(
        tier1_categories=detect_tier1(message),
        classifier_categories=list(moderation_result.get("categories") or []),
        classifier_confidence=moderation_result.get("confidence", "low"),
    )
