"""
Bede's Constitution — the immutable, tamper-evident foundational layer
governing Bede's persona, ethics, and limits (Faith/Hope/Love, the seven
gifts of the Holy Spirit, the three dimensions of human formation, the
moral law — the Ten Commandments and Christ's two great commandments,
scoped to Bede's OWN conduct rather than content it teaches or a basis to
judge a child's or family's beliefs — and the non-negotiable rules).
faith_content_scope is a technical-representation clarification of the
7th non-negotiable rule (added under amendment_policy.technical_
representation, not a substance change — see the field's own "clarifies"
key): it names WHEN explicit faith content belongs in a lesson (Morning
Time, Scripture & Bible Study, Saints & Catechism, a sincere question, or
real context), not whether it may exist. See docs/CONSTITUTION.md for the
human-readable version and constitution/bede.constitution.json for the
canonical, digest-pinned source this module verifies.

Verified once, at import time — the same fail-fast convention core/config.py
already uses for settings = Settings(). Any module that imports this one is
guaranteed the constitution file is present, byte-identical to what was
reviewed and pinned, and structurally intact — or the import itself raises
ConstitutionIntegrityError. main.py imports this module and re-checks it
explicitly as the first statement of its startup lifespan, before database
initialization, so a missing or tampered constitution prevents Bede from
ever coming up.

Threat model, honestly: this is tamper-evident, not tamper-proof. Someone
who can rewrite both this file's _PINNED_SHA256 and the constitution file
together can still produce a different build that verifies against itself.
Repository review, protected branches, founder approval, and signed
releases are the actual trust boundary (see the constitution's own
amendment_policy.required_change_control) — this module only guarantees
that a RUNNING build's constitution matches what was reviewed and pinned
in that build's own source.
"""
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

_CONSTITUTION_PATH = Path(__file__).resolve().parent.parent / "constitution" / "bede.constitution.json"

# Recomputed and re-pinned ONLY as part of the change-control process in
# amendment_policy.required_change_control (constitution file itself) —
# never hand-edited just to make verification pass. Any change here must
# ship in the same reviewed commit as the (permitted) file change that
# produced it, per docs/CONSTITUTION.md's "Change control" section.
_PINNED_SHA256 = "268017aa24b976ea3f6a5da3aeb622626ffff856407730e90e2c8277ab03dba9"

_REQUIRED_VIRTUE_NAMES = ("Faith", "Hope", "Love")
_REQUIRED_GIFT_NAMES = (
    "Wisdom", "Understanding", "Counsel", "Fortitude", "Knowledge", "Piety", "Fear of the Lord",
)
_REQUIRED_FORMATION_NAMES = ("Comprehension", "Compassion", "Conscience")
_REQUIRED_LOOP_STEPS = 10
_REQUIRED_COMMANDMENT_COUNT = 10
_REQUIRED_GREAT_COMMANDMENT_COUNT = 2
# The three faith subjects that exist today — Subject.morning_time,
# Subject.scripture, Subject.saints in models/schemas.py, using their exact
# SUBJECT_LABELS strings. _validate_structure checks each name is present
# somewhere in faith_content_scope.applies_when (a list of condition
# sentences, not a list of bare subject names), so a future edit that drops
# or renames one of the three — rather than genuinely adding a fourth faith
# subject — fails this check instead of silently narrowing scope.
_REQUIRED_FAITH_CONTENT_SUBJECTS = ("Morning Time", "Scripture & Bible Study", "Saints & Catechism")


class ConstitutionIntegrityError(RuntimeError):
    """
    Raised when the constitution file is missing, malformed, structurally
    incomplete, or does not match the digest pinned above. A subclass of
    RuntimeError so it's caught by main.py's existing fatal-startup-error
    handling (the same one initialize_encryption already raises into) —
    Bede must never start in this state.
    """


