"""
The demo's own Parent Setup.

The demo used to run a fixed showcase — every subject, no plan — while the
product had a whole ParentSetup page, so the one surface a prospective
family judges Bede by demonstrated the chat and hid the work. These guards
cover the two things that make closing that gap safe rather than merely
possible:

  1. **The demo cannot accept a configuration the product would refuse.**
     The endpoint validates by building a real ``SessionConfig``, so there
     is no second, looser copy of those rules — the failure this repository
     has already shipped twice (``bede_tools.py``'s ``password`` field, the
     e2e stub that accepted any JSON body).
  2. **Anonymous public free text is sanitized on the way in**, not only at
     prompt-build time, exactly as ``current_unit`` and ``faith_tradition``
     already are at ``POST /auth/demo-code``.

Plus the ordinary two-copies-of-one-fact parity: the demo's own TypeScript
mirrors of the option lists must equal the Python ones a parent's UI is
built from, or the demo offers choices the product does not have.
"""
import re
from pathlib import Path

import pytest

from models.schemas import (
    BIBLE_TRANSLATIONS,
    CHARACTER_VIRTUE_SUGGESTIONS,
    CURRICULUM_RESOURCE_SUGGESTIONS,
    DemoParentConfigRequest,
    GradeStage,
    LEARNING_SUPPORT_SUGGESTIONS,
    PUBLIC_DOMAIN_BIBLE_TRANSLATIONS,
    SessionConfig,
    Subject,
)

# One quoted entry: single-quoted, or double-quoted because it contains an
# apostrophe. Built with concatenation rather than a triple-quoted raw
# string, where the closing quote of the second alternative gets eaten by
# the delimiter — which is how this parser first shipped, silently
# matching an unterminated run and blaming the data for it.
_ENTRY = r"'([^']*)'" + r'|"([^"]*)"'

_DEMO_API = Path(__file__).resolve().parents[2] / "demo" / "src" / "api.ts"
_DEMO_PANEL = Path(__file__).resolve().parents[2] / "demo" / "src" / "DemoParentSetup.tsx"


# ── The wire model declares no rules of its own ─────────────────────────


def test_the_request_model_carries_no_validators_of_its_own():
    """The whole safety property. If this model grew a validator, the demo
    would have a second, independent set of rules that could drift from the
    product's — and the drift would be invisible, because both sides would
    keep accepting input."""
    validators = [
        name for name in vars(DemoParentConfigRequest)
        if name.startswith("_validate") or name.endswith("_validator")
    ]
    assert not validators, (
        f"DemoParentConfigRequest has grown its own validators ({validators}). "
        "Validation belongs to SessionConfig, which the endpoint builds — see "
        "routers/auth.py's set_demo_parent_config."
    )


def test_every_field_it_offers_is_a_real_session_config_field():
    """A field here that SessionConfig does not have would be stored,
    never read, and silently do nothing."""
    unknown = set(DemoParentConfigRequest.model_fields) - set(SessionConfig.model_fields)
    assert not unknown, (
        f"DemoParentConfigRequest offers {sorted(unknown)}, which SessionConfig "
        "does not have. A setting the demo collects and the prompt never sees "
        "is worse than one it does not collect."
    )


# ── The product's own validators are what decide ────────────────────────


def _config(**over):
    base = dict(student_name="Guest", grade="4", grade_stage=GradeStage.core_mastery)
    base.update(over)
    return SessionConfig(**base)


def test_the_product_rules_the_demo_inherits_actually_bite():
    """Sanity: these are the rules a demo visitor's setup is held to, so a
    change that quietly stopped applying them should fail here rather than
    reach the demo. Each is checked through SessionConfig, which is what the
    endpoint builds."""
    # Lists are capped and de-duplicated rather than rejected.
    many = _config(curriculum_resources=[f"Publisher {i}" for i in range(20)])
    assert len(many.curriculum_resources) <= 6

    virtues = _config(character_virtues=[f"Virtue {i}" for i in range(30)])
    assert len(virtues.character_virtues) <= 12

    support = _config(learning_support=[f"Helps {i}" for i in range(30)])
    assert len(support.learning_support) <= 10


def test_logic_is_dropped_for_a_k2_visitor_exactly_as_it_is_for_a_family():
    """The stage gate is the sharpest rule the demo inherits: a K-2 visitor
    choosing Logic must get the same silent drop a K-2 student's own config
    gets, not a demo that teaches formal reasoning to a five-year-old
    because nobody wired the gate up."""
    younger = SessionConfig(
        student_name="Guest",
        grade="1",
        grade_stage=GradeStage.foundations,
        subjects=[Subject.morning_time, Subject.logic],
    )
    assert Subject.logic not in younger.subjects

    older = _config(subjects=[Subject.morning_time, Subject.logic])
    assert Subject.logic in older.subjects


