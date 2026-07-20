# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

**Agnus Dei / Bede** — a self-hosted, LAN-deployed Catholic Classical homeschool AI tutor. A parent configures each student's daily plan; students connect from their own tablets. Claude (Bede persona) tutors via Socratic dialogue, agentic tools, and subject-specific personas. All student data is AES-256-GCM encrypted at rest; voice biometrics authenticate children at session start.

## Bede's Constitution

Bede's persona, ethics, and limits are governed by an immutable, tamper-evident
constitution — see **[docs/CONSTITUTION.md](docs/CONSTITUTION.md)** for the full
human-readable text (Faith/Hope/Love, the seven gifts of the Holy Spirit, the
three dimensions of human formation, the non-negotiable rules). The canonical,
digest-pinned source is `homeschool-api/constitution/bede.constitution.json`;
`core/constitution.py` verifies its SHA-256 digest and structure at import
time and exposes it as recursively read-only data. `main.py`'s startup
lifespan re-verifies it explicitly before database initialization — a
missing or modified constitution prevents Bede from starting at all.
`services/ai_service.py`'s `_constitution_preamble()` renders it into every
prompt that shapes Bede's behavior: the tutor persona (`_build_static_prompt`,
part of the cached static block), the parent sandbox
(`_build_sandbox_prompt`), the session summary
(`generate_session_summary`), and learner-profile synthesis
(`synthesize_learner_profile`). No parent setting, custom instruction,
retrieved content, or child prompt can override it. Changing the
foundational substance requires the change-control process in
`docs/CONSTITUTION.md`'s "Change control" section, not just an edit.

**Never measure, score, or quantify a child's spiritual engagement or
growth.** The constitution's faith dimension (`connect_to_faith`, Piety,
Fear of the Lord, the non-negotiable "never force or trivialize" and
"informs but never replaces conscience" rules) is deliberately governed
qualitatively, by rule, not tracked as a metric — unlike, say,
`LearnerBehaviorCheck`'s per-style tool-call counts. That
pattern must not be extended to faith: a child's spiritual life comes
from the child, not from a number Bede optimizes against. If a future
change proposes any kind of "faith engagement" signal, counter, or
score, that is out of scope — raise it as a question, don't build it.

## Running the Full Stack

Full deployment instructions (Docker Compose, database choice, day-to-day
commands) live in `docs/PRODUCTION_SETUP.md` — that's the single source of
truth for `make setup`/`make update`/etc. so it doesn't drift out of sync
with a second copy here. Quick orientation: the stack is **Caddy (TLS/443)
→ nginx (UI/80) → FastAPI (API/8000)**, optionally plus a local Postgres.

## Local Development (without Docker)

**Frontend** — Vite + React + TypeScript + Tailwind, no test runner configured:
```bash
cd homeschool-tutor
npm install
npm run dev        # http://localhost:5173 with HMR
npm run build      # tsc + vite build (type errors fail the build)
npx tsc --noEmit   # type-check without building
```

**Backend** — FastAPI with async SQLAlchemy:
```bash
cd homeschool-api
pip install -r requirements.txt
cp .env.example .env   # then fill in values
uvicorn main:app --reload --port 8000
# API docs at http://localhost:8000/docs  (only when DISABLE_API_DOCS=false)
```

The API requires a live PostgreSQL connection (`DATABASE_URL`) on startup — it runs `CREATE TABLE IF NOT EXISTS` and initialises AES key material from the DB. There is no in-memory fallback.

## Required Environment Variables

