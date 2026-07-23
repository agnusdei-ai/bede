# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

**Agnus Dei / Bede** — a self-hosted, LAN-deployed, Charlotte Mason-inspired classical homeschool AI tutor. A parent configures each student's daily plan; students connect from their own tablets. Claude (Bede persona) tutors via Socratic dialogue, agentic tools, and subject-specific personas. All student data is AES-256-GCM encrypted at rest; voice biometrics authenticate children at session start.

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
startup if any credential matches a known-weak default, if `SECRET_KEY`/
`MASTER_SECRET` is under 32 characters or `PARENT_PASSWORD` is under 8
(`reject_weak_defaults_in_production`), if `CHILD_PIN`/`DEMO_PIN`/
`SANDBOX_PIN` isn't a strong pattern (same validator — see `pin_is_strong()`
for the exact rules), if `DISABLE_API_DOCS` isn't `true` or `CORS_ORIGINS`
contains a wildcard (`reject_exposed_docs_and_wildcard_cors_in_production`
— the wildcard check runs outside production too), or if none of
`ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`MISTRAL_API_KEY`/
`LOCAL_LLM_BASE_URL` is set (`reject_no_ai_provider_configured_in_production`
— at least one AI provider is required, but never a specific one; see
`docs/PROVIDER_ADAPTERS.md`). All four validators live in `core/config.py`.

## Architecture

### Backend (`homeschool-api/`)

```
main.py              FastAPI app + lifespan (constitution verify, DB init, encryption init, voice-model warm-up, periodic data-retention purge — see docs/DATA_RETENTION.md)
core/
  config.py          Pydantic Settings — all env vars + production validation
  constitution.py    Verifies constitution/bede.constitution.json's SHA-256 digest + structure at import time; exposes recursively read-only data (see "Bede's Constitution" above)
  database.py        Async SQLAlchemy engine, ORM models (EncryptionConfig, VoiceProfile, StudentConfig, AuditLog, LearnerProfile, LearnerBehaviorCheck, MasteryProfile, ParentSecurityKey, ParentTotpConfig, ParentCredentialOverride, ParentRecoveryCode, ParentRecoveryPin, ParentLoginLockout, and more — non-exhaustive list)
  encryption.py      AES-256-GCM; MASTER_SECRET → KEK → DATA_KEY hierarchy; all BYTEA columns encrypted
  audit.py           Encrypted audit log — every security event written independently of request transaction; log_event() also runs a per-IP sliding-window anomaly watch (repeated auth failures, JWT fingerprint mismatches, access-denied hits, a single ExfiltrationGuard block, a burst of tool invocations, one suppressed tool call, or 3 adversarial-pipeline detections — see services/ai_service.py and services/policy_engine.py below) and, past threshold, records AuditEvent.ANOMALY_ALERT + best-effort emails PARENT_EMAIL — see docs/SECURITY.md; log_event_nowait() fire-and-forgets the write itself (asyncio.create_task, tracked so it can't be GC'd mid-write) for hot paths like login/voice-verify, and every tool invocation during a tutoring turn, where the DB round-trip must not add to response latency
  deps.py            require_auth / require_parent / require_parent_recovery FastAPI dependencies (JWT + IP/UA fingerprint). require_auth also checks a 'cv' (credentials_version) claim on parent/parent_pending tokens against core/parent_credential.py's cached current value — a mismatch means the password changed since this token was issued, and 401s it immediately rather than letting it linger to natural expiry; see "Parent account lockout & recovery" below
  license_state.py   Effective-license resolution: DB-applied key (POST /admin/license) wins over env LICENSE_KEY; unlicensed production boots GATED instead of refusing (renewal is pasted into the parent UI, no .env edit)
  parent_credential.py  DB-backed PARENT_PASSWORD override — same "DB value wins over env, live, no restart" precedent as license_state.py, applied to the password so it's actually changeable in-app for the first time. Caches credentials_version in-process (refreshed at startup and on every change) so core/deps.py's per-request check is a sync int comparison, not a DB round trip. See "Parent account lockout & recovery" below.
  parent_lockout.py  DB-backed account lockout for the parent role (10 failures/30min window → 15min lock) — the piece core/audit.py's E009 anomaly watch never provided (it alerts, never blocks). DB-backed, unlike the anomaly watch's in-memory window, so a restart can't reset an attacker's progress. See "Parent account lockout & recovery" below.
  credential_hash.py  PBKDF2-HMAC-SHA256 hash/verify for verify-only secrets (the parent password override, the recovery code) — reuses core/encryption.py's exact KDF primitive. Strictly stronger than this app's usual reversible AES-256-GCM encrypt_json for a secret that never needs to be read back in plaintext.
  middleware.py      SecurityHeaders, RateLimit (per-IP sliding window; `/voice/stream/{id}/chunk|finish|events` — the mechanics of an already-approved streaming-transcription session — get their own, more generous `voice_stream_session` bucket, separate from `voice`'s stricter new-session-start budget; see docs/VOICE_SETUP.md's rate-limit regression section for why), LicenseGate (unlicensed production → only login/MFA + license endpoints answer), ExfiltrationGuard (blocks known exfiltration endpoints + scans JSON response bodies for leaked key material; SSE streams pass through untouched — see Security Constraints)
  security.py        JWT encode/decode; device fingerprint binding
