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

`_synthesize_openai` now retries a rate limit or 5xx up to twice more (3
attempts total, ~0.5s/1s backoff) before giving up — a non-retryable error
(bad API key, malformed request) still fails immediately rather than
wasting two more attempts on something that will never succeed. This
reduces how often a transient hiccup costs a whole turn's narration; it
doesn't eliminate silent turns entirely (a sustained OpenAI outage or a
persistently exhausted rate limit will still exhaust all 3 attempts and go
silent, by the same intentional no-fallback design above) — check Render's
server logs for `OpenAI TTS request failed after 3 attempts` to see how
often that's actually still happening on your deployment.
