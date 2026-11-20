"""The pilot's small-model probe: its endpoint rule and its pure checks.

The probe itself is run by hand against a model server. What a test can pin is
the rule that keeps it local or private (never a public host) and the tool-call
check, so neither can quietly loosen.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "slm_pilot_probe.py"
_spec = importlib.util.spec_from_file_location("slm_pilot_probe", _PATH)
probe = importlib.util.module_from_spec(_spec)
sys.modules["slm_pilot_probe"] = probe
_spec.loader.exec_module(probe)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:11434/v1", "http://localhost:8000/v1", "http://[::1]:8000/v1"])
def test_loopback_is_always_allowed(url):
    assert probe.endpoint_allowed(url, allow_private=False)[0]


@pytest.mark.parametrize("url", [
    "http://10.0.0.5:8000/v1", "http://192.168.1.20/v1", "http://172.16.4.9/v1",
    "http://models.school.lan/v1", "http://gpu.internal:8000/v1"])
def test_private_hosts_need_the_flag(url):
    assert not probe.endpoint_allowed(url, allow_private=False)[0]
    assert probe.endpoint_allowed(url, allow_private=True)[0]


@pytest.mark.parametrize("url", [
    "https://api.openai.com/v1", "http://8.8.8.8/v1", "http://example.com/v1",
    "ftp://10.0.0.5/v1", "http://",
    "http://models.school.lan.evil.com/v1"])
@pytest.mark.parametrize("allow_private", [False, True])
def test_public_hosts_are_always_refused(url, allow_private):
    assert not probe.endpoint_allowed(url, allow_private)[0]


def test_tool_call_check_needs_the_right_tool_and_every_required_field():
    schemas = {"offer_socratic_hint": {"input_schema": {"required": ["hint"]}}}
    ok = [{"name": "offer_socratic_hint", "input": {"hint": "Try groups of 4."}}]
    assert probe.valid_tool_call(ok, "offer_socratic_hint", schemas)
    assert not probe.valid_tool_call([{"name": "offer_socratic_hint", "input": {"hint": ""}}],
                                     "offer_socratic_hint", schemas)
    assert not probe.valid_tool_call([{"name": "other", "input": {"hint": "x"}}],
                                     "offer_socratic_hint", schemas)
    assert not probe.valid_tool_call([], "offer_socratic_hint", schemas)


def test_the_probe_renders_a_picture_when_pillow_is_present():
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        pytest.skip("Pillow is not usable here")
    data = probe.render_quiz_page()
    assert data and len(data) > 100
