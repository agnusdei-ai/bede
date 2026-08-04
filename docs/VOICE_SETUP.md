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
OPENAI_TTS_INSTRUCTIONS=Speak as an elderly, warm, unhurried Southern English monk with clear, distinct diction.
OPENAI_TTS_SPEED=0.9               # 0.25-4.0, API default 1.0 — a real, hard lever on pacing (see below)
```

`gpt-4o-mini-tts`'s `instructions` field is what actually lets you steer
character and delivery in plain English — that's the real lever for sounding
like a specific persona rather than a generic preset voice, and it's the main
reason to prefer `gpt-4o-mini-tts` over the older `tts-1`/`tts-1-hd` models
(which accept a fixed voice only, no instructions). `OPENAI_TTS_SPEED` is a
separate, harder lever specifically for pace: `instructions` alone is only
ever a soft steer the model can drift from turn to turn, so when real
listening feedback asked for a more distinct, unhurried pace, the actual fix
was setting `speed` on the API call itself (slightly under `1.0`), not just
stronger wording in `instructions`. (`onyx`, a deeper preset, was tried
briefly in place of `fable`; real listening found it read as higher-pitched
and less like Bede than `fable`, not deeper as its own description implied
— a preset's on-paper description doesn't reliably predict how it actually
sounds, so if you retune this, test a real session rather than trusting the
description alone.) Then apply your own choice to your running deployment —
see "Applying this to a running deployment" below — and test in a real
session; there's no local script for this path since it's a live API call,
not a local model to benchmark offline.

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

## Voice input: server-side streaming transcription (chunked Whisper over SSE)

**As of this rewrite, browser-native `SpeechRecognition` has been removed
entirely from both apps.** Every section below that talks about "native
recognition," a "stall watchdog," `useSpeechRecognition.ts`, or a hybrid
native-with-a-recorder-fallback design is **historical** — it documents real
bugs fought and fixed across that architecture's lifetime, kept for context,
but the code it describes no longer exists. This section describes the
current design.

**Why native was removed, not just patched again:** across this file's own
history (the many "Fixed in both copies" sections below), browser-native
speech recognition was the single largest source of voice-pipeline bugs in
this app — WebKit audio-session races, native failing to even *start* within
10-30ms on some devices, an ever-more-elaborate stall watchdog trying to
paper over undocumented, per-browser, sometimes per-OS-version failure
modes that could only ever be root-caused after the fact from a live
debug-panel trace. Each fix closed one specific failure mode; none of them
addressed the underlying problem, which is that native recognition's
behavior isn't actually specified or reliable across browsers. Removing it
outright, rather than continuing to patch around it, was a deliberate
architecture decision, not an incremental fix.

**How it works now:** the mic button (`useHybridVoiceInput.ts`, identical
design in both `homeschool-tutor/src/hooks/` and `demo/src/`) always
captures raw PCM audio locally via `useVoiceRecorder.ts` — the same
recording path that used to be the *fallback*, now the only path. While a
press is held, the hook uploads a snapshot of everything captured so far
roughly every 2.5 seconds (`CHUNK_UPLOAD_INTERVAL_MS`) to
`POST /voice/stream/{id}/chunk`. `homeschool-api/services/streaming_transcription.py`
holds one in-memory session per active turn, with a single worker loop that
re-transcribes the *whole growing buffer* (not a delta — `faster-whisper` is
batch-only, with no native incremental-streaming mode) each time new audio
arrives, coalescing any upload that lands while a transcription is already
in flight rather than queueing redundant overlapping Whisper calls. Results
stream back to the client over `GET /voice/stream/{id}/events`, an SSE
endpoint following the exact same pattern `/tutor/chat` already used
(`sse_starlette.EventSourceResponse`, plain JSON lines, no native
`EventSource` — that API can't attach the `Authorization` header this
endpoint requires, so both apps consume it via `fetch()` + a manual
`ReadableStream` reader instead, same as the tutor chat stream). Releasing
the mic button pushes one final chunk and calls
`POST /voice/stream/{id}/finish`; the server transcribes the final buffer
once more, emits a `'final'` event, then `'done'` closes the stream.

**Single-process, in-memory only.** Streaming sessions live in a plain
Python dict inside the API process, not a shared store — fine for this
app's current single-instance deployment model, but a future move to
multiple horizontally-scaled API instances (or Render's autoscaling) would
need a shared backing store (e.g. Redis) for a session to survive routing to
a different instance mid-turn. Abandoned/orphaned sessions (a browser tab
closed mid-hold, a dropped connection) are swept after 180 seconds of no
activity, so nothing leaks indefinitely.

**Known gap: no real end-of-speech detection.** Hold-to-talk
(`startHold`/`release`) is unaffected by this — the child's own release()
already marks the end of a turn explicitly, exactly as before. But
`start()` (tap mode) is only ever called by each app's opt-in, off-by-default
**continuous "Voice on" mode** (see that feature's own section further
below), which used to rely entirely on native recognition's own autonomous
endpointing to decide a turn was over and fire `onFinal` on its own — there
was never an explicit `release()` call on that path. With native gone,
`start()` now behaves exactly like `startHold()` and needs an explicit end
signal the same way; continuous mode's call site still doesn't provide one,
so as of this rewrite a continuous-mode turn runs for the full
`HOLD_SAFETY_TIMEOUT_MS` ceiling (120 seconds) before auto-finishing,
instead of ending snappily the moment the child actually stops talking.
This is a real, known regression for that one opt-in feature specifically —
not something this rewrite silently papered over — and needs real
client-side silence/voice-activity detection as a follow-up before
continuous mode is genuinely usable again. Hold-to-talk (the default for
every family) is fully unaffected.

## Troubleshooting: the mic works at first, then every attempt fails with "something's wrong with the microphone"

Reported live on the public demo shortly after the server-side-streaming
rewrite above shipped, confirmed via two debug-panel traces roughly a
minute apart: the first several mic presses in a session worked normally
(`_start()` → `useVoiceRecorder.startRecording()` → `release()` →
`useVoiceRecorder.stopRecording()`, clean), then every subsequent press
failed instantly with `startVoiceStream failed: Could not start voice
streaming` — never even reaching `useVoiceRecorder.startRecording()` — and
the child saw `chat.micUnavailable` ("I can't hear you right now —
something's wrong with the microphone") on every attempt from then on, for
the rest of the session.

Root cause: `POST /voice/stream/start` returning `!res.ok` is exactly what
`startVoiceStream()` (`api.ts`) turns into that error message — and
`core/middleware.py`'s `RateLimitMiddleware` treats *any* path containing
`/voice/` as one shared bucket, capped at `rate_limit_voice_per_minute`
(20/minute per IP by default). That limit was sized for the old
architecture, where **one voice utterance cost exactly one request**
(`POST /voice/transcribe`). The streaming rewrite costs far more per
utterance against the same unchanged budget:

- `POST /voice/stream/start` — 1
- `GET /voice/stream/{id}/events` — 1
- at least one `POST /voice/stream/{id}/chunk` (`release()` always pushes a
  final snapshot even for a very short hold; longer holds add one more per
  `CHUNK_UPLOAD_INTERVAL_MS`, 2.5s)
- `POST /voice/stream/{id}/finish` — 1

That's a **minimum of four requests per single tap**, even an accidental
brief one — against a budget that used to allow 20 entire utterances per
minute. As few as five taps in one minute (completely ordinary behavior —
a child re-pressing after nothing seemed to happen, exactly what both
traces showed) now exhausts the whole bucket, and every mic press for the
rest of that 60-second window gets a 429 back immediately, surfaced as a
hardware-sounding error that has nothing to do with the actual microphone.

Fix: `POST /voice/stream/start` (the real "new attempt" signal — matching
the old architecture's one-request-per-utterance semantics) stays in the
stricter `voice` bucket unchanged. `POST /voice/stream/{id}/chunk`,
`POST /voice/stream/{id}/finish`, and `GET /voice/stream/{id}/events` — the
bounded, mechanical follow-up calls of a session that already passed that
check — now share a separate, more generous `voice_stream_session` bucket
(`rate_limit_voice_stream_session_per_minute`, 120/minute by default)
instead. A single approved hold can only ever generate a handful of these
(capped by the upload interval and `HOLD_SAFETY_TIMEOUT_MS`), so they were
never the right thing to gate against new-attempt abuse in the first
place — counting them there just punished ordinary multi-turn
conversation. See `core/middleware.py`'s `RateLimitMiddleware.dispatch()`
and `tests/test_middleware.py`'s `test_voice_stream_session_mechanics_do_not_share_the_new_session_bucket`
(verified via the standard break-then-restore discipline: reverted the
fix, confirmed the new tests actually fail, restored it).

If a family reports this again after updating, check whether the
`voice_stream_session` bucket itself is now the one being hit (a single
IP running an unusually large number of simultaneous or extremely long
holds) rather than `voice` — the fix separates the two failure modes, it
doesn't make rate limiting disappear entirely.

## Troubleshooting: the mic keeps saying "something's wrong with the microphone" every single press, with a `startVoiceStream failed: Load failed` line in the debug panel

Different failure from the rate-limit one just above — same surfaced error
message, different root cause and different fix. Reported live via a
debug-panel trace: `startVoiceStream failed: Load failed` on nearly every
single hold attempt in a row, each one failing within roughly 100ms of the
press — far too fast to be a real round trip to the server that actually
got a response. `"Load failed"` (Safari/WebKit's own wording for a failed
`fetch()`; Chrome's equivalent is `"Failed to fetch"`) means the request
never got a response at all — a dropped connection, a brief Wi-Fi/cellular
blip, a momentary DNS hiccup — not the server rejecting it (that would
instead read `startVoiceStream failed: Could not start voice streaming`,
the message the code throws for a real non-2xx response, as in the section
above).

Before this fix, `_start()`'s `startVoiceStream()` call had **no retry at
all** — a single transient network failure gave up on the entire turn
immediately (`clearHoldSafety()`, `setMode('idle')`,
`setMicError('unavailable')`), with no native-SpeechRecognition fallback
left to fall back to (see this doc's own history on why that path was
removed entirely). On a real tablet over real household Wi-Fi, a brief
connection blip is common enough that this made voice input feel
unreliable well beyond what the underlying connection quality actually
warranted — especially noticeable as "every attempt fails" during a run of
bad connectivity, since nothing about the failure was self-healing.

Fix: `useHybridVoiceInput.ts`'s `_start()` (both `homeschool-tutor` and the
demo — the two files are kept as intentional mirrors of each other) now
retries `startVoiceStream()` once, after a short `START_STREAM_RETRY_DELAY_MS`
(500ms) delay, before surfacing an error at all (`network` now rather than
`unavailable` — see the follow-up section below) — the same "one quick retry
before giving up" reasoning `services/voice_synthesis.py`'s OpenAI TTS call
already applies on the backend side for the identical class of transient
failure. `pushVoiceStreamChunk`/`finishVoiceStream` deliberately keep their
existing no-retry, throw-and-let-the-caller-decide contract unchanged — a
single dropped chunk mid-turn is already tolerated (the next chunk a few
seconds later carries the whole growing buffer anyway); only the turn's
*first* request, whose failure is otherwise unrecoverable, gets a retry.

If a family reports this again after updating, and the debug panel still
shows two failed `startVoiceStream` attempts in a row for the same hold
(not just one), that's a real, sustained connectivity problem on that
device/network, not something a client-side retry can paper over — check
whether the server itself is reachable at all from that device.

## Troubleshooting: after a run of `Load failed`, the mic button stops doing anything at all — and the phone still shows the recording indicator

The follow-up to the section above, from a second real debug-panel trace on
the public demo. The connection blip itself was genuine and the retry above
worked as designed, but the trace showed three separate problems the moment
the retry was exhausted — and the third is why "the connection dropped for
20 seconds" turned into "voice input is dead for the rest of the lesson."

The tell, in the trace itself:

```
[225067ms] _start() attempt=7
[225068ms] useVoiceRecorder.startRecording()
[225152ms] startVoiceStream failed: Load failed (attemptsLeft=1)
[225841ms] startVoiceStream failed: Load failed (attemptsLeft=0)
[235865ms] _start() attempt=8            ← no startRecording() line
[243038ms] _start() attempt=9            ← no startRecording() line
[246383ms] _start() attempt=10           ← no startRecording() line
```

Attempt 7 logged `useVoiceRecorder.startRecording()`; attempts 8, 9 and 10
did not. Every press after the first failure was reaching `_start()` and
then never reaching the recorder at all.

**1. The give-up path never handed the microphone back.** `_start()` starts
the recorder immediately (the audio has to be captured from the instant of
the press) and opens the streaming session over the network afterwards.
When that session could not be opened, `_start()` cleared its timers and
set the mode to `idle` — but never called `recorder.stopRecording()`. The
microphone stayed live, capturing into a buffer for a turn that had already
been abandoned. On iOS that is visible: the orange recording dot stays lit
over an app whose mic button looks idle. The `!token` branch had the same
omission. Both now stop the recorder.

**2. That orphaned recording then blocked every later press.**
`useVoiceRecorder.startRecording()` refuses to start a second recording
while one is already running — correct in itself, and exactly what made the
first problem permanent instead of momentary. With a recording nobody would
ever stop, the guard rejected every subsequent press silently: the child
held the button, spoke, released, and nothing whatsoever happened. That is
the missing `startRecording()` line in the trace above.

The same guard had a second way in, independent of any network failure.
`startRecording()` is asynchronous — it awaits `getUserMedia()` — so a
short hold can reach `stopRecording()` while the microphone is still
opening. `stopRecording()` then found every ref still null and took its
early return, and the pending `getUserMedia()` resolved a moment later and
built a live audio graph with nothing left that could stop it: the same
orphaned-recording state, arrived at from an ordinary quick tap on a slow
connection. `useVoiceRecorder.ts` now carries a generation counter that
`stopRecording()` bumps and `startRecording()` re-checks after the await,
so a stream granted after its turn ended is handed straight back instead of
being wired up. Its "am I already recording" guard also reads a ref set
synchronously at the top of `startRecording()` rather than the React
`isRecording` state, which only flips true once the graph is live — the
state could not cover the window where the problem actually happened, and
a state update that never landed used to latch the button off for good.

**3. The message blamed the microphone for a network problem.** All of the
above surfaced as *"I can't hear you right now — something's wrong with the
microphone"*, which sends a family off checking browser permissions for a
microphone that was working perfectly. `MicError` now has a `network`
value, chosen when the rejection came from the transport layer rather than
from a server (`fetch()` rejects with a `TypeError` for every transport
failure — `"Load failed"` on Safari, `"Failed to fetch"` on Chrome,
`"NetworkError…"` on Firefox), and it reads *"we lost the connection for a
moment. Try holding the mic again, or type your answer instead."* A real
non-2xx response from the server still reports `unavailable` as before.
Both strings are localized in `en.json` and `es.json` for both apps.

**Also fixed alongside: the same warning stacking up.** Whatever is wrong
with the mic is usually still wrong on the next press, so each attempt
appended another identical warning to the conversation — the reported
screenshot showed the lesson buried under repeats of the same bubble.
`SocraticChat.tsx` and the demo's `App.tsx` now skip an error that is
already the most recent thing on screen. Only an *immediate* repeat is
suppressed: once Bede or the child has said anything since, the same
warning is new information again rather than a duplicate.

All of it is mirrored across `homeschool-tutor` and `demo` (the voice hooks
are intentional mirrors of each other), and pinned by tests in
`useVoiceRecorder.test.ts` and `useHybridVoiceInput.test.ts` in both apps —
including that the recorder is stopped on both give-up paths, that a stream
granted after the turn ended is released rather than wired up, and that the
next press after either failure genuinely reopens the microphone.

**And the cause underneath all of it, on the public demo: the backend was
being OOM-killed.** Everything above makes the client recover honestly from
a backend that vanishes mid-lesson. It does not stop the backend vanishing.
On `bede-demo-api` it was vanishing on a schedule, and the thing consuming
the memory was the voice stack itself — `faster-whisper`'s `ctranslate2`
backend imports torch (~480MB of RSS on import alone), putting the process
at 642MB warmed against Render's 512MB free-tier cap. Because
`services/streaming_transcription.py` keeps its sessions in memory in a
single process, every one of those restarts destroyed every in-flight
child's voice turn, which reaches the tablet as exactly the `Load failed`
run above.

That is why the same symptom kept coming back with a different explanation
each time: two independent causes were producing one message, and the
message blamed the microphone for both. The memory half is fixed by
`TRANSCRIPTION_PROVIDER=openai` on that deployment — see the section below.

## Where speech-to-text actually runs (`TRANSCRIPTION_PROVIDER`)

`core/config.py`'s `transcription_provider` selects the backend behind
`services/transcription.py`'s single `transcribe_audio()`:

- **`local` (the default).** `faster-whisper` runs in the API process. This
  is the right setting for a family, and it is not a performance
  preference: the premise of self-hosting Bede is that a child's voice
  never leaves the house. Every `WHISPER_*` knob applies only here. A
  deployment that never touches this setting behaves exactly as it always
  has.
- **`openai`.** The recorded audio is POSTed to
  `https://api.openai.com/v1/audio/transcriptions`
  (`OPENAI_TRANSCRIPTION_MODEL`, default `gpt-4o-mini-transcribe`), and
  **nothing imports `faster_whisper` at all** — which is the entire point.
  The saving is the import that does not happen, not the inference that
  gets moved, so both `main.py`'s warm-up and `preload()` check before
  touching the model rather than relying on one of them.

