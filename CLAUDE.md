# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

**Agnus Dei / Sage** — a self-hosted, LAN-deployed Catholic Charlotte Mason homeschool AI tutor. A parent configures each student's daily plan; students connect from their own tablets. Claude (Sage persona) tutors via Socratic dialogue, agentic tools, and subject-specific personas. All student data is AES-256-GCM encrypted at rest; voice biometrics authenticate children at session start.

## Running the Full Stack

```bash
# First-time setup (generates .env, starts Docker services)
make setup        # or: bash setup.sh

# Day-to-day
make start        # docker compose up -d
make stop         # docker compose down
make restart      # pick up .env changes
make logs         # all services
make logs-api     # FastAPI only
make status       # container health + /api/health check

# Install Caddy's local CA on each tablet (run once per device)
make caddy-trust
```

The stack is: **Caddy (TLS/443) → nginx (UI/80) → FastAPI (API/8000)**. Caddy generates a local CA for LAN HTTPS — tablets need its root cert installed once.

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

All from `.env` (gitignored — never commit):

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API access |
| `SECRET_KEY` | JWT signing (32 hex bytes) |
| `MASTER_SECRET` | AES key derivation root (32 hex bytes) |
| `PARENT_PASSWORD` | Parent login credential |
| `CHILD_PIN` | Child login PIN (4+ digits) |
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host/db?ssl=require` |
| `CORS_ORIGINS` | Comma-separated allowed origins |

In production mode (`PRODUCTION=true`), the API rejects startup if any credential matches a known-weak default (enforced by `model_validator` in `core/config.py`).

## Architecture

### Backend (`homeschool-api/`)

```
main.py              FastAPI app + lifespan (DB init, encryption init)
core/
  config.py          Pydantic Settings — all env vars + production validation
  database.py        Async SQLAlchemy engine, ORM models (EncryptionConfig, VoiceProfile, StudentConfig, AuditLog)
  encryption.py      AES-256-GCM; MASTER_SECRET → KEK → DATA_KEY hierarchy; all BYTEA columns encrypted
  audit.py           Encrypted audit log — every security event written independently of request transaction
  deps.py            require_auth / require_parent FastAPI dependencies (JWT + IP/UA fingerprint)
  middleware.py      SecurityHeaders, RateLimit, ExfiltrationGuard (blocks prompt-injection in SSE)
  security.py        JWT encode/decode; device fingerprint binding
routers/
  auth.py            POST /auth/login → JWT; GET /auth/validate
  tutor.py           POST /tutor/chat (SSE stream); POST /tutor/summary
  pod.py             CRUD /pod/configs — parent saves, child loads by name
  voice.py           POST /voice/enroll; POST /voice/verify
  admin.py           GET /admin/status; GET /admin/audit
services/
  ai_service.py      stream_tutor_response() + generate_session_summary()
  voice_auth.py      Resemblyzer speaker embedding + MFCC similarity scoring
  transcription.py   Whisper transcription for voice enrollment phrases
models/
  schemas.py         Pydantic models: SessionConfig, Subject, TutorRequest, etc.
```

**AI service pattern:** Two-block system prompt with prompt caching. The static block (`_build_static_prompt`) carries Sage's persona and rules and is marked `cache_control: ephemeral` — it's reused across turns. The subject block (`_build_subject_prompt`) changes per subject and is sent fresh. Tools block is also cached. The `[START]` sentinel triggers Sage's subject opener without showing a user bubble.

**SSE streaming format:** Each chunk is `data: {"type":"text","content":"..."}`, `data: {"type":"tool","tool":"<name>","content":"..."}`, or `data: {"type":"done"}`. Tool calls are accumulated in a buffer, JSON-parsed at `ContentBlockStop`, then formatted and emitted.

**Four agentic tools:** `request_narration`, `offer_socratic_hint`, `celebrate_discovery`, `connect_to_faith`. These render as styled cards in the UI (not chat bubbles).

### Frontend (`homeschool-tutor/src/`)

```
App.tsx              React Router routes + RequireAuth guard + GlobalAuthInterceptor (401 → logout)
guards/
  AppShell.tsx       Token validation on mount + inactivity timeout (30 min) — sets ready:true before rendering
pages/
  Login.tsx          Parent password / child PIN tabs; voice-verify phase if voice_required
  ParentSetup.tsx    Configure up to 10 students per pod with subject/grade/context
  PodDashboard.tsx   Per-student "Open on This Device" + "Copy Link for Tablet"
  TutorSession.tsx   Main session view — timer, subject sidebar, chat, break overlay
components/
  SocraticChat.tsx   Chat UI + SSE stream consumer + Sage opener ([START] sentinel)
  SessionTimer.tsx   Countdown display; grade-aware (K-3 vs 4-8)
  SubjectNav.tsx     Sidebar subject list with completion tracking
  VoiceVerification.tsx  Child voice passphrase check at session start
  VoiceEnrollment.tsx   Parent-triggered enrollment flow
store/
  sessionStore.ts    Zustand store (persisted to sessionStorage — auth fields only)
services/
  api.ts             fetch wrappers for all REST endpoints
  voiceApi.ts        Voice enrollment/verification API calls
hooks/
  useSpeechRecognition.ts  Web Speech API (Chrome/Edge/Safari); interim results
  useTextToSpeech.ts       Browser TTS for Sage's responses
  useVoiceRecorder.ts      MediaRecorder for voice enrollment audio
utils/
  gradeTimer.ts      K-3: 20-min per-subject; 4-8: 60-min block + 10-min break cycles
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

- **Tutor:** `claude-sonnet-4-6` (streaming, `max_tokens: 400`, tight for Charlotte Mason brevity)
- **Summary:** `claude-haiku-4-5-20251001` (non-streaming, `max_tokens: 600`, end-of-session parent report)

To change models, update `tutor_model` / `session_model` in `core/config.py`.

## Security Constraints

- `.env`, `.env.backup`, `.env.local` are gitignored — never commit them
- JWTs are IP + User-Agent fingerprinted at issuance; replaying from a different device returns 401
- Auth credential comparisons use `hmac.compare_digest()` (constant-time)
- `ExfiltrationGuard` middleware strips `data:` lines from SSE that contain prompt-injection markers
- The `sage` container user has no shell; containers run `read_only: true`, `cap_drop: ALL`
- Voice profiles and student configs are stored as AES-256-GCM BYTEA — the database provider never sees plaintext

## Adding a New Subject

1. `models/schemas.py` — add to `Subject` enum, `SUBJECT_DURATIONS`, `SUBJECT_LABELS`
2. `services/ai_service.py` — add to `_SUBJECT_CONTEXT` dict
3. `homeschool-tutor/src/types/index.ts` — add to `Subject` type, `SUBJECTS` array, and `SUBJECT_MAP`
