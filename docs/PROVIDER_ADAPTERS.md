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
- a **self-hosted vLLM** server running
  `mistralai/Mistral-Small-3.2-24B-Instruct-2506` (start vLLM with
  `--tool-call-parser mistral --enable-auto-tool-choice` so it emits tool
  calls in the OpenAI `tool_calls` shape the adapter reads back)
- **Ollama** on the family's own computer, which is what the installers set
  up (`docs/WINDOWS_INSTALLER.md`, `docs/UNIX_INSTALLER.md`)
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
submission (`invite_handwriting`) reaches it intact. The recommended vLLM
model, Mistral Small 3.2, accepts images, and so do the
`ministral-3` and `mistral-small3.2` Ollama models the installers pull on
most tiers. The `granite3.3` Ollama models are text-only, and Mistral's API
default `mistral-large-latest` is text-only — configuring one of those as
primary means a drawing submission may be rejected or ignored by that
backend rather
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
| `LOCAL_LLM_MODEL` | *(not set)* | Model name the local server serves. Written by every installer and by setup. Not set: the server's only model, or an error naming this setting (see "When `LOCAL_LLM_MODEL` is not set" below). Recommended for vLLM: `mistralai/Mistral-Small-3.2-24B-Instruct-2506`. |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Chat model for the OpenAI adapter (reuses `OPENAI_API_KEY`). |
| `MISTRAL_API_KEY` / `MISTRAL_MODEL` | *(empty)* / `mistral-large-latest` | Mistral secondary. |
| `AI_PROVIDER_HEADERS` | *(empty)* | Extra request headers per provider, as JSON keyed by provider (`anthropic`, `openai`, `mistral`, `local`). See "Extra request headers" below. |

An adapter is **"configured"** when the credentials it needs are present:
`local` needs `LOCAL_LLM_BASE_URL`; `anthropic` needs `ANTHROPIC_API_KEY`;
`openai`/`mistral` need their API key. The router picks the first configured
adapter in the order and **skips the rest** — and never raises at import time
even if nothing is configured (construction is lazy; only a real request would
surface a misconfiguration), so the app always boots.

## Extra request headers (`AI_PROVIDER_HEADERS`)

Some providers, and some gateways in front of a local model, will not answer
until a request carries a header of their own. Rather than a named setting
for each one, there is a single setting, a JSON object keyed by provider:

```
AI_PROVIDER_HEADERS={"anthropic":{"anthropic-workspace-id":"wrkspc_..."},"openai":{"OpenAI-Project":"proj_..."}}
```

- **Claude with an organization-level key** is the case that prompted it: such
  a key is refused with "API key is not scoped to a workspace" (the demo's
  backup, 2026-11-17) unless every request names the workspace to bill. A key
  created inside a workspace needs nothing.
- **OpenAI** organizations and projects (`OpenAI-Organization`,
  `OpenAI-Project`), and any gateway's own header for `local`, go the same way.
- **Checked when Bede starts** (`core/request_headers.py`), so a mistake stops
  boot with a plain sentence rather than refusing a lesson later: a provider
  that does not exist, a header name that is not a valid HTTP token, a value
  with a line break or control character (which could otherwise start a second
  header), more than 16 headers, or a header the HTTP client owns (`Host`,
  `Content-Type`, `Cookie`, ...). Error messages never repeat a value.
- **The key stays in the provider's own key setting.** `Authorization`,
  `x-api-key` and `api-key` are refused here: two places holding a key is how
  the wrong one gets sent.
- Without the setting, every provider's client is built exactly as before.

`tests/test_provider_request_headers.py` sends a real request through each
provider's real SDK client into a mock transport and reads the headers off the
wire, on both the direct and failover paths. External MCP servers take the same
checks per server; see `docs/MCP.md`.

## Private inference (proposed)

Whether a family's or school's data may leave their boundary at all, and how
that would be enforced, is set out as a proposed target in
[`PRIVATE_INFERENCE.md`](PRIVATE_INFERENCE.md) (decision register entry 44).
Today, outside school mode, a configured cloud key is a live fallback for a
failed local model.

## Why the default is `local,anthropic` — the account-closure scenario

