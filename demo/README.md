# Bede — Demo Build

A version of Bede for trying it out without setting up the full server stack.
Both paths on the landing screen are backend-mediated — the operator's
Anthropic key stays server-side in both cases, never pasted into the browser:

- **"Try it now — free, 15 minutes"** — a shared trial session against a real
  `homeschool-api` backend, gated by a shared `DEMO_PIN`. One active session
  at a time regardless of how many people know the PIN; logs out after 15
  minutes or 5 minutes of inactivity, whichever comes first.
- **"Get your own code"** — one click mints a fresh, one-time 6-digit code
  (`POST /auth/demo-code`) and logs the visitor in immediately with it — no
  PIN to remember, no key to paste. Capped at 50 messages per code instead of
  a wall-clock limit; generating a new code starts a fresh allotment.

Both require `VITE_DEMO_API_BASE` set at build time to a publicly-reachable
`homeschool-api` deployment with `DEMO_PIN` configured (see the root
`homeschool-api/.env.example`) — without that, the landing screen says the
demo isn't configured on this deployment. See `docs/DEMO_HOSTING.md` at the
repo root for how to actually stand this backend up (a Render Blueprint is
included).

The shared key never reaches the browser in either tier: `core/deps.py`'s
`require_real_user` blocks both scoped demo roles from every endpoint that
reads or writes real student data (pod configs, narration history,
transcripts, voice enrollment, admin) — the handful of ephemeral, per-request
endpoints either role *can* reach (chat, voice output, the one-time
diagnostic email, and the sandbox preview below) use `require_auth` directly
instead, and each still enforces its own session limits on top (single-active
+ 5-min-inactivity for the shared trial; a 50-message cap per code for the
self-service tier). Nothing is persisted for either (`db=None` in
`routers/tutor.py`). Voice output uses OpenAI TTS if the backend has it
configured, falling back to the browser's own speech otherwise.

An **"Ask Bede"** button during either tier previews the parent-only sandbox
from the real app — direct answers instead of Socratic, free
topic-switching, and a "custom instructions" box, so a prospective parent
can see what their own private sandbox would feel like. Same session limits
as the rest of the demo; nothing typed there is saved either.

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
whether it's served from a domain root or a subpath (e.g. a GitHub Pages
project site) — but `VITE_DEMO_API_BASE` itself must be an absolute URL,
since it points at a different host entirely. `.github/workflows/deploy-demo.yml`
reads it from the `VITE_DEMO_API_BASE` repository variable (Settings →
Secrets and variables → Actions → Variables) automatically.

## What's included vs. left out

Behavior (persona, grade-stage guidance, the four interactive tools, the
deterministic safeguarding check, curated book catalogs) is identical to the
real backend, since both demo tiers stream from the same `homeschool-api`
deployment the production app uses (`services/ai_service.py`).

Left out because they need a real family's own deployment: voice-biometric
login, encrypted persistent storage, multi-student pods, and progress
tracking.
