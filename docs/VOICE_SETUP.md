# Setting up Bede's spoken voice

Bede's voice output is entirely optional. If you don't configure anything
below, the tablet's browser speaks Bede's lines using its own built-in voice.
On top of that, Bede supports one cloud backend: **OpenAI TTS**, using the
`gpt-4o-mini-tts` model — a small per-character cost, meaningfully more
natural than a browser's default voice. Confirmed against real listening
feedback that this is what it takes to get past "sounds computerized."

## Setup

Get an API key from [platform.openai.com](https://platform.openai.com/), then
set in `.env`:

```bash
OPENAI_API_KEY=sk-...
OPENAI_TTS_MODEL=gpt-4o-mini-tts   # the only OpenAI TTS model with `instructions` support
OPENAI_TTS_VOICE=fable             # OpenAI's own description: closest preset to a British storyteller tone
OPENAI_TTS_INSTRUCTIONS=Speak as an elderly, warm, unhurried Southern English monk.
```

`gpt-4o-mini-tts`'s `instructions` field is what actually lets you steer
character and delivery in plain English — that's the real lever for sounding
like a specific persona rather than a generic preset voice, and it's the main
reason to prefer `gpt-4o-mini-tts` over the older `tts-1`/`tts-1-hd` models
(which accept a fixed voice only, no instructions). Then apply it to your
running deployment — see "Applying this to a running deployment" below —
and test in a real session; there's no local script for this path since it's
a live API call, not a local model to benchmark offline.

Leave `OPENAI_API_KEY` unset to skip cloud voice entirely — the browser's own
speech takes over automatically, with no other changes needed.

## Applying this to a running deployment

The commands above (`.env` edits) only take effect on a machine that's
actually running `homeschool-api` — editing files in a dev checkout or this
Claude Code session does nothing for a live deployment on its own. On **the
host running the service**, after editing `.env` there:

```bash
make update     # git pull + docker rebuild + restart — use this whenever the
                 # CODE changed (e.g. adding OpenAI TTS support itself)
make restart     # .env-only change on a host already running the latest
                 # code — faster, but does NOT pull or rebuild
```

If you're not sure which applies: `make update` always does the right thing
(it's a superset of `restart`, just slower since it rebuilds). Follow with
`make status` to confirm the container came back healthy.

**Demo vs. production are separate deployments — each needs this done
independently.** `demo/README.md`'s self-service demo flow talks to
whatever `homeschool-api` host `VITE_DEMO_API_BASE` points to (a GitHub
Actions repository variable — Settings → Secrets and variables → Actions →
Variables), which may or may not be the same host as a family's private
production instance. Setting `OPENAI_API_KEY` on one does nothing for the
other. The demo's static frontend itself (GitHub Pages) needs no rebuild or
redeploy for a voice-provider change — voice selection is entirely
server-side, so only the backend host(s) need updating.

## Troubleshooting: voice works once, then goes silent

If Bede speaks the opening line fine but goes silent from the second turn
onward — reported specifically on Android tablets in Chrome — this was a
confirmed browser autoplay-policy issue, not a backend/API problem. A
freshly-constructed `<audio>` element created well after the page's initial
unlock gesture can be silently refused by the browser's autoplay policy even
though the page itself is otherwise "unlocked," and the older code reported
that refusal as a successful play, masking the failure and skipping the
browser-speech fallback entirely.

Both `homeschool-tutor` and `demo` now reuse a single, pre-blessed `<audio>`
element across every turn instead of constructing a new one per line
(`useTextToSpeech.ts`'s `getSharedAudioElement()`), and treat a rejected
`play()` as a genuine playback failure rather than a success — falling back
to the browser's own voice instead of staying silent. If a family reports
persistent silence after the first line despite this, confirm they're on a
current app build first; this class of autoplay restriction has historically
gotten stricter across browser versions, not looser, so a stale deployment
is the most likely cause.

## Troubleshooting: the microphone stopped working after a browser update

Browsers periodically change or break their built-in speech recognition —
a Chrome update once removed working recognition outright (the mic appears,
starts, then dies instantly with an error event). Both apps are built to
survive this without anyone doing anything: when the browser's own
recognition is unsupported, errors, or stalls, the mic automatically falls
back to recording the utterance and transcribing it server-side with the
local Whisper model (`useHybridVoiceInput` in `homeschool-tutor` and, since
this section was written, mirrored in `demo` too — `/voice/transcribe`
accepts demo sessions for exactly this reason). The fallback path is a
little slower per utterance — the child speaks, then sees a brief
"Transcribing…" moment — but voice input keeps working. If the mic seems
gone entirely, check that the deployment is on a current build; older demo
builds relied on the browser's recognition alone and had nothing to fall
back to.

## Under the hood: the local fallback-STT model (faster-whisper)

`services/transcription.py`'s server-side fallback runs on
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) (a CTranslate2
reimplementation of Whisper), not the original `openai-whisper` package —
several times faster on CPU with `int8` quantization, and it drops the
PyTorch runtime `openai-whisper` needed, for a meaningfully smaller/faster
Docker build. Same `base` model weights, same accuracy trade-off already
described above; only the inference engine changed. No `.env` setting or
deployment action is needed for this — nothing to configure, no account,
still 100% local (see docs/VENDOR_DATA_FLOW.md).

One thing that *did* need a deployment-level fix alongside the swap: the
`api` container runs `read_only: true` in production
(`docker-compose.yml`) with no writable volume outside a 64MB `/tmp`
tmpfs, so a model download attempted at container *startup* — faster-whisper's
(and previously openai-whisper's) normal first-use behavior — would fail
with nowhere to write, and `services/transcription.py`'s loader degrades
that failure silently (fallback STT just stops working, with no visible
error to a parent or child — matching the same class of silent failure
described in the troubleshooting sections above, just from a different root
cause). The Dockerfile now pre-downloads the model weights at *build* time
instead, so the running container only ever reads an already-baked file.
If you maintain a custom Dockerfile or build pipeline for this service,
make sure it keeps that pre-download `RUN` step, or the fallback STT path
will silently stop working the same way once deployed read-only.

## Troubleshooting: the mic shows "listening" but nothing reaches Bede

Reported on Safari/iOS: the mic indicator stays lit, the child speaks, and
the conversation just goes quiet — no transcript, no error, no fallback.
Root cause (fixed): the stall watchdog in `useHybridVoiceInput.ts` that
exists specifically for Safari's documented tendency to stop delivering
recognition events partway through an utterance was disarmed *permanently*
the moment a single interim result arrived, rather than reset on each one.
Safari's failure mode is stalling out mid-utterance, not just at the very
start — so a stall any time after the first flicker of interim text had no
safety net at all, and the session just sat there indefinitely. The
watchdog now re-arms on every new interim result (a rolling window, not a
one-shot disarm), so a stall at any point still falls back to recording +
server-side transcription within ~4 seconds. **Fixed in both copies of this
hook** — `homeschool-tutor/src/hooks/useHybridVoiceInput.ts` (the real
product) and `demo/src/useHybridVoiceInput.ts` (the public demo's own
mirrored copy, per this file's earlier note) — they're independent
codebases, so a fix landing in one alone leaves the other's users, and the
public demo specifically, still hitting the original bug. If you still see
this after updating, it's worth checking whether the fallback recording
itself came back empty (`transcribeFallback` in `voiceApi.ts`/`api.ts`
silently returns `''` on a failed or blank transcription, and nothing is
sent — no error surfaces to the child either) rather than the watchdog
failing to trigger at all.

## Troubleshooting: Bede's spoken narration goes silent for some turns

Reported after moving to a higher-traffic Render plan / more concurrent
capacity: individual turns lose their spoken narration with nothing visible
to the child or parent — the text still appears, Bede just doesn't say it
out loud that turn. Root cause: `services/voice_synthesis.py`'s OpenAI TTS
call had no retry at all — a single attempt, and *any* failure (a
transient rate limit, a momentary network hiccup, a brief 5xx from
OpenAI) returned `None`. That matters more here than it would look:
`useTextToSpeech.ts` (both `homeschool-tutor`'s and the demo's own copy)
deliberately does **not** fall back to the browser's own speech when
backend TTS is configured but one call fails — the design choice is to
stay silent for that line rather than audibly switch voices mid-turn. So
"configured but this one call failed" was never a soft degradation, it was
a fully silent turn. More concurrent capacity means more concurrent OpenAI
TTS calls, which means more chances to actually hit OpenAI's own rate
limits or a transient error — so scaling up made this failure mode show up
more often, even though nothing about the TTS integration itself changed.

`_synthesize_openai` now retries a rate limit or 5xx once more (2 attempts
total, 10s timeout per attempt, 0.5s backoff between) before giving up — a
non-retryable error (bad API key, malformed request) still fails
immediately rather than wasting a second attempt on something that will
never succeed. This reduces how often a transient hiccup costs a whole
turn's narration; it doesn't eliminate silent turns entirely (a sustained
OpenAI outage or a persistently exhausted rate limit will still exhaust
both attempts and go silent, by the same intentional no-fallback design
above) — check Render's server logs for `OpenAI TTS request failed after 2
attempts` to see how often that's actually still happening on your
deployment. The retry budget is deliberately tight (worst case ~20s, not
the ~90s three 30s-timeout attempts could reach) — see the next section for
why that ceiling matters even though it isn't awaited on the critical path
anymore.

## Troubleshooting: the whole chat UI freezes/spins after Bede replies

A second, distinct problem the retry fix above briefly introduced on its
own: `demo/src/App.tsx`'s `send()` used to `await speak(...)` — the TTS
call — *inside* the same block that controls `isStreaming`, so the send
button, mic, and text input all stayed disabled/spinning for however long
TTS synthesis took, including every retry attempt. Before the retry fix
this was already true but brief (a single ~30s-capped attempt); with
retries added it could compound toward ~90s in the worst case, which is
what actually surfaced this — reported as the send button spinning
indefinitely with a fully-rendered reply already on screen.
`homeschool-tutor/src/components/SocraticChat.tsx` never had this coupling
(`speak()` there was already fire-and-forget, with `isSpeaking` — a
separate state — independently gating the mic/turn-coordination effects);
the demo's own independently-maintained copy did. `speak()` in the demo is
now fire-and-forget too, and the subject-advance logic that used to
piggyback on `speak()` finishing (in `send()`'s `finally` block) moved to
its own effect that waits for both `isStreaming` and `isSpeaking` to settle
— so a subject transition still won't cut off Bede's spoken line
mid-sentence, it just no longer blocks the rest of the UI while waiting.

## Troubleshooting: the mic shows "Listening…" forever and nothing ever reaches Bede, even after waiting

A more persistent variant of the Safari/iOS stall covered above — reported
specifically as voice input never producing any interpreted text at all, not
even after the mic sits "listening" for a long time. Root cause: `useHybridVoiceInput.ts`'s
`start()` called native recognition's own `start()` and only registered the
4-second stall watchdog on the line immediately *after* that call. iOS
Safari's `SpeechRecognition` can throw synchronously out of `start()` itself
(a WebKit quirk for some already-started/permission-state edge cases)
instead of delivering the failure asynchronously as an `onerror` event. When
that happens, the watchdog registration is skipped entirely — the session's
internal mode gets stuck at `'native'` permanently, with no timer left to
ever rescue it and fall back to recording + server-side transcription. This
is different from (and not fixed by) the interim-result stall watchdog
above, since that watchdog only re-arms once it has *already* been armed at
least once — a synchronous throw at the very first `start()` call meant it
was never armed in the first place.

`start()` now wraps the call to native recognition's `start()` in a
try/catch and falls straight to the recording fallback on a synchronous
throw, rather than relying on a watchdog that would never get set up.
**Fixed in both copies** — `homeschool-tutor/src/hooks/useHybridVoiceInput.ts`
and `demo/src/useHybridVoiceInput.ts` — same independent-codebases caveat as
every other voice-pipeline fix in this file.

## Under the hood: connection reuse for OpenAI TTS and email

`services/voice_synthesis.py`'s OpenAI TTS calls (and, for the same reason,
`services/email_service.py`'s Resend calls) share one pooled `httpx.AsyncClient`
per process instead of opening a fresh one for every request. A fresh client
per call pays a full new TCP+TLS handshake to OpenAI on every line Bede
speaks, then tears the connection down immediately — reusing a pooled client
keeps a warm connection alive between calls (a real latency win) and its
`max_connections` limit doubles as a natural throttle: a request past the cap
waits for a free pooled connection instead of firing immediately, so a burst
of concurrent turns can't send an unbounded number of simultaneous requests
to OpenAI or Resend from one instance. This mirrors `services/ai_service.py`'s
existing shared Anthropic client, which already worked this way.

This cap is per-process, not fleet-wide: on a single Render instance it's a
real limit, but each horizontally-scaled instance holds its own independent
pool, so the true concurrent-request ceiling across a scaled deployment is
`instance_count × max_connections`, not `max_connections` alone. A true
cross-instance cap would need a shared store (Redis, a Postgres-backed token
bucket) this app doesn't have today.
