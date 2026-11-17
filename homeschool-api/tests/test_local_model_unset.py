"""LOCAL_LLM_MODEL has no default name: an explicit name is used unchanged,
an unset one is the server's only model or a configuration error.

docs/DECISIONS.md entry 43 changed which model Bede recommends for vLLM.
Before this, LOCAL_LLM_MODEL defaulted to a model name, so a vLLM household
that pressed Enter at setup.sh's model prompt (no LOCAL_LLM_MODEL line in
.env) would have been switched to the new name by an ordinary update and
every lesson would have failed with a bare model-not-found. These tests
drive the REAL adapter against a stand-in OpenAI-compatible server and
record every request it receives, so "only lists, never downloads" is
observed rather than assumed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from core.audit import AuditEvent
from core.config import LOCAL_LLM_DEFAULT_MODEL, Settings
from services.adapters import openai_compatible_adapter as adapter
from services.adapters.openai_compatible_adapter import (
    LocalModelNotConfiguredError,
    LocalModelUnreachableError,
    OpenAICompatibleClient,
    backend_failure_detail,
)
from services.adapters.router import _build, resolve_local_only
from tests.test_locuto_ipc_boot import _settings_kwargs

ROOT = Path(__file__).resolve().parents[2]
QWEN_CODER = "Qwen/Qwen3-Coder-30B-A3B-Instruct"


@pytest.fixture(autouse=True)
def _fresh_discovery_state():
    adapter._DISCOVERED_MODELS.clear()
    adapter._LOGGED_PROBLEMS.clear()
    yield
    adapter._DISCOVERED_MODELS.clear()
    adapter._LOGGED_PROBLEMS.clear()


class _Server:
    """An OpenAI-compatible server that lists `models` and answers chat."""

    def __init__(self, models):
        self.requests: list[tuple[str, str, dict]] = []
        outer = self
        payload = json.dumps({"object": "list",
                              "data": [{"id": m, "object": "model"} for m in models]}).encode()

        class Handler(BaseHTTPRequestHandler):
            def _send(self, data: bytes, ctype="application/json"):
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                outer.requests.append(("GET", self.path, {}))
                self._send(payload)

            def do_DELETE(self):
                outer.requests.append(("DELETE", self.path, {}))
                self._send(b"{}")

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
                outer.requests.append(("POST", self.path, body))
                if body.get("stream"):
                    chunks = [
                        {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": body["model"],
                         "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Hola"},
                                      "finish_reason": None}]},
                        {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": body["model"],
                         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                    ]
                    data = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
                    self._send(data.encode(), "text/event-stream")
                    return
                self._send(json.dumps({
                    "id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hola"},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }).encode())

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def chat_models(self):
        return [b["model"] for m, p, b in self.requests if m == "POST" and p.endswith("/chat/completions")]

    def only_listed_and_chatted(self):
        """Every request was a model listing or a chat completion: nothing was
        pulled, created, copied or deleted."""
        allowed = {("GET", "/v1/models"), ("POST", "/v1/chat/completions")}
        return all((m, p) in allowed for m, p, _ in self.requests)

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def server_factory():
    servers = []

    def make(models):
        s = _Server(models)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.close()


def _local(url: str, model: str = "") -> OpenAICompatibleClient:
    return OpenAICompatibleClient(base_url=url, api_key="not-needed", model=model, discover_model=True)


def _ask(client) -> None:
    asyncio.run(client.messages.create(max_tokens=8, messages=[{"role": "user", "content": "hola"}]))


# ── The four cases ───────────────────────────────────────────────────────────

def test_an_explicit_model_is_used_unchanged_and_nothing_is_asked(server_factory):
    server = server_factory(["some-other-model"])
    _ask(_local(server.url, model="granite3.3:8b"))
    assert server.chat_models() == ["granite3.3:8b"]
    assert not any(p == "/v1/models" for _, p, _ in server.requests)


def test_unset_with_exactly_one_served_model_uses_it_and_logs_once(server_factory, caplog):
    server = server_factory([QWEN_CODER])
    caplog.set_level(logging.INFO, logger=adapter.__name__)
    _ask(_local(server.url))
    _ask(_local(server.url))  # a second client: no second listing, no second log line
    assert server.chat_models() == [QWEN_CODER, QWEN_CODER]
    assert [p for m, p, _ in server.requests if m == "GET"] == ["/v1/models"]
    found = [r for r in caplog.records if QWEN_CODER in r.getMessage() and "exactly one" in r.getMessage()]
    assert len(found) == 1
    assert f"LOCAL_LLM_MODEL={QWEN_CODER}" in found[0].getMessage()
    assert server.only_listed_and_chatted()


@pytest.mark.parametrize("served", [["a:1", "b:2"], []], ids=["two", "zero"])
def test_unset_with_several_or_no_models_is_an_actionable_error(server_factory, served, caplog):
    server = server_factory(served)
    with pytest.raises(LocalModelNotConfiguredError) as info:
        _ask(_local(server.url))
    assert not isinstance(info.value, ConnectionError)
    assert "LOCAL_LLM_MODEL=<the model your server serves>" in str(info.value)
    assert server.chat_models() == []  # never guessed
    assert any("LOCAL_LLM_MODEL=" in r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
    assert server.only_listed_and_chatted()


def test_unset_with_an_unreachable_server_is_an_actionable_error_that_still_fails_over():
    with pytest.raises(LocalModelUnreachableError) as info:
        _ask(_local("http://127.0.0.1:9/v1"))
    assert isinstance(info.value, ConnectionError)  # FailoverClient's existing rule
    assert "LOCAL_LLM_MODEL=<the model your server serves>" in str(info.value)


def test_the_streaming_path_resolves_the_same_way(server_factory):
    server = server_factory([QWEN_CODER])

    async def stream():
        async with _local(server.url).messages.stream(
                max_tokens=8, messages=[{"role": "user", "content": "hola"}]) as s:
            async for _ in s:
                pass

    asyncio.run(stream())
    assert server.chat_models() == [QWEN_CODER]


def test_other_providers_never_discover(server_factory):
    server = server_factory(["only-one"])
    client = OpenAICompatibleClient(base_url=server.url, api_key="k", model="")
    _ask(client)
    assert server.chat_models() == [""]
    assert not any(p == "/v1/models" for _, p, _ in server.requests)


# ── The audit detail names the fix ───────────────────────────────────────────

def test_the_backend_failure_detail_names_the_setting():
    detail = backend_failure_detail(LocalModelNotConfiguredError("x"))
    assert "error=LocalModelNotConfiguredError" in detail
    assert "LOCAL_LLM_MODEL=<the model your server serves>" in detail
    assert backend_failure_detail(RuntimeError("child words")) == "error=RuntimeError"


@pytest.mark.parametrize("path", ["routers/tutor.py", "routers/sandbox.py", "routers/pilot_tutor.py"])
def test_every_exception_audit_site_uses_the_detail_helper(path):
    """Invocation guard: the helper is useless unless the AI_BACKEND_FAILURE
    call sites use it instead of formatting the exception type themselves."""
    source = (ROOT / "homeschool-api" / path).read_text(encoding="utf-8")
    assert "backend_failure_detail(exc)" in source
    assert "error={type(exc).__name__}" not in source


def test_startup_check_records_the_fix_in_the_audit_log(monkeypatch, server_factory):
    import main

    server = server_factory(["a:1", "b:2"])
    events = []

    async def fake_log_event(event, **kwargs):
        events.append((event, kwargs))

    monkeypatch.setattr(main, "log_event", fake_log_event)
    monkeypatch.setattr(main.settings, "local_llm_base_url", server.url)
    monkeypatch.setattr(main.settings, "local_llm_model", "")
    asyncio.run(main._discover_local_model_at_startup())
    assert len(events) == 1
    event, kwargs = events[0]
    assert event == AuditEvent.AI_BACKEND_FAILURE
    assert "cause=startup" in kwargs["detail"] and "LOCAL_LLM_MODEL=" in kwargs["detail"]


def test_startup_check_does_nothing_when_the_model_is_set(monkeypatch, server_factory):
    import main

    server = server_factory(["a:1", "b:2"])
    monkeypatch.setattr(main.settings, "local_llm_base_url", server.url)
    monkeypatch.setattr(main.settings, "local_llm_model", "a:1")
    asyncio.run(main._discover_local_model_at_startup())
    assert server.requests == []


def test_the_lifespan_starts_the_startup_check():
    source = (ROOT / "homeschool-api" / "main.py").read_text(encoding="utf-8")
    lifespan = source[source.index("async def lifespan("):]
    assert "_start_background(\n        _discover_local_model_at_startup()" in lifespan


# ── The old blank-Enter setup keeps working after the update ─────────────────

def _blank_install_settings(url: str) -> Settings:
    """Settings exactly as the api container builds them for a household whose
    .env has LOCAL_LLM_BASE_URL and no LOCAL_LLM_MODEL line (setup.sh's blank
    Enter, or the wizard's old optional field), from the REAL compose block."""
    kwargs = _settings_kwargs("api")
    assert kwargs["local_llm_model"] == "", "compose must pass an unset model as empty"
    kwargs["local_llm_base_url"] = url
    kwargs["bede_adapter_order"] = "local"
    return Settings(**kwargs)


def test_an_old_blank_name_vllm_setup_keeps_its_qwen_model(server_factory):
    server = server_factory([QWEN_CODER])
    settings = _blank_install_settings(server.url)
    assert settings.local_llm_model == ""
    _ask(_build("local", settings))
    assert server.chat_models() == [QWEN_CODER]
    assert LOCAL_LLM_DEFAULT_MODEL not in server.chat_models()
    assert server.only_listed_and_chatted()


def test_the_settings_default_is_unset_not_a_model_name():
    assert Settings.model_fields["local_llm_model"].default == ""


@pytest.mark.parametrize("service", ["api", "locuto-ipc"])
def test_compose_passes_an_unset_model_as_empty_for_every_process(service):
    assert _settings_kwargs(service)["local_llm_model"] == ""


# ── The Locuto listener behaves the same way ─────────────────────────────────

@pytest.mark.parametrize("served,expected", [
    ([QWEN_CODER], f"local:{QWEN_CODER}"),
    (["a:1", "b:2"], "unavailable"),
    ([], "unavailable"),
])
def test_locuto_reports_the_discovered_model_or_refuses_to_guess(monkeypatch, server_factory, served, expected):
    from services.locuto_ipc import server as locuto

    server = server_factory(served)
    monkeypatch.setattr(locuto.settings, "local_llm_base_url", server.url)
    monkeypatch.setattr(locuto.settings, "local_llm_model", "")
    assert asyncio.run(locuto._adapter_identity()) == expected
    assert server.only_listed_and_chatted()


def test_resolve_local_only_clients_discover_too(monkeypatch, server_factory):
    from core.config import settings

    server = server_factory([QWEN_CODER])
    monkeypatch.setattr(settings, "local_llm_base_url", server.url)
    monkeypatch.setattr(settings, "local_llm_model", "")
    _ask(resolve_local_only(settings))
    assert server.chat_models() == [QWEN_CODER]


# ── setup.sh and the docs say the same thing ─────────────────────────────────

def test_setup_sh_always_writes_the_model():
    text = (ROOT / "setup.sh").read_text(encoding="utf-8")
    assert f'LOCAL_LLM_MODEL="${{LOCAL_LLM_MODEL:-{LOCAL_LLM_DEFAULT_MODEL}}}"' in text
    assert f"Model name [{LOCAL_LLM_DEFAULT_MODEL}]" in text


def test_the_provider_doc_describes_the_unset_behaviour():
    text = re.sub(r"\s+", " ", (ROOT / "docs" / "PROVIDER_ADAPTERS.md").read_text(encoding="utf-8"))
    assert "When `LOCAL_LLM_MODEL` is not set." in text
    assert "add LOCAL_LLM_MODEL=<the model your server serves> to .env and restart Bede" in text
    assert adapter.LOCAL_MODEL_FIX in text
