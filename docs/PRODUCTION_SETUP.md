# Running Bede for your family (production)

This is the self-hosted, LAN-only deployment for actually tutoring your
children — see `docs/PARENT_SETUP.md` for the non-technical walkthrough
(including the security model you should understand before handing a
tablet to your child) and `docs/CHILD_GUIDE.md` for the child-facing guide.
This page is the technical/ops reference.

**Looking for the public demo instead?** That's a separate, lighter-weight
setup — see `docs/DEMO_HOSTING.md`. Don't use the steps below for a public
demo; don't use the demo's approach (a cloud platform) for your family's
real instance — the two have different security models on purpose.

## First-time setup

Two ways to do this — same result, different experience:

**Terminal wizard** (`setup.sh`) — for anyone comfortable typing in a
terminal:
```bash
make setup        # or: bash setup.sh
```
An interactive wizard: it asks for your Anthropic API key, your database
choice (see below), a parent password, and a child PIN, generates the
cryptographic secrets, writes `.env`, and starts everything.

**Browser wizard** — no terminal typing at all, for anyone who isn't
comfortable with the above. Requires [Docker Desktop](https://docker.com/products/docker-desktop)
already installed and running (that part still needs its own installer —
this doesn't replace installing Docker itself, just everything after):

- **macOS**: double-click `setup-gui.command` in the repo folder.
- **Windows**: double-click `setup-gui.bat`.
- **Linux**: run `./setup-gui.sh` (or `make setup-gui`).

A browser tab opens with a form — fill it in, click the button, close the
tab when it says Bede is starting. It asks the exact same questions as the
terminal wizard, just as text fields and clickable choices instead of typed
answers, and produces the identical `.env`/Docker setup underneath.

> **Status: proven end-to-end, on an ongoing basis.** A scheduled CI job
> (`.github/workflows/production-regression.yml`, weekly plus on every
> relevant change) builds the wizard image, submits the form exactly as a
> parent would, confirms the generated `.env` and file permissions, then
> boots the *entire* real stack from that `.env` — Caddy, nginx, FastAPI,
> local Postgres — and confirms `https://.../api/health` actually answers
> through the full TLS→proxy→API path, plus that `make db-backup`/
> `make db-restore` round-trip cleanly. This is a real Docker daemon doing
> a real `docker build`/`docker run`/`docker compose up`, not a dry run.
> What CI can't cover: the double-click launchers themselves
> (`setup-gui.command`/`setup-gui.bat`) run on a Linux runner under the
> hood, so a literal double-click on macOS/Windows hasn't been observed —
> if that differs for you, please report back.

## Choosing a database

`make setup` asks which of these you want:

1. **Local Postgres (recommended for most people)** — runs alongside Bede
   in its own Docker container. No external account, nothing leaves this
   machine. You're responsible for backups yourself — see `make db-backup`
   below, and actually run it regularly.
2. **Managed Postgres** (Neon's free tier, Supabase, Railway, Render, etc.)
   — automatic backups handled by the provider, but it's an extra account
   to create, and your encrypted data leaves this machine for their cloud
   (still AES-256-GCM encrypted at rest either way — the provider only ever
   sees ciphertext — but it's an extra party in the chain).

Both are fully supported; `make setup` wires up whichever you pick. See the
"Storage model" comment at the top of `docker-compose.yml` if you want to
switch later by hand.

## Day-to-day commands

```bash
make start        # docker compose up -d
make stop         # docker compose down
make restart      # pick up .env changes only (no code changes)
make update       # git pull + rebuild + restart — use this after pulling new commits
make logs         # all services
make logs-api     # FastAPI only
make status       # container health + /api/health check

# Local Postgres only (skip if you chose managed Postgres):
make db-backup    # dump the local database to backups/ — do this regularly
make db-restore FILE=backups/bede-....sql   # restore from a backup

# Install Caddy's local CA on each tablet (run once per device) — or skip
# the terminal entirely: open http://<server-ip>/trust on the tablet itself
# (or scan the QR code it shows), no CLI required either way.
make caddy-trust

# iPad/iPad Pro shortcut: one profile install instead of the manual steps above
# (trusts the cert AND adds a Home Screen icon in a single tap)
make ipad-profile
```

`make restart` vs. `make update`: if you only changed a value in `.env`
(like adding `OPENAI_API_KEY`), `make restart` is enough and is faster. If
you pulled new code (a new feature, a bug fix), you need `make update` —
it rebuilds the Docker image; `make restart` alone will NOT pick up code
changes, only `.env` changes.

The stack is: **Caddy (TLS/443) → nginx (UI/80) → FastAPI (API/8000)**,
plus an optional local Postgres. Caddy generates a local CA for LAN HTTPS —
tablets need its root cert installed once.

For iPads specifically, `make ipad-profile` generates `bede-ipad.mobileconfig`,
which bundles the CA trust and a "Bede" Home Screen icon into one installable
profile — AirDrop it to the iPad (or host it and open the link in Safari),
then **Settings → Profile Downloaded → Install**. iOS still requires one
manual step no matter how the cert is delivered: **Settings → General →
About → Certificate Trust Settings** → enable full trust for "Bede LAN Root
CA". After that, tapping the Home Screen icon opens Bede directly over
HTTPS with no browser chrome.

## Required environment variables

All from `.env` (gitignored — never commit). See `.env.example` for the
full list, with comments: `ANTHROPIC_API_KEY`, `SECRET_KEY`,
`MASTER_SECRET`, `PARENT_PASSWORD`, `CHILD_PIN`, `DATABASE_URL`,
`CORS_ORIGINS`, `LICENSE_KEY` (see **Licensing** below). Optional:
`OPENAI_API_KEY` for voice (see `docs/VOICE_SETUP.md`), `RESEND_API_KEY`
for the post-session diagnostic email, `PARENT_EMAIL` for an urgent alert
when Bede detects a child in distress or danger (reuses `RESEND_API_KEY`),
`SANDBOX_PIN` to unlock a direct-answer "Ask Bede" chat for you to
test/explore Bede's behavior (see the Pod Dashboard's **Sandbox** button —
requires being logged in as parent plus this PIN; nothing said there is
ever saved), `WEBAUTHN_RP_ID`/TOTP settings for parent MFA.

## Licensing

Once `PRODUCTION=true`, Bede refuses to start without a valid `LICENSE_KEY`
(`core/config.py`'s `reject_missing_or_invalid_license_in_production`
validator, mirroring the same fail-fast pattern as its weak-credential
checks). A license is a compact, **offline-verifiable** certificate — no
phone-home, no license server, no telemetry. Verification happens entirely
against a public key embedded in `homeschool-api/core/licensing.py`; your
server never needs outbound network access to prove it's licensed, and it
never reports back to us.

**Getting one:** if you purchased Bede or started a trial, you were given a
`LICENSE_KEY=...` line — paste it into `.env` as-is (both setup wizards —
terminal and browser — also prompt for it directly and write it for you).

**What it controls today:**
- Startup itself — a missing, tampered, or expired license refuses to boot
  (check `make logs` for the exact reason if the API container won't come
  up after a license change).
- The pod's seat cap — `POST /pod/configs` (`routers/pod.py`) rejects
  adding a student past your license's `seats` count.
- The parent dashboard's status strip shows your tier, licensee, and (for a
  trial) days remaining, sourced from `GET /admin/status`.

**Tiers:** `trial` (must carry an expiry — a fully-featured, time-limited
evaluation), `core` (a single household, up to `seats` students), `coop`
(a co-op/parish school license covering multiple households under one
`seats` count).

**Issuing a license (operator-only):** this is for whoever runs the Bede
business, not something a family does. One-time: generate the signing
keypair with `python homeschool-api/scripts/generate_license_keypair.py`
— keep the private key offline and out of every repo; paste the public key
into `core/licensing.py`. Per sale/trial: `python
homeschool-api/scripts/issue_license.py --tier core --licensee "The Smith
Family" --seats 10 --private-key /path/to/private.pem` prints the
`LICENSE_KEY=` line to send the customer. See both scripts' docstrings for
the full flag reference (trial expiry via `--days`, co-op seat counts,
etc.).

**Threat model, honestly:** this is a trust-and-verify gate for legitimate
self-hosters, not DRM — anyone with the source (which every self-hosted
deployer has) could patch the check out. It exists to make honest use easy
and accidental/casual misuse visible, not to withstand a determined bypass.

**The public demo is exempt.** `Settings.is_demo_deployment` (true whenever
`DEMO_PIN` is set — see `core/config.py`) skips this check entirely: the
demo is a stateless, zero-seat instance meant to be frictionless for
prospective customers, not gated behind the same license it exists to sell.
See `docs/DEMO_HOSTING.md#licensing`. A family's real instance is never
exempt — it should never set `DEMO_PIN`.

**Never commit a real LICENSE_KEY, even a "test" one.** A valid license is
worth real money to whoever holds it — this repo has no revocation
mechanism, so a key exposed in a public commit, PR description, or issue
is usable forever by anyone who finds it, not just embarrassing. Treat it
with the same handling as any other credential in this repo (`.env`, a
platform's secret store) — never a plaintext file or workflow `env:`
value. `production-regression.yml`'s CI run still needs one real, signed
license (it exercises the family-install path, which is never exempt) to
prove the full stack actually boots with `PRODUCTION=true`; that value
lives in this repo's **Settings → Secrets and variables → Actions** as
`CI_TEST_LICENSE_KEY`, not in the workflow file itself. To rotate it:
`python homeschool-api/scripts/issue_license.py --tier trial --licensee
"CI Test" --seats 10 --days 1095 --private-key /path/to/private.pem`
(bounded to a long-but-finite expiry, not perpetual, as defense in depth),
then update the secret's value in GitHub's UI.