This refactor exists precisely for the case where **Anthropic access is gone**
(account closed or denied). So the default order deliberately does **not** put
Anthropic first:

- **`local`** — a self-hosted model server (Ollama or vLLM) — is the practical
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

## Live, in-app provider switching (no .env edit, no restart)

`BEDE_ADAPTER_ORDER`/`BEDE_FORCE_ADAPTER` above are read once at process
startup — changing them normally means an `.env` edit and a restart. For the
common case of "my local model is degraded, I want to move to a cloud
provider right now" that's an unnecessary amount of friction, so there's a
second, live way to change primary: the parent-facing **AI Provider** card
(`homeschool-tutor/src/components/AIProviderSettings.tsx`, in the same
settings panel as license renewal), backed by `GET`/`POST /admin/ai-provider`
(`routers/admin.py`) and `core/provider_state.py`.

- It only ever picks among adapters that are **already configured** —
  credentials still come exclusively from `.env`. Choosing a provider with no
  credentials set is rejected (422) before anything is stored.
- The choice is stored in the database (`AIProviderOverride`, one row) and
  cached in-process, the same "DB value wins over env, live, no restart"
  pattern `core/license_state.py`/`core/parent_credential.py` use for the
  license key and password. `services/adapters/router.py`'s `FailoverClient`
  — what `ai_service._client` actually is — checks this cache on every
  tutoring turn, so a switch takes effect on the very next message, not the
  next deploy.
- `BEDE_FORCE_ADAPTER`, if set, still wins unconditionally — a DB override
  can only reorder among configured adapters, and a force-pin leaves exactly
  one adapter in that set.
- Clearing the override (`provider: null`) reverts to the env-configured
  `BEDE_ADAPTER_ORDER` preference.

This is a manual switch a parent makes, distinct from Phase 6's *automatic*
failover above — use the failover order (`BEDE_ADAPTER_ORDER=local,mistral`,
say) for "keep working if my primary errors out," and the AI Provider card
for "I've decided the other one should be primary now."

### Choosing the failover itself, not just primary

With exactly two adapters configured, picking a primary already answers
"what's the failover" implicitly — the other one is the only fallback
there is. With **three or more** configured (e.g. `openai`, `mistral`,
`anthropic` all credentialed), that's no longer true: a family might
prefer Claude over Mistral as backup, or vice versa, and previously had
no way to express that short of editing `BEDE_ADAPTER_ORDER` and
restarting.

`POST /admin/ai-provider/secondary` (`routers/admin.py`, backed by
`core/provider_state.py`'s `set_secondary`/`clear_secondary`/
`current_secondary`) is the same "DB value wins over env, live, no
restart" mechanism as primary, applied one slot deeper: it picks which
configured adapter is tried FIRST if primary errors, leaving the rest of
the configured list to follow in its original relative order after that.
`AIProviderOverride`'s `key` column was always a string primary key
rather than a hardcoded singleton specifically so a second row
(`key="secondary"`) could be added later without a schema change — this
is that second row. The parent-facing AI Provider card
(`AIProviderSettings.tsx`) only shows this second picker once 3+ adapters
are configured, since with two it would have nothing meaningful to offer;
naming the current primary as secondary is rejected (422) as a no-op.
Clearing it (`provider: null`) reverts the failover-after-primary to
whichever adapter is next in the env order, exactly as before this
existed.

This is also what makes the public demo's disclosed failover choice
(`docs/RETENTION_POLICY.md`, `demo/public/privacy.html`) an actual,
codepath-backed configuration rather than a hardcoded claim: `render.yaml`
lists `openai,mistral,anthropic` for that deployment specifically so
Anthropic is a legitimate, already-in-the-order candidate the moment its
API key is filled in, and this endpoint (called directly against the
demo's own backend with its parent credentials — the demo's frontend
never renders this UI, but the same FastAPI backend code path exists
underneath it) is how an operator would actually pick Claude over Mistral
as that deployment's backup, live, without a redeploy.

**Practical example for a home-server local model (e.g. Ollama):** keep both
credentials populated in `.env` at all times —

