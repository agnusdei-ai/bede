"""The Spanish local-model probe reports honestly.

homeschool-api/scripts/spanish_local_model_probe.py is run by hand against
real models (docs/DECISIONS.md entry 43). These tests check the probe
itself, against a stand-in OpenAI-compatible server, so that it can never
report a pass it did not observe: a model that is not installed is NOT_RUN,
an English or mixed reply FAILS, and a tool call counts only when it names
the requested tool with every required field filled.
"""
from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from scripts import spanish_local_model_probe as probe

SCHEMAS = {
    "offer_socratic_hint": {
        "name": "offer_socratic_hint",
        "input_schema": {"type": "object", "required": ["hint_question"],
                         "properties": {"hint_question": {"type": "string"}}},
    },
}


def test_a_spanish_reply_passes_pending_human_review():
    verdict = probe.judge("¿Qué crees que pasa si sumas el siete ocho veces?", [], None, SCHEMAS)
    assert verdict["status"] == "PASS_NEEDS_HUMAN_REVIEW"
    assert verdict["stays_in_spanish"] and verdict["no_english_mixed"]


def test_english_mixed_into_spanish_fails():
    verdict = probe.judge("¡Muy bien! Let's think about what the siete means.", [], None, SCHEMAS)
    assert verdict["status"] == "FAIL"
    assert not verdict["no_english_mixed"]
    assert "the" in verdict["english_words_found"]


def test_an_english_reply_fails():
    verdict = probe.judge("What do you think happens when you add seven eight times?", [], None, SCHEMAS)
    assert verdict["status"] == "FAIL" and not verdict["stays_in_spanish"]


def test_an_empty_reply_fails():
    assert probe.judge("", [], None, SCHEMAS)["status"] == "FAIL"


@pytest.mark.parametrize("calls,ok", [
    ([{"name": "offer_socratic_hint", "input": {"hint_question": "¿Cuántos grupos de cuatro hay en el treinta y seis?"}}], True),
    ([{"name": "offer_socratic_hint", "input": {"hint_question": "  "}}], False),
    ([{"name": "offer_socratic_hint", "input": {}}], False),
    ([{"name": "made_up_tool", "input": {"hint_question": "¿Qué es la mitad?"}}], False),
    ([], False),
])
def test_a_tool_call_counts_only_when_it_is_the_requested_tool_and_complete(calls, ok):
    verdict = probe.judge("", calls, "offer_socratic_hint", SCHEMAS)
    assert verdict["valid_tool_call"] is ok
    assert (verdict["status"] == "PASS_NEEDS_HUMAN_REVIEW") is ok


def test_the_probe_refuses_a_non_loopback_endpoint_and_paid_keys(monkeypatch):
    with pytest.raises(SystemExit):
        probe._require_loopback("http://gpu-box.lan:11434/v1")
    with pytest.raises(SystemExit):
        probe._require_loopback("https://127.0.0.1:11434/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-sample")
    with pytest.raises(SystemExit):
        probe._require_loopback("http://127.0.0.1:11434/v1")


def _stand_in(installed, reply_text, tool_args):
    """An OpenAI-compatible server: lists `installed`, answers every chat
    request with `reply_text`, or a tool call when one is forced."""
    seen: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def _send(self, body):
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._send({"object": "list", "data": [{"id": m, "object": "model"} for m in installed]})

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(request)
            message = {"role": "assistant", "content": reply_text}
            if isinstance(request.get("tool_choice"), dict):
                name = request["tool_choice"]["function"]["name"]
                message = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(tool_args)}}]}
            self._send({"id": "x", "object": "chat.completion", "created": 0,
                        "model": request["model"],
                        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


def _run(monkeypatch, tmp_path, installed, reply, tool_args, models):
    for key in probe.PAID_KEYS:
        monkeypatch.delenv(key, raising=False)
    # run() points the adapter settings at the probe endpoint; register the
    # variables here so they are restored after the test.
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "")
    monkeypatch.setenv("BEDE_FORCE_ADAPTER", "")
    server, seen = _stand_in(installed, reply, tool_args)
    out = tmp_path / "report.json"
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/v1"
        code = asyncio.run(probe.run(url, models, out))
    finally:
        server.shutdown()
    return code, json.loads(out.read_text()), seen


def test_a_model_that_is_not_installed_is_not_run_never_passed(monkeypatch, tmp_path):
    code, report, seen = _run(monkeypatch, tmp_path, [], "Hola", {}, ["granite3.3:2b"])
    assert code == 1
    assert report["models"][0]["status"] == "NOT_RUN"
    assert seen == []


def test_the_real_prompt_and_tools_go_through_the_adapter_and_spanish_passes(monkeypatch, tmp_path):
    code, report, seen = _run(
        monkeypatch, tmp_path, ["granite3.3:2b"],
        "¿Qué crees que pasa si cuentas de ocho en ocho?",
        {"hint_question": "¿Cuántos grupos de cuatro caben en el treinta y seis?"},
        ["granite3.3:2b"],
    )
    model = report["models"][0]
    assert model["status"] == "PASS_NEEDS_HUMAN_REVIEW", model
    assert code == 0
    assert len(seen) == len(probe.CASES)
    # The real tool list and a forced tool call reached the server.
    names = {t["function"]["name"] for t in seen[0]["tools"]}
    assert "offer_socratic_hint" in names and "record_skill_evidence" in names
    forced = [r for r in seen if isinstance(r.get("tool_choice"), dict)]
    assert forced and forced[0]["tool_choice"]["function"]["name"] == "offer_socratic_hint"
    # The real Spanish-session system prompt, constitution included.
    system = seen[0]["messages"][0]
    assert system["role"] == "system" and len(system["content"]) > 5000


def test_an_english_answering_model_fails(monkeypatch, tmp_path):
    code, report, _ = _run(
        monkeypatch, tmp_path, ["granite3.3:2b"],
        "Great thinking! What do you think the answer is?",
        {"hint_question": "What is half of eight?"},
        ["granite3.3:2b"],
    )
    assert code == 1
    assert report["models"][0]["status"] == "FAIL"
