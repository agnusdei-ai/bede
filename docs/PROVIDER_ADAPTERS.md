# Provider adapters — a vendor-agnostic tutor backend

Bede's tutor engine (`homeschool-api/services/ai_service.py`) was originally
written directly against the Anthropic Messages API: a single module-level
`_client = anthropic.AsyncAnthropic(...)` whose `.messages.stream(...)` /
`.messages.create(...)` it called with Anthropic-shaped requests and whose
streaming events it consumed by their Anthropic wire-protocol `.type` strings.

That hardcoded a single vendor into ~2000 lines of prompt/tool/streaming logic.
If the Anthropic account is closed, rate-limited, or otherwise unreachable, the
whole tutor goes down with it. The `services/adapters/` package removes that
single point of failure **without rewriting the engine**.

## The design in one sentence

`_client` is still one object exposing `.messages.stream()` / `.messages.create()`
with Anthropic-shaped inputs and outputs — but *which* concrete object it is now
comes from a provider-adapter router instead of being hardcoded to Anthropic.

Because the shape is identical, none of ai_service.py's call sites changed, and
none of the ~20 tests that monkeypatch `ai_service._client.messages.stream`/
`.create` changed either.

## The package

```
homeschool-api/services/adapters/
  base.py                       Anthropic-shaped vocabulary a translating adapter emits
                                (StreamEvent, AdapterMessage, TextBlock, ToolUseBlock, AdapterUsage)
                                + the ChatAdapter Protocol.
  anthropic_adapter.py          Trivial: returns a real anthropic.AsyncAnthropic
                                (it already IS the target shape).
  openai_compatible_adapter.py  ONE class, OpenAICompatibleClient, parameterized by
                                base_url + api_key + model, that TRANSLATES the Anthropic
                                Messages shape to/from OpenAI /v1/chat/completions.
  router.py                     get_default_client() (single resolved _client) and
                                resolve_with_failover() (Phase-6 failover router).
```

### The one OpenAI-compatible class covers every non-Anthropic provider

`OpenAICompatibleClient` talks to any endpoint that speaks OpenAI's
`/v1/chat/completions` — which is nearly everything that isn't Anthropic:

- **OpenAI** itself (no `base_url` override needed)
- a **self-hosted vLLM** server running `Qwen/Qwen3-Coder-30B-A3B-Instruct`
  (start vLLM with `--tool-call-parser qwen3_coder` so it emits tool calls in
  the OpenAI `tool_calls` shape the adapter reads back)
- **Mistral**'s API
- any other OpenAI-compatible or HF Inference endpoint (Together, LM Studio, TGI…)

It translates symmetrically:

| Direction | Anthropic shape | OpenAI shape |
|-----------|-----------------|--------------|
| request | `system` list of cache-controlled text blocks | a single `system` role message (cache_control dropped) |
| request | `tools[].input_schema` | `tools[].function.parameters` |
| request | `tool_choice` auto / any / tool | `auto` / `required` / named function |
| response | streamed `content_block_delta` (`text_delta`) | `choices[].delta.content` |
| response | streamed `tool_use` + `input_json_delta` + `content_block_stop` | `choices[].delta.tool_calls` fragments |
| response | `.usage.input_tokens` / `.output_tokens` | `usage.prompt_tokens` / `completion_tokens` |

## Configuration

All in `homeschool-api/core/config.py` (env vars via `.env`):

| Env var | Default | Meaning |
|---------|---------|---------|
| `BEDE_ADAPTER_ORDER` | `local,anthropic` | Comma preference list; first *configured* adapter wins. |
| `BEDE_FORCE_ADAPTER` | *(empty)* | Pin to one adapter, skipping order/failover. |
| `LOCAL_LLM_BASE_URL` | *(empty)* | vLLM/OpenAI-compatible `/v1` endpoint. Empty ⇒ local adapter skipped. |
| `LOCAL_LLM_API_KEY` | `not-needed` | Placeholder; vLLM's OpenAI server has no built-in auth. |
| `LOCAL_LLM_MODEL` | `Qwen/Qwen3-Coder-30B-A3B-Instruct` | Model name the local server serves. |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Chat model for the OpenAI adapter (reuses `OPENAI_API_KEY`). |
| `MISTRAL_API_KEY` / `MISTRAL_MODEL` | *(empty)* / `mistral-large-latest` | Mistral secondary. |