All from `.env` (gitignored — never commit) — see `.env.example` for the
full, current list with comments, or `docs/PRODUCTION_SETUP.md` for the
narrative version. In production mode (`PRODUCTION=true`), the API rejects
startup if any credential matches a known-weak default, if `CHILD_PIN`/
`DEMO_PIN` isn't a strong pattern (enforced by `model_validator` in
`core/config.py` — see `pin_is_strong()` for the exact rules), or if none
of `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`MISTRAL_API_KEY`/
`LOCAL_LLM_BASE_URL` is set (`reject_no_ai_provider_configured_in_production`
— at least one AI provider is required, but never a specific one; see
`docs/PROVIDER_ADAPTERS.md`).

## Architecture

### Backend (`homeschool-api/`)

```
main.py              FastAPI app + lifespan (constitution verify, DB init, encryption init, voice-model warm-up, periodic data-retention purge — see docs/DATA_RETENTION.md)
core/
  config.py          Pydantic Settings — all env vars + production validation
  constitution.py    Verifies constitution/bede.constitution.json's SHA-256 digest + structure at import time; exposes recursively read-only data (see "Bede's Constitution" above)
  database.py        Async SQLAlchemy engine, ORM models (EncryptionConfig, VoiceProfile, StudentConfig, AuditLog, LearnerProfile, LearnerBehaviorCheck, MasteryProfile, and more — non-exhaustive list)
  encryption.py      AES-256-GCM; MASTER_SECRET → KEK → DATA_KEY hierarchy; all BYTEA columns encrypted
  audit.py           Encrypted audit log — every security event written independently of request transaction; log_event() also runs a per-IP sliding-window anomaly watch (repeated auth failures, JWT fingerprint mismatches, access-denied hits, a single ExfiltrationGuard block) and, past threshold, records AuditEvent.ANOMALY_ALERT + best-effort emails PARENT_EMAIL — see docs/SECURITY.md; log_event_nowait() fire-and-forgets the write itself (asyncio.create_task, tracked so it can't be GC'd mid-write) for hot paths like login/voice-verify where the DB round-trip must not add to response latency
  deps.py            require_auth / require_parent FastAPI dependencies (JWT + IP/UA fingerprint)
  middleware.py      SecurityHeaders, RateLimit, ExfiltrationGuard (blocks known exfiltration endpoints + scans JSON response bodies for leaked key material; SSE streams pass through untouched — see Security Constraints)
  security.py        JWT encode/decode; device fingerprint binding
routers/
  auth.py            POST /auth/login → JWT (embeds a `locale` claim chosen at the login screen itself — see docs/LOCALIZATION.md); GET /auth/validate; GET /auth/locales (public — which locale, if any, this deployment offers as a login-time toggle)
  tutor.py           POST /tutor/chat (SSE stream); POST /tutor/summary
  pod.py             CRUD /pod/configs — parent saves, child loads by name; DELETE now cascades through services/student_deletion.py to remove ALL of that student's data (narration, learner profile, mastery, transcripts, voice, usage), not just the day's config — see docs/DATA_RETENTION.md
  voice.py           POST /voice/enroll; POST /voice/verify
  admin.py           GET /admin/status; GET /admin/audit
  narration.py       Narration assessment history + learner profile: GET/POST /narration/{student}/profile, GET /narration/{student}/assessments, GET /narration/{student}/behavior-check (parent-only processing_style-adaptation observation for TRACKABLE_STYLES — see LearnerBehaviorCheck)
