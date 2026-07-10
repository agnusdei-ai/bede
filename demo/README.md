# Bede — Demo Build

A version of Bede for trying it out without setting up the full server stack.
The landing screen offers two paths:

- **"Use your own API key"** — fully static, no backend needed. Runs entirely
  in the browser (client-only, works on GitHub Pages, an iPad, anywhere) using
  a key the visitor pastes in themselves, stored only in that browser's local
  storage, sent straight to Anthropic. Voice output uses the browser's own
  built-in speech (no cloud TTS in this path). No time limit; the visitor
  pays Anthropic directly for what they use. This path always works.
- **"Try it now — free, 15 minutes"** *(optional)* — a shared trial session
  against a real `homeschool-api` backend, so nobody needs their own key to
  try it. Only appears if `VITE_DEMO_API_BASE` is set at build time to a
  publicly-reachable `homeschool-api` deployment with `DEMO_PIN` configured
  (see the root `homeschool-api/.env.example`) — without that, the demo just
  quietly offers the own-key path only. See `docs/DEMO_HOSTING.md` at the
  repo root for how to actually stand this backend up (a Render Blueprint is
  included). The shared key never reaches the
  browser: `core/deps.py`'s `require_real_user` blocks the scoped `demo` role
  from every endpoint that reads or writes real student data (pod configs,
  narration history, transcripts, voice enrollment, admin) — the handful of
  ephemeral, per-request endpoints it *can* reach (chat, voice output,
  the one-time diagnostic email, and the sandbox preview below) all use
  `require_auth` directly instead, and each still enforces the demo role's
  own single-active-session + 5-minute-inactivity rules on top. Sessions
  expire in 15 minutes, and nothing is persisted (`db=None` for the demo
  role in `routers/tutor.py`). Voice output tries the backend's self-hosted
  Kokoro voice first, falling back to the browser's own speech if the model
  files aren't set up on that deployment.
  When the trial ends, the UI prompts the visitor to get their own free key
  for unlimited use, noting that beyond a small free credit, usage is billed
  per token by Anthropic directly to them.
  An **"Ask Bede"** button during the trial previews the parent-only sandbox
  from the real app (`homeschool-api/routers/sandbox.py`'s `/demo-chat`) —
  direct answers instead of Socratic, free topic-switching, and a "custom
  instructions" box, so a prospective parent can see what their own private
  sandbox would feel like. Same session/rate limits as the rest of the
  trial; nothing typed there is saved either.

**This is a demo, not the real app.** See `DEMO_SCRIPT.md` for a guided walkthrough
with reference prompts, and the table there for exactly what's different from the
production version in `docs/PARENT_SETUP.md` at the repo root.

## Running it

```bash
cd demo
npm install
npm run dev       # http://localhost:5173 — own-key path only
# or, to also enable the free-trial path against a local backend:
VITE_DEMO_API_BASE=http://localhost:8000 npm run dev
```

## Building for deployment

```bash
npm run build     # outputs to demo/dist — own-key path only
# or, to also offer the free trial:
VITE_DEMO_API_BASE=https://your-backend.example.com npm run build
```

The build uses a relative base path for its own assets, so the output works
whether it's served from a domain root or a subpath (e.g. a GitHub Pages
project site) — but `VITE_DEMO_API_BASE` itself must be an absolute URL,
since it points at a different host entirely. `.github/workflows/deploy-demo.yml`
reads it from the `VITE_DEMO_API_BASE` repository variable (Settings →
Secrets and variables → Actions → Variables) automatically; leave that unset
to ship own-key-only, same as today.

## What's included vs. left out

Ported from the real backend (`homeschool-api/services/ai_service.py`): the Bede
persona, grade-stage guidance, the four interactive tools (narration, hints,
celebration, faith connections), the deterministic safeguarding check, and — for
grades K, 4, and 8 specifically — the same curated book catalogs and subject term
plans (math scope, composer/artist/poet study) as the real `data/catalog/` files.

Left out because they need a real backend: voice-biometric login, encrypted
persistent storage, multi-student pods, progress tracking, and Whisper-based voice
fallback (this demo relies on the browser's native speech recognition only).
