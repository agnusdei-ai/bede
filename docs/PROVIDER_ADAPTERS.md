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
| request | a user turn's `{"type":"image",...}` block (invite_handwriting's drawing submissions) | `{"type":"image_url","image_url":{"url":"data:<mime>;base64,<data>"}}` |

**The image translation needs a vision-capable model on the far end.** OpenAI's
default (`gpt-4.1-mini`) is vision-capable, so a child's handwriting/drawing
submission (`invite_handwriting`) reaches it intact. `Qwen/Qwen3-Coder-30B-A3B-Instruct`
(the local adapter's default) is a code model, not a vision one, and Mistral's
default `mistral-large-latest` is text-only — configuring either as primary
means a drawing submission may be rejected or ignored by that backend rather
than silently dropped the way it was before this translation existed. If a
non-vision model is your primary, `BEDE_ADAPTER_ORDER` should still list a
vision-capable adapter (Anthropic or OpenAI) as a fallback so handwriting
submissions keep working through failover.

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

## Setup guide — configuring and installing each adapter

### OpenAI (cloud, no local install)

1. Create an account and API key at [platform.openai.com](https://platform.openai.com/api-keys),
   and add a billing method (pay-as-you-go).
2. Set `OPENAI_API_KEY=sk-...` in `.env` (or Render's dashboard for the demo).
   This is the **same key** already used for OpenAI TTS — no second key needed.
3. Optionally set `OPENAI_MODEL` (default `gpt-4.1-mini`) to a different chat model.
4. Add `openai` to `BEDE_ADAPTER_ORDER`, e.g. `BEDE_ADAPTER_ORDER=openai,mistral`.
5. No package install needed — the `openai` Python SDK (`>=1.40.0`) is already in
   `homeschool-api/requirements.txt` (it was already a dependency for TTS).

### Mistral AI (cloud, no local install)

1. Create an account and API key at [console.mistral.ai](https://console.mistral.ai/)
   ("La Plateforme") -> API Keys.
2. Set `MISTRAL_API_KEY=...` in `.env` (or Render's dashboard).
3. Optionally set `MISTRAL_MODEL` (default `mistral-large-latest`).
4. Add `mistral` to `BEDE_ADAPTER_ORDER`. No package install needed — Mistral's
   API is OpenAI-compatible, so it reuses `OpenAICompatibleClient` and the same
   `openai` SDK dependency, just pointed at `https://api.mistral.ai/v1`.

### Render demo/dev deployment — cloud-only, OpenAI + Mistral

`render.yaml` sets `BEDE_ADAPTER_ORDER=openai,mistral` for the `bede-demo-api`
service specifically (OpenAI primary, Mistral fallback), because Render has no
GPU (the `local` adapter can't run there) and this deployment should boot and
serve without needing Anthropic access at all. After a Blueprint deploy, fill
in `OPENAI_API_KEY` and `MISTRAL_API_KEY` from Render's dashboard (both
`sync: false`, per docs/DEMO_HOSTING.md's setup walkthrough) —
`ANTHROPIC_API_KEY` is left declared but optional/unused by default here.

**This is live failover, not just a boot-time preference.**
`services/ai_service.py`'s `_client` is resolved via
`router.resolve_with_failover()` (Phase 6), which wraps every adapter in
`BEDE_ADAPTER_ORDER` behind a `FailoverClient`: if OpenAI errors with an
auth/rate-limit/connection failure on a request, that same request
automatically retries against Mistral before any content is streamed back —
no restart or key removal needed. A short in-memory circuit breaker then
skips OpenAI on subsequent calls for ~60s rather than re-paying its timeout
every time, and resets once a call to it succeeds again.

### Local self-hosted vLLM + Qwen3-Coder-30B-A3B-Instruct (needs a GPU)

**Hardware — vLLM is Linux/CUDA-only.** It does not run on Raspberry Pi (no
discrete GPU/CUDA) or on Apple Silicon Macs (no native vLLM support). It needs
an NVIDIA GPU on Linux (bare metal or WSL2):

| Tier | GPU VRAM | System RAM | Storage | Notes |
|------|----------|------------|---------|-------|
| Minimum | 16 GB (RTX 4060 Ti 16GB+) | 32 GB | ~30-45 GB SSD | 4-bit AWQ/GPTQ quant |
| Recommended | 24 GB (RTX 3090/4090) | 64 GB | 45+ GB SSD | Full quality Q4/Q5, better throughput/longer context |

If your household hardware is a laptop/tablet/Raspberry Pi without a suitable
GPU, skip this adapter and rely on `openai`/`mistral` (or `anthropic` if/when
restored) instead — that's exactly what the adapter design is for.

**Install/run** (on the separate GPU machine, not on Render):

```bash
docker run --gpus all -p 8000:8000 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai:latest \
  --model Qwen/Qwen3-Coder-30B-A3B-Instruct \
  --tool-call-parser qwen3_coder \
  --enable-auto-tool-choice \
  --max-model-len 131072
```

Then on the Bede backend (wherever it runs — laptop/Pi/tablet or Render), set:

```bash
LOCAL_LLM_BASE_URL=http://your-gpu-box.lan:8000/v1
LOCAL_LLM_API_KEY=not-needed
LOCAL_LLM_MODEL=Qwen/Qwen3-Coder-30B-A3B-Instruct
BEDE_ADAPTER_ORDER=local,anthropic
```

Put the vLLM server behind a tunnel/VPN (Tailscale, WireGuard) or an
authenticating reverse proxy before exposing it beyond your LAN — its OpenAI
server has no built-in auth.

### Anthropic (optional/legacy — kept for whenever access returns)

1. `ANTHROPIC_API_KEY=sk-ant-...` in `.env`, same as before this refactor.
2. Add `anthropic` to `BEDE_ADAPTER_ORDER` (or leave it there — it's in the
   default already) to use it again the moment it's set.
3. No install needed — `anthropic>=0.40.0` was already a dependency.

## Adding another provider

If it speaks OpenAI's `/v1/chat/completions`, you don't need new code — add a
branch in `router._build` / `router._is_configured` pointing an
`OpenAICompatibleClient` at its `base_url`, plus its config fields. Only a
provider with a genuinely different wire protocol would need a new adapter class
implementing the `base.ChatAdapter` shape.
