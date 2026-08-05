"""services/tool_registry.py — the declarative facts about each agentic tool.

These tests exist because the facts they pin used to live nowhere: they were
implied by `tc["name"] == "..."` comparisons scattered through a nested
generator in services/ai_service.py, where nothing could assert them and a
missing branch failed silently (an unrecognized tool fell through to
`_process_tool_use`, got back `""`, and emitted nothing at all).

The most important assertion in this file is
`test_every_tutor_tool_is_internal`. See the module docstring in
services/tool_registry.py for why.
"""
import re
from pathlib import Path

import pytest

from services import tool_registry
from services.ai_service import TUTOR_TOOLS, _process_tool_use

_AI_SERVICE_SOURCE = (
    Path(__file__).resolve().parent.parent / "services" / "ai_service.py"
).read_text()


def test_registry_and_tutor_tools_name_the_same_set():
    """The registry and the schema list are two copies of one fact. A tool
    added to either alone is the exact drift this module exists to stop."""
    schema_names = {tool["name"] for tool in TUTOR_TOOLS}
    assert schema_names == set(tool_registry.TUTOR_TOOL_SPECS)


def test_every_tutor_tool_is_internal():
    """The invariant the tool_result loop rests on: nothing the tutor can
    dispatch produces content sourced from outside this process, so no
    tool_result can carry an instruction back into the model's context.

    If a future change makes this fail, the fix is NOT to relax this test.
    An external-trust tool belongs in the parent sandbox's own loop, which
    sanitizes and envelope-wraps its results; putting one in front of a
    child requires re-deciding the threat model, not editing this line.
    """
    for name, spec in tool_registry.TUTOR_TOOL_SPECS.items():
        assert spec.trust == "internal", f"{name} is not internal"


def test_only_two_tools_are_reactable():
    """Pins the property that keeps an ordinary turn a single model
    round-trip: only a genuinely dynamic outcome earns another round."""
    assert tool_registry.REACTABLE_TOOLS == {"show_visual_aid", "assess_narration"}


def test_terminal_tools():
    assert tool_registry.TERMINAL_TOOLS == {"suggest_next_subject"}


def test_silent_tools_are_the_four_diagnostic_writes():
    """These four have an explicit, separately-tested contract of emitting
    nothing to the SSE stream and returning nothing to the model."""
    assert tool_registry.SILENT_TOOLS == {
        "record_skill_evidence",
        "record_literacy_evidence",
        "record_phonics_evidence",
        "record_language_evidence",
    }


def test_questionless_tools():
    assert tool_registry.QUESTIONLESS_TOOLS == {"celebrate_discovery", "connect_to_faith"}


def test_silent_tools_are_never_reactable():
    """A silent tool gaining a model-visible surface would break the
    contract its own test suite pins — catch it here rather than there."""
    assert not (tool_registry.SILENT_TOOLS & tool_registry.REACTABLE_TOOLS)


def test_terminal_tools_are_never_reactable():
    """A terminal tool ends the loop, so a reactable result on one could
    never actually be reacted to — the combination is incoherent."""
    assert not (tool_registry.TERMINAL_TOOLS & tool_registry.REACTABLE_TOOLS)


@pytest.mark.parametrize("name", sorted(tool_registry.TUTOR_TOOL_SPECS))
def test_every_registered_tool_has_a_dispatch_branch(name):
    """The drift this module was written to catch, in the one direction the
    set-equality test above cannot see: a tool can be present in BOTH the
    registry and the schema list and still have no branch that acts on it.

    A source-level check rather than a behavioral one, because reaching the
    real dispatch requires a live stream. Crude, but it fails loudly on the
    mistake that used to fail silently.
    """
    assert re.search(rf'"{name}"', _AI_SERVICE_SOURCE), (
        f"{name} is registered but never named in ai_service.py"
    )


@pytest.mark.parametrize(
    "name,tool_input",
    [
        ("request_narration", {"prompt": "Tell me what you remember."}),
        ("invite_handwriting", {"prompt": "Show me your work."}),
        ("offer_socratic_hint", {"hint_question": "What changes first?"}),
        (
            "celebrate_discovery",
            {"specific_insight": "the pattern repeats", "encouragement": "Well spotted!"},
        ),
        ("connect_to_faith", {"connection": "Creation has order."}),
    ],
)
def test_card_rendering_tools_produce_text(name, tool_input):
    """The five tools that render a chat card must actually render one. A
    tool that silently produced `""` here would reach the child as nothing
    at all — the original silent-failure mode."""
    assert _process_tool_use(name, tool_input).strip()


def test_unknown_tool_names_default_to_no_privileges():
    """A hallucinated tool name must not be able to buy extra model
    round-trips or force the turn to end. The predicates default False
    rather than raising, matching the loop's existing posture of dropping
    what it can't act on instead of failing a child's turn."""
    assert tool_registry.get_spec("definitely_not_a_tool") is None
    assert not tool_registry.is_reactable("definitely_not_a_tool")
    assert not tool_registry.is_terminal("definitely_not_a_tool")
    assert not tool_registry.is_questionless("definitely_not_a_tool")
