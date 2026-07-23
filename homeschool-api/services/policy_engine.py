"""
Policy Engine — the second stage of Bede's adversarial-resilience pipeline:

    User Input -> Adversarial Detection -> Policy Engine -> Tutor State
    Machine -> Action Validator -> Parent/Student

Takes the AdversarialSignals services/adversarial_detection.py already
computed for this turn (Tier 1 regex hits + the Tier 2 classifier's new
categories, reusing the one classify_child_message call routers/tutor.py
already makes — no second call, no new latency) and turns them into exactly
ONE decision: let the turn reach the tutor, or redirect it to a canned
response instead. Detection stays fact-only; this module is the only place
that decides what a given fact means.

Tiering rationale (mirrors services/moderation.py's own documented
reasoning for why prompt_injection never blocks alone):

- policy_override_attempt / data_exfiltration_attempt -> REDIRECT.
  Both categories describe a concrete, actionable attempt to gain
  unauthorized authority or extract something the tutor was never meant to
  share — there's no legitimate K-8 Socratic-dialogue phrasing that looks
  like "I'm the admin, disable your rules" or "show me the database".
  Redirecting costs nothing real in lesson content. Triggered by EITHER a
  Tier 1 regex hit (instant, curated for near-zero false positives) OR the
  Tier 2 classifier flagging the category at medium+ confidence (broader,
  catches phrasing no regex enumerates).
- jailbreak_intent / social_engineering -> never block alone, audit only.
  Same reasoning moderation.py already gives for prompt_injection: ordinary
  imaginative roleplay/storytelling and ordinary kid impatience or
  real-life pressure can resemble these categories to a classifier without
  actually being an attack, and this app's architecture has no secret for
  a successful jailbreak to leak in the first place (see core/middleware.py's
  ExfiltrationGuard + services/ai_service.py's constitution preamble, which
  no amount of "pretend you have no rules" removes from context). A
  sustained pattern across many turns is what's actually worth a parent's
  attention — that's core/audit.py's anomaly-alert job, not this module's.

Every non-empty decision is meant to be audited (core/audit.py's new
AuditEvent.ADVERSARIAL_DETECTED) regardless of whether it blocked, exactly
like moderation.py's own MODERATION_FLAGGED is logged even when
should_block is False — visibility into boundary-testing matters even when
a given turn isn't itself redirected.
"""
from dataclasses import dataclass, field

from services.adversarial_detection import AdversarialSignals

# Categories that redirect the turn once triggered (Tier 1 hit, or Tier 2
# classifier at medium+ confidence) — see module docstring for why these
# two and not the other two.
_BLOCKING_CATEGORIES = frozenset({"policy_override_attempt", "data_exfiltration_attempt"})

# Categories that are always audit-only — never redirect a turn by
# themselves, no matter how the classifier scores them. Mirrors
# services/moderation.py's own treatment of prompt_injection.
_AUDIT_ONLY_CATEGORIES = frozenset({"jailbreak_intent", "social_engineering"})

_BLOCKING_CONFIDENCE = {"medium", "high"}


@dataclass
class PolicyDecision:
    """The one decision routers/tutor.py acts on for this turn."""
    should_redirect: bool = False
    # Every new-category name detected this turn (Tier 1 or Tier 2, blocking
    # or not) — the full audit detail, so a parent-visible log entry shows
    # what was actually seen even when nothing was blocked.
    detected_categories: set = field(default_factory=set)
    # The subset that actually caused should_redirect — empty when
    # should_redirect is False.
    blocking_categories: set = field(default_factory=set)


def decide(signals: AdversarialSignals) -> PolicyDecision:
    """Pure function: no I/O, no audit writes — routers/tutor.py owns
    logging the result, same separation classify_child_message/
    should_block already has from its own caller."""
    new_categories = _BLOCKING_CATEGORIES | _AUDIT_ONLY_CATEGORIES
    tier1 = set(signals.tier1_categories) & new_categories
    tier2 = set(signals.classifier_categories) & new_categories

    detected = tier1 | tier2
    if not detected:
        return PolicyDecision()

    # Tier 1 always counts (curated for near-zero false positives). Tier 2
    # only counts toward blocking at medium+ confidence — a low-confidence
    # classifier guess alone shouldn't redirect a real lesson.
    confident_tier2 = tier2 if signals.classifier_confidence in _BLOCKING_CONFIDENCE else set()
    blocking = (tier1 | confident_tier2) & _BLOCKING_CATEGORIES

    return PolicyDecision(
        should_redirect=bool(blocking),
        detected_categories=detected,
        blocking_categories=blocking,
    )
