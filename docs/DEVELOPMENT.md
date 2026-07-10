# Working on the Bede codebase

This is for people editing the code itself — parents setting up Bede for
their family want `docs/PRODUCTION_SETUP.md` instead; the public demo has
its own `docs/DEMO_HOSTING.md`.

## Project layout

```
homeschool-api/      FastAPI backend — the real production API
homeschool-tutor/    Production React frontend (Vite + TypeScript + Tailwind)
demo/                Lighter public demo frontend — see demo/README.md
docs/                All documentation (this file, setup guides, etc.)
```

`CLAUDE.md` at the repo root has the full architecture deep-dive (request
flow, the AI service's prompt structure, the frontend's streaming state
machine, etc.) — read that first if you're orienting yourself in the
codebase, this page just covers running things locally.

## Frontend (`homeschool-tutor/`)

Vite + React + TypeScript + Tailwind, no test runner configured:

```bash
cd homeschool-tutor
npm install
npm run dev         # http://localhost:5173 with HMR
npm run build       # tsc + vite build — type errors fail the build
npx tsc --noEmit    # type-check without building
```

## Backend (`homeschool-api/`)

FastAPI with async SQLAlchemy — requires a live PostgreSQL connection on
startup (it runs `CREATE TABLE IF NOT EXISTS` and initializes encryption key
material from the DB; there's no in-memory fallback):

```bash
cd homeschool-api
pip install -r requirements.txt
cp .env.example .env   # then fill in values, including a real DATABASE_URL
uvicorn main:app --reload --port 8000
# API docs at http://localhost:8000/docs (only when DISABLE_API_DOCS=false)
```

## Demo (`demo/`)

Fully static, no backend required for the bring-your-own-key path:

```bash
cd demo
npm install
npm run dev       # http://localhost:5173 — own-key path only
# or, to also enable the free-trial path against a local backend:
VITE_DEMO_API_BASE=http://localhost:8000 npm run dev
```

See `demo/README.md` for what's different from production, and
`docs/DEMO_HOSTING.md` for deploying the demo's own backend.

## Full stack via Docker

If you want to run the whole production stack locally (Caddy + nginx +
FastAPI + Postgres) rather than the pieces individually above, see
`docs/PRODUCTION_SETUP.md` — `make setup` works the same way for local
development as it does for a real deployment.