The public demo runs on `openai` (`render.yaml`) for the memory reason
above: it already sends the whole conversation to OpenAI's chat models and
already uses OpenAI for TTS, so local transcription there was paying 480MB
for a privacy property that deployment does not claim. **Turning this on is
a disclosure change** wherever a deployment publishes one — the demo's
Privacy Notice (both languages), `docs/RETENTION_POLICY.md`,
`docs/INFORMATION_SECURITY_POLICY.md` §5 and `docs/VENDOR_DATA_FLOW.md`
were all updated in the same change.

Misconfiguration fails at boot rather than at the first child who presses
the mic: an unrecognized value, or `openai` with no `OPENAI_API_KEY`, both
raise from `core/config.py`. There is deliberately no silent fallback to
the local model on the `openai` setting, since falling back would
reintroduce the import the setting exists to avoid.

Two things this does NOT change on a local deployment: the concurrency
semaphore (`VOICE_TRANSCRIPTION_MAX_CONCURRENCY`) still serializes local
inference, which the OpenAI path does not need because an HTTP request
isn't competing for the same CPU cores; and voice biometric child
authentication (`services/voice_auth.py`) is untouched by this setting
entirely — it is a different model, on a different path, and it is
parent-only.

### One thing the `openai` backend deliberately gives up: live partials

`services/streaming_transcription.py` re-transcribes the **whole growing
buffer** on every pass, because nothing here has an incremental mode. On
`local` that is CPU we already own and are not otherwise using mid-hold, so
a discarded preview is close to free and is capped by duration
(`VOICE_PARTIAL_MAX_SECONDS`) rather than forbidden.

Against a metered API the same behaviour is a real, recurring cost: at the
client's 4-second chunk cadence a 20-second answer would become roughly
**five billed requests, each re-uploading everything captured so far**, and
four of the five are discarded the moment the final pass lands. So on any
non-local backend the worker skips partial passes entirely
(`services/transcription.py`'s `partial_passes_are_affordable()`).

What the child loses is the live word-by-word settle while they are still
talking — they still see "Transcribing…" and then their words, which is
already exactly what happens on any hold shorter than one chunk interval.
**The final pass is never skipped on either backend**, so what actually
reaches Bede is identical; only the preview differs. Both halves are pinned
by `tests/test_transcription_provider.py`, including that partials still
run on `local` — so this cost fix can't quietly become a downgrade for
self-hosted families.

## Troubleshooting: "Transcribing…" sits for a while after releasing the mic

Reported on the public demo, same debug-panel-trace session as the
rate-limit issue above: a hold (~7.4s, `_start()` attempt 14) released
cleanly (`useVoiceRecorder.stopRecording()` logged right on release), but
the "Transcribing…" spinner then sat for a noticeably long time before the
final text ever arrived.

This is unambiguously a server-side delay, not a client bug: once
`release()` fires, the client is doing nothing but waiting on the SSE
stream's `'final'`+`'done'` events (`consumeEvents()` in
`useHybridVoiceInput.ts`) — there is no client-side logic left to go wrong
at that point.

**What's architecturally true regardless of hardware**, from
`services/streaming_transcription.py`'s own design: every transcription
pass re-transcribes the *whole* growing buffer, not just the newest audio
(faster-whisper has no incremental-streaming mode — see that file's
docstring), and the per-session worker processes exactly one pass at a
time (deliberate — it's what coalesces rapid chunk uploads instead of
queueing redundant overlapping Whisper calls). Two consequences follow
directly from that:

1. **Total CPU-seconds per hold scales faster than the hold's own
   length.** A 10-second hold with partial passes at 2.5s/5s/7.5s plus a
   final pass at release doesn't transcribe 10 seconds of audio once — it
   transcribes roughly 2.5+5+7.5+10 = 25 "seconds of audio" worth of
   Whisper calls, all serialized. Shortening the chunk-upload interval (to
   feel more "live") directly increases this multiplier.
2. **The final pass can get stuck behind an in-flight partial pass the
   coalescing design has no way to cancel.** If `finish()` arrives while a
   partial pass (over slightly-stale audio) is still running, the final
   pass — the one thing the child is actually waiting on — can't start
   until that in-flight pass completes, even though its result is about to
   be superseded.

