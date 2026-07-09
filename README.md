# Bede

A self-hosted, LAN-deployed Catholic Charlotte Mason homeschool AI tutor. A parent
configures each student's daily plan; students connect from their own tablets.
Claude (the Sage persona) tutors via Socratic dialogue, agentic tools, and
subject-specific personas. All student data is AES-256-GCM encrypted at rest;
voice biometrics authenticate children at session start.

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

# iPad/iPad Pro shortcut: one profile install instead of the manual steps above
# (trusts the cert AND adds a Home Screen icon in a single tap)
make ipad-profile
```

The stack is: **Caddy (TLS/443) → nginx (UI/80) → FastAPI (API/8000)**. Caddy generates
a local CA for LAN HTTPS — tablets need its root cert installed once.

For iPads specifically, `make ipad-profile` generates `bede-ipad.mobileconfig`, which
bundles the CA trust and a "Bede" Home Screen icon into one installable profile — AirDrop
it to the iPad (or host it and open the link in Safari), then **Settings → Profile
Downloaded → Install**. iOS still requires one manual step no matter how the cert is
delivered: **Settings → General → About → Certificate Trust Settings** → enable full
trust for "Bede LAN Root CA". After that, tapping the Home Screen icon opens Bede directly
over HTTPS with no browser chrome.

## Local Development (without Docker)

**Frontend** — Vite + React + TypeScript + Tailwind:
```bash
cd homeschool-tutor
npm install
npm run dev        # http://localhost:5173 with HMR
npm run build      # tsc + vite build (type errors fail the build)
```

**Backend** — FastAPI with async SQLAlchemy:
```bash
cd homeschool-api
pip install -r requirements.txt
cp .env.example .env   # then fill in values
uvicorn main:app --reload --port 8000
```

See [`CLAUDE.md`](CLAUDE.md) for full architecture documentation.

## Required Environment Variables

All from `.env` (gitignored — never commit). See [`.env.example`](.env.example) for the
full list: `ANTHROPIC_API_KEY`, `SECRET_KEY`, `MASTER_SECRET`, `PARENT_PASSWORD`,
`CHILD_PIN`, `DATABASE_URL`, `CORS_ORIGINS`.