```bash
LOCAL_LLM_BASE_URL=http://localhost:11434/v1
LOCAL_LLM_MODEL=granite3.3:8b
MISTRAL_API_KEY=your-key
BEDE_ADAPTER_ORDER=local,mistral
```

— and when the local model's hardware can't keep up, open the AI Provider
card and select Mistral. No SSH access to the server needed for that switch.

## Infrastructure note — the local model needs a GPU, and Render has none

The backend is deployed on **Render**, which has **no GPU instance types**. The
local vLLM adapter running Mistral Small 3.2 therefore **CANNOT run inside the
Render web service container**. It must run on separate GPU hardware:

- a home/office GPU box or a LAN server, or
- a rented GPU instance (RunPod, Lambda, Vast.ai, etc.).

The Render-hosted API just points `LOCAL_LLM_BASE_URL` at that server's `/v1`
endpoint over the network. Because vLLM's OpenAI-compatible server has **no
built-in authentication**, expose it over a private tunnel/VPN (Tailscale,
WireGuard, an SSH tunnel) or at minimum put an authenticating reverse proxy in
front of it and set `LOCAL_LLM_API_KEY` accordingly — never hang it directly on
the public internet.

## Model weight integrity — self-hosted local models (OWASP LLM04)

Neither `packaging/unix/install.sh` nor `packaging/windows/Setup-Bede.ps1`
(nor the browser wizard, `scripts/setup_wizard/wizard.py`) adds any
checksum or signature verification of its own on top of `ollama pull
<tag>` — it's a plain call into Ollama's own pull mechanism.
This isn't an unverified download: Ollama's own protocol is
content-addressed (each model layer is fetched and checked against a
SHA256 digest named in its manifest, the same scheme container registries
use), so integrity is delegated to a well-known upstream tool's own
mechanism rather than skipped — the same posture this codebase already
takes toward `apt`/`pip`/`npm`. It just isn't independently re-verified by
Bede, and until now that delegation wasn't written down anywhere.

For a self-hosted vLLM deployment (the "rented/home GPU box" path above),
model sourcing is the deployer's own choice, which is inherent to a
bring-your-own-model architecture rather than something a checksum in
this repo could enforce. The rules this project sets for it (GGUF or
safetensors only, never pickle-based weights, never `trust_remote_code`)
are in `docs/SECURITY.md`'s "Local model files and network" section,
which also says which of them Bede enforces and which it only
recommends. See `docs/OWASP_LLM_TOP10.md`'s LLM04 section for the fuller
reasoning.

**Which models the installers pull, and why.** The default lineup, its
developers and licences, and the selection criteria are `docs/DECISIONS.md`
entry 43. The Qwen lineup is still offered as an explicit installer choice.

## Setup guide — configuring and installing each adapter

**For a first-time family install, `setup.sh`/`setup-gui` (see
`docs/PRODUCTION_SETUP.md`) ask which provider to use and write the right
`.env` lines for you** — no single vendor is required to get through
setup, and `core/config.py` rejects startup in production if none of the
four ends up configured. The steps below are for configuring an adapter by
hand afterward — adding a second one for failover, switching providers, or
setting one up outside the wizard (e.g. `render.yaml` for a cloud
deployment).

### OpenAI (cloud, no local install)

