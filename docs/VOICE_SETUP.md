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

**What shipped**: two changes, one diagnostic and one mitigation.

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
   failure mode (2) above and reduces the *frequency* component of (1);
   it does **not** reduce the inherent cost of the final pass itself if a
   slow/shared CPU tier turns out to be the dominant factor — that would
   need a smaller Whisper model, a beefier instance, or skipping partial
   transcription entirely (a bigger, not-yet-made change). Treat this as a
   reasoned mitigation shipped alongside real diagnostics, not a confirmed
   complete fix — the next live trace with the new timing log will say
   which further step (if any) is actually needed.

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
