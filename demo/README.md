# Bede — Public Demo Build

A lightweight, single-PIN demo of Bede for letting someone try it out without
handing them a real family's access — no per-visitor setup, no API key to
paste in, no configuration rights. One shared demo login, one fixed
tutoring session, 15 minutes, then it logs out automatically.

**This is a demo, not the real app.** See `DEMO_SCRIPT.md` for a guided
walkthrough with reference prompts.

## How it works

Unlike earlier versions of this demo, **it is not a fully static, keyless
build** — it talks to a real `homeschool-api` backend over the network. That's
deliberate: a single shared demo credential that visitors never see requires
something to hold the real Anthropic API key server-side. A static site
cannot hide a secret, so there had to be a backend somewhere.

- The visitor enters one shared **demo PIN** (set by whoever runs the demo,
  via `DEMO_PIN` on the backend — see `homeschool-api/.env.example`).
- That logs them in as a scoped `demo` role: a token that expires in
  **15 minutes** (`DEMO_TOKEN_EXPIRE_MINUTES`), rejected by every parent/config
  endpoint (`core/deps.py`'s `require_real_user`), and can only reach one
  fixed, server-defined tutoring session (`routers/tutor.py`'s
  `_demo_session_config()` — name/grade/subjects come from `DEMO_STUDENT_NAME`
  / `DEMO_GRADE` / `DEMO_GRADE_STAGE`, never from the visitor).
- All persona, curriculum, and tool logic lives entirely server-side now
  (`services/ai_service.py` — the full 8-year catalog, the monk persona, the
  `show_visual_aid` picture-study tool). This build no longer duplicates any
  of that; `src/api.ts` is a thin fetch/SSE client, nothing more.
- The real Anthropic key stays exactly where it always belonged: server-side,
  never shipped to the browser.

## The one manual step: deploying the backend

This demo cannot work until a `homeschool-api` instance is running somewhere
**publicly reachable** (not LAN-only — see the note in the root
`docs/PARENT_SETUP.md` about the production deployment model being LAN-scoped
by default). Concretely, for a public demo you need:

1. A `homeschool-api` deployment reachable over the public internet, with:
   - `DEMO_PIN` set to something that isn't `PARENT_PASSWORD` or `CHILD_PIN`
     (startup fails otherwise — see `core/config.py`'s validator).
   - `ANTHROPIC_API_KEY` set to a real key you're comfortable being used by
     anonymous public visitors for up to 15 minutes at a time each.
   - `CORS_ORIGINS` including this demo's actual deployed URL
     (e.g. `https://<you>.github.io`).
   - Real TLS in front of it — this is public internet traffic now, not a LAN.
2. This repo's `VITE_DEMO_API_BASE` repository variable
   (Settings → Secrets and variables → Actions → Variables) set to that
   backend's base URL — `.github/workflows/deploy-demo.yml` bakes it into the
   build at deploy time, since a static site has no runtime config.

Nothing about hosting that backend (which provider, what domain) can be
decided or provisioned from inside this repo — that part is genuinely a
deployment decision and action for whoever runs the demo.

## Running it locally

```bash
cd demo
npm install
VITE_DEMO_API_BASE=http://localhost:8000 npm run dev   # http://localhost:5173
```

Point `VITE_DEMO_API_BASE` at a `homeschool-api` instance you're running
locally (see the root `README.md`) with `DEMO_PIN` set in its `.env`.

## Building for deployment

```bash
VITE_DEMO_API_BASE=https://your-backend.example.com npm run build
```

The build uses a relative base path for its own static assets, so the
*frontend* works whether it's served from a domain root or a subpath (e.g. a
GitHub Pages project site) — but `VITE_DEMO_API_BASE` itself must be an
absolute URL, since it's pointing at a different host entirely.

## What's different from the real app

No voice-biometric login (the demo's fixed persona has `voice_required:
false`), no persistent progress tracking or encrypted transcripts (demo
sessions aren't saved — `db` is intentionally `None` for the demo role in
`routers/tutor.py`), no cloud TTS (browser `speechSynthesis` only, to avoid
a public visitor running up an ElevenLabs bill), and no way to change subject
list, grade, or any other setting — the whole point is zero configuration
rights.