services/
  ai_service.py      stream_tutor_response() + generate_session_summary(); _constitution_preamble() prepends the verified constitution to every persona/summary/profile-synthesis prompt. Its module-level `_client` is resolved through services/adapters/ (resolve_with_failover()), NOT hardcoded to Anthropic — see docs/PROVIDER_ADAPTERS.md
  adapters/          Provider-adapter layer decoupling the tutor from any single LLM vendor. base.py (Anthropic-shaped vocabulary + ChatAdapter Protocol), anthropic_adapter.py (returns a real anthropic.AsyncAnthropic), openai_compatible_adapter.py (ONE class translating Anthropic↔OpenAI /v1/chat/completions — covers OpenAI, a self-hosted vLLM/Qwen3-Coder server, Mistral, any OpenAI-compatible endpoint), router.py (get_default_client() picks the first CONFIGURED adapter in BEDE_ADAPTER_ORDER — default "local,anthropic", never requires ANTHROPIC_API_KEY to boot; resolve_with_failover() is the Phase-6 failover client, and is what `services/ai_service.py`'s module-level `_client` actually resolves through). The library/self-hosted default treats a local vLLM server as primary and Anthropic as optional fallback, for the account-closure case. **The public Render demo overrides this**: `render.yaml` sets `BEDE_ADAPTER_ORDER=openai,mistral` for the `bede-demo-api` service specifically (OpenAI primary, Mistral fallback). Because `_client` is a `FailoverClient`, this is LIVE failover, not just a boot-time preference: if OpenAI errors (auth/rate-limit/connection failure) on a request, that request automatically retries against Mistral before any content streams back, with a ~60s circuit-breaker cooldown on the failed provider — see docs/PROVIDER_ADAPTERS.md (merged in PR #159; live failover wired in as a follow-up).
  moderation.py      classify_child_message() — AIUC-1 B005 automated moderation classifier (Haiku, reuses session_model/ANTHROPIC_API_KEY) run before every tutoring turn; fails open on any error, self_harm routes through the same safeguarding crisis path as check_safeguarding, prompt_injection is logged but never blocks alone — see docs/SECURITY.md
  voice_auth.py      Resemblyzer speaker embedding + MFCC similarity scoring
  transcription.py   Whisper transcription for voice enrollment phrases
  student_deletion.py  delete_all_student_data() — cascading deletion across every per-student table, called from routers/pod.py's DELETE /pod/configs/{student} (see docs/DATA_RETENTION.md)
models/
  schemas.py         Pydantic models: SessionConfig, Subject, TutorRequest, etc.
```

**AI service pattern:** Two-block system prompt with prompt caching. The static block (`_build_static_prompt`) carries Bede's persona and rules and is marked `cache_control: ephemeral` — it's reused across turns. The subject block (`_build_subject_prompt`) changes per subject and is sent fresh. Tools block is also cached. The `[START]` sentinel triggers Bede's subject opener without showing a user bubble. Morning Time's subject block also layers in two verbatim-text catalogs that rotate weekly off the calendar (ISO week number, offset by `config.current_term` so families/demo visitors don't all land on the same entry the same week) rather than off any parent-set field: `services/poetry_catalog.py` (Catholic poetry/hymn-texts, grade-tagged, also shown in Living Books — English-locale sessions only) and `services/prayer_catalog.py` (traditional Catholic prayers — English or Spanish per the session's own login-time locale, Morning Time only; see docs/LOCALIZATION.md — not a global `settings.locale` read, it's threaded through as a parameter from the JWT the request authenticated with). Both give Bede a fixed, pre-reviewed text to quote VERBATIM instead of improvising from memory, since long devotional/poetic passages are exactly what a model can subtly misquote. A non-English session gets `_native_poetry_note` in poetry's place instead (same file, wired into `_build_subject_prompt` for Morning Time/Living Books whenever `locale != "en"`): Bede composes a short original reflection or verse rather than quoting a real poet's work in a language no catalog entry covers — see docs/LOCALIZATION.md's poetry co-study section for why quoting was replaced rather than translated. This is distinct from sacred_rule #10's own daily opening/closing prayer, which stays freshly worded and personal to that day rather than a fixed recitation. `_guadalupe_note` (also in `services/ai_service.py`, wired into `_build_subject_prompt` for `Subject.saints`/`Subject.morning_time` only) is prose guidance, not verbatim stored text: when `locale == "es"` it gives Bede verified facts about Our Lady of Guadalupe and St. Juan Diego, since the app's single Spanish locale is deliberately framed as Mexican rather than pan-Hispanic-neutral — see docs/LOCALIZATION.md's "`es` is Mexican Spanish, not pan-Hispanic-neutral" section for the full scope rationale.

**Socratic follow-up pacing:** `_build_static_prompt`'s persona paragraph caps how many consecutive follow-up questions Bede asks on the very same idea before simplifying, offering a hint, or moving on — two rounds is the general outer limit, and when a child's answer opens several directions at once, Bede follows just one thread rather than all of them. `_STAGE_GUIDANCE[GradeStage.foundations]` (K-2) tightens this further: one simple, single-idea question at a time (never two things stacked into one question), and usually just one follow-up round before backing off — a Grammar-stage child is more easily lost by deep or compound questioning than an older one. See `docs/SOCRATIC_METHOD.md`'s pacing note, which teaches parents the same restraint for their own dinner-table questions.

**SSE streaming format:** Each chunk is `data: {"type":"text","content":"..."}`, `data: {"type":"tool","tool":"<name>","content":"..."}`, or `data: {"type":"done"}`. Tool calls are accumulated in a buffer, JSON-parsed at `ContentBlockStop`, then formatted and emitted.

**Agentic tools include:** `request_narration`, `invite_handwriting` (opens the tablet's writing/drawing canvas — the app's applied-practice step after dialogue: written narration, nature-notebook sketches, showing math work, per the child's `GradeStage`; also supports a structured, DITK-style mode via an optional `elements` list), `offer_socratic_hint`, `celebrate_discovery`, `connect_to_faith`, `show_visual_aid`, `assess_narration`, `suggest_next_subject`, `record_skill_evidence`. The first five render as styled cards in the UI (not chat bubbles); `assess_narration` is silent (server-side only); `record_skill_evidence` is stricter still — it emits nothing to the SSE stream at all, silently persisting math-skill diagnostic evidence via `_record_skill_evidence` (`services/ai_service.py`), which routes to exactly one of two backends: the real, db-backed `services/diagnostic/` (parent/child sessions) or the demo's in-memory `services/diagnostic_demo.py` (demo_code sessions only) — see `docs/diagnostic/`.

**processing_style adaptation:** `_processing_style_note` (`services/ai_service.py`) nudges Bede's tool choice per the synthesized learner profile — kinesthetic (favor `invite_handwriting` WITH `elements`, a structured DITK task), reading_writing (favor `invite_handwriting` WITHOUT `elements`, plain written narration), visual (favor `show_visual_aid` when this subject has one available), auditory (favor oral narration/discussion/recitation — a behavioral nudge only, no tool call to count). For the three tool-backed styles, each matching call also increments `LearnerBehaviorCheck` (`_increment_behavior_check`; row lifecycle in `routers/narration.py`'s `TRACKABLE_STYLES`/`_sync_behavior_check`) — a minimal, parent-only, encrypted count of whether that profile's own nudge is actually changing Bede's behavior, surfaced on the Progress page. It is deliberately not a psychometric claim that any of these labels improves learning, and auditory is deliberately excluded from the counter — no honest tool-level signal exists for it (almost all ordinary Socratic dialogue already is auditory).

**companion_mode (setup-time preset):** `SessionConfig.companion_mode` (`models/schemas.py`) is a parent-chosen starting point at setup — `ParentSetup.tsx`'s preset picker ("Book Companion" / "A Bit More Structure" / "Full Daily Plan") — for how much of the day Bede should drive versus defer to the family's own physical books. Picking a preset pre-fills the subject list and session length below it (both remain freely editable, and the preset doesn't itself restrict which subjects can be picked). `full_plan` is the default and the only value that existed before this field — `_companion_mode_note` (`services/ai_service.py`, wired into the STATIC prompt block, `_build_static_prompt`, not the per-subject block, since it's a session-long framing) returns `""` for it, so today's prompt is byte-for-byte unchanged for every family that never touches this setting. `book_companion`/`guided` add a `<companion_mode_guidance>` block nudging Bede to anchor questions on whatever the family is already reading (via `current_unit`/`lesson_focus`) and keep a lighter tool-call footprint — meant for families new to homeschooling, or adopting AI deliberately and cautiously, per `docs/PARENT_SETUP.md`'s §5.

### Frontend (`homeschool-tutor/src/`)

```
App.tsx              React Router routes + RequireAuth guard + GlobalAuthInterceptor (401 → logout)
guards/
  AppShell.tsx       Token validation on mount + inactivity timeout (30 min) — sets ready:true before rendering
pages/
  Login.tsx          Parent password / child PIN tabs; voice-verify phase if voice_required
  ParentSetup.tsx    Configure up to 10 students per pod with subject/grade/context; each student card opens with a companion_mode preset picker (Book Companion / A Bit More Structure / Full Daily Plan) that pre-fills subjects + session length, still freely editable after
  PodDashboard.tsx   Per-student "Open on This Device" + "Copy Link for Tablet" + "Delete all data…" (type-to-confirm modal, calls the cascading DELETE — see docs/DATA_RETENTION.md)
  TutorSession.tsx   Main session view — timer, subject sidebar, chat, break overlay; shows `MeetBede` full-screen in place of the break/summary overlays + `SocraticChat` whenever `showIntro` (child role, not yet seen this device, or reopened via the header's "?" button) is true; root container uses `h-dvh` (dynamic viewport height), not `h-screen`/`100vh` — the fixed unit is routinely taller than what's actually visible on mobile Safari/Chrome whenever the address-bar chrome is showing, which pushed the header into the page's own scroll; `BREAK_INACTIVITY_LOGOUT_MS` (5 min) force-logs-out either role if nothing touches the page while a break overlay is showing — deliberately shorter than `AppShell.tsx`'s own 30-minute general inactivity timeout, which stays generous for active learning (reading/thinking time) since it applies session-wide, not just during a break; the header's `DebugOverlay` toggle (`showDebug`) is deliberately set apart from every real session control next to it (a `border-l` divider, muted gray-300 vs. the header's usual gray-400/navy accents) — a developer/tester tool a family will never need, not something to mix in among the things they actually tap during a lesson (mirrors the demo's own `App.tsx`)
  Progress.tsx       Parent-only: narration history, learner profile (+ behavior-check observation for kinesthetic/reading_writing/visual profiles), math mastery summary, AI usage — non-exhaustive, see the page itself
components/
  SocraticChat.tsx   Chat UI + SSE stream consumer + Bede opener ([START] sentinel); press-and-hold mic (`useHybridVoiceInput`'s `holdStart`/`holdEnd`) shows a Confirm/Cancel review step before sending rather than sending on release, and calls `stopSpeech()` synchronously on `holdStart` so a child can barge in over Bede's TTS mid-sentence; `DebugOverlay`'s own toggle lives in `TutorSession.tsx`'s header, not here — see that entry below for why; a denied/unavailable microphone (`useHybridVoiceInput`'s `micError`) surfaces as a plain-language chat message rather than the mic button silently doing nothing; the scroll-to-bottom effect reacts to the live voice-input state (`isListening`/`interim`/`isTranscribing`/`pendingVoiceTranscript`), not just new messages, so the child's own live transcript can't render below the fold with nothing bringing it into view. A `Radio`-icon pill (next to the mic) toggles `useVoiceModePreference`'s opt-in continuous "Voice on" mode — off (hold-to-talk) by default for every family. When on, a `useEffect` keyed off `awaitingChildTurn` (itself already gated on `!isStreaming && !isSpeaking && !isListening && !isTranscribing && !breakActive`) calls `start()` automatically once it's genuinely the child's turn, and `onFinal` sends the transcript straight through (via a `sendRef` forward-reference, bypassing the hold-to-talk review step, since hands-free is the whole point) instead of holding it for Confirm/Cancel. Restart is driven entirely by that state transition, never a bare timer — the specific difference from an earlier, since-removed "voice mode" that auto-restarted on an interval and bred recurring audio bugs (see `useHybridVoiceInput.ts`'s own comment on why press-and-hold replaced it); `MIN_MS_BETWEEN_AUTO_STARTS` (800ms) is defense-in-depth against a rapid-restart loop regardless. `MAX_CONSECUTIVE_VOICE_FAILURES` (3) — or a single `'permission-denied'` — falls back to hold-to-talk automatically with a chat message (`chat.voiceModeFallbackMessage`) rather than continuing to auto-restart into the same failure — see `docs/VOICE_SETUP.md`'s continuous-mode section.
  MeetBede.tsx       One-time, skippable "Meet Bede" introduction (mic/pencil/breaks/safety, condensed from docs/CHILD_GUIDE.md) shown before a child's first-ever session on a device — see `useMeetBede.ts`. Demo is deliberately excluded: its sessions are short `demo_code` previews with no persistent per-student identity to gate "has this child seen it" against.
  DebugOverlay.tsx   Fixed-position, screenshot-able voice-flow debug panel (monospace, green-on-black) fed by `hooks/debugBus.ts`'s pub/sub ring buffer; Clear/Close controls
  SessionTimer.tsx   Countdown display; grade-aware (K-3 vs 4-8)
  SubjectNav.tsx     Sidebar subject list with completion tracking
  VoiceVerification.tsx  Child voice passphrase check at session start
  VoiceEnrollment.tsx   Parent-triggered enrollment flow
  ThemePicker.tsx    Chat-header palette: background theme + reader's bubble color (hidden in child sessions when SessionConfig.appearance_locked)
store/
  sessionStore.ts    Zustand store (persisted to sessionStorage — auth fields only)
services/
  api.ts             fetch wrappers for all REST endpoints; `streamTutorChat` logs the `local_date`/`local_time_of_day` it's about to send via `debugBus.logDebug()` — previously untraceable, so a "wrong greeting" or "wrong week's poem" report had no way to show what the client thought "now" was
  voiceApi.ts        Voice enrollment/verification API calls
hooks/
  useSpeechRecognition.ts  Web Speech API (Chrome/Edge/Safari); interim results
  useTextToSpeech.ts       Browser TTS for Bede's responses
  useVoiceRecorder.ts      MediaRecorder for voice enrollment audio; recordings capped at 120s (`MAX_RECORDING_MS`/`HOLD_SAFETY_TIMEOUT_MS`); `getUserMedia()` rejection is classified (`onError` callback, `'permission-denied'` vs `'unavailable'`) rather than only logged — see docs/VOICE_SETUP.md's mic-permission troubleshooting section
  useHybridVoiceInput.ts   Press-and-hold (walkie-talkie) mic: native Web Speech API with recorder+Whisper fallback; `debugBus.logDebug()` calls at every guard/branch for `DebugOverlay`; surfaces a denied/unavailable microphone as `micError` (native's own `'not-allowed'` code specifically, or the recorder's `onError` once its fallback is the active attempt) instead of leaving `mode` stuck with the mic looking permanently mid-press — native's `'service-not-allowed'` deliberately still falls through to the recorder fallback instead (a narrower "speech recognition service unavailable" signal, e.g. iOS in-app browsers, distinct from the mic permission itself being blocked) rather than assuming the mic is blocked before ever trying, see docs/VOICE_SETUP.md's in-app-browser section; the recorder fallback's `onComplete` wraps its transcription call in `try`/`catch`/`finally` (a rejected call used to strand `mode` at `'transcribing'` forever) and a `RECORDING_SAFETY_TIMEOUT_MS` (10s) backstops the rarer case where `onComplete` never runs at all — see docs/VOICE_SETUP.md's "permanently stuck after the child interrupts Bede" section; a `mode`-driven effect calls `utils/audioSession.ts`'s `enterRecordingAudioSession()`/`restorePlaybackAudioSession()` on every listening start/stop so opening the mic on iOS/iPadOS Safari doesn't leave Bede's TTS permanently rerouted to the device's built-in speaker instead of the family's actually-selected output — see docs/VOICE_SETUP.md's "switches from the family's chosen output" section; `NATIVE_STALL_TIMEOUT_MS` (2500ms, down from 4000ms) is permanently disarmed by the first interim result so lowering it only affects a hold that's produced nothing at all yet, and `release()` itself surfaces a third `MicError` value, `'no-speech-heard'`, when a real (`MIN_HOLD_MS_FOR_NO_SPEECH_FEEDBACK`, 1200ms+) hold is released with nothing captured and the watchdog hasn't fired yet — see docs/VOICE_SETUP.md's "a real, multi-second answer produces nothing at all" section
  useChatTheme.ts          localStorage-backed theme/bubble preference (CHAT_THEMES, BUBBLE_COLORS; instances synced via window event)
  useVoiceModePreference.ts  localStorage-backed hold-to-talk vs. continuous "Voice on" preference (`bede-voice-mode`, per-device not per-student — deliberately doesn't follow the student to another tablet, since hands-free behavior is device-mic-sensitive), same window-event-sync pattern as `useChatTheme.ts`; consumed by `SocraticChat.tsx` — see that entry above and `docs/VOICE_SETUP.md`
  useMeetBede.ts           localStorage-backed, per-student, per-device flag (`hasSeenMeetBede`/`markSeen`) gating `MeetBede`'s one-time appearance; versioned key prefix so future content changes can force re-display
  debugBus.ts              Pub/sub ring-buffer logger (`logDebug`, `subscribeDebug`, `clearDebugEntries`, `MAX_ENTRIES=100`) backing `DebugOverlay`
utils/
  gradeTimer.ts      Session hard stop for every grade (SessionConfig.session_cap_minutes: 2h default, 4h schema-enforced max) + mandatory 10-min break each hour; K-3 additionally paces subjects in 20-min blocks
  breakActivities.ts Off-screen break suggestions (nature / faith / eyes / movement rotation)
  audioSession.ts    Best-effort wrapper around WebKit's `navigator.audioSession` (iOS/iPadOS 17+ only, feature-checked + try/catch elsewhere): `enterRecordingAudioSession()`/`restorePlaybackAudioSession()`, called from `useHybridVoiceInput.ts` — see that hook's own entry above and docs/VOICE_SETUP.md
types/
  index.ts           Subject enum, SessionConfig interface, SUBJECTS array, SUBJECT_MAP
```

### Key Frontend Flows

**Child session URL flow:** Parent copies `/session?student=Emma` to tablet → `RequireAuth` redirects to `/?returnTo=%2Fsession%3Fstudent%3DEmma` → child logs in with PIN → `fetchStudentConfig` loads config → navigate to session. `AppShell` deliberately does NOT redirect unauthenticated users (that's `RequireAuth`'s job — a prior bug where AppShell did this stripped the `returnTo` param).

**Zustand store:** `persist` middleware saves only `{token, role, sessionConfig, podStudents}` to `sessionStorage`. Chat history and streaming state are never persisted. `getApiMessages(displayMessages, subjectStart)` slices the message array to the current subject's history before sending to the API.

**Subject opener:** `openerFiredRef = useRef(new Set<string>())` gates exactly one `[START]` send per subject. `sendOpener` reads live store state via `useSessionStore.getState()` (not the hook closure) to avoid stale-closure issues during streaming.

**Streaming state machine:**
```
startAssistantStream() → adds empty 'streaming-response' placeholder
appendAssistantChunk() → mutates placeholder content
addToolMessage()       → finalizes placeholder text, inserts tool card, reopens placeholder
finalizeAssistantMessage() → promotes placeholder to a real message, sets isStreaming=false
```

## Models

Which model actually serves a tutor turn now depends on `services/adapters/` (see
above) — the first *configured* adapter in `BEDE_ADAPTER_ORDER` wins, and each
adapter has its own model setting in `core/config.py`:

- **Anthropic** (`tutor_model`/`session_model`) — `claude-sonnet-4-6` (streaming,
  `max_tokens: 400`, tight for Mater Amabilis brevity) /
  `claude-haiku-4-5-20251001` (non-streaming, `max_tokens: 600`, end-of-session
  parent report). This is the model pair a self-hosted deployment gets when
  `anthropic` resolves (the library default, `local,anthropic`, falls through
  to this once `ANTHROPIC_API_KEY` is the only thing configured).
- **OpenAI** (`openai_model`, default `gpt-4.1-mini`) and **Mistral**
  (`mistral_model`, default `mistral-large-latest`) — the models the public
  Render demo actually uses in production, since its
  `BEDE_ADAPTER_ORDER=openai,mistral` (OpenAI primary, Mistral as the live
  failover if OpenAI errors mid-request).
- **Local** (`local_llm_model`, default `Qwen/Qwen3-Coder-30B-A3B-Instruct`) —
  the self-hosted vLLM option; needs a GPU (see docs/PROVIDER_ADAPTERS.md's
  hardware tiers).

To change which model a given adapter uses, update its `*_model` setting in
`core/config.py`; to change which adapter wins, update `BEDE_ADAPTER_ORDER`
(or `render.yaml`'s copy of it for the demo).

## Security Constraints

For the audit-facing view of this section — AIUC-1/SOC 2 control mapping,
the Society-pillar scope statement, and tracked open compliance gaps —
see **[docs/SECURITY.md](docs/SECURITY.md)**. If something has actually
gone wrong, or you've found a vulnerability in Bede's code, see
**[docs/INCIDENT_RESPONSE.md](docs/INCIDENT_RESPONSE.md)** and the
root-level **[SECURITY.md](SECURITY.md)**. For the dependency SBOM and
what actually flows to Anthropic/OpenAI/Mistral/Resend at runtime (or
nothing at all, for the self-hosted local model option), see
**[docs/VENDOR_DATA_FLOW.md](docs/VENDOR_DATA_FLOW.md)**
(`docs/sbom/`, regenerable via `scripts/generate_sbom.py`). For live
red-team probing of the actual tutoring persona against the real model
(costs real API money, not part of the test suite or CI), see
`scripts/adversarial_probe.py` and its transcripts/findings in
`docs/adversarial-probes/`.

- `.env`, `.env.backup`, `.env.local` are gitignored — never commit them
- JWTs are IP + User-Agent fingerprinted at issuance; replaying from a different device returns 401
- Auth credential comparisons use `hmac.compare_digest()` (constant-time)
- `ExfiltrationGuard` middleware blocks known exfiltration endpoints (`/export`, `/download`, `/dump`, `/backup`, `/debug`) and, for buffered JSON responses only, scans the body for leaked key material (`embedding` arrays, `data_key`, `device_salt`, the SAGE encrypted-file magic) before returning it — capped at 2MB. It deliberately does NOT buffer or re-scan `text/event-stream` (the `/tutor/chat` SSE stream): prompt-injection defense for that path relies on the model's own training plus the constitution's `<ethical_boundaries>` rules rather than input-side filtering. `_sanitize_parent_field`/`_INJECTION_PATTERN` (`services/ai_service.py`) strip injection phrasing out of *parent*-supplied `SessionConfig` fields specifically (`faith_emphasis`, `lesson_focus`, `current_unit`, topics) — those sit in the cached static prompt block for the whole session — but never the child's own live per-turn chat text; there's no server-side secret in Bede's context for a jailbroken turn to leak in the first place. Credential-shaped text (API keys, tokens, connection strings) is a separate concern with different scope: `_redact_credentials` (also `services/ai_service.py`, AIUC-1 control A008) redacts it wherever free text enters the backend — `child_message`, replayed `conversation_history`, and the `/transcripts` save path — see `docs/SECURITY.md`. The child's live chat text does get one real-time layer beyond the model's own training: `services/moderation.py`'s `classify_child_message()` (AIUC-1 B005) runs a Haiku classification on every turn before it reaches the tutor, redirecting (not just logging) for self_harm/violence/sexual_content/hate_or_harassment — but its own `prompt_injection` category is deliberately logged only, never blocking alone, so the "no input-side filtering for injection" reasoning above still holds for that specific category.
- The `sage` container user has no shell; containers run `read_only: true`, `cap_drop: ALL`
- Voice profiles and student configs are stored as AES-256-GCM BYTEA — the database provider never sees plaintext

## Adding a New Subject

1. `models/schemas.py` — add to `Subject` enum, `SUBJECT_DURATIONS`, `SUBJECT_LABELS`
2. `services/ai_service.py` — add to `_SUBJECT_CONTEXT` dict
3. `homeschool-tutor/src/types/index.ts` — add to `Subject` type, `SUBJECTS` array, and `SUBJECT_MAP`

## Standing Workflow: Root-Cause Fixes

When you find and fix a root cause (a bug, a performance issue, etc.) in
this repo, don't stop at opening a PR and waiting — drive it to done:

1. **Test first.** Verify the fix actually resolves the issue before doing
   anything else. Prefer a real end-to-end check over a code-reading
   argument — e.g. for a GitHub Actions workflow, trigger it for real
   (`workflow_dispatch`) and read the job logs, rather than asserting the
   YAML "looks right." If a live check isn't reachable from the sandbox,
   say so explicitly rather than claiming full verification.
2. **Open a PR** once the fix is confirmed to work, with a test plan in the
   body describing exactly what was verified and how.
3. **Merge it automatically** — do not wait for manual approval on this
   repo. This authorization stands until the user says otherwise.
4. **Tell the user** once it's merged (and, where applicable, live) so they
   can do their own testing.

This is a standing rule for this repo across sessions, not a one-off for
whichever task prompted it.

## Standing Workflow: Feature Documentation

Every feature or user-facing behavior change introduced to this repo needs
to be documented as part of that same change — not left as a follow-up. A
feature is not done until its documentation is:

1. **Parent-facing controls and behavior** — `docs/PARENT_SETUP.md` (the
   per-student settings live in §5 "Setting up each student"). Written as
   plain instructions to a non-technical parent.
2. **Child-facing features** (anything the learner sees or uses) —
   `docs/CHILD_GUIDE.md`, keeping its voice: Bede speaking directly and
   warmly to the child, no jargon.
3. **Setup/troubleshooting-relevant change** (voice, auth, deployment,
   backup, etc.) — update the relevant file in `docs/` (e.g. a voice-
   pipeline reliability fix belongs in `docs/VOICE_SETUP.md`, not just the
   commit message).
4. **Architectural/config change** (a new router, frontend flow, service
   module, table, SessionConfig field, or env var) — update the relevant
   subsection under `## Architecture` above so this file keeps matching
   the real codebase.
5. **Anything else user-facing** — put it somewhere it will actually be
   found later (an existing doc if one fits, a new one if none does). A
   thorough PR description is not a substitute — PRs get buried in git
   history; docs are what the next person (or session) actually reads.

Also check whether the change makes existing doc text stale (e.g. a new
setting that replaces "this isn't configurable") and fix that text in the
same change.

This is a standing rule for this repo across sessions, not a one-off for
whichever change prompted it.