def _freeze(obj: Any) -> Any:
    """
    Recursively converts dicts to MappingProxyType and lists to tuples, so
    the parsed constitution can never be mutated in place by any caller —
    "recursively read-only data" per the design. Scalars pass through
    unchanged.
    """
    if isinstance(obj, dict):
        return MappingProxyType({k: _freeze(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return tuple(_freeze(v) for v in obj)
    return obj


def _validate_structure(data: dict) -> None:
    """
    An independent check on top of the digest comparison — this guards the
    change-control process itself, not just runtime tampering. If someone
    ever updates both the constitution file AND _PINNED_SHA256 together
    (the one path digest comparison alone can't catch), this is what a
    reviewer or CI run relies on to confirm the foundational substance
    itself — not just the wording — is still intact.
    """
    if data.get("constitution_id") != "agnus-dei.bede.v1":
        raise ConstitutionIntegrityError("constitution_id does not match the expected constitution")

    virtue_names = tuple(v.get("name") for v in data.get("theological_virtues", []))
    if virtue_names != _REQUIRED_VIRTUE_NAMES:
        raise ConstitutionIntegrityError(
            f"theological_virtues must be exactly {_REQUIRED_VIRTUE_NAMES}, got {virtue_names}"
        )

    gift_names = tuple(g.get("name") for g in data.get("gifts_of_the_holy_spirit", []))
    if gift_names != _REQUIRED_GIFT_NAMES:
        raise ConstitutionIntegrityError(
            f"gifts_of_the_holy_spirit must be exactly the seven canonical gifts in order, got {gift_names}"
        )

    formation_names = tuple(f.get("name") for f in data.get("human_formation", []))
    if formation_names != _REQUIRED_FORMATION_NAMES:
        raise ConstitutionIntegrityError(
            f"human_formation must be exactly {_REQUIRED_FORMATION_NAMES}, got {formation_names}"
        )

    loop = data.get("infinite_loop", [])
    if len(loop) != _REQUIRED_LOOP_STEPS or [step.get("order") for step in loop] != list(
        range(1, _REQUIRED_LOOP_STEPS + 1)
    ):
        raise ConstitutionIntegrityError(
            f"infinite_loop must be exactly {_REQUIRED_LOOP_STEPS} steps, consecutively ordered from 1"
        )

    rules = data.get("non_negotiable_rules", [])
    if len(rules) < 10:
        raise ConstitutionIntegrityError("non_negotiable_rules is missing entries")
    joined_rules = " ".join(rules)
    if "escalate" not in joined_rules.lower():
        raise ConstitutionIntegrityError("non_negotiable_rules is missing the safeguarding escalation rule")
    if "override this constitution" not in joined_rules:
        raise ConstitutionIntegrityError("non_negotiable_rules is missing the anti-override rule")

    if "required_change_control" not in data.get("amendment_policy", {}):
        raise ConstitutionIntegrityError("amendment_policy.required_change_control is missing")

    moral_law = data.get("moral_law", {})
    commandments = moral_law.get("commandments", [])
    if len(commandments) != _REQUIRED_COMMANDMENT_COUNT:
        raise ConstitutionIntegrityError(
            f"moral_law.commandments must be exactly {_REQUIRED_COMMANDMENT_COUNT} entries, got {len(commandments)}"
        )
    great_commandments = moral_law.get("great_commandments", [])
    if len(great_commandments) != _REQUIRED_GREAT_COMMANDMENT_COUNT:
        raise ConstitutionIntegrityError(
            f"moral_law.great_commandments must be exactly {_REQUIRED_GREAT_COMMANDMENT_COUNT} entries, "
            f"got {len(great_commandments)}"
        )
    if "spiritual advisor" not in moral_law.get("function", "") and "priest" not in moral_law.get("function", ""):
        raise ConstitutionIntegrityError(
            "moral_law.function is missing the limit that Bede is not a spiritual advisor/priest substitute"
        )

    faith_scope = data.get("faith_content_scope", {})
    applies_when = faith_scope.get("applies_when", [])
    joined_conditions = " ".join(applies_when)
    missing_subjects = [s for s in _REQUIRED_FAITH_CONTENT_SUBJECTS if s not in joined_conditions]
    if len(applies_when) < 4 or missing_subjects:
        raise ConstitutionIntegrityError(
            "faith_content_scope.applies_when must name all three faith subjects "
            f"{_REQUIRED_FAITH_CONTENT_SUBJECTS}, missing {missing_subjects}"
        )
    if "does not seek assent" not in faith_scope.get("posture", ""):
        raise ConstitutionIntegrityError(
            "faith_content_scope.posture is missing the 'does not seek assent' non-proselytizing limit"
        )


def _load_and_verify(path: Path = _CONSTITUTION_PATH, expected_digest: str = _PINNED_SHA256) -> Any:
    """Exposed with path/digest parameters (rather than hardcoded globals
    inline) purely so tests can point this at a deliberately-tampered copy
    without touching the real constitution file or this module's pinned
    digest."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConstitutionIntegrityError(f"Constitution file not found at {path}") from exc

    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_digest:
        raise ConstitutionIntegrityError(
            f"Constitution digest mismatch — expected {expected_digest}, got {digest}. "
            "The constitution file does not match what was reviewed and pinned in this build; "
            "see docs/CONSTITUTION.md's change-control process."
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConstitutionIntegrityError("Constitution file is not valid JSON") from exc

    _validate_structure(data)
    return _freeze(data)


CONSTITUTION = _load_and_verify()


def get_constitution() -> Any:
    """Returns the verified, recursively read-only constitution data."""
    return CONSTITUTION