# ── The demo's TypeScript mirrors ───────────────────────────────────────


def _ts_list(name: str, source: Path) -> list[str]:
    text = source.read_text()
    match = re.search(rf"export const {name} = \[(.*?)\n\] as const", text, re.S)
    assert match, (
        f"Could not find {name} in {source.name}. If it was renamed or moved, "
        "update this test rather than deleting it."
    )
    # Alternation rather than one character class: an entry like
    # "Say what's coming next" is double-quoted precisely BECAUSE it holds an
    # apostrophe, and a class of ['"] ends the match on it. That produced a
    # confident-looking diff blaming the data for a defect in this parser.
    items = [
        single if single else double
        for single, double in re.findall(_ENTRY, match.group(1))
    ]
    assert items, f"Parsed no entries out of {name} — a vacuous pass."
    return items


@pytest.mark.parametrize(
    "ts_name, python_list",
    [
        ("BIBLE_TRANSLATIONS", list(BIBLE_TRANSLATIONS)),
        ("CURRICULUM_RESOURCE_SUGGESTIONS", list(CURRICULUM_RESOURCE_SUGGESTIONS)),
        ("CHARACTER_VIRTUE_SUGGESTIONS", list(CHARACTER_VIRTUE_SUGGESTIONS)),
        ("LEARNING_SUPPORT_SUGGESTIONS", list(LEARNING_SUPPORT_SUGGESTIONS)),
    ],
)
def test_the_demos_option_lists_match_the_products(ts_name, python_list):
    """Two copies of one fact. The demo's panel is built from its own
    TypeScript copy; if that drifts, the demo offers a family options the
    product does not have — the exact way a demo stops demonstrating the
    product."""
    assert _ts_list(ts_name, _DEMO_API) == python_list, (
        f"demo/src/api.ts's {ts_name} and models/schemas.py's have drifted."
    )


def test_the_public_domain_split_is_mirrored_too():
    """Which translations Bede may quote verbatim is a licensing and
    accuracy claim, not a styling choice — see _bible_translation_note."""
    mirrored = set(_ts_list("PUBLIC_DOMAIN_BIBLE_TRANSLATIONS", _DEMO_API))
    assert mirrored == set(PUBLIC_DOMAIN_BIBLE_TRANSLATIONS)


def test_the_panel_offers_no_setting_that_belongs_to_a_deployment():
    """A demo visitor has no deployment, so the panel must not appear to
    offer one. Licensing, the AI provider, security keys, the audit log and
    permanent deletion are a real family's, and showing them here would
    demonstrate a control that cannot work."""
    panel = _DEMO_PANEL.read_text().lower()
    # Only the rendered markup — the docstring names these deliberately, to
    # say why each is absent.
    body = panel.split("*/", 1)[1] if "*/" in panel else panel
    for forbidden in (
        "license", "ai provider", "security key", "totp", "audit",
        "delete all", "recovery code",
    ):
        assert forbidden not in body, (
            f"DemoParentSetup renders {forbidden!r}, which belongs to a "
            "deployment a demo visitor does not have."
        )


def test_the_panel_never_names_a_condition():
    """Same rule the product's own reading panel holds itself to: settings
    say what they do, never what a reader has. See decision register entry
    24."""
    panel = _DEMO_PANEL.read_text().lower()
    body = panel.split("*/", 1)[1] if "*/" in panel else panel
    for word in ("dyslex", "adhd", "diagnos", "disorder", "disabilit"):
        assert word not in body, f"DemoParentSetup names a condition: {word!r}"


# ── The guard has to be reachable for the change it guards ──────────────


@pytest.mark.parametrize("path", [
    "demo/src/api\\.ts",
    "demo/src/DemoParentSetup\\.tsx",
])
def test_the_files_this_guard_reads_are_in_the_ci_change_filter(path):
    """This suite reads two files outside homeschool-api/. Until they are
    named in .github/workflows/test.yml's filter, a demo-only edit computes
    relevant=false, skips api-tests entirely, and this guard never runs for
    exactly the change it exists to catch — the failure
    test_decision_register.py documents.

    Reads the grep pattern line itself rather than the whole workflow: the
    first version of the equivalent guard passed on a comment beside the
    filter, which is a vacuous pass."""
    workflow = (Path(__file__).resolve().parents[2]
                / ".github" / "workflows" / "test.yml").read_text()
    pattern_lines = [ln for ln in workflow.splitlines() if "grep -qE" in ln]
    assert pattern_lines, "Could not find the change filter's grep line in test.yml."
    assert any(path in ln for ln in pattern_lines), (
        f"{path} is not in test.yml's change filter, so a demo-only edit "
        "would skip the suite that reads it."
    )