routers/
  auth.py            POST /auth/login → JWT (embeds a `locale` claim chosen at the login screen itself — see docs/LOCALIZATION.md, and a `cv` credentials_version claim for parent/parent_pending — see core/deps.py above); GET /auth/validate; GET /auth/locales (public — which locale, if any, this deployment offers as a login-time toggle). login() also checks/records core/parent_lockout.py state and resolves the password via core/parent_credential.py (DB override wins over env) — see "Parent account lockout & recovery" below.
  mfa.py             Parent MFA enrollment/login-completion (FIDO2 security keys + TOTP, services/mfa_service.py) plus, as of "Parent account lockout & recovery" below: POST /mfa/change-password (a full parent session changing its own password — core/parent_credential.py), POST /mfa/recovery-pin/enroll + DELETE /mfa/recovery-pin and POST /mfa/recovery-code/enroll + DELETE /mfa/recovery-code (the mutually-exclusive "something you know" leg of account recovery, services/parent_recovery.py — enrolling one clears the other). GET /mfa/status now also reports recovery_secret ("pin" | "code" | null).
  recovery.py        Public (unauthenticated by necessity — a locked-out parent has no session), narrowly-scoped account-recovery flow: GET /auth/recovery/methods (which factors are enrolled — booleans only), POST /auth/recovery/webauthn/options, POST /auth/recovery/verify (requires proving >=2 of {recovery code, TOTP, WebAuthn} — never one alone; issues a short-lived "parent_recovery" token good for exactly one thing), POST /auth/recovery/reset-password (require_parent_recovery-gated, sets a new password via core/parent_credential.py). See "Parent account lockout & recovery" below.
  tutor.py           POST /tutor/chat (SSE stream) — safeguarding regex → moderation classifier → Policy Engine (services/policy_engine.py) → stream_tutor_response, see "Adversarial resilience pipeline" below; POST /tutor/summary
  pod.py             CRUD /pod/configs — parent saves, child loads by name; DELETE now cascades through services/student_deletion.py to remove ALL of that student's data (narration, learner profile, mastery, transcripts, voice, usage), not just the day's config — see docs/DATA_RETENTION.md
  voice.py           POST /voice/enroll; POST /voice/verify; POST /voice/stream/start, POST /voice/stream/{id}/chunk, POST /voice/stream/{id}/finish, GET /voice/stream/{id}/events (SSE) — server-side streaming transcription, the ONLY voice-input path for the tutor mic since browser-native SpeechRecognition was removed entirely, see services/streaming_transcription.py below and docs/VOICE_SETUP.md
  admin.py           GET /admin/status; GET /admin/audit; GET+POST /admin/license (in-app license view/renew — verified offline, stored in LicenseConfig, effective immediately)
  narration.py       Narration assessment history + learner profile: GET/POST /narration/{student}/profile, GET /narration/{student}/assessments, GET /narration/{student}/behavior-check (parent-only processing_style-adaptation observation for TRACKABLE_STYLES — see LearnerBehaviorCheck)
  feedback.py        GET /feedback/enabled (public, gates whether the frontend shows any feedback UI at all); POST /feedback — any authenticated role (parent, child, demo visitor), routed via `services/email_service.py` to `FEEDBACK_EMAIL` over Resend, never persisted server-side beyond that one outbound email. `FeedbackRequest.category` (`models/schemas.py`) covers ordinary in-use feedback (cx/ux/content_quality/other), the demo's own "interested in plans" lead capture (`plans`) and end-of-session survey (`beta_close`), and a real beta family's one-time setup-completion intake (`onboarding` — see `ParentSetup.tsx`/`BetaIntakeModal.tsx` above) — each gets its own email subject-line prefix (`_feedback_prefix`) so the operator's inbox stays triageable at a glance.
