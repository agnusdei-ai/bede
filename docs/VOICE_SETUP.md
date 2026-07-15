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
