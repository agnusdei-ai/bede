# Choosing Bede's tutor model provider

Bede talks to hosted Claude by default — the best tutoring quality available,
and the recommended setting for almost every deployment. For a fully
air-gapped homeschool (no outbound internet at all), or as a hedge against a
compromised or poisoned upstream model, Bede can instead be pointed at any
self-hosted, OpenAI-compatible chat-completions server: Ollama, vLLM, a
llama.cpp server, or LM Studio all work. This is a real quality tradeoff —
open-weight local models are not as strong Socratic tutors as Claude — so
only switch if air-gapping or provider independence genuinely matters more
than tutoring quality for your deployment.

## Setup

```bash
MODEL_PROVIDER=local
LOCAL_MODEL_BASE_URL=http://localhost:11434/v1   # Ollama's default; adjust for vLLM/llama.cpp/LM Studio
LOCAL_MODEL_NAME=llama3.1:8b                      # must match a model already loaded on that server
```

Leave `MODEL_PROVIDER` unset (or `anthropic`) to keep using hosted Claude —
that's the default, and `ANTHROPIC_API_KEY` is the only thing required.

`core/config.py` refuses to start with `MODEL_PROVIDER=local` and no
`LOCAL_MODEL_NAME` set — there's no sensible "use the server's default model"
behavior to fall back to, since most OpenAI-compatible servers require an
explicit model id per request.

## What this does and doesn't protect against

Switching to a local provider changes two things: no tutoring conversation
ever leaves your network, and Bede keeps working with the network
disconnected entirely (true air-gap). Both are real, and both are worth
having if that's the goal.

What it does **not** do on its own is verify that the model weights sitting
on your inference server haven't been tampered with. Bede's `LocalProvider`
talks HTTP to whatever answers at `LOCAL_MODEL_BASE_URL` — it has no way to
inspect the actual weight file behind that server, so it cannot detect a
supply-chain compromise of the model artifact itself (a poisoned checkpoint
published under a legitimate-looking name, a swapped `.gguf`/`.safetensors`
file on disk, etc.). That verification is an operator-side step, done once
when you provision the model, not something an API client can check per
request:

- Download model weights only from the model's official source (e.g. the
  publisher's page on Hugging Face), and verify the file's published
  checksum/hash before loading it into Ollama/vLLM/llama.cpp.
- Pin an exact model file, not a moving "latest" tag, so a later swap
  upstream can't silently change what's running without you re-verifying.
- Treat the inference server itself as part of your trusted boundary — same
  as the database and the API container.

For the hosted-Claude path, the equivalent guarantee is that `tutor_model` /
`session_model` in `core/config.py` are already pinned to exact model
strings (`claude-sonnet-4-6`, `claude-haiku-4-5-20251001`) rather than a
"latest" alias, and Anthropic's own infrastructure is the trust boundary
instead of a self-managed server.

## Architecture note

Both backends implement the same `ModelProvider` interface
(`services/model_providers/base.py`): `AnthropicProvider` wraps the hosted
Claude SDK, `LocalProvider` speaks the OpenAI-compatible chat-completions
protocol. `services/ai_service.py` — the Socratic-tutor prompt building,
per-tool dispatch, and SSE streaming to the frontend — never references
either backend directly; it only sees normalized `TextDelta`/`ToolCall`
events from `get_provider()`. Adding a third backend means implementing that
one interface, not touching the tutor logic.