services/
  ai_service.py      stream_tutor_response() + generate_session_summary(); _constitution_preamble() prepends the verified constitution to every persona/summary/profile-synthesis prompt. Its module-level `_client` is resolved through services/adapters/ (resolve_with_failover()), NOT hardcoded to Anthropic — see docs/PROVIDER_ADAPTERS.md
  adapters/          Provider-adapter layer decoupling the tutor from any single LLM vendor. base.py (Anthropic-shaped vocabulary + ChatAdapter Protocol), anthropic_adapter.py (returns a real anthropic.AsyncAnthropic), openai_compatible_adapter.py (ONE class translating Anthropic↔OpenAI /v1/chat/completions — covers OpenAI, a self-hosted vLLM/Qwen3-Coder server, Mistral, any OpenAI-compatible endpoint), router.py (get_default_client() picks the first CONFIGURED adapter in BEDE_ADAPTER_ORDER — default "local,anthropic", never requires ANTHROPIC_API_KEY to boot; resolve_with_failover() is the Phase-6 failover client, and is what `services/ai_service.py`'s module-level `_client` actually resolves through). The library/self-hosted default treats a local vLLM server as primary and Anthropic as optional fallback, for the account-closure case. **The public Render demo overrides this**: `render.yaml` sets `BEDE_ADAPTER_ORDER=openai,mistral` for the `bede-demo-api` service specifically (OpenAI primary, Mistral fallback). Because `_client` is a `FailoverClient`, this is LIVE failover, not just a boot-time preference: if OpenAI errors (auth/rate-limit/connection failure) on a request, that request automatically retries against Mistral before any content streams back, with a ~60s circuit-breaker cooldown on the failed provider — see docs/PROVIDER_ADAPTERS.md (merged in PR #159; live failover wired in as a follow-up).
  moderation.py      classify_child_message() — AIUC-1 B005 automated moderation classifier (Haiku, reuses session_model/ANTHROPIC_API_KEY) run before every tutoring turn; fails open on any error, self_harm routes through the same safeguarding crisis path as check_safeguarding, prompt_injection is logged but never blocks alone — see docs/SECURITY.md. Its taxonomy also carries four adversarial-resilience categories (jailbreak_intent, policy_override_attempt, data_exfiltration_attempt, social_engineering) that `_BLOCKING_CATEGORIES`/`should_block` deliberately do NOT act on — those are read out of this same classification result by services/policy_engine.py instead, so adding them cost no second LLM call. See "Adversarial resilience pipeline" below.
  adversarial_detection.py  Tier 1 of the adversarial-resilience pipeline — free, instant, deterministic regex (`detect_tier1`) for the same four categories above, curated for near-zero false positives against ordinary K-8 Socratic dialogue; still catches the bluntest attack phrasings during a moderation-classifier outage, when Tier 2 (moderation.py, above) is unavailable. `build_signals()` merges a Tier 1 pass with the already-computed Tier 2 result into one `AdversarialSignals` for policy_engine.py — no second classifier call.
  policy_engine.py   Tier-agnostic policy stage — `decide(signals) -> PolicyDecision`. Pure function, no I/O: policy_override_attempt/data_exfiltration_attempt redirect the turn (Tier 1 hit OR Tier 2 at medium+ confidence); jailbreak_intent/social_engineering never redirect alone, mirroring moderation.py's own prompt_injection treatment — see "Adversarial resilience pipeline" below and docs/SECURITY.md.
  voice_auth.py      Resemblyzer speaker embedding + MFCC similarity scoring
  parent_recovery.py  The "something you know" leg of the >=2 factors routers/recovery.py's account-recovery flow requires — a parent picks ONE of two mutually exclusive shapes at enrollment: a recovery PIN (favored — short, parent-chosen, memorable, same pin_is_strong() floor as CHILD_PIN) or a recovery code (the alternative — longer, machine-generated, higher entropy). Enrolling either clears the other; both hashed via core/credential_hash.py, shown/settable once. Deliberately independent of both PARENT_PASSWORD and CHILD_PIN. See "Parent account lockout & recovery" below.
  transcription.py   faster-whisper transcribe_audio() — used directly for voice enrollment phrases, and as the underlying per-chunk transcription call streaming_transcription.py's worker loop makes repeatedly
  streaming_transcription.py  In-memory, per-session, worker-loop-coalescing state behind POST/GET /voice/stream/* above: push_chunk()/finish_session() are synchronous and just update state + set an asyncio.Event, while a single long-running worker task per session re-transcribes the WHOLE growing audio buffer (faster-whisper is batch-only, no native incremental-streaming mode) each time new audio arrives, coalescing rapid chunk uploads into "transcribe the latest buffer once free" rather than queueing overlapping Whisper calls; each pass logs its own `elapsed=` duration (`session=`/`pass=partial|final`/`audio_bytes=`) — added after a reported "Transcribing…" delay with no server-side visibility into whether the final pass itself was slow or queued behind an in-flight partial, see docs/VOICE_SETUP.md's transcription-delay section; events() is an async generator the router wraps in EventSourceResponse (see core/sse_utils.py's with_stall_timeout, same pattern as /tutor/chat). Single-process, in-memory only — sessions don't survive routing to a different instance under horizontal scaling; a TTL sweep (180s idle) evicts abandoned sessions. Each session carries an `owner` (routers/voice.py's `_stream_owner` — a demo visitor's unique `code`, or `role` for the single-shared-credential parent/child roles) set at `start_session()` and checked on every subsequent chunk/finish/events call, closing an IDOR-shaped gap where any authenticated caller could act on another session's id if they somehow learned it — a mismatch reads identically to "unknown session" rather than confirming the id exists (see docs/SECURITY.md's "Closed gaps"). See docs/VOICE_SETUP.md's "server-side streaming transcription" section for the full design rationale and history.
  student_deletion.py  delete_all_student_data() — cascading deletion across every per-student table, called from routers/pod.py's DELETE /pod/configs/{student} (see docs/DATA_RETENTION.md)
models/
  schemas.py         Pydantic models: SessionConfig, Subject, TutorRequest, etc.
```

**AI service pattern:** Two-block system prompt with prompt caching. The static block (`_build_static_prompt`) carries Bede's persona and rules and is marked `cache_control: ephemeral` — it's reused across turns. The subject block (`_build_subject_prompt`) changes per subject and is sent fresh. Tools block is also cached. The `[START]` sentinel triggers Bede's subject opener without showing a user bubble. Morning Time's subject block also layers in two verbatim-text catalogs that rotate weekly off the calendar (ISO week number, offset by `config.current_term` so families/demo visitors don't all land on the same entry the same week) rather than off any parent-set field: `services/poetry_catalog.py` (Catholic poetry/hymn-texts, grade-tagged, also shown in Living Books — English-locale sessions only) and `services/prayer_catalog.py` (traditional Catholic prayers — English or Spanish per the session's own login-time locale, Morning Time only; see docs/LOCALIZATION.md — not a global `settings.locale` read, it's threaded through as a parameter from the JWT the request authenticated with). Both give Bede a fixed, pre-reviewed text to quote VERBATIM instead of improvising from memory, since long devotional/poetic passages are exactly what a model can subtly misquote. A non-English session gets `_native_poetry_note` in poetry's place instead (same file, wired into `_build_subject_prompt` for Morning Time/Living Books whenever `locale != "en"`): Bede composes a short original reflection or verse rather than quoting a real poet's work in a language no catalog entry covers — see docs/LOCALIZATION.md's poetry co-study section for why quoting was replaced rather than translated. This is distinct from sacred_rule #10's own daily opening/closing prayer, which stays freshly worded and personal to that day rather than a fixed recitation. `_guadalupe_note` (also in `services/ai_service.py`, wired into `_build_subject_prompt` for `Subject.saints`/`Subject.morning_time` only) is prose guidance, not verbatim stored text: when `locale == "es"` it gives Bede verified facts about Our Lady of Guadalupe and St. Juan Diego, since the app's single Spanish locale is deliberately framed as Mexican rather than pan-Hispanic-neutral — see docs/LOCALIZATION.md's "`es` is Mexican Spanish, not pan-Hispanic-neutral" section for the full scope rationale.

**Socratic follow-up pacing:** `_build_static_prompt`'s persona paragraph caps how many consecutive follow-up questions Bede asks on the very same idea before simplifying, offering a hint, or moving on — two rounds is the general outer limit, and when a child's answer opens several directions at once, Bede follows just one thread rather than all of them. `_STAGE_GUIDANCE[GradeStage.foundations]` (K-2) tightens this further: one simple, single-idea question at a time (never two things stacked into one question), and usually just one follow-up round before backing off — a Grammar-stage child is more easily lost by deep or compound questioning than an older one. See `docs/SOCRATIC_METHOD.md`'s pacing note, which teaches parents the same restraint for their own dinner-table questions.

**SSE streaming format:** Each chunk is `data: {"type":"text","content":"..."}`, `data: {"type":"tool","tool":"<name>","content":"..."}`, or `data: {"type":"done"}`. Tool calls are accumulated in a buffer, JSON-parsed at `ContentBlockStop`, then formatted and emitted.

**Agentic tools include:** `request_narration`, `invite_handwriting` (opens the tablet's writing/drawing canvas — the app's applied-practice step after dialogue: written narration, nature-notebook sketches, showing math work, per the child's `GradeStage`; also supports a structured, DITK-style mode via an optional `elements` list), `offer_socratic_hint`, `celebrate_discovery`, `connect_to_faith`, `show_visual_aid`, `assess_narration`, `suggest_next_subject`, `record_skill_evidence`. The first five render as styled cards in the UI (not chat bubbles); `assess_narration` is silent (server-side only); `record_skill_evidence` is stricter still — it emits nothing to the SSE stream at all, silently persisting math-skill diagnostic evidence via `_record_skill_evidence` (`services/ai_service.py`), which routes to exactly one of two backends: the real, db-backed `services/diagnostic/` (parent/child sessions) or the demo's in-memory `services/diagnostic_demo.py` (demo_code sessions only) — see `docs/diagnostic/`. `generate_session_summary` reads that evidence back out again: `services.diagnostic.get_session_growth` computes a per-skill before/after (session-start prior vs. session-end posterior, from `DiagnosticEvidenceLog`) whenever Mathematics was covered, and a **Math Skill Growth** section is added to the parent-facing summary reporting the real movement — never a guess, and gated to the `parent` role only (never `demo_code`, whose evidence lives in `diagnostic_demo.py`'s ephemeral store instead and whose `student_name` isn't guaranteed isolated from a real family's). Requires `settings.diagnostic_evidence_log_enabled` (on by default — see `docs/diagnostic/DIAGNOSTIC_ENGINE_DESIGN.md` §5.3).

**Tool-call defense-in-depth:** every tool call `stream_tutor_response` actually dispatches (not just attempts) is audit-logged as `AuditEvent.TOOL_INVOKED` — role, student, subject, tool name, IP/user-agent from the request — the first durable record of tool use for real (parent/child) sessions; the demo's `interaction_signals.py` structural counters are a separate, privacy-scoped, demo-only pipeline, not a substitute. `_MAX_TOOL_CALLS_PER_TURN` (6) caps how many tool calls a single turn may execute — a call past the cap is silently dropped (never executed or rendered, the child's turn is never interrupted) and logged as `AuditEvent.TOOL_CALL_SUPPRESSED`, which alerts the parent immediately (`core/audit.py`'s anomaly rules — see docs/SECURITY.md). Independent of, and a backstop under, the constitution/prompt-level guidance against misuse.

**Adversarial resilience pipeline:** `routers/tutor.py`'s `chat()` implements

```
User Input → Adversarial Detection → Policy Engine → Tutor State Machine → Action Validator → Parent/Student
```

as additive stages layered onto the pre-existing safeguarding/moderation gate, each reached only once the turn survives the one before it — no existing behavior in an earlier stage changed to build this:

- **Adversarial Detection** — two tiers, both scoped to four categories a fixed phrase list alone can't safely cover for jailbreak/policy-override/exfiltration, plus a fifth (social engineering) with no Tier 1 at all: Tier 1 is `services/adversarial_detection.py`'s `detect_tier1()`, free/instant regex; Tier 2 is `services/moderation.py`'s classifier, extended with `jailbreak_intent`/`policy_override_attempt`/`data_exfiltration_attempt`/`social_engineering` categories on the SAME single classify_child_message() call every turn already makes (no added latency or cost). Prompt injection itself is detected upstream of this pipeline and unchanged by it: `_INJECTION_PATTERN`/`_sanitize_parent_field` (`services/ai_service.py`, parent-supplied `SessionConfig` fields) plus the classifier's own `prompt_injection` category. Tool abuse detection is downstream by necessity (it needs to see actual tool calls) — that's the Action Validator stage below, not this one.
- **Policy Engine** — `services/policy_engine.py`'s `decide()`, a pure function turning `AdversarialSignals` (Tier 1 ∪ Tier 2 for this turn) into ONE `PolicyDecision`. `policy_override_attempt`/`data_exfiltration_attempt` redirect the turn (a Tier 1 hit, curated for near-zero false positives, OR a Tier 2 flag at medium+ confidence); `jailbreak_intent`/`social_engineering` never redirect alone, no matter the confidence — same reasoning `moderation.py` already documents for `prompt_injection`: ordinary K-8 roleplay/storytelling and ordinary kid impatience can resemble these categories to a classifier without being an attack, and this app's architecture has no secret for a jailbreak to actually leak. Every non-empty decision is logged as `AuditEvent.ADVERSARIAL_DETECTED` (blocking or not) — `core/audit.py`'s anomaly watch alerts a parent at 3 in 10 minutes from one IP, the same "routine boundary-testing vs. a sustained pattern" threshold `MODERATION_FLAGGED` uses.
- **Tutor State Machine** — the existing SSE dispatch loop inside `stream_tutor_response` (`services/ai_service.py`) — unchanged by this work; a turn only reaches it once Adversarial Detection/Policy Engine haven't already redirected it.
- **Action Validator** — the existing, already-shipped tool-call defense-in-depth described just above (`_MAX_TOOL_CALLS_PER_TURN`, `AuditEvent.TOOL_INVOKED`/`TOOL_CALL_SUPPRESSED`) — it validates each individual tool call the state machine actually dispatches, which is why it has to live downstream of, not inside, Adversarial Detection.
- **Parent/Student** — the SSE stream reaching `SocraticChat.tsx`, same as any other turn.

Deliberately excluded from this build: live adversarial pentesting against the running persona (humans/AI red-teamers doing that separately, outside this environment — see `scripts/adversarial_probe.py` for the existing offline probe harness). This pipeline is the deterministic/architectural defense the probing tests against, not a replacement for it.

**Parent account lockout & recovery:** answers "what actually happens if `PARENT_PASSWORD` (or the only enrolled second factor) is lost or exposed" — the gap left after the pre-production hardening pass (`docs/SECURITY.md`'s Closed gaps) made a *weak* password impossible, but said nothing about a *leaked or forgotten* one.

- **`PARENT_PASSWORD` is now changeable in-app.** It used to live only in `.env` — changing it meant a server-side file edit and a restart. `core/parent_credential.py` adds a DB-backed override that wins over the env default, live, no restart — the same precedence `core/license_state.py` already established for `LICENSE_KEY`. `POST /mfa/change-password` (`routers/mfa.py`) is a full parent session changing its own password on purpose; a deployment that never touches this sees byte-for-byte the same login behavior as before.
- **Account lockout** (`core/parent_lockout.py`) — DB-backed (survives a restart, unlike `core/audit.py`'s in-memory anomaly window), role-scoped (not per-IP — this app has exactly one parent identity, so an attacker spreading attempts across IPs should still trip it). 10 failures in a 30-minute window locks the parent role for 15 minutes; deliberately above the anomaly watch's own 5-failure email-alert threshold, so a parent who mistypes their password gets a heads-up before they'd ever actually get locked out. `routers/auth.py`'s `login()` checks/records this on every parent attempt.
- **Account recovery** (`services/parent_recovery.py`, `routers/recovery.py`) — a locked-out or password-forgetting parent's way back in without server access. Requires proving **at least 2** of three independent factors, never just one: a "something you know" secret — a recovery PIN (favored/default: short, parent-chosen, memorable, `pin_is_strong()`-checked like `CHILD_PIN`) or a recovery code (the alternative: longer, machine-generated, higher entropy) — mutually exclusive, one choice at enrollment via `POST /mfa/recovery-pin/enroll` or `POST /mfa/recovery-code/enroll`, hashed like the password override, deliberately independent of both `PARENT_PASSWORD` and `CHILD_PIN` so a leak of one doesn't expose the others — plus TOTP, or WebAuthn (both reusing `services/mfa_service.py` unchanged — a recovery-flow WebAuthn ceremony is identical to a login one). `GET /auth/recovery/methods` is public and reports only which factors are enrolled (`recovery_secret: "pin" | "code" | null`, plus totp/webauthn booleans), never enough to help guess anything. Proving 2 factors issues a narrowly-scoped `parent_recovery` token (`core/deps.py`'s `require_parent_recovery`) good for exactly one call: `POST /auth/recovery/reset-password`.
- **Voice biometrics are deliberately NOT a recovery factor.** `services/voice_auth.py`'s current speaker verification has no random challenge phrase or liveness detection — a soft, parent-overridable identity signal (see its own medium-confidence "parent can override" path), not a spoof-resistant credential a security-critical recovery flow should ever accept.
- **Credentials_version — the piece that makes recovery actually end a takeover.** Every credential change (in-app or via recovery) bumps a version counter (`core/parent_credential.py`) embedded in every parent/parent_pending JWT at issuance and checked on every request (`core/deps.py`, cached in-process — not a DB round trip per request). A mismatch 401s immediately: changing the password doesn't just add a new valid session alongside whatever an attacker might be holding, it ends every other one, including that stolen token, instantly rather than at natural expiry (up to 8h). The frontend (`ParentSecuritySettings.tsx`'s change-password form) knows this and logs the parent out immediately after a successful change, rather than letting their own next click surprise-401.
- **All secrets that only ever need verifying, never redisplaying** (the password override, the recovery code) are hashed with PBKDF2-HMAC-SHA256 (`core/credential_hash.py`, reusing the exact KDF primitive `core/encryption.py`'s key derivation already depends on) rather than this app's usual reversible AES-256-GCM `encrypt_json` — a strictly stronger property for a verify-only secret.
- **Child-role lockout/recovery is deliberately out of scope.** This app's single-tenant design makes the parent the ultimate authority over the one shared `CHILD_PIN` — "recovery" for a locked-out child is simply a parent changing it, a capability that already exists, not a gap.

**processing_style adaptation:** `_processing_style_note` (`services/ai_service.py`) nudges Bede's tool choice per the synthesized learner profile — kinesthetic (favor `invite_handwriting` WITH `elements`, a structured DITK task), reading_writing (favor `invite_handwriting` WITHOUT `elements`, plain written narration), visual (favor `show_visual_aid` when this subject has one available), auditory (favor oral narration/discussion/recitation — a behavioral nudge only, no tool call to count). For the three tool-backed styles, each matching call also increments `LearnerBehaviorCheck` (`_increment_behavior_check`; row lifecycle in `routers/narration.py`'s `TRACKABLE_STYLES`/`_sync_behavior_check`) — a minimal, parent-only, encrypted count of whether that profile's own nudge is actually changing Bede's behavior, surfaced on the Progress page. It is deliberately not a psychometric claim that any of these labels improves learning, and auditory is deliberately excluded from the counter — no honest tool-level signal exists for it (almost all ordinary Socratic dialogue already is auditory).

**companion_mode (setup-time preset):** `SessionConfig.companion_mode` (`models/schemas.py`) is a parent-chosen starting point at setup — `ParentSetup.tsx`'s preset picker ("Book Companion" / "A Bit More Structure" / "Full Daily Plan") — for how much of the day Bede should drive versus defer to the family's own physical books. Picking a preset pre-fills the subject list and session length below it (both remain freely editable, and the preset doesn't itself restrict which subjects can be picked). `full_plan` is the default and the only value that existed before this field — `_companion_mode_note` (`services/ai_service.py`, wired into the STATIC prompt block, `_build_static_prompt`, not the per-subject block, since it's a session-long framing) returns `""` for it, so today's prompt is byte-for-byte unchanged for every family that never touches this setting. `book_companion`/`guided` add a `<companion_mode_guidance>` block nudging Bede to anchor questions on whatever the family is already reading (via `current_unit`/`lesson_focus`) and keep a lighter tool-call footprint — meant for families new to homeschooling, or adopting AI deliberately and cautiously, per `docs/PARENT_SETUP.md`'s §5.

### Frontend (`homeschool-tutor/src/`)

```
App.tsx              React Router routes + RequireAuth guard + GlobalAuthInterceptor (401 → logout)
guards/
  AppShell.tsx       Token validation on mount + inactivity timeout (30 min) — sets ready:true before rendering
pages/
  Login.tsx          Parent password / child PIN tabs; voice-verify phase if voice_required; parent tab shows a "Forgot password?" link into `AccountRecovery.tsx` below (see "Parent account lockout & recovery" above)
  ParentSetup.tsx    Configure up to 10 students per pod with subject/grade/context; each student card opens with a companion_mode preset picker (Book Companion / A Bit More Structure / Full Daily Plan) that pre-fills subjects + session length, still freely editable after. `handleSavePod` captures whether `podStudents` was empty *before* this save — this family's first-ever pod, not just adding another student to an existing one — and when so (and `GET /feedback/enabled` says the deployment has feedback configured), shows `BetaIntakeModal` once before navigating on to `/session`/`/pod`, rather than navigating immediately
  PodDashboard.tsx   Per-student "Open on This Device" + "Copy Link for Tablet" + "Delete all data…" (type-to-confirm modal, calls the cascading DELETE — see docs/DATA_RETENTION.md)
  TutorSession.tsx   Main session view — timer, subject sidebar, chat, break overlay; shows `MeetBede` full-screen in place of the break/summary overlays + `SocraticChat` whenever `showIntro` (child role, not yet seen this device, or reopened via the header's "?" button) is true; root container uses `h-dvh` (dynamic viewport height), not `h-screen`/`100vh` — the fixed unit is routinely taller than what's actually visible on mobile Safari/Chrome whenever the address-bar chrome is showing, which pushed the header into the page's own scroll; `BREAK_INACTIVITY_LOGOUT_MS` (5 min) force-logs-out either role if nothing touches the page while a break overlay is showing — deliberately shorter than `AppShell.tsx`'s own 30-minute general inactivity timeout, which stays generous for active learning (reading/thinking time) since it applies session-wide, not just during a break; the header's `DebugOverlay` toggle (`showDebug`) is deliberately set apart from every real session control next to it (a `border-l` divider, muted gray-300 vs. the header's usual gray-400/navy accents) — a developer/tester tool a family will never need, not something to mix in among the things they actually tap during a lesson (mirrors the demo's own `App.tsx`)
  Progress.tsx       Parent-only: narration history, learner profile (+ behavior-check observation for kinesthetic/reading_writing/visual profiles), math mastery summary, AI usage — non-exhaustive, see the page itself
components/
  SocraticChat.tsx   Chat UI + SSE stream consumer + Bede opener ([START] sentinel); press-and-hold mic (`useHybridVoiceInput`'s `holdStart`/`holdEnd`) shows a Confirm/Cancel review step before sending rather than sending on release, and calls `stopSpeech()` synchronously on `holdStart` so a child can barge in over Bede's TTS mid-sentence; `DebugOverlay`'s own toggle lives in `TutorSession.tsx`'s header, not here — see that entry below for why; a denied/unavailable microphone (`useHybridVoiceInput`'s `micError`) surfaces as a plain-language chat message rather than the mic button silently doing nothing; the scroll-to-bottom effect reacts to the live voice-input state (`isListening`/`interim`/`isTranscribing`/`pendingVoiceTranscript`), not just new messages, so the child's own live transcript can't render below the fold with nothing bringing it into view. A `Radio`-icon pill (next to the mic) toggles `useVoiceModePreference`'s opt-in continuous "Voice on" mode — off (hold-to-talk) by default for every family. When on, a `useEffect` keyed off `awaitingChildTurn` (itself already gated on `!isStreaming && !isSpeaking && !isListening && !isTranscribing && !breakActive`) calls `start()` automatically once it's genuinely the child's turn, and `onFinal` sends the transcript straight through (via a `sendRef` forward-reference, bypassing the hold-to-talk review step, since hands-free is the whole point) instead of holding it for Confirm/Cancel. Restart is driven entirely by that state transition, never a bare timer — the specific difference from an earlier, since-removed "voice mode" that auto-restarted on an interval and bred recurring audio bugs (see `useHybridVoiceInput.ts`'s own comment on why press-and-hold replaced it); `MIN_MS_BETWEEN_AUTO_STARTS` (800ms) is defense-in-depth against a rapid-restart loop regardless. `MAX_CONSECUTIVE_VOICE_FAILURES` (3) — or a single `'permission-denied'` — falls back to hold-to-talk automatically with a chat message (`chat.voiceModeFallbackMessage`) rather than continuing to auto-restart into the same failure — see `docs/VOICE_SETUP.md`'s continuous-mode section. This `start()` call site never calls a corresponding `release()` — a known, documented gap since server-side streaming transcription replaced native SpeechRecognition (see `useHybridVoiceInput.ts`'s own KNOWN GAP comment): a continuous-mode turn now runs for the full `HOLD_SAFETY_TIMEOUT_MS` (120s) before auto-finishing rather than ending snappily when the child stops talking.
  MeetBede.tsx       One-time, skippable "Meet Bede" introduction (mic/pencil/breaks/safety, condensed from docs/CHILD_GUIDE.md) shown before a child's first-ever session on a device — see `useMeetBede.ts`. Demo is deliberately excluded: its sessions are short `demo_code` previews with no persistent per-student identity to gate "has this child seen it" against.
  BetaIntakeModal.tsx  One-time, skippable "what are you hoping Bede helps with" prompt shown from `ParentSetup.tsx` right after a family's first-ever pod save — parent-facing only, before a child is ever involved. Submits via the same `POST /feedback` pipeline as `FeedbackModal.tsx` below (`homeschool-api/routers/feedback.py`), tagged with the `onboarding` category so it reads distinctly in the operator's inbox rather than as ordinary in-use feedback (see `services/email_service.py`'s `_feedback_prefix`). Unlike `FeedbackModal.tsx`, this one IS localized (`betaIntake.*` in both locale files) — a brand-new user-facing form has no excuse to break a Spanish family's immersion the same turn this session's other fixes addressed exactly that.
  FeedbackModal.tsx  Anytime, in-session "Share feedback with the team" button (header, gated on `GET /feedback/enabled`) — category (cx/ux/content_quality/other) + optional rating + free text + optional reply-to email, routed to `FEEDBACK_EMAIL` via Resend and never persisted server-side beyond that one outbound send (`homeschool-api/routers/feedback.py`, `services/email_service.py`). Not currently localized (plain English strings) — a pre-existing gap, unlike `BetaIntakeModal.tsx` above.
  DebugOverlay.tsx   Fixed-position, screenshot-able voice-flow debug panel (monospace, green-on-black) fed by `hooks/debugBus.ts`'s pub/sub ring buffer; Clear/Close controls
  ParentMfaVerification.tsx  Login-time second-factor completion (security key tap or TOTP code) shown when `POST /auth/login` returns `mfa_required` — full-screen, replaces `Login.tsx`'s form entirely rather than an inline step.
  ParentSecuritySettings.tsx  Collapsible parent-settings panel (rendered from `ParentSetup.tsx`): security keys, TOTP, account recovery (see "Parent account lockout & recovery" above — needs 2 of 3 factors enrolled to ever be usable), and change-password. The recovery section favors a PIN (listed first) over a recovery code, mutually exclusive — after setting a PIN, a checkbox ("I've written this PIN down somewhere safe") must be checked before the enrollment screen can be dismissed, a gentle-but-real nudge since a memorable secret is exactly the kind that's easy to assume you'll never forget. Change-password calls `logout()` + navigates to `/` immediately on success rather than waiting for the next request's inevitable 401 — the credentials_version bump invalidates the very session making the change too.
  AccountRecovery.tsx  Login.tsx's "Forgot password?" destination — public, no session required. Fetches which recovery factors are enrolled (`GET /auth/recovery/methods`), collects >=2 (the "something you know" input adapts its label/placeholder to whichever of PIN or code this parent enrolled), verifies, then sets a new password. Reports plainly when recovery isn't set up (fewer than 2 factors enrolled) rather than pretending it might work. Not currently localized (plain English strings), same disclosed gap as `FeedbackModal.tsx` above — a rare, emergency-only flow, not blocking on a translation pass.
  SessionTimer.tsx   Countdown display; grade-aware (K-3 vs 4-8)
  SubjectNav.tsx     Sidebar subject list with completion tracking
  VoiceVerification.tsx  Child voice passphrase check at session start
  VoiceEnrollment.tsx   Parent-triggered enrollment flow
  ThemePicker.tsx    Chat-header palette: background theme + reader's bubble color (hidden in child sessions when SessionConfig.appearance_locked)
store/
  sessionStore.ts    Zustand store (persisted to sessionStorage — auth fields only)
services/
  api.ts             fetch wrappers for all REST endpoints; `parseSSEStream<T>` is the shared generic line-buffered SSE parser behind `streamTutorChat`/`streamSandboxChat` AND (via `voiceApi.ts`) the voice-streaming endpoints below; `streamTutorChat` logs the `local_date`/`local_time_of_day` it's about to send via `debugBus.logDebug()` — previously untraceable, so a "wrong greeting" or "wrong week's poem" report had no way to show what the client thought "now" was. Also: `changePassword`/`enrollRecoveryCode`/`disableRecoveryCode` (parent-authenticated) and the public `fetchRecoveryMethods`/`recoveryWebauthnOptions`/`verifyRecovery`/`resetPasswordRecovery` (see "Parent account lockout & recovery" above).
  voiceApi.ts        Voice enrollment/verification API calls, plus `startVoiceStream`/`pushVoiceStreamChunk`/`finishVoiceStream`/`streamVoiceEvents` — the client side of server-side streaming transcription (see homeschool-api's `services/streaming_transcription.py` above), consumed by `useHybridVoiceInput.ts` below
hooks/
  useTextToSpeech.ts       Browser TTS for Bede's responses
  useVoiceRecorder.ts      Raw-PCM capture (ScriptProcessorNode tap) for voice enrollment AND the tutor mic's only capture path; recordings capped at 120s (`MAX_RECORDING_MS`/`HOLD_SAFETY_TIMEOUT_MS`); `getUserMedia()` rejection is classified (`onError` callback, `'permission-denied'` vs `'unavailable'`) rather than only logged — see docs/VOICE_SETUP.md's mic-permission troubleshooting section; `snapshotWav()` is a non-destructive mid-recording peek at everything captured so far (doesn't clear the PCM buffer the way `stopRecording()` does) — used by `useHybridVoiceInput.ts`'s periodic chunk-upload loop
  useHybridVoiceInput.ts   Press-and-hold (walkie-talkie) mic. Browser-native SpeechRecognition (and `useSpeechRecognition.ts`) was removed entirely — server-side streaming transcription (chunked Whisper over SSE) is now the ONLY path: `useVoiceRecorder.ts` captures raw PCM locally, a `CHUNK_UPLOAD_INTERVAL_MS` (4s, raised from 2.5s — see docs/VOICE_SETUP.md's transcription-delay section) timer uploads a growing snapshot via `pushVoiceStreamChunk`, and a fire-and-forgotten `consumeEvents()` loop (started once per turn) reads `streamVoiceEvents`'s SSE stream, updating `interim` on each `'partial'` and delivering `onFinal` + returning to idle once the stream's own `'final'`+`'done'` arrive — `release()` itself only triggers the final upload + `finishVoiceStream` call, never duplicating that delivery logic. `debugBus.logDebug()` calls at every guard/branch for `DebugOverlay`; surfaces a denied/unavailable microphone as `micError` via the recorder's own `onError`; `HOLD_SAFETY_TIMEOUT_MS` (120s) bounds a missed release event, applied unconditionally to every turn (not just an explicit hold) since `start()` now behaves exactly like `startHold()` — see the KNOWN GAP this creates for continuous "Voice on" mode, in this file's own top comment and docs/VOICE_SETUP.md's "server-side streaming transcription" section; `release()` surfaces `MicError`'s `'no-speech-heard'` value when a real (`MIN_HOLD_MS_FOR_NO_SPEECH_FEEDBACK`, 1200ms+) hold's SSE stream ends with an empty final transcript. See docs/VOICE_SETUP.md for the full rewrite rationale and the native-era bug history it replaced.
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
`docs/adversarial-probes/`. For pentesting the *deployed environment*
instead (network, auth/session binding, rate limiting, container
hardening, TLS config, encryption at rest) — including a self-hosted
deployer testing their own instance — see
**[docs/environment-pentests/README.md](docs/environment-pentests/README.md)**,
which tracks findings pinned to the git SHA tested so they can be
correlated release-to-release.

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

**Carve-out for the public-facing demo/marketing pages (`site/`, `demo/`):**
step 3 above does NOT apply to changes under these two directories. Instead:
run a thorough self-review (the `/code-review` or `/security-review` skill,
whichever fits the change) on the diff, report the findings, and then wait
for the user's explicit sign-off before merging — no auto-merge. These paths
are the first thing a prospective family sees, and copy/content changes in
particular (not just code) carry a higher risk of drifting from what the
product actually does, so they get an extra human checkpoint the rest of the
repo doesn't require. Everything else about the workflow (test first, open a
PR with a real test plan, tell the user once merged) still applies.

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
