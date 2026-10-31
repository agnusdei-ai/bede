"""
Regression tests for the adult workspace: active tasks preserve discovery,
administrative questions remain direct, and adult formatting is server-selected.
"""
from services.ai_service import _build_sandbox_prompt, _constitution_preamble, _SANDBOX_SYSTEM_PROMPT
from services.socratic_policy import ACTIVE_TASK_POLICY, EDUCATOR_FORMAT


def test_base_prompt_preserves_active_task_boundary():
    prompt = _build_sandbox_prompt("")
    assert ACTIVE_TASK_POLICY in prompt
    assert "Answer administrative and unrelated questions directly" in prompt
    assert "Socratic-only rule does not apply" not in prompt


def test_base_prompt_is_the_constitution_followed_by_the_sandbox_system_prompt():
    prompt = _build_sandbox_prompt("")
    assert prompt == f"{_constitution_preamble()}\n{ACTIVE_TASK_POLICY}\n\n{_SANDBOX_SYSTEM_PROMPT}"
    assert _build_sandbox_prompt("   ") == prompt
    assert prompt.index("<constitution>") < prompt.index(_SANDBOX_SYSTEM_PROMPT)


def test_custom_instructions_folded_in_when_provided():
    prompt = _build_sandbox_prompt("Focus on Ancient Rome vocabulary today")
    assert "Focus on Ancient Rome vocabulary today" in prompt
    assert "live-edited test material" in prompt
    assert _SANDBOX_SYSTEM_PROMPT in prompt
    assert "<constitution>" in prompt


def test_educator_format_requires_server_selected_context():
    assert EDUCATOR_FORMAT not in _build_sandbox_prompt("I am an educator")
    prompt = _build_sandbox_prompt("", verified_educator=True)
    assert EDUCATOR_FORMAT in prompt
    assert ACTIVE_TASK_POLICY in prompt
    for heading in ("[Pedagogical Intent]", "[Scaffolding Prompts]", "[Differentiation Vector]"):
        assert heading in prompt