1. Create an account and API key at [platform.openai.com](https://platform.openai.com/api-keys),
   and add a billing method (pay-as-you-go).
2. Set `OPENAI_API_KEY=sk-...` in `.env` (or Render's dashboard for the demo).
   This is the **same key** already used for OpenAI TTS — no second key needed.
3. Optionally set `OPENAI_MODEL` (default `gpt-4.1-mini`) to a different chat model.
4. Add `openai` to `BEDE_ADAPTER_ORDER`, e.g. `BEDE_ADAPTER_ORDER=openai,mistral`.
5. No package install needed — the `openai` Python SDK (`>=1.40.0`) is already in
   `homeschool-api/requirements.in` (it was already a dependency for TTS).

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

### Local self-hosted vLLM + Mistral Small 3.2 (needs a large GPU)

The recommended vLLM model (`core/config.py`'s `LOCAL_LLM_DEFAULT_MODEL`,
which `setup.sh` offers and writes) is
`mistralai/Mistral-Small-3.2-24B-Instruct-2506` (Mistral AI, Apache-2.0),
the full-precision build. **It needs about 55 GB of GPU memory and vLLM
0.9.1 or later**, both from Mistral's model card for the bf16/fp16 weights.
The ~15GB figure in the installer tables is Ollama's quantised build of the
same model, which is a different file. A household that does not have that
much GPU memory uses the Ollama path the installers set up instead.

**Hardware — vLLM is Linux/CUDA-only.** It does not run on Raspberry Pi (no
discrete GPU/CUDA) or on Apple Silicon Macs (no native vLLM support). It needs
NVIDIA GPUs on Linux (bare metal or WSL2):

| Tier | GPU memory | Notes |
|------|------------|-------|
| Recommended model | about 55 GB in total (one 80 GB card, or two 32 GB+ cards with `--tensor-parallel-size 2`) | Full precision, the model card's figure |
| Less GPU memory | — | Use the Ollama path (quantised GGUF builds, see the installer tables) |

If your household hardware is a laptop/tablet/Raspberry Pi without a suitable
GPU, skip this adapter and rely on Ollama, `openai`/`mistral` (or `anthropic`
if/when restored) instead — that's exactly what the adapter design is for. The
parent-facing version of this same decision (plus what modest hardware does and
doesn't affect elsewhere — voice transcription, encryption) is
`docs/PARENT_SETUP.md`'s "Choosing your server machine".

**Install/run** (on the separate GPU machine, not on Render). Use a vLLM
image at 0.9.1 or later; the `--load_format mistral` flag loads Mistral's
own safetensors file, and the command deliberately has no
`--trust-remote-code`:

```bash
docker run --gpus all -p 8000:8000 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai:latest \
  --model mistralai/Mistral-Small-3.2-24B-Instruct-2506 \
  --tokenizer_mode mistral --config_format mistral --load_format mistral \
  --tool-call-parser mistral --enable-auto-tool-choice \
  --tensor-parallel-size 2
```

Then on the Bede backend (wherever it runs — laptop/Pi/tablet or Render), set:

```bash
LOCAL_LLM_BASE_URL=http://your-gpu-box.lan:8000/v1
LOCAL_LLM_API_KEY=not-needed
LOCAL_LLM_MODEL=mistralai/Mistral-Small-3.2-24B-Instruct-2506
BEDE_ADAPTER_ORDER=local,anthropic
```

**Qwen is still a choice.** `Qwen/Qwen3-Coder-30B-A3B-Instruct` (the vLLM
default before `docs/DECISIONS.md` entry 43) still works: serve it with
`--tool-call-parser qwen3_coder --enable-auto-tool-choice` and set
`LOCAL_LLM_MODEL` to its name. A deployment that already sets
`LOCAL_LLM_MODEL` keeps whatever it set.

**When `LOCAL_LLM_MODEL` is not set.** It has no default model name. An
explicitly set `LOCAL_LLM_MODEL` is always used unchanged. When it is not
set (absent or empty), Bede asks the local server which models it serves
(`GET /models`, which only lists; nothing is downloaded, replaced or
deleted) at startup and again when a lesson first needs the model:

- **Exactly one model:** Bede uses it and logs once which model it found,
  with the line to add to `.env` to make it explicit. This is how an older
  setup that left the name blank (for example a vLLM server running
  `Qwen/Qwen3-Coder-30B-A3B-Instruct`, set up before this change) keeps
  working after an update, with no edit.
- **Several models, none, or the server cannot be reached:** Bede does not
  guess. The local adapter fails with a configuration error that names the
  fix, `add LOCAL_LLM_MODEL=<the model your server serves> to .env and
  restart Bede`, in the log and in the `AI_BACKEND_FAILURE` audit detail
  (so the parent's backend-failure alert names it too). An unreachable
  server still fails over to a configured backup provider exactly as it did
  before.

The installers, `setup.sh` and the browser wizard all write
`LOCAL_LLM_MODEL`, so a new installation never relies on this. The same
rule applies to every process that uses the local model, including the
Locuto listener.

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
