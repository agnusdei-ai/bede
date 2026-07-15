"""
Regression tests for core/constitution.py — Bede's tamper-evident,
digest-pinned foundational layer (see BEDE_CONSTITUTION.md /
docs/CONSTITUTION.md for the design, constitution/bede.constitution.json
for the canonical file).

Covers: the real file verifies clean; a one-word tamper fails closed
(digest mismatch); missing/malformed files fail closed; structural
validation catches a substantively-altered-but-still-valid-JSON file
independent of the digest check; the exposed data is genuinely read-only;
and all four prompt-building call sites in services/ai_service.py actually
include the constitution, not just claim to.
"""
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from core.constitution import (
    CONSTITUTION,
    ConstitutionIntegrityError,
    _PINNED_SHA256,
    _load_and_verify,
    _validate_structure,
    get_constitution,
)


# ── The real, shipped file ────────────────────────────────────────────────────

def test_real_constitution_verifies_and_matches_pinned_digest():
    c = get_constitution()
    assert c["constitution_id"] == "agnus-dei.bede.v1"
    assert [v["name"] for v in c["theological_virtues"]] == ["Faith", "Hope", "Love"]
    assert len(c["gifts_of_the_holy_spirit"]) == 7
    assert c["gifts_of_the_holy_spirit"][-1]["name"] == "Fear of the Lord"
    assert len(c["human_formation"]) == 3
    assert len(c["infinite_loop"]) == 10


def test_constitution_is_recursively_read_only():
    c = CONSTITUTION
    with pytest.raises(TypeError):
        c["title"] = "hacked"
    with pytest.raises(TypeError):
        c["theological_virtues"][0]["name"] = "hacked"
    # Lists are frozen to tuples, so item assignment isn't even the right
    # failure mode to check — confirm the type itself changed instead.
    assert isinstance(c["theological_virtues"], tuple)
    assert isinstance(c["non_negotiable_rules"], tuple)


# ── Tamper detection (fails closed) ───────────────────────────────────────────

def test_one_word_tamper_fails_closed(tmp_path):
    real = json.loads(_load_real_json_text())
    real["theological_virtues"][2]["name"] = "Lovee"  # one word changed
    tampered_path = tmp_path / "tampered.json"
    tampered_path.write_text(json.dumps(real), encoding="utf-8")

    with pytest.raises(ConstitutionIntegrityError, match="digest mismatch"):
        _load_and_verify(path=tampered_path, expected_digest=_PINNED_SHA256)


def test_missing_file_fails_closed(tmp_path):
    with pytest.raises(ConstitutionIntegrityError, match="not found"):
        _load_and_verify(path=tmp_path / "does-not-exist.json", expected_digest=_PINNED_SHA256)


def test_malformed_json_fails_closed(tmp_path):
    import hashlib

    bad = tmp_path / "bad.json"
    bad.write_bytes(b"{not valid json")
    digest = hashlib.sha256(bad.read_bytes()).hexdigest()

    with pytest.raises(ConstitutionIntegrityError, match="not valid JSON"):
        _load_and_verify(path=bad, expected_digest=digest)


def _load_real_json_text() -> str:
    from core.constitution import _CONSTITUTION_PATH
    return _CONSTITUTION_PATH.read_text(encoding="utf-8")


# ── Structural validation (independent of the digest check) ──────────────────

def _valid_data() -> dict:
    return deepcopy(json.loads(_load_real_json_text()))


def test_structural_validation_accepts_the_real_data():
    _validate_structure(_valid_data())  # must not raise


def test_missing_gift_is_rejected():
    data = _valid_data()
    data["gifts_of_the_holy_spirit"].pop()  # drop "Fear of the Lord"
    with pytest.raises(ConstitutionIntegrityError, match="gifts_of_the_holy_spirit"):
        _validate_structure(data)


def test_wrong_virtue_count_is_rejected():
    data = _valid_data()
    data["theological_virtues"].append({"name": "Extra", "function": "not real"})
    with pytest.raises(ConstitutionIntegrityError, match="theological_virtues"):
        _validate_structure(data)


def test_missing_escalation_rule_is_rejected():
    # Replaced (not removed) so the rule COUNT stays >= 10 and this test
    # exercises the escalation-content check specifically, not the
    # separate "missing entries" count check above it.
    data = _valid_data()
    data["non_negotiable_rules"] = [
        ("Some harmless unrelated rule." if "escalate" in r.lower() else r)
        for r in data["non_negotiable_rules"]
    ]
    with pytest.raises(ConstitutionIntegrityError, match="escalation"):
        _validate_structure(data)


def test_missing_anti_override_rule_is_rejected():
    data = _valid_data()
    data["non_negotiable_rules"] = [
        ("Some harmless unrelated rule." if "override this constitution" in r else r)
        for r in data["non_negotiable_rules"]
    ]
    with pytest.raises(ConstitutionIntegrityError, match="anti-override"):
        _validate_structure(data)


def test_out_of_order_loop_is_rejected():
    data = _valid_data()
    data["infinite_loop"][0]["order"] = 99
    with pytest.raises(ConstitutionIntegrityError, match="infinite_loop"):
        _validate_structure(data)


# ── Wired into all four prompt-building call sites (services/ai_service.py) ──

from models.schemas import ChatMessage, GradeStage, SessionConfig, SessionSummaryRequest, Subject  # noqa: E402
from services import ai_service  # noqa: E402


def _config() -> SessionConfig:
    return SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery)


def test_tutor_persona_prompt_includes_constitution_before_persona():
    prompt = ai_service._build_static_prompt(_config())
    assert "<constitution>" in prompt
    assert "Fear of the Lord" in prompt
    assert prompt.index("<constitution>") < prompt.index("<persona>")


def test_sandbox_prompt_includes_constitution():
    assert "<constitution>" in ai_service._build_sandbox_prompt("")
    assert "<constitution>" in ai_service._build_sandbox_prompt("custom test instructions")


@pytest.mark.asyncio
async def test_session_summary_system_prompt_includes_constitution():
    fake_response = SimpleNamespace(
        content=[SimpleNamespace(text="A lovely summary.")],
        usage=SimpleNamespace(input_tokens=10, output_tokens=10),
    )
    mock_create = AsyncMock(return_value=fake_response)
    req = SessionSummaryRequest(
        session_config=_config(),
        conversation_history=[ChatMessage(role="user", content="hi")],
        subjects_completed=[Subject.mathematics],
        duration_minutes=10,
    )
    with patch.object(ai_service._client.messages, "create", mock_create):
        await ai_service.generate_session_summary(req)

    assert "<constitution>" in mock_create.await_args.kwargs["system"]


@pytest.mark.asyncio
async def test_learner_profile_synthesis_system_prompt_includes_constitution():
    fake_response = SimpleNamespace(
        content=[SimpleNamespace(text='{"trivium_stage": "grammar", "processing_style": "visual", '
                                       '"narration_mode": "sequential", "attention_profile": "sustained", '
                                       '"bede_profile_notes": "Notes."}')],
        usage=SimpleNamespace(input_tokens=10, output_tokens=10),
    )
    mock_create = AsyncMock(return_value=fake_response)
    with patch.object(ai_service._client.messages, "create", mock_create):
        await ai_service.synthesize_learner_profile("Emma", [{"total_score": 20}], session_count=1)

    assert "<constitution>" in mock_create.await_args.kwargs["system"]
