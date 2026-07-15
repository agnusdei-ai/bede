"""
Regression tests for services/ai_service.py's sandbox prompt builder — the
parent-only, direct-answer mode used by routers/sandbox.py. The one thing
that must never regress: the Socratic-only rule is explicitly turned off
here (unlike the real tutor prompt), and a parent's custom instructions get
folded in only when actually provided. The sandbox relaxes the Socratic
rule but NOT the constitution (see core/constitution.py) — that must
still precede everything else, same as the real tutor prompt.
"""
from services.ai_service import _build_sandbox_prompt, _constitution_preamble, _SANDBOX_SYSTEM_PROMPT


def test_base_prompt_disables_socratic_only_rule():
    prompt = _build_sandbox_prompt("")
    assert "Socratic-only rule does not apply" in prompt
    assert "Answer directly" in prompt


def test_base_prompt_is_the_constitution_followed_by_the_sandbox_system_prompt():
    prompt = _build_sandbox_prompt("")
    assert prompt == f"{_constitution_preamble()}\n\n{_SANDBOX_SYSTEM_PROMPT}"
    assert _build_sandbox_prompt("   ") == prompt
    assert prompt.index("<constitution>") < prompt.index(_SANDBOX_SYSTEM_PROMPT)


def test_custom_instructions_folded_in_when_provided():
    prompt = _build_sandbox_prompt("Focus on Ancient Rome vocabulary today")
    assert "Focus on Ancient Rome vocabulary today" in prompt
    assert "live-edited test material" in prompt
    assert _SANDBOX_SYSTEM_PROMPT in prompt
    assert "<constitution>" in prompt