An adapter is **"configured"** when the credentials it needs are present:
`local` needs `LOCAL_LLM_BASE_URL`; `anthropic` needs `ANTHROPIC_API_KEY`;
`openai`/`mistral` need their API key. The router picks the first configured
adapter in the order and **skips the rest** — and never raises at import time
even if nothing is configured (construction is lazy; only a real request would
surface a misconfiguration), so the app always boots.

## Why the default is `local,anthropic` — the account-closure scenario

This refactor exists precisely for the case where **Anthropic access is gone**
(account closed or denied). So the default order deliberately does **not** put
Anthropic first:

- **`local`** — a self-hosted vLLM/Qwen3-Coder server — is the practical
  primary. A deployment that has lost Anthropic sets `LOCAL_LLM_BASE_URL`, and
  `local` wins.
- **`anthropic`** is kept in the code and last in the order so access can be
  restored instantly by just setting the key again — but the router **never
  requires `ANTHROPIC_API_KEY` to boot or serve**.
- A legacy deployment that only has `ANTHROPIC_API_KEY` set (and the test suite)
  falls through to `anthropic` and behaves exactly as before.

### Why OpenAI/Mistral are secondaries kept OUT of the default order

`OPENAI_API_KEY` already exists in this codebase to drive **OpenAI TTS**
(`services/voice_synthesis.py`). Auto-selecting the OpenAI **chat** adapter
merely because a TTS key is present would silently reroute the tutor to OpenAI on
any voice-enabled deployment. So `openai`/`mistral` are fully supported but must
be enabled explicitly, e.g. `BEDE_ADAPTER_ORDER=local,openai,anthropic`.

## Phase 6: failover / provider continuity

`router.resolve_with_failover()` returns a `FailoverClient` presenting the same
`.messages` surface but trying each *configured* adapter in order, catching
auth (401/403), rate-limit (429), and connection/timeout errors and falling
through to the next. A short in-memory circuit breaker (per-adapter cooldown)
keeps a downed provider from being retried on every request. Streaming fails
over only *before* the first event is yielded (switching mid-stream to the child
isn't safe). It is an opt-in helper, not the default `_client`, so the
single-resolved-client contract the existing tests rely on stays intact. When a
non-primary adapter is used, it best-effort emails the operator
(`PARENT_EMAIL`/Resend, via the existing `services/email_service.py`) as an FYI.

## Infrastructure note — the local model needs a GPU, and Render has none

The backend is deployed on **Render**, which has **no GPU instance types**. The
local vLLM adapter running Qwen3-Coder-30B-A3B-Instruct therefore **CANNOT run
inside the Render web service container**. It must run on separate GPU hardware:

- a home/office GPU box or a LAN server, or
- a rented GPU instance (RunPod, Lambda, Vast.ai, etc.).

The Render-hosted API just points `LOCAL_LLM_BASE_URL` at that server's `/v1`
endpoint over the network. Because vLLM's OpenAI-compatible server has **no
built-in authentication**, expose it over a private tunnel/VPN (Tailscale,
WireGuard, an SSH tunnel) or at minimum put an authenticating reverse proxy in
front of it and set `LOCAL_LLM_API_KEY` accordingly — never hang it directly on
the public internet.

## Adding another provider

If it speaks OpenAI's `/v1/chat/completions`, you don't need new code — add a
branch in `router._build` / `router._is_configured` pointing an
`OpenAICompatibleClient` at its `base_url`, plus its config fields. Only a
provider with a genuinely different wire protocol would need a new adapter class
implementing the `base.ChatAdapter` shape.
