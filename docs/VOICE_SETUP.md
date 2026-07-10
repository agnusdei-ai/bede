# Setting up Bede's spoken voice

Bede's voice output is entirely optional. If you don't configure anything
below, the tablet's browser speaks Bede's lines using its own built-in voice.
There are two backends you can add on top of that, tried in this order:

1. **OpenAI TTS** (recommended) — a cloud API, small per-character cost,
   meaningfully more natural than Kokoro. Confirmed against real listening
   feedback that this is what it takes to get past "sounds computerized."
2. **Kokoro** — free, fully self-hosted, no cloud dependency, no per-user
   key. A good *small* (~82M-parameter) open model, but it has a real
   ceiling: it will not sound as natural as OpenAI TTS, ElevenLabs, or
   Google/Azure Neural voices, no matter how much KOKORO_VOICE/KOKORO_SPEED
   are tuned. Worth using only if avoiding all cloud cost/dependency matters
   more to you than voice quality.

## Option 1: OpenAI TTS (recommended)

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

If `OPENAI_API_KEY` is set, it's used for every voice request; Kokoro (below)
is never even loaded. Leave it unset to use Kokoro or the browser instead.

## Option 2: Kokoro (free, self-hosted fallback)

### 1. Download the model files

Get both files from the
[kokoro-onnx releases page](https://github.com/thewh1teagle/kokoro-onnx/releases)
(look for the `model-files-v1.0` release):

- `kokoro-v1.0.onnx`
- `voices-v1.0.bin`

Place both in `homeschool-api/models/kokoro/` (or wherever you set
`KOKORO_MODEL_DIR` in `.env`).

### 2. Pick Bede's voice

Kokoro ships several dozen named voices across languages and genders. Bede's
voice must stay warm, elderly, and male — never gender-ambiguous or female —
so only a handful of English male voices are worth trying at all.

Run the evaluation script once the model files are in place:

```bash
cd homeschool-api
python scripts/evaluate_bede_voice.py
```

This synthesizes the same sample line with a shortlist of candidate voices —
including a couple of *blended* voices (see below) — at three speeds each,
saves every combination as a WAV file under
`homeschool-api/scripts/voice_samples/`, and prints a rough pitch-based
ranking (lower pitch tends to read as older/deeper — a starting hint, not a
verdict). **Listen to the files yourself** — that's the actual test — then
set your pick in `.env`:

```bash
KOKORO_VOICE=bm_george   # or whichever candidate actually sounded right
KOKORO_SPEED=1.0         # Kokoro's native speed — usually the most natural
```

The full, current voice list lives in Kokoro-82M's
[VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md) if
you want to try one outside the script's shortlist.

### Blending two voices

`KOKORO_VOICE` can also be a `+`-separated blend of two or more voices'
style vectors — e.g. `bm_george+bm_lewis` (equal blend) or
`bm_george:0.7+bm_lewis:0.3` (weighted). This is a real, supported technique
(Kokoro accepts a raw style vector as well as a name) that sometimes smooths
over a single voice's rough edges — worth trying if neither George nor
Lewis alone sounds right, though it's still bounded by the same ceiling as
any other Kokoro voice.

### Speed

Kokoro's native speed is `1.0`. Slowing it down doesn't reliably make a
small model sound more "thoughtful" — it tends to stretch phonemes and make
existing artifacts more noticeable instead. Try `0.92`–`1.08` if you want
(the evaluation script generates all three by default), but don't assume
slower is better without actually listening.

### 3. Check real-time performance

Kokoro is CPU-friendly, but "friendly" isn't the same as "fast enough" on
every host — that depends on your actual hardware. Watch the time between a
response finishing and Bede's voice starting during a real session. If it's
consistently sluggish (multiple seconds of dead air), your host is probably
too weak to run this in real time — that's fine, just leave the model files
out (or delete `KOKORO_MODEL_DIR`) and the browser's own voice takes over
automatically, with no other changes needed.

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
independently.** `demo/README.md`'s "Try it now" trial path talks to
whatever `homeschool-api` host `VITE_DEMO_API_BASE` points to (a GitHub
Actions repository variable — Settings → Secrets and variables → Actions →
Variables), which may or may not be the same host as a family's private
production instance. Setting `OPENAI_API_KEY` on one does nothing for the
other. The demo's static frontend itself (GitHub Pages) needs no rebuild or
redeploy for a voice-provider change — voice selection is entirely
server-side, so only the backend host(s) need updating.
