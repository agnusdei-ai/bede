# Bede — Demo Build

A version of Bede for trying it out without setting up the full server stack.
One click gets you in — no PIN to remember, no key to paste. The operator's
Anthropic key stays server-side, never pasted into the browser:

- **"Generate my code"** — one click mints a fresh, one-time 6-digit code
  (`POST /auth/demo-code`) and logs the visitor in immediately with it. No
  message cap, no wall-clock limit — a code is good for its own TTL (see
  `core/demo_code_session.py`). Each code is independent, so concurrent
  visitors never collide with each other.

This requires `VITE_DEMO_API_BASE` set at build time to a publicly-reachable
`homeschool-api` deployment with `DEMO_PIN` configured (see the root
`homeschool-api/.env.example`) — without that, clicking the button says the
demo isn't enabled on this deployment. See `docs/DEMO_HOSTING.md` at the
repo root for how to actually stand this backend up (a Render Blueprint is
included).

The operator's key never reaches the browser: `core/deps.py`'s
`require_real_user` blocks the scoped `demo_code` role from every endpoint
that reads or writes real student data (pod configs, narration history,
transcripts, voice enrollment, admin) — the handful of ephemeral, per-request
endpoints it *can* reach (chat, voice output, the one-time diagnostic email,
and the sandbox preview below) use `require_auth` directly instead. Nothing
is persisted (`db=None` in `routers/tutor.py`). Voice output uses OpenAI TTS
if the backend has it configured, falling back to the browser's own speech
otherwise.

An **"Ask Bede"** button during the session previews the parent-only sandbox
from the real app — direct answers instead of Socratic, free
topic-switching, and a "custom instructions" box, so a prospective parent
can see what their own private sandbox would feel like. Nothing typed there
is saved either.

**This is a demo, not the real app.** See `DEMO_SCRIPT.md` for a guided walkthrough
with reference prompts, and the table there for exactly what's different from the
production version in `docs/PARENT_SETUP.md` at the repo root.

## Running it

```bash
cd demo
npm install
VITE_DEMO_API_BASE=http://localhost:8000 npm run dev
```

## Building for deployment

```bash
VITE_DEMO_API_BASE=https://your-backend.example.com npm run build     # outputs to demo/dist
```

The build uses a relative base path for its own assets, so the output works
whether it's served from a domain root or a subpath — which it is in
practice: `.github/workflows/deploy-demo.yml` publishes this build under
`/bede/`, alongside a separate small company landing page (`site/`) at the
domain root — see `docs/DEMO_HOSTING.md`'s "Why the apex isn't just the
demo" for the full picture. `VITE_DEMO_API_BASE` itself must still be an
absolute URL, since it points at a different host entirely; the workflow
reads it from the `VITE_DEMO_API_BASE` repository variable (Settings →
Secrets and variables → Actions → Variables) automatically.

## What's included vs. left out

Behavior (persona, grade-stage guidance, the four interactive tools, the
deterministic safeguarding check, curated book catalogs) is identical to the
real backend, since the demo streams from the same `homeschool-api`
deployment the production app uses (`services/ai_service.py`).

Left out because they need a real family's own deployment: voice-biometric
login, encrypted persistent storage, multi-student pods, and progress
tracking.