**What's NOT yet confirmed**: the exact magnitude of the delay, and
whether it's dominated by (1) the final pass's own inherent cost
(proportional to total hold length, on whatever CPU tier the deployment
runs — the public demo's Render instance in particular), (2) the
in-flight-partial-blocking case above, or (3) contention from *multiple
concurrent visitors'* voice sessions on a shared host, each pass competing
for the same limited CPU. This sandbox has no access to the deployed
instance's real CPU tier or live request concurrency, so this could not be
measured directly — only reasoned about from the architecture.

**What shipped initially**: two changes, one diagnostic and one mitigation
— see below for the follow-up fix once the diagnostic actually caught the
root cause live.

1. **A per-pass timing log** (`streaming_transcription.py`'s worker loop) —
   `streaming_transcription: session=<id> pass=partial|final
   audio_bytes=<n> elapsed=<seconds>` on every single transcription call.
   This is the one number that was missing to actually distinguish the
   three candidate causes above next time this is reported — check
   Render's server logs for it.
2. **`CHUNK_UPLOAD_INTERVAL_MS` raised from 2500ms to 4000ms** (both
   copies of `useHybridVoiceInput.ts`) — a real, provable reduction in
   total wasted CPU work per hold (fewer partial passes means less audio
   re-transcribed overall, and less chance a partial pass is still running
   when release() arrives), at the minor cost of live partial text
   updating somewhat less often during a long hold. This directly helps
   failure mode (2) above and reduces the *frequency* component of (1).

**Confirmed via a live client trace** (repeated hold-to-talk presses spaced
1-2s apart, iOS/mobile Chrome — note: Chrome on iOS runs on the same
WebKit engine Safari does, Apple requires it of every iOS browser, so this
isn't a Chrome-vs-Safari difference): candidate cause (3) above, contention
between concurrent transcription passes, not (1) or (2) alone. Each fresh
mic press opens its own `streaming_transcription.py` session with its own
worker task; a quick press/release/press sequence left more than one
session's worker mid-`transcribe_audio()` call at the same time, with
nothing serializing them. `faster-whisper`'s CTranslate2 backend is itself
internally multi-threaded per call, so concurrent passes don't parallelize —
they fight each other for the same CPU cores and all slow down together.
The trace showed exactly this signature: successive turns in the *same*
session taking 6.9s, then 33.3s, then producing a garbled transcript after
~28s, then never resolving at all — a runaway pile-up, not a fixed
per-utterance cost, and one bad enough that the garbled pass actually
mis-transcribed the audio (not just slowly).

**What shipped**: `services/transcription.py`'s `transcribe_audio()` now
serializes actual inference through an `asyncio.Semaphore` sized by
`settings.voice_transcription_max_concurrency` (default 1 — `VOICE_TRANSCRIPTION_MAX_CONCURRENCY`
env var). Overlapping callers now queue for their turn instead of running
concurrently and thrashing CPU — this caps candidate cause (3) directly,
whether the overlap comes from one family's rapid re-presses or several
tablets' turns landing close together on a shared host. A deployment with
real CPU headroom can raise the setting to let genuinely-concurrent turns
overlap instead of always serializing to one. This does **not** reduce the
inherent per-pass cost on a slow/shared CPU tier — a queued pass still
takes as long as it always would — it only stops that cost from compounding
across overlapping passes. See `tests/test_transcription.py` for the
regression coverage (proves passes are actually serialized, and that the
concurrency cap is configurable, not hardcoded).

## Troubleshooting (historical): the microphone stopped working after a browser update

The section below predates the server-side-streaming rewrite above and
describes the now-removed native/fallback hybrid design. Kept for
historical context only — with native `SpeechRecognition` gone entirely,
there is no longer a "browser broke recognition" failure mode to fall back
from in the first place.

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
PyTorch runtime `openai-whisper` needed, for the transcription path itself.
Same `base` model weights, same accuracy trade-off already described above;
only the inference engine changed. No `.env` setting or deployment action
is needed for this — nothing to configure, no account, still 100% local
(see docs/VENDOR_DATA_FLOW.md).

That "drops PyTorch" framing only holds for transcription specifically —
`services/voice_auth.py`'s speaker-verification library (`resemblyzer`) has
its own, separate hard dependency on `torch`, so the `api` image ends up
with PyTorch installed regardless of faster-whisper's own choice not to
need it. What faster-whisper's swap DOES still make possible: the
Dockerfile installs torch from PyTorch's CPU-only wheel index specifically
*because* nothing in this image ever uses a GPU — without that one line,
pip would resolve resemblyzer's `torch` requirement from the default index
instead, which serves the full CUDA-bundled build (measured directly:
526.6MB, versus the CPU-only build's well-documented roughly one-third of
that) into a container that will never touch a GPU. See the Dockerfile's
own comment for the mechanism (installing torch first so the later
`requirements.txt` install sees it as already satisfied).

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

### Running on low-power hosts (Raspberry Pi, ARM, small NAS)

`docs/PARENT_SETUP.md` lists a Raspberry Pi as a legitimate server machine,
and it is — but transcription is the one part of a lesson that is genuinely
CPU-bound *on your own server*, so it's worth knowing what that means before
choosing hardware.

Everything else in a tutoring turn is either a network call to whichever AI
provider you configured or a fast database write. Speech-to-text is the
exception: `faster-whisper` inference runs locally on the host CPU, always.
There is deliberately **no cloud speech-to-text option** in Bede — the child's
audio never leaves the house — so this work cannot be offloaded the way the
tutoring model can. (`OPENAI_API_KEY` buys cloud **TTS**, Bede's spoken output;
it does nothing for microphone input.)

Practical consequences on a Pi-class host:

- **Expect meaningfully longer per-turn transcription** than on a modern
  x86 desktop. The `base` model at `int8` is already the fast end of the
  accuracy/speed trade-off (see above); dropping to `tiny` was tried and
  produced noticeably worse transcripts on real sentences, so that isn't a
  recommended lever.
- **Leave `VOICE_TRANSCRIPTION_MAX_CONCURRENCY` at its default of 1.** That
  setting exists precisely because overlapping Whisper passes contend for the
  same cores rather than parallelizing (see the transcription-delay section
  above) — the failure it prevents is *worse*, not milder, on fewer/slower
  cores. Raising it is only appropriate on a host with real CPU headroom.
- **Typing remains a first-class input path.** A child who doesn't want to wait
  can always type; nothing about the lesson depends on the mic.

This has not been benchmarked against a physical Pi in this repo — the guidance
above follows from the architecture (batch-only local inference, one pass at a
time per session) rather than from a measured figure. If you run Bede on a Pi,
the per-pass `elapsed=` log described in the transcription-delay section above
is the number that tells you what your hardware actually does.

Encryption, by contrast, is **not** a concern on this hardware. Per-request
`encrypt`/`decrypt` is plain AES-256-GCM over small payloads. The one
deliberately expensive step is `core/encryption.py`'s PBKDF2-HMAC-SHA256 KEK
derivation (600k iterations, ~0.3–1.5s depending on hardware), and it runs
**once at startup**, off the event loop, never per request — see that module's
`_derive_kek` docstring, which already treats the Pi as the low-power target
it optimized the PRF loop for.

## Troubleshooting (historical): the mic shows "listening" but nothing reaches Bede

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

## Troubleshooting: voice input uploads a lot of data, or "Transcribing…" hangs on a slow connection

**Symptom.** Long answers take a very long time to transcribe, worst on a slow
home connection. Mobile data usage looks far higher than the length of the
recordings would suggest.

**Cause (fixed).** The chunk-upload loop re-sent **everything captured so far**
on every tick, and the server replaced its buffer each time, so the client had
no choice. That is O(N²) upload over a hold:

| Hold | Uploads | Audio actually sent | Bytes | Waste |
|---|---|---|---|---|
| 20s | 6 | 80s | 2.6 MB | 4.0× |
| 40s | 11 | 260s | 8.3 MB | 6.5× |
| 120s (safety cap) | 31 | 1980s | 63 MB | 16.5× |

Home connections upload far slower than they download, so a 40-second answer
could spend over a minute uploading on a 1 Mbps uplink. Raising
`CHUNK_UPLOAD_INTERVAL_MS` from 2.5s to 4s (see the transcription-delay
section above) reduced the number of uploads but left the quadratic growth.

**Now:** the client sends only what it captured since its last upload
(`useVoiceRecorder.ts`'s `snapshotPcmDelta`), as raw 16kHz mono int16 PCM with
no container, and the server appends it (`streaming_transcription.py`'s
`push_chunk`), wrapping the accumulated buffer in a WAV header when it
transcribes. **Upload bandwidth** goes from O(N²) to O(N).

Server decode cost does *not* — every pass still re-transcribes the whole
buffer, because faster-whisper has no incremental mode. That is a separate
problem, addressed by `VOICE_PARTIAL_MAX_SECONDS` below.

Two details worth knowing if you touch this path:

- **The protocol is sniffed, not flagged.** `push_chunk` treats a payload
  starting with `RIFF` as the old whole-buffer upload and replaces; anything
  else is a PCM delta and appends. An older client therefore keeps working
  against a newer server with no version negotiation.
- **A dropped chunk is retried.** The old protocol got this for free — any
  failed upload was covered by the next one. Deltas do not, so a failed chunk
  is held and prepended to the following upload
  (`useHybridVoiceInput.ts`'s `pendingPartsRef`). One network blip never costs
  the child a word.

## Troubleshooting: everything feels slow and inconsistent on the public demo specifically

**Symptom.** Bede takes several seconds to start speaking, or voice-stream
session-open times vary wildly between two attempts seconds apart (seen in a
real trace: 225ms, then 1445ms for the next hold). Both symptoms in the same
session, with no obvious pattern.

**Likely cause.** `render.yaml` runs `bede-demo-api` on Render's **free**
plan — a single shared, CPU-constrained instance that sleeps after idle and
cold-starts on the next request. A chat turn's LLM stream, its TTS
synthesis, and a voice-input transcription pass can all be competing for the
same tiny CPU at once. This is a hosting-tier property, not a bug in the
voice pipeline itself, and it will not reproduce on a self-hosted deployment
running on real hardware.

If this is affecting real usage rather than occasional testing, moving
`bede-demo-api` off the free plan is the fix — a `render.yaml`/billing
change, not a code change.

A ~10-second delay specifically, on what feels like an early interaction in
a session, is consistent with an additional contributor stacking on top of
the above: `services/transcription.py`'s faster-whisper model is **lazy**
— `_get_model()` loads it (deserializing the "base" model's weights into
memory, real work even though they're pre-baked into the image at build
time rather than downloaded) on the first call that actually needs it.
`main.py`'s `_warm_voice_models()` tries to pre-empt this at startup, but it
is a fire-and-forget background task (`asyncio.create_task`, deliberately
non-blocking so it doesn't delay the server's own readiness) — on a
free-tier instance that just woke from sleep, the first REAL transcription
request can still land before that warm-up finishes, paying the model-load
cost inline instead of finding it already done. Confirmed from the code;
not confirmed as the actual cause of any one specific report, since nothing
here currently logs whether warm-up had completed by the time a given
request arrived.

**Ruled out, not assumed:** the diagnostic below distinguishes this from an
actual capture-side bug. If a hold produces "voice stream produced nothing"
with `~0ms` of audio captured, that is NOT this — see below. And as of this
change, a *successful* transcription now logs its own release-to-delivery
time too (`voice stream delivered "..." — Nms after release (Nms total
hold)`) — previously only the empty-result path had any timing signal at
all, so a slow-but-successful transcription was invisible in the debug
panel. That log is what actually confirms or rules out everything in this
section for a specific report, rather than each of us reasoning about it
from the architecture alone.

## Troubleshooting: transcription is slow, especially in Spanish

Three levers, in the order worth trying.

> **If you tried these before August 2026 and nothing changed, that was
> not your imagination.** `docker-compose.yml` passes environment
> variables to the API container by naming them one at a time, and none
> of the three below was on that list, so setting them in `.env` had no
> effect at all under the packaged Docker deployment. Nothing failed
> visibly: the container simply used the built-in default and ran. They
> are wired now, and `tests/test_compose_settings_passthrough.py` fails
> if any documented setting goes missing from that list again. Changes
> here need `make update` (a rebuild), not just a restart.

**1. `WHISPER_BEAM_SIZE` (default `1`).** faster-whisper's own default is `5`,
i.e. beam search, which is several times slower than greedy decoding. This
project now defaults to `1`. For short, single-language child utterances where
the language is already known, greedy gives up very little. Raise it only if
*accuracy* is the complaint and latency is not.

**2. `WHISPER_MODEL_SIZE` (default `base`).** This lever cuts both ways, so be
clear which problem you have:

| Problem | Direction |
|---|---|
| Transcription is **slow** | Go **down**: `tiny` is roughly 2-3× faster than `base` |
| Transcription is **wrong** | Go **up**: `small` is materially more accurate, at ~3× the compute |

Spanish is genuinely harder for the smaller models, so a Spanish deployment
can find itself wanting accuracy *and* speed. If so, the honest answer is
hardware, not configuration — Whisper on a CPU is the constraint.

**3. `WHISPER_VAD_FILTER` (default `false`).** Skips silence instead of
decoding it, a real saving on a hold full of pauses. Off by default on
purpose: VAD can clip a child who answers quietly, and losing a word is worse
than waiting for one. Turn it on only after hearing it work on your own
hardware, with your own children.

### Why long answers get disproportionately slow

faster-whisper has no incremental mode, so **every pass re-transcribes the
whole buffer from the start**. Across a hold that is O(N²) decode work — a
40-second answer costs roughly 220 seconds of audio decoded, spread over ten
passes.

`VOICE_PARTIAL_MAX_SECONDS` (default `25`) caps that: past this much audio,
live partial transcripts stop being computed and the buffer rides to the
final pass. A partial computed over 60 seconds of audio is expensive *and*
stale by the time it lands, so it was never worth much. **The final pass is
never skipped** — what actually reaches Bede does not depend on this setting.
Set it to `0` to always compute partials.

Note this is a different problem from the upload-bandwidth one above, and the
delta-upload change did not fix it. That change made the *network* cost linear;
this one is *decode* cost, and it is capped rather than eliminated.

The cap applies regardless of which upload protocol a client is speaking — the
current delta protocol above, or the legacy whole-buffer one a stale browser
tab might still be running mid-deploy (`streaming_transcription.py`'s
`push_chunk` supports both — see that module's own docstring). An earlier
version of this cap computed buffered-audio duration from the delta
protocol's own buffer only, so a legacy-protocol client silently never hit
it and kept paying the full O(N²) decode cost for the whole hold; fixed to
derive the duration from whichever protocol the session is actually using.

## Troubleshooting: Bede is slow to start speaking, especially in Spanish or on a slow connection

**Symptom.** A noticeable gap between the child finishing their turn and Bede
starting to speak. Worse on a slow home connection, and worse again in a
Spanish session than an English one.

**Cause (fixed).** `/tutor/speak` used to return **uncompressed WAV**. At
OpenAI TTS's 24kHz 16-bit mono that is **48KB for every second of speech**, so
a 30-second line ran to roughly 1.4MB. The whole utterance is synthesized
server-side, buffered, and only then sent as one response body, so all of
those bytes sit squarely between the child asking and hearing anything:

| Format | 30s of speech | Time to arrive on a 1.5 Mbps link |
|---|---|---|
| WAV (old) | ~1.4 MB | ~7.7s |
| MP3 (tried, then replaced — see below) | ~240 KB | ~1.3s |
| **AAC (now)** | roughly similar to MP3 | roughly similar to MP3 |

Spanish suffered most, and predictably so: Spanish runs roughly 15-25% longer
than English for the same content, so the same lesson produces proportionally
more audio seconds and therefore proportionally more bytes.

**MP3 was the first fix, and it introduced a real regression of its own.**
Reported back from actual use as sounding "like a lisp," with "a residual
echo." That is close to a textbook description of MP3's own well-known
pre-echo artifact — its transform coding spreads quantization noise
backward in time around a sharp transient, and sibilants/consonants (s, sh,
f, t — exactly what "lisp" calls out) are the sharpest, most transient-heavy
content in speech. Bede's own voice (slow, measured, softly spoken, per
`openai_tts_instructions`) is close to a worst case for this specific
artifact: lots of soft consonants with quiet space around them for the
smearing to be audible in.

`services/voice_synthesis.py` now requests `AUDIO_FORMAT = "aac"` and
`routers/tutor.py` serves it as `AUDIO_MEDIA_TYPE = "audio/aac"`. AAC uses
temporal noise shaping specifically to control pre-echo, so it should not
reproduce the same artifact at a similar bitrate, while keeping most of
MP3's size win over WAV — and it's Apple's own preferred codec, reinforcing
rather than fighting the tablet-first reasoning that already ruled out Opus
below. Both frontends read the response with `res.blob()` and hand it to
`createObjectURL`, so the blob inherits whatever Content-Type `/speak` sets
and no client change was needed either time — but the two constants must
agree, which is why the media type is derived from the same module rather
than restated.

**Not verified by ear.** Same caveat as the MP3 change it replaces — this is
reasoned from how these codecs actually work, not confirmed against a real
recording. If a lisp/echo report recurs against AAC, that argues against
codec choice as the explanation entirely: two different lossy codecs
producing the same complaint would point at the separate, still-open
overlapping-playback investigation below ("Diagnosing a reported speech
echo") rather than a third codec swap.

AAC rather than Opus (which would be smaller still, ~16x, and also avoids
MP3's pre-echo behavior): Safari/iOS support for Opus in `<audio>` is patchy
and this is a tablet-first product, so it's not the first thing to reach for.

**This does not change Bede's speaking pace.** Pacing is
`settings.openai_tts_speed` (0.9) plus `openai_tts_instructions`, both
untouched. Compression changes the bytes on the wire, never the delivery —
pinned by `tests/test_voice_synthesis.py`'s
`test_pacing_is_untouched_by_the_format_change`.

**Still outstanding.** Synthesis itself is not streamed: `/speak` waits for
the complete audio before sending the first byte. Streaming OpenAI's chunked
response through FastAPI would remove the other half of the delay, and is a
separate change.

## Troubleshooting: in a Spanish session, Bede's fallback voice reads Spanish with an English accent

**Symptom.** With backend TTS unconfigured (or on a deployment relying on the
browser's own `speechSynthesis`), a Spanish session reads Spanish text in an
audibly English voice.

**Cause (fixed).** `pickBestVoice()` in both frontends filtered exclusively on
`v.lang.startsWith('en')` at every priority level, so a Spanish session could
only ever be handed an English voice. It now takes a language prefix, derived
from the session's own locale (`i18n.language`) rather than the device's —
the same rule the speech-recognition language already follows.

- Spanish sessions prefer a known Spanish male voice (`Jorge`, `Diego`,
  `Microsoft Pablo`, …), then any Spanish voice that is not explicitly female,
  then any Spanish voice.
- If **no** Spanish voice exists on the device, `pickBestVoice` returns `null`
  rather than falling through to an English one — a wrong-language voice is
  worse than none. `utterance.lang` is always set (`es-MX`), so the engine
  picks something appropriate itself.
- English behaviour is deliberately unchanged, including its long-standing
  last-resort "any voice at all" fallback.

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

## Troubleshooting: Bede's spoken voice briefly switches to the browser's default voice mid-conversation

Reported during beta testing: Bede's narration is audibly the backend's
OpenAI TTS voice for most of a session, then for one turn sounds like the
browser's own built-in speech synthesis instead (on Chrome, often its
"Google US English" default) before reverting back. Distinct from the
"goes silent" failure above — that one is a backend TTS call failing
outright, which `useTextToSpeech.ts` (both copies) deliberately treats as
silence rather than a voice switch (see that section). A voice switch
specifically means the backend call *succeeded* — real audio bytes came
back — but this browser's `audio.play()` refused to actually play them for
that one call.

**This used to fall back to the browser voice on purpose** ("browser
speech is better than total silence"). A later real report showed why
that reasoning didn't hold up in practice: a family on a browser that kept
blocking `audio.play()` (see the autoplay-block section below) got the
jarring, robotic browser default voice on *every single turn* for the
whole session, not just an occasional one — worse, by far, than staying
silent for the handful of lines actually affected. **Bede's voice now has
no fallback to the browser's default voice for this case at all** — real
audio that was fetched but blocked from playing just stays silent for
that one line; see the autoplay-block section below for the actual fix
(a self-healing retry), which is what makes staying silent an acceptable
trade rather than a real loss. The *only* remaining fallback case is the
genuinely different one: TTS was never configured on this deployment at
all (no `OPENAI_API_KEY`), where the browser's own voice is a reasonable
zero-config default rather than a mid-session bait-and-switch.

Two related things were also fixed in the process, both still true today:

1. **No visibility into which failure class actually happened.**
   `speakViaBackend`/`playBackendVoice` distinguish "backend request
   itself failed" from "backend succeeded but this browser blocked
   playback," and both copies of `useTextToSpeech.ts` log the exact
   `spoke`/`configured`/`fetchedAudio` state whenever either happens, plus
   the specific rejection reason when `audio.play()` itself throws — so an
   occurrence is diagnosable from `DebugOverlay.tsx` rather than guessed
   at.
2. **A real leak on every mic barge-in during backend-voice playback.**
   Both copies reuse one shared `<audio>` element across turns (see the
   `getSharedAudioElement` comment on why). `stop()` — called on every
   barge-in via `stopSpeech()` in `SocraticChat.tsx`/`App.tsx` — paused
   that element to cut Bede off, but `pause()` never fires `'ended'` or
   `'error'`, which is what the in-flight `speakViaBackend`/
   `playBackendVoice` call was `await`-ing to resolve its own promise.
   Interrupting Bede mid-playback left that call's promise pending
   forever. `stop()` (and the hook's unmount cleanup) now fires `onended`
   manually right after `pause()`, then detaches both handlers, so an
   interrupted call resolves cleanly instead of leaking.

**Fixed in both copies** of `useTextToSpeech.ts`, same
independent-codebases caveat as every other voice-pipeline fix in this
file.

## Troubleshooting: Bede's voice keeps getting blocked by the browser's autoplay policy, turn after turn

Reported live via a debug-panel trace: `backend TTS audio.play() rejected:
The request is not allowed by the user agent or the platform in the
current context` on repeated turns within the same session — not a one-off.
Real audio came back from the backend every time (`fetchedAudio: true`),
it just never played.

Some background: `unlockSpeechForSession()` "spends" a real, synchronous
user gesture (the login/code-entry button click) on a silent `play()` of
the shared `<audio>` element (`getSharedAudioElement()`) specifically so
every later *programmatic* `play()` call on that SAME element — the
opener, every subsequent turn — is allowed by the browser's autoplay
policy without needing its own fresh gesture. By spec, once an element has
actually played due to a user gesture, it stays "blessed" for the rest of
the page's lifetime. A session where the block recurs on *every* turn
means that initial unlock either didn't actually succeed on that
browser/device, or didn't durably stick — and before this fix, there was
no recovery from that state short of a full page reload: every future
`play()` call kept failing identically for the rest of the session.

Fix: both copies of `useTextToSpeech.ts` now arm a one-shot,
self-removing `pointerdown` listener on `document` (`armAutoReUnlock()`)
the moment a real `audio.play()` rejection happens. The very next genuine
tap anywhere on the page — a subject switch, the mic button, anything —
re-primes the same shared element with another silent, synchronous
`play()`/`pause()`, inside that real gesture, the same trick
`unlockSpeechForSession()` already uses. If that re-prime succeeds, every
`play()` call after it succeeds too, without the family needing to reload
anything. This is deliberately paired with the "no fallback" decision
above, not a replacement for it — staying silent for the blocked line(s)
while this self-heals is the whole reason no fallback is needed here.

If a family reports audio never recovering even after several taps, that
points to something more persistent than an autoplay-policy quirk (a
device/browser genuinely refusing to ever unlock audio playback) — check
whether `armAutoReUnlock`'s own re-prime attempt is itself rejecting in
the debug panel, not just the original turn's.

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

## Troubleshooting (historical): the mic shows "Listening…" forever and nothing ever reaches Bede, even after waiting

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

## Troubleshooting (historical): pressing the mic does nothing when the browser has blocked microphone access

Reported as: the child presses and holds the mic, nothing happens — no
"Listening…" state, no error, no transcript, just silence, with no way to
tell whether the tap didn't register or something is actually wrong. Root
cause: both voice-input paths ultimately depend on the same browser
microphone permission — native `SpeechRecognition` and the recording
fallback's own `getUserMedia()` call (`useVoiceRecorder.ts`) — and neither
one told the rest of the app anything when that permission was denied.
`getUserMedia()` rejecting was caught and logged to the browser console
only; `useHybridVoiceInput.ts` had already flipped its internal mode to
`'recording'` in anticipation of the fallback succeeding, and nothing ever
moved it back, so the mic button looked and behaved as if it were
permanently mid-press with zero indication why.

Both hooks now report *why* a mic attempt failed instead of swallowing it:
`useVoiceRecorder.ts` classifies the rejection (`NotAllowedError`/
`PermissionDeniedError` → `'permission-denied'`, anything else — no
hardware, mic already in use, etc. — → `'unavailable'`) and reports it via
a new `onError` callback; `useHybridVoiceInput.ts` also checks native
`SpeechRecognition`'s own `'not-allowed'` error code directly, so a browser
that blocks the microphone permission itself at the native-recognition step
gets the same clear signal without wastefully trying (and failing at) the
recording fallback too. Either path now returns the mic to idle and sets a
`micError` the hook exposes, which `SocraticChat.tsx`/`App.tsx` show as a
plain-language chat message (`chat.micPermissionDenied` /
`chat.micUnavailable` — see the child-facing copy in `en.json`/`es.json`):
"I can't hear you — this browser has blocked the microphone..." with a
pointer to type instead or have a parent check the browser's site
permissions. **Fixed in both copies** of `useHybridVoiceInput.ts` and
`useVoiceRecorder.ts` — same independent-codebases caveat as every other
voice-pipeline fix in this file.

**`'not-allowed'` only, deliberately not `'service-not-allowed'` too** — an
earlier version of this fix treated both the same way, which turned out to
be its own bug; see the next section.

If a family reports this after updating, the actual fix is usually in the
browser's own site settings (the padlock/site-info icon next to the address
bar → Microphone), not in Bede — this change only makes the existing
denial visible instead of silent.

## Troubleshooting (historical): voice input reports "blocked" inside an app's in-app browser (WhatsApp, Instagram, etc.), even though the mic itself might actually work

Reported with a live debug-panel trace: opening Bede's link from inside
WhatsApp (its own embedded in-app browser, not real Safari — note the
"← WhatsApp" back button in the browser chrome) made every single mic
press fail immediately (~10ms, no permission prompt ever shown) with
native `SpeechRecognition`'s `'service-not-allowed'` error — and, after the
fix in the section above shipped, that surfaced as "I can't hear you — this
browser has blocked the microphone," even though the *same device's* real
Safari had used voice input successfully minutes earlier in the same
session.

Root cause of the false "blocked" report: the fix above initially treated
`'not-allowed'` and `'service-not-allowed'` as the same thing — reasoning
that both meant the getUserMedia-backed microphone permission was already
denied, so falling back to server-side transcription would just fail the
same way. That reasoning is correct for `'not-allowed'` but wrong for
`'service-not-allowed'`, which is a narrower signal: the browser's SPEECH
RECOGNITION *SERVICE* specifically is unavailable — on iOS, third-party
in-app browsers (WhatsApp, Instagram, and similar embedded WebViews) don't
carry the entitlement for Apple's on-device Speech framework that real
Safari has, so on-device recognition fails instantly with this exact code.
That says nothing about whether plain microphone capture
(`getUserMedia()`, which the recording + server-Whisper fallback uses)
works in that same embedded browser — it very often still does.

`'service-not-allowed'` now falls through to the recorder fallback like
any other non-permission native error, instead of being told the mic is
blocked before ever trying. If `getUserMedia()` genuinely is also
unavailable there, the recorder's own `onError` (from the section above)
still reports that correctly — this fix doesn't remove error reporting,
it just gives the fallback path a real chance first. **Fixed in both
copies** of `useHybridVoiceInput.ts` — same independent-codebases caveat
as every other voice-pipeline fix in this file.

If a family reports voice input not working inside a specific app's
in-app browser, the most reliable fix is usually to open the link in the
device's real default browser instead (on iOS, the share/menu button in
most in-app browsers offers "Open in Safari" or similar) — that's what
gives native on-device speech recognition its best shot, with the
server-side fallback as a safety net either way.

## Troubleshooting (historical): the mic gets permanently stuck after the child interrupts Bede mid-speech

Reported with a live debug-panel trace (see `DebugOverlay.tsx`): a child
pressed the mic while Bede was still talking (a normal barge-in — see the
`stopSpeech()` note in `SocraticChat.tsx`'s `holdStart`), native
recognition produced *zero* signal for that press (no interim, no final —
the same category of silent failure the stall watchdog above exists for),
the recorder fallback kicked in as designed, and then the mic never
recovered for the rest of the session: later presses did nothing at all,
with no further debug output even logged. Root cause: `useHybridVoiceInput.ts`'s
recorder `onComplete` callback had no `try`/`catch` around the transcription
network call —

```js
onComplete: async (wavBlob) => {
  setMode('transcribing')
  const text = token ? await transcribeFallback(token, wavBlob, ...) : ''
  setMode('idle')  // never reached if the line above throws
  if (text) onFinal?.(text)
},
```

— so any thrown/rejected transcription call (a transient fetch failure, a
malformed JSON response, anything) skipped straight past the
`setMode('idle')` that was supposed to run right after it. `mode` was left
permanently stranded at `'transcribing'`, which disables the mic button via
`isTranscribing` — with no timer or event left anywhere to ever clear it.
Since a disabled `<button>` doesn't dispatch pointer events at all, later
presses produced no debug output whatsoever, which is exactly the "stuck"
symptom the trace showed.

Two fixes, both defense-in-depth for the same failure class:

1. The transcription call is now wrapped in `try`/`catch`/`finally` —
   `setMode('idle')` runs unconditionally in the `finally` block, so a
   failed transcription surfaces a `micError` (reusing the same
   `chat.micUnavailable` message and UI path as the permission-denial fix
   above) instead of silently stranding the mode forever.
2. A new `RECORDING_SAFETY_TIMEOUT_MS` (10s) timer, armed the moment the
   recorder fallback starts and disarmed the moment it actually completes
   (success or failure), catches the *other* way this could theoretically
   still hang: `recorder.stopRecording()` (in `useVoiceRecorder.ts`)
   silently no-ops (`if (!processor || !audioCtx || !stream) return`) if
   called before `startRecording()`'s own async setup has finished
   populating those refs — a real, if rare, race that would otherwise never
   call `onComplete` at all. Mirrors `HOLD_SAFETY_TIMEOUT_MS`'s existing
   "never trust a single point of recovery" philosophy in the same file.

**Fixed in both copies** of `useHybridVoiceInput.ts` — same
independent-codebases caveat as every other voice-pipeline fix in this
file. Why interrupting Bede specifically seemed to trigger native
recognition's silent failure in the first place wasn't conclusively
root-caused (a live device with real speech hardware would be needed, not
available in the sandbox this was fixed in) — the working theory is some
form of audio-focus contention between `stopSpeech()`'s abrupt playback
cutoff and `SpeechRecognition.start()` firing moments later in the same
call stack, a known category of browser quirk. Regardless of that trigger,
both fixes above close off the *consequence* (mode getting permanently
stuck) for good.

## Troubleshooting (historical): a real, multi-second answer produces nothing at all, with no error shown

Reported with a live debug-panel trace (see `DebugOverlay.tsx`): a child
held the mic and answered a question out loud for ~3.3-3.5 seconds — twice
in the same session — and native recognition produced *zero* signal the
entire time (no interim, no final), the exact "Safari can accept the mic
press and then never fire ONE SINGLE onresult for the entire hold" failure
mode `_start`'s own comment already documented. The existing stall watchdog
exists precisely to catch this, but at its old 4000ms threshold it never
got the chance: both holds were released at ~3.3-3.5s, just under the
watchdog's deadline, so `release()` ran with `mode` still `'native'` and
nothing ever accumulated — the child's whole answer was silently lost, with
nothing sent to Bede and no sign anything had gone wrong. The debug trace's
repeated very-short re-presses (76ms, 53ms) right around the same failures
read exactly like a confused child trying again after nothing seemed to
happen.

Two changes, addressing the same trace:

1. **`NATIVE_STALL_TIMEOUT_MS` lowered from 4000ms to 2500ms.** Safe to
   lower because this watchdog is *permanently disarmed* the moment even a
   single interim result ever arrives (see the interim effect) — shortening
   it only changes how long the app waits before deciding "native has
   produced literally nothing yet," never a hold that's actually making
   progress. A hold like the one in the trace now hits the watchdog *while
   still held*, switching over to the recorder+Whisper fallback partway
   through instead of reaching `release()` with nothing at all.
2. **`release()` itself now recognizes the narrower remaining gap** — a
   hold released between `MIN_HOLD_MS_FOR_NO_SPEECH_FEEDBACK` (1200ms, below
   which an empty release is almost certainly just an accidental brief tap,
   not worth alarming anyone over) and the stall watchdog's own deadline,
   that still produced nothing. `MicError` gained a third value,
   `'no-speech-heard'` (alongside `'permission-denied'`/`'unavailable'`),
   surfaced through the same `SocraticChat.tsx`/`App.tsx` chat-message path
   as the other two, telling the child plainly rather than staying silent.

**Fixed in both copies** of `useHybridVoiceInput.ts` — same
independent-codebases caveat as every other voice-pipeline fix in this
file. As with the "permanently stuck" bug above, *why* native produced zero
signal for this specific device/session wasn't root-caused (needs a live
device to actually reproduce, not available in the sandbox this was fixed
in) — this fix closes off the *consequence* (a lost answer with no
feedback) rather than the underlying recognition-service flakiness itself.

## Troubleshooting (historical): the recorder fallback itself reports "I can't hear you right now" right after switching over

Reported with a live debug-panel trace, immediately after the fix above
shipped: the stall watchdog correctly fired and handed off to the recorder
fallback (`startFallback()` → `useVoiceRecorder.startRecording()`, right on
schedule), but the fallback then failed outright with the `'unavailable'`
`MicError` — twice in a row, on consecutive holds in the same session — with
no `recorder onError reason=...` trace line anywhere to explain why.

Root cause: `_start()` calls `recorder.prewarm()` — a `getUserMedia()` call
made *in parallel* with native Web Speech Recognition grabbing the
microphone for its own internal capture, so the fallback stream is ready the
instant it's needed (see the "permanently stuck" section above for why this
has to happen synchronously inside the press gesture). On some
devices/browsers those two concurrent mic opens contend, and prewarm's call
can lose that race and reject (e.g. `NotReadableError`, "device in use") —
a transient hiccup, correctly ignored while `mode` is still `'native'` (a
prewarm failing doesn't mean the whole press is doomed). But
`startRecording()` then reused that same *stale, already-settled* promise
when the fallback actually engaged, seconds later — by which point native
had already released its own grab (`native.stop()` already ran), so a fresh
request would very likely have succeeded. A settled promise is truthy, so
`prewarmPromiseRef.current ?? getStream(...)` never fell through to retry;
`startRecording()` just gave up on the stale failure instead, explaining
both the missing trace line (the *original* rejection was reported once,
early, while `mode` was still `'native'`, and the caller's own guard
correctly suppressed reacting to it then — but no second attempt was ever
made once the fallback needed the mic for real) and why it repeated on every
subsequent hold in the same session (the same contention recurs at the
start of each one).

Fix, in both copies of `useVoiceRecorder.ts`: `startRecording()` now retries
`getUserMedia()` fresh whenever the prewarmed stream turns out to be `null`,
instead of treating that stale failure as final. Also added a `logDebug()`
call inside `getStream()`'s own catch block, alongside the existing
`console.error` — the underlying `DOMException` name (which classifies
`permission-denied` vs. `unavailable`) previously only reached the browser's
own DevTools console, invisible in any on-screen `DebugOverlay` trace a
remote user could actually screenshot and send us.

## Troubleshooting (historical): the very first press-and-hold right after Bede speaks captures nothing at all

That `logDebug()` line added above immediately paid off — a follow-up trace
showed a first hold ending with `accum=""` `interim=""` (nothing captured
whatsoever), and a rejection logged a few ms after `_start`:
`getStream() rejected name=InvalidStateError message=AudioSession category
is not compatible with audio capture.` This is iOS Safari's
`navigator.audioSession` (see `audioSession.ts`) rejecting `getUserMedia()`
because the session was still pinned to `'playback'` — Bede had just
finished speaking — at the exact moment the press tried to open the mic.

Root cause: the switch to a recording-capable `AudioSession` category
(`enterRecordingAudioSession()`) only ran inside a `useEffect` keyed on
`mode`, which fires *after* the render commits. But `_start()` calls
`recorder.prewarm()` and `native.start()` — both of which trigger
`getUserMedia()` — synchronously, in the very same call stack that also
calls `setMode('native')`, a beat *before* that effect gets a chance to run.
Right after Bede's TTS ends, that race loses every time: the session is
still `'playback'` when `getUserMedia()` fires. Native Web Speech
Recognition depends on the same category internally (see `audioSession.ts`'s
own comment), so this doesn't just break the recorder fallback — it can
silently swallow the very words native recognition was supposed to hear,
which is exactly what a parent reported as "Bede doesn't capture the initial
input." (Native recognition's *own* internal `getUserMedia` call isn't
perfectly synchronous the way `prewarm()`'s is, so it sometimes wins this
same race on a later press — which is why the symptom reads as intermittent
rather than a hard, everytime failure.)

Fix, in both copies of `useHybridVoiceInput.ts`: `_start()` now calls
`enterRecordingAudioSession()` synchronously, as its very first action —
before `prewarm()`, before `native.start()`, before anything else that could
touch the microphone — rather than waiting on the mode-driven effect. No
added delay: switching `audioSession.type` is a plain synchronous property
set, so doing it eagerly costs nothing and closes the race outright, for
both the native-recognition path and the direct-to-recorder path (when
native isn't supported at all). The mode-driven effect is left in place
unchanged for the "restore to playback" side, which was never time-critical
the same way.

## Troubleshooting (historical): push-to-talk regressed right after the fix above — native fails instantly on every press, and long holds get cut off mid-answer

Reported directly, with two live traces, immediately after the fix above
shipped to the public demo. Every single press in both traces showed
`startFallback() from mode=native` within **10-30ms** of the press starting
— not the 2500ms stall watchdog, `native.start()` itself failing to even
begin, on literally every attempt. That forced every hold into the recorder
fallback path, which then exposed two more, compounding bugs:

1. A hold released before `MIN_RECORDING_MS` (400ms) while already in the
   fallback path — an accidental brief tap, easy to trigger when native is
   failing this fast — gets silently discarded inside `useVoiceRecorder`'s
   `stopRecording()`, whose early-return path never calls `onComplete`.
   `useHybridVoiceInput`'s `mode` had no other way to learn the recording
   ended, so it stayed stuck at `'recording'` — silently swallowing every
   subsequent press — until `RECORDING_SAFETY_TIMEOUT_MS` (10s) eventually
   forced it back to idle.
2. That same 10-second safety timeout doesn't just recover a genuinely stuck
   state — it fires against a **real, still-in-progress hold**, too. A trace
   showed it firing at the 10s mark while a child was still actively
   holding and speaking, wiping `mode` back to idle and showing "can't hear
   you" nearly a full second *before* the child even released the button,
   orphaning a recording that was never actually broken.

**Root cause of the instant native failure (the actual regression):** the
fix directly above made `enterRecordingAudioSession()` run before
*everything* in `_start()`, including immediately before `native.start()`.
The reasoning at the time was that native recognition also depends on the
audio session category internally (true — see `audioSession.ts`'s own
comment) — but that was never confirmed by a trace, only `prewarm()`'s own
`getStream()` failure was. Forcing a WebKit audio-session category change in
the exact same tick as calling `native.start()` turned out to break native's
*own* initialization outright — a different race than the one being fixed,
introduced by the fix, and far more damaging: instead of an occasional lost
first press, it failed **every single press** in both reported traces.

Fix, in both copies of `useHybridVoiceInput.ts` and `useVoiceRecorder.ts`:

1. `enterRecordingAudioSession()` is scoped back to only the two call sites
   actually proven to need it — immediately before `recorder.prewarm()`,
   and immediately before `startFallback()` in the "native isn't supported
   at all" branch — never before `native.start()` itself.
2. `useVoiceRecorder` gained two new callbacks: `onStarted` (fires the
   moment the audio graph is genuinely live) and `onStopped` (fires at the
   end of *every* `stopRecording()` call, regardless of outcome — produced
   a blob, discarded as too short, or had nothing to stop). `onStarted`
   clears the recording safety timeout as soon as recording is confirmed
   underway, so it stops being a hold-duration cap and goes back to its
   original, narrow purpose (catching a recording that never started at
   all) — `MAX_RECORDING_MS` (120s, matching native hold-to-talk's own
   `HOLD_SAFETY_TIMEOUT_MS`) is the real ceiling for a long hold now.
   `onStopped` gives `useHybridVoiceInput` a callback-based signal for "this
   recording has finished" that fires even when `onComplete` doesn't (the
   too-short-discard case), so `mode` returns to idle immediately instead of
   waiting on that same safety timeout as the only way out.

This is the second time a fix to this exact call site (`enterRecordingAudioSession()`'s
placement in `_start()`) has needed correcting after shipping — worth
internalizing for next time: a WebKit-specific audio-session race is very
hard to reason about from first principles alone, and "native also probably
needs this" is a hypothesis, not a finding, until an actual trace confirms
which specific call it was racing against.

## Troubleshooting: "I didn't quite catch that" on short holds, especially on cellular

Caught from a real debug-panel capture on a phone, and the most damaging
voice bug found so far — it silently threw away a child's whole answer.

The trace:

```
[270187ms] holdStart type=pointerdown isSpeaking=false
[270188ms] _start() attempt=6
[270188ms] useVoiceRecorder.startRecording()
[271228ms] holdEnd type=pointerup            <- 1041ms hold
[271228ms] release() from mode=recording
[271229ms] useVoiceRecorder.stopRecording()
[272098ms] voice stream produced nothing after a 1910ms turn — surfacing to the user
```

**The race.** `_start()` starts the recorder synchronously, but opens the
server-side streaming session over the network — `sessionIdRef` is only set
inside `startVoiceStream(...).then()`. A short hold on a slow connection
therefore reaches `release()` while that request is still in flight, with
`sessionIdRef.current` still `null`. `release()` used to treat that as
unrecoverable:

```js
if (!token || !sessionId) {
  clearHoldSafety()
  setMode('idle')
  return          // audio discarded — no upload, no finish, no error
}
```

The captured audio was simply dropped. Nothing was uploaded, nothing was
transcribed, and no error was surfaced — from the child's side, they spoke
and Bede ignored them.

**It compounded.** `release()` does not bump `attemptRef` (only `stop()`
does), so when the session finally opened a moment later, the `.then()`
still passed its staleness check and went on to install an SSE consumer
*and* a `CHUNK_UPLOAD_INTERVAL_MS` timer for a turn that had already ended
with a stopped recorder. Since nothing ever called `finishVoiceStream`,
that consumer waited until the stream died on its own, then reported "voice
stream produced nothing" and raised `no-speech-heard` — which is the
`[272098ms]` line above and the "I didn't quite catch that" bubble the
family actually sees. The stray chunk timer kept firing every 4 seconds
against a recorder that had nothing left to give.

**The fix** is to defer the release rather than discard it. A
`pendingReleaseRef` parks the already-captured audio plus its attempt id;
`_start()`'s `.then()` checks for it the instant the session opens and
completes the turn immediately — uploading the final chunk and calling
`finishVoiceStream` — instead of arming a chunk timer. The mode stays
`transcribing` while parked, which is what the UI was already claiming, and
the hold-safety timer stays armed as the backstop. `stop()` clears the
parked release, since a cancel should discard it. If the session never
opens at all, the existing retry-exhausted path clears it and surfaces
`unavailable` rather than sitting in `transcribing` forever.

Why it looked intermittent: it is purely a race between hold length and
session-open latency. On a fast connection with a normal multi-second hold,
the session is open long before release and nothing is wrong. Short holds,
cellular, or a cold backend are what expose it — which is also why it hit a
phone capture and not desktop testing.

`startVoiceStream` success is now logged with the elapsed time
(`startVoiceStream opened session after Nms`), which the trace above was
missing entirely — there was no way to tell from a capture whether the
session had opened before the release or not.

Regression coverage lives in each app's `useHybridVoiceInput.test.ts`
("release() arriving before the streaming session opens"), including a test
that the ordinary fast-hold path still arms the chunk timer, so this cannot
be "fixed" by never arming it. Two of those tests were confirmed to fail
against the unfixed hook.

## Open: "produced nothing" with the session already open (not the release-race above)

A real trace from a phone, captured after the session-open race above was
already fixed:

```
[40598ms] useVoiceRecorder.startRecording()
[40822ms] startVoiceStream opened session after 225ms
[40582ms] holdStart type=pointerdown isSpeaking=true   <- barge-in: mic
                                                            pressed while
                                                            Bede was still
                                                            speaking
[42926ms] holdEnd type=pointerup                       <- 2344ms hold
[42926ms] release() from mode=recording
[43107ms] voice stream produced nothing after a 2510ms turn — surfacing to the user
```

Unlike the race documented above, `startVoiceStream` had already resolved
2.1 seconds before `release()` — `sessionIdRef` was populated the whole
time, so `pendingReleaseRef` never enters into it. The hold was real and
well past `MIN_HOLD_MS_FOR_NO_SPEECH_FEEDBACK` (1200ms), yet the round trip
came back with empty text.

**Not yet root-caused.** Two open hypotheses, not confirmed:

1. **A genuinely quiet or silent hold** — the child didn't actually speak,
   or spoke too quietly for the mic to pick up. Ordinary and not a bug.
2. **A capture-side race specific to barge-in.** `isSpeaking=true` in the
   trace means this hold started by interrupting Bede's own speech —
   `stopSpeech()` fires synchronously, then `enterRecordingAudioSession()`
   switches the (iOS) audio session category from playback to
   play-and-record, then `recorder.startRecording()` begins. If the
   hardware doesn't finish that switch as fast as the JS call returns, real
   audio could be lost during a window early in the hold specifically when
   it's barge-in-triggered — a different failure mode from the
   `enterRecordingAudioSession()` placement bug fixed above, but the same
   general class of "the JS call returned before the hardware caught up."

**What would tell the two apart, and didn't exist yet at the time of the
trace above:** `release()` now logs the actual size of the audio it's about
to upload — `release() captured ~Nms of audio this delta (B bytes)` — right
where the final delta snapshot is taken, in both apps'
`useHybridVoiceInput.ts`. Compare that number to the hold length reported in
the same trace:

- **`~0ms` captured against a multi-second hold** confirms hypothesis 2 (a
  real capture-side bug) and rules out 1 — something prevented the mic from
  producing samples during a hold that definitely happened.
- **`capturedMs` roughly matching the hold length** rules out 2 — the audio
  reached the server intact, so an empty result is either a genuinely quiet
  utterance or a server-side transcription problem, not a client capture
  race.

Until a trace with this line lands, treat this as open. If it turns out to
be hypothesis 2 and specific to barge-in, the fix is almost certainly
awaiting the audio-session switch (or at least a short buffer/delay) before
`startRecording()` runs when `isSpeaking` was true at `holdStart` — but that
is a plan for once the diagnostic confirms it, not a fix shipped blind.

## Diagnosing a reported speech "echo"

Open, as of this writing: a doubled/echoing voice has been reported on a
current build. Root cause not yet found — the earlier fixes in #292 and
#314 addressed one specific doubling (the browser `speechSynthesis`
fallback playing *alongside* real backend audio) and are still in place,
so whatever is happening now is something else.

**A second, distinct hypothesis exists for a similar-sounding complaint —
don't conflate the two.** A report of "sounds like a lisp" plus "a residual
echo" was traced instead to MP3's pre-echo artifact on sibilants (see the
transcription-delay section's MP3→AAC entry above) and addressed by
switching codecs, not by anything in this section. Both explanations can
produce something a parent would call "echo": this section is about two
separate audio clips actually overlapping on playback; the codec one is a
single clip whose own encoding smears transients. The table below is what
tells them apart — a genuine overlap shows two `STARTED` events with no
`ENDED` between them; a codec artifact shows one clean playback with
nothing unusual in the log at all, since there's only one clip and it never
overlaps anything. If a report includes the word "lisp" specifically, check
the AAC change above first; if the debug panel shows a genuine double
`STARTED`, it's this section instead.

**The debug overlay only used to log failure paths** — an autoplay
rejection, a fallback decision. During a normal-looking turn that happens
to echo, it emitted nothing at all, so a capture came back empty and told
you nothing. The TTS path is now instrumented on the success paths too, in
both apps, specifically so one screenshot can distinguish the three
plausible causes:

| What the log shows | What it means |
|---|---|
| `TTS speak()` twice with the same `text="…"` for one turn | Duplication is **upstream**, in the turn-stream consumer batching speech segments — not in playback at all. |
| Two `TTS backend playback STARTED` with no `ENDED` between | Two clips **overlapping on the shared `<audio>` element** — the doubled/"reverby" case. |
| `TTS browser fallback STARTED` while a backend clip is playing | **Two different voices at once** — the #292/#314 class, not fully closed. |

Also logged: `TTS processQueue start` (tutor only — the demo has no queue),
playback `ENDED`/`ERROR`, and `TTS stop()` with the generation counter, so
barge-in and subject-switch boundaries are visible and a superseded call
resuming can be spotted by its stale `gen=`.

To capture: open the session, toggle the debug overlay from the session
header (the muted control set apart from the real session controls),
reproduce the echo, screenshot the panel. The buffer holds 100 entries
(`hooks/debugBus.ts`), so screenshot reasonably promptly after it happens.

## Troubleshooting: press-and-hold cuts off mid-sentence, or "the voice button is unreliable"

Reported as press-and-hold feeling unreliable compared with other
assistants' recording buttons. This was a real bug in the button's pointer
wiring, not in transcription, the audio graph, or the model.

The mic button's handlers were:

```jsx
onPointerDown={holdStart}
onPointerUp={holdEnd}
onPointerLeave={holdEnd}     // <- the bug
onPointerCancel={holdEnd}
```

with no pointer capture. `pointerleave` fires the moment the pointer crosses
outside the element's box, and it was wired straight to the "stop recording
and send" path. So any finger drift off the button mid-hold ended the turn
immediately — silently, mid-sentence, with no error and nothing in the
resulting transcript to explain the truncation.

On a tablet, held by a child, against what was then a ~38px target, that is
not an edge case. It is the common case, and it is exactly what "the mic
keeps cutting me off" and "it only caught half of what she said" look like
from the outside. Note the failure is *silent*: the partial audio still
transcribes fine, so the child simply sees a short, oddly-truncated version
of what they said reach Bede.

**The fix** is `setPointerCapture()`, in `utils/holdGesture.ts` (mirrored to
`demo/src/holdGesture.ts`). Once the pointer is captured, the capturing
element receives every subsequent event for that pointer regardless of where
it travels, and boundary events are suppressed while capture is held. The
hold then ends only when the child actually lifts their finger — the entire
contract of a press-and-hold control.

This app already used the technique elsewhere: `HandwritingCanvas.tsx`
captures the pointer so a drawing stroke survives leaving the canvas bounds.
The mic button simply never got the same treatment.

Three details worth keeping:

- **`onPointerLeave` is retained, but only as a fallback for when capture
  could not be established at all** (a very old WebView, a synthetic pointer
  with no usable id). When capture succeeded, a leave event is ignored,
  because leaving the box is not the end of the gesture. Degrading to the
  old lossy behavior is still better than a hold that can only end at the
  120-second `HOLD_SAFETY_TIMEOUT_MS` ceiling.
- **Gesture-active is tracked separately from capture-held.** Releasing
  capture necessarily clears the captured flag, and the spec allows a
  deferred `pointerleave` immediately afterwards — with a single flag, that
  trailing event falls through the "capture unavailable" branch and fires a
  *second* send for one gesture. A regression test caught this during
  development; the call sites happen to carry their own `holdingRef` guard,
  but the helper is correct on its own rather than depending on every caller
  to re-derive that.
- **The touch target was raised to a 44px floor** (Apple HIG minimum) from
  roughly 38px. Capture makes drift harmless, but a larger target means less
  drift to begin with, and this button is aimed at K-8 hands.

`touch-action: none` was already correctly set on this button (Tailwind's
`touch-none`), so scroll-gesture `pointercancel` was never part of this
particular failure.

**Not the same issue as continuous mode's missing endpointing** (see that
feature's section below). Hold-to-talk has always had an explicit end signal
— the child's own finger lift — and this fix is about that signal being
delivered reliably. Continuous "Voice on" mode has no end signal at all,
which remains open, separate work.

## Troubleshooting: the live transcript while speaking is off-screen

Reported with a screenshot: while holding the mic and talking, the child's
own words never appeared on screen at all — not missing, just scrolled out
of view below the input bar. Root cause: the live interim transcript, the
"transcribing…" indicator, and the voice-review confirm/cancel card are all
rendered inside the scrollable message list (`SocraticChat.tsx`/`App.tsx`),
but they aren't part of the `displayMessages`/`messages` array — they're
synthesized from separate `useHybridVoiceInput` state. The auto-scroll
effect that keeps the latest content in view only re-ran when the message
list itself changed, so appending any of these three transient elements
never triggered a scroll — if the chat was already scrolled up, or the
previous message filled the viewport, the child's live transcript rendered
below the fold with nothing bringing it into view. Fixed by adding
`isListening`, `interim`, `isTranscribing`, and `pendingVoiceTranscript` to
that effect's dependency array in both files, so the view now follows the
child's own words the same way it already follows Bede's replies.

## Troubleshooting: Bede's voice switches from the family's chosen output to the device's built-in speaker mid-lesson

**Still current** (unlike most of the sections above) — the mechanism this
section describes is exactly how `audioSession.ts` still works after the
server-side-streaming rewrite, just with one fewer `mode` value: the effect
now reacts to `mode === 'recording'` alone (native's own `'native'` mode no
longer exists), still pinning the session to `'play-and-record'` while
capturing and back to `'playback'` otherwise.

Reported as: audio "switching to browser embedded [sound] instead of mobile
audio" during a lesson, specifically tied to using the press-to-talk mic —
and once it happens, playback doesn't settle back onto one output for the
rest of the session; each mic press re-triggers the same switch. This is a
routing issue, not a volume/mute one: whatever output the family had
actually selected (a Bluetooth speaker, wired headphones, AirPlay) gets
overridden by the tablet's own built-in speaker/earpiece, and Bede's voice
noticeably changes character (quieter, more "in the device") as a result.

Root cause: on iOS/iPadOS Safari, opening ANY microphone stream —
`useHybridVoiceInput.ts`'s own recorder fallback/prewarm
(`useVoiceRecorder.ts`), or native `SpeechRecognition`'s own internal
capture, which uses `getUserMedia` under the hood regardless of whether
this app calls it directly — switches WebKit's *audio session category*
into a mode that can route subsequent `<audio>`/TTS playback through the
device's built-in earpiece speaker rather than whatever output was actually
selected. Nothing in the app was ever telling WebKit to switch the session
back once the mic closed, so the override could persist for the rest of the
lesson, with every subsequent press-to-talk re-triggering it.

Fix: `utils/audioSession.ts` wraps WebKit's `navigator.audioSession` API
(iOS/iPadOS 17+; unsupported everywhere else, so every call is a
feature-checked, try/catch-guarded best-effort no-op on Android
Chrome/desktop/older iOS — nothing to break there). `useHybridVoiceInput.ts`
now has a `useEffect` reacting to its own `mode` state: `'native'` or
`'recording'` (the mic is actually capturing) pins the session to
`'play-and-record'`; anything else (`'idle'`, `'transcribing'`) pins it back
to `'playback'`, telling WebKit to route audio to the family's actual
chosen output again. Driven off `mode` rather than threaded into every
individual call site (`release()`, `stop()`, native's
`onFinal`/`onError`/`onNoSpeech`, the stall watchdog's fallback handoff)
means every path that starts or stops listening is covered by one effect.

**Fixed in both copies** of `useHybridVoiceInput.ts` (and a new
`audioSession.ts` in each) — same independent-codebases caveat as every
other voice-pipeline fix in this file. Android Chrome has no equivalent
public API for a page to control audio session category directly, so this
fix is iOS/iPadOS-specific; Android's own routing behavior around
`getUserMedia` wasn't reported as broken and is left alone.

## Troubleshooting: a held turn is silently discarded, and then the mic button stops working

From a real trace on the public demo. The server answered a session's very
first `events` request with **"unknown or expired session" 238 milliseconds
after creating it**. The TTL is 180 seconds, so that is not expiry — it is the
request landing on a different process from the one that created the session.
`services/streaming_transcription.py` keeps sessions in memory, in one
process, and says so in its own docstring; the same trace shows the signature
plainly, with chunks on one session id succeeding, then 404ing, then
succeeding again.

**That root cause is server-side and no frontend change fixes it.** It needs
the instance count pinned to one, session affinity, or a shared store. Note
`render.yaml` carries no instance or scaling configuration at all, so that
number lives only in the Render dashboard — the same blueprint-versus-
dashboard drift `render.yaml`'s own plan comments were written about.

Two client faults made it far worse than it needed to be, and both are fixed:

**The turn was reported as finished while the child was still holding.**
`consumeEvents` logged the error event, fell out of its loop, and ran straight
into `setMode('idle')`. The child went on speaking for another seven seconds
and all of it was discarded. `heldMs` at that instant was 643ms — under
`MIN_HOLD_MS_FOR_NO_SPEECH_FEEDBACK` — so not even an error appeared. The
stream ending while `mode` is still `recording` is now treated as the turn
dying underneath the child: the recorder is stopped, the chunk timer cleared,
and `network` surfaced (the microphone is fine; the session it was streaming
to is gone).

**Nothing tore the turn down, so the next press did nothing.** The recorder
kept capturing and the chunk timer kept uploading. `useVoiceRecorder` refuses
to start a second recording while one is live, so the child's next press
reached `_start()` and never reached `startRecording()` — visible in the trace
as an `_start() attempt=9` with no `useVoiceRecorder.startRecording()` line
after it. Same latch-off failure the give-up path was fixed for, arriving
through a different door.

**Every successful turn also fired a second `finish` that 404'd.** `release()`
finishes the session but leaves `sessionIdRef` populated, because the final
`uploadSnapshot` still needs it — so the `stop()` that follows when the child
confirms and sends finished the same session again. Harmless on its own, but a
wasted round trip per turn, and it filled the log with 404s that made the real
one above hard to find. A `finishRequestedRef` set synchronously at release
now makes it exactly one finish per session; an outright cancel with no
release still finishes properly, or the session would leak until its TTL.

## Troubleshooting: "I can't hear you" appears the instant it becomes the child's turn, before any press

A parent sent two real traces from a live iOS Safari session, five minutes
apart, both showing the same shape: `_start() attempt=11` (and climbing),
two `getStream() rejected name=NotAllowedError` lines back to back on every
attempt, the mic message on screen, and Bede continuing to converse normally
via typed input in between. Not a one-off — every turn in the trace failed
the same way.

Root cause, found by reading `prewarm()`'s own call site rather than
guessing from the log: `SocraticChat.tsx` calls `prewarm()` from a
`useEffect` the instant `awaitingChildTurn` goes true — *before* the child
has pressed anything, and therefore *not inside a user gesture at all*.
`useVoiceRecorder.ts` carries its own comment on exactly why that matters:
iOS Safari only honors `getUserMedia()` when it's initiated directly inside
a user gesture's call stack, and rejects (or never settles) a call made from
anywhere else. A prewarm effect is exactly "anywhere else."

That alone would just make prewarm fail quietly on a strict browser — not
itself the bug, since `startRecording()`'s own fresh-retry fallback exists
precisely to recover from a failed prewarm. The actual defect is that
`getStream()` called `onError` unconditionally on every rejection, with no
way to tell "this was only the provisional prewarm attempt, a retry is
still coming" from "this was the truly final attempt, nothing is left to
try." So a prewarm failure and a real press-time failure were
indistinguishable to the child: both flipped `mode` to `'idle'` and set
`micError`, both showed the same message — including, worst of all,
*before the child had touched the mic button*.

This gap used to be covered. `startRecording()`'s own comment on the
prewarm-fails-then-retry-succeeds case recorded that a failed prewarm
"never even reached onError (mode was still `'native'` when it rejected, so
the guard in useHybridVoiceInput correctly ignored it)" — a `mode !==
'native'` check from the browser-native SpeechRecognition era. When native
recognition was removed entirely (see the top of `useHybridVoiceInput.ts`
and this file's own rewrite section), that guard went with it, and nothing
replaced it. The comment describing the old protection stayed in the file
long after the protection itself was gone.

Fix: `getStream()` takes a `report` option (default `true`). `prewarm()`
always passes `report: false` — a prewarm failure is never the final word.
`startRecording()`'s own first attempt (reusing the prewarm promise, or a
cold call for a caller with no separate prewarm step) is `report: false`
too, for the identical reason: a fresh retry still follows it. Only that
fresh retry — genuinely the last attempt, nothing left to fall back to —
reports normally. `logDebug()` still records every rejection regardless of
`report`, so a provisional failure remains visible in a debug trace even
though the child never sees it.

**What this fix does and does not explain about the two traces above.** It
closes a real, provable gap: a prewarm-stage failure can no longer surface
as though it were the turn's own outcome, and (per the regression test
added alongside it) a turn that ultimately succeeds after a failed prewarm
attempt no longer shows a spurious error along the way. What it can't
settle from a log alone is whether that specific family's *in-gesture*
retry — the one now correctly reporting — was failing because the site's
own microphone permission was genuinely blocked on that device, or because
even a same-tick `await` on an already-rejected prewarm promise is enough
to cost WebKit's user-activation window before the fresh call runs. Both
produce the identical `NotAllowedError` text on iOS Safari, and only a real
device trace after this fix ships can distinguish them going forward.

## Endpointing: how a continuous-mode turn ends

Hold-to-talk needs no endpointing — releasing the button *is* the endpoint.
Continuous "Voice on" mode had none at all: `start()` behaved exactly like
`startHold()`, nothing ever called `release()`, and the turn therefore ran to
the 120-second `HOLD_SAFETY_TIMEOUT_MS` ceiling. A child answered in four
seconds and the microphone stayed open for another hundred and sixteen.

`homeschool-tutor/src/utils/endpointing.ts` closes that. It samples the
recorder's existing level meter every 200ms and ends the turn on trailing
silence.

**The silence window is deliberately longer than a dictation app's, and that
is the whole design.** General-purpose dictation endpoints after roughly
700-1500ms. That is wrong here: this app's central activity is narration — a
child recalling a passage aloud, from memory, in their own words. Thinking
pauses mid-narration are not hesitation to be trimmed, they are the work.
Cutting a child off to "helpfully" submit half a sentence is worse than any
latency it saves, and it punishes exactly the unhurried recall the method is
built on. `TRAILING_SILENCE_MS` is 3000ms, and a test asserts it stays clear
of dictation territory so shortening it has to be an argument rather than a
quiet edit.

Two independent reasons end a turn, kept apart on purpose:

- **`finished-speaking`** — at least `MIN_SPEECH_MS` (600ms) of speech was
  heard, then `TRAILING_SILENCE_MS` of quiet.
- **`no-speech`** — nothing was ever heard, so after `NO_SPEECH_TIMEOUT_MS`
  (12s) the turn ends rather than holding the mic to the 120s ceiling. Covers
  an auto-start that fired after the child walked away.

Both are logged to the debug overlay with the speech/silence split, so a
report can say *why* a turn ended rather than only that it did.

**They exit differently, and that is the difference between a helpful
endpoint and an irritating one.** `finished-speaking` calls `release()` — the
child spoke, so the turn is delivered. `no-speech` calls `stop()` instead,
which discards silently.

Routing `no-speech` through `release()` looks harmless and is not. It produces
an empty transcript, which `MIN_HOLD_MS_FOR_NO_SPEECH_FEEDBACK` turns into an
"I didn't quite catch that" bubble **and** a tick on `SocraticChat`'s
voice-mode circuit breaker — telling a child the microphone failed when they
had simply not spoken yet. That cascade already existed at the 120-second
ceiling, where it took six minutes to reach three strikes. At a 12-second
no-speech timeout it would take **thirty-six seconds**, so shortening the
timeout without changing the exit would have made an existing annoyance ten
times more frequent. Silence is ordinary; it is not a fault.

Repeated silence still needs an answer, though, because a cheap endpoint makes
an empty room expensive: the mic would re-arm, open a streaming session and
tear it down five times a minute forever. After `MAX_CONSECUTIVE_SILENT_TURNS`
(3) the app stands continuous mode down to hold-to-talk with one plain line —
not an error — and hold-to-talk works the instant the child returns. Any real
transcript resets the count, so pauses between thoughts never accumulate
toward it.

**`SILENCE_LEVEL` is untuned against real hardware** and says so in its own
comment — it cannot be tuned from a sandbox with no microphone. If turns end
too early, raise `TRAILING_SILENCE_MS` first, then lower `SILENCE_LEVEL`; if
they never end, raise `SILENCE_LEVEL`. Everything stays bounded by the 120s
safety timeout regardless, so a badly tuned threshold degrades to the old
behaviour rather than to something worse.

## Feature: continuous "Voice on" mode (opt-in, hold-to-talk stays the default)

Reported by a parent: "I don't really want to hold it down." Press-and-hold
is the well-considered default (see the "mic gets permanently stuck" and
"switches audio output" sections above for why it replaced two earlier,
less reliable designs — a plain tap-to-speak, and before that a
fully-automatic "voice mode"), but a family can now opt into a genuinely
hands-free alternative: tap the `Radio`-icon pill next to the mic
(`SocraticChat.tsx`) to switch from **Hold to talk** to **Voice on**. The
preference is per-device, stored in `localStorage`
(`useVoiceModePreference.ts`, `bede-voice-mode`) the same way as the chat
theme — deliberately *not* synced server-side to follow the student to
another tablet, since hands-free behavior is sensitive to that specific
device's own microphone/speaker setup.

**How it behaves once on:** the mic starts listening on its own the moment
it's genuinely the child's turn (nothing streaming, Bede not speaking, not
on a break, not already listening/transcribing) — no press needed. A
finished utterance sends itself immediately, bypassing the hold-to-talk
mode's Confirm/Cancel review step (holding a hands-free turn for a manual
tap would defeat the point). Tapping the mic button itself while continuous
mode is active switches straight back to hold-to-talk — a one-tap escape
hatch, not a hold gesture.

**Known gap since the server-side-streaming rewrite above:** this mode's
"a finished utterance sends itself immediately" behavior relied entirely on
browser-native recognition's own autonomous end-of-speech detection —
`start()` was called once and native's own engine decided when the turn was
over. With native removed, `start()` now needs an explicit `release()` the
same way `startHold()` always has, and this feature's own call site
(`SocraticChat.tsx`'s auto-start effect) doesn't provide one. In practice
this means a continuous-mode turn currently runs for the full 120-second
hold-safety ceiling before auto-finishing, rather than ending promptly when
the child stops talking — a real regression for this one opt-in feature
until client-side silence/voice-activity detection is built as a follow-up.
Hold-to-talk (the default for every family) is unaffected.

**Why this isn't the same bug that got the earlier "voice mode" removed:**
that design restarted listening on a **bare timer** after every turn, which
meant every restart re-ran the same timing-fragile "is the browser still
listening?" heuristics on a fixed schedule regardless of what was actually
happening — the documented cause of its recurring audio bugs. Continuous
mode's restart is instead driven entirely by an explicit **state
transition** — `SocraticChat.tsx`'s own `awaitingChildTurn` flag flipping
true, the same signal the hold-to-talk button's idle styling already uses —
never a timer. `MIN_MS_BETWEEN_AUTO_STARTS` (800ms) is defense-in-depth
against a rapid-restart loop even so. This also lands after, and directly
benefits from, two fixes earlier in this same file: the mic-stuck-after-
interruption fix and the iOS audio-session/output-routing fix, both of
which address failure classes that repeated mic opens would otherwise
aggravate.

**Circuit breaker:** `MAX_CONSECUTIVE_VOICE_FAILURES` (3) consecutive mic
failures in a row — or a single `'permission-denied'`, which no amount of
retrying fixes — automatically switches the preference back to hold-to-talk
and tells the child in a plain chat message (`chat.voiceModeFallbackMessage`),
rather than continuing to silently auto-restart into the same failure.

**Not yet built:** a UI affordance to tune recognition accuracy/language
model bias (a parent also asked for this) — that needs a specific
reproduction (what was misheard, which language/accent, native recognition
vs. the Whisper fallback) to act on, the same way every other voice fix in
this file started from a debug-panel trace rather than a general request.

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
