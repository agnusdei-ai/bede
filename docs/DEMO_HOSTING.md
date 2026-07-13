# Hosting the public demo's backend

The demo's self-service "Get your own code" flow (see `demo/README.md`)
needs a real `homeschool-api` backend to talk to. There's no fully-static,
key-in-the-browser path anymore; the operator's Anthropic key always stays
server-side.

This backend is **only** for the public demo — a family's real production
instance should stay self-hosted on a LAN per the main `README.md` and
`CLAUDE.md`'s security model (voice biometrics, encrypted student data,
tablet-only network exposure). The demo role persists nothing (`db=None` in
`routers/tutor.py`), so it doesn't need that LAN-only posture — a managed
cloud platform is a better fit: no server to SSH into, no `make update`,
just push to `main` and it redeploys itself.

## One-time setup (Render)

1. Create an account at [render.com](https://render.com) if you don't have
   one, and connect your GitHub account so it can see `agnusdei-ai/bede`.
2. **New → Blueprint**, select this repo. Render reads `render.yaml` at the
   repo root and proposes a web service (`bede-demo-api`) plus a free
   Postgres database (`bede-demo-db`).
3. Render will pause on every env var marked `sync: false` in `render.yaml`
   and ask you to fill it in — these are the actual secrets (never
   committed):
   - `ANTHROPIC_API_KEY` — your real Claude key (same one your production
     instance uses, or a separate one if you want the demo's usage billed
     separately).
   - `OPENAI_API_KEY` — for the voice feature (see `docs/VOICE_SETUP.md`).
   - `CHILD_PIN` — must satisfy `pin_is_strong()` (6+ digits, no sequential
     run/repeated block/palindrome — e.g. `602656`, not `111111`). Unused in
     practice (this instance's parent/child roles aren't advertised), but
     the app still validates it at startup.
   - `DEMO_PIN` — not a credential anyone types; purely the on/off switch for
     the whole public demo (empty = disabled). Must still satisfy
     `pin_is_strong()` (same rules as `CHILD_PIN`) since `core/config.py`
     validates it the same way regardless.
   - `RESEND_API_KEY` and `RESEND_FROM_ADDRESS` — optional, but every
     email-sending feature (the post-session summary email, the safeguarding
     distress alert, and the beta feedback form) silently no-ops without
     them. `RESEND_FROM_ADDRESS` must be a sender verified against a domain
     you've added in [Resend](https://resend.com)'s dashboard, not just any
     address. `FEEDBACK_EMAIL` (where beta feedback is routed) is already set
     as a plain, non-secret value in `render.yaml` — it just does nothing
     until these two are filled in.
   - `DIAGNOSTIC_PIN` — optional, off by default (empty = disabled). Gates a
     separate parent-only login (not the child's demo session — the "Parent
     diagnostic preview" link on the demo's landing screen) into a live,
     single-session preview of the mastery-tracking diagnostic feature.
     Same strength rules as `CHILD_PIN`/`DEMO_PIN` if you do set it.
4. Everything else in `render.yaml` is either auto-generated
   (`SECRET_KEY`, `MASTER_SECRET`, `PARENT_PASSWORD` — random, nobody needs
   to remember them) or a fixed non-secret value, including `CORS_ORIGINS`
   (already set to `https://agnusdei-ai.github.io` — a browser's CORS
   `Origin` header is always just `scheme://host[:port]`, never a path, so
   this is correct even though the demo itself lives at
   `https://agnusdei-ai.github.io/bede/`).
5. Click deploy. First build takes a few minutes (installing
   `openai-whisper`, `librosa`, etc.). Once it's up, copy the service URL
   Render gives you — looks like `https://bede-demo-api-XXXX.onrender.com`.

## Wiring the demo frontend to it

1. On GitHub: `agnusdei-ai/bede` → **Settings → Secrets and variables →
   Actions → Variables** → add/edit `VITE_DEMO_API_BASE` = the Render URL
   from step 5 above (no trailing slash).
2. Re-run the **"Deploy demo to GitHub Pages"** workflow (Actions tab →
   select it → **Run workflow**, or just push any change under `demo/`) —
   `VITE_DEMO_API_BASE` is baked in at build time since the demo is a static
   site, so it won't pick up a variable change until the next build.
3. Open the deployed demo, click **"Generate my code"**, and confirm Bede's
   voice comes through.

## Custom domain (optional)

To serve the demo from your own apex domain (e.g. `agnusdei.ai`) instead of
`agnusdei-ai.github.io/bede/`:

1. **DNS** — at your domain's DNS provider, replace whatever's currently at
   the apex (`@`) with four `A` records, all pointing at GitHub Pages:
   `185.199.108.153`, `185.199.109.153`, `185.199.110.153`,
   `185.199.111.153`. (A `CNAME` record can't be used at a zone apex per
   DNS rules — that's why it's four `A` records instead of the single
   `CNAME` a subdomain like `demo.agnusdei.ai` could use instead.) Optionally
   add a `www` `CNAME` pointing at `<owner>.github.io` if you want
   `www.yourdomain` to resolve too — GitHub Pages will redirect it to the
   apex automatically once both are configured.
2. **Repo** — `demo/public/CNAME` already contains the target domain (Vite
   copies everything in `public/` verbatim into the build output, so this
   ships automatically on the next deploy). Update this one-line file if the
   final domain differs from what's there now.
3. **GitHub Pages settings** — once DNS has propagated (can take anywhere
   from minutes to a few hours), go to `agnusdei-ai/bede` → **Settings →
   Pages** and enter the custom domain in the **Custom domain** field, then
   save. GitHub verifies the DNS and provisions a free TLS certificate
   automatically — this step can't be done before DNS is live, since
   verification will fail against a domain that isn't pointed at GitHub yet.
4. **Backend CORS** — `render.yaml`'s `CORS_ORIGINS` already lists both
   `agnusdei.ai` and `bede.ai` (plus their `www` variants) ahead of time, so
   switching the live domain later needs no backend redeploy. Trim it back
   to just whichever domain is actually in use once that's settled, and drop
   the `agnusdei-ai.github.io` fallback once the custom domain is confirmed
   working end to end.
5. **Confirm** — open the new domain, generate a code, and confirm the chat
   works (a CORS mismatch here shows up as every `/tutor/chat` request
   silently failing in the browser console, not a visible error banner).

## Cold starts (free plan)

Render's free web-service plan spins `bede-demo-api` down after 15 minutes
with no inbound traffic; the next visitor eats a ~1-minute cold boot before
Bede responds. `.github/workflows/keep-demo-warm.yml` pings `/health` every
10 minutes during a 12:00-23:50 UTC window to keep the service warm for
most demo traffic without it — deliberately not 24/7, since Render's free
plan grants a shared **750 instance-hours/month across the whole
workspace**, and keeping one service warm around the clock burns nearly all
744 of a 31-day month's hours by itself, leaving nothing for `bede-demo-db`
or any other free service before the workspace gets suspended for the rest
of the month.

It starts working automatically once `VITE_DEMO_API_BASE` (see below) is
set — no separate setup. If demo traffic falls outside 12:00-23:50 UTC,
widen the hour range in that workflow's cron expression. If you want true
24/7 zero-cold-start coverage instead, skip the keep-alive workflow
entirely and upgrade `bede-demo-api` to Render's paid Starter plan (~$7/mo)
in the dashboard — it isn't subject to spin-down or the shared free-hours
cap at all.

## Staying up to date

Render auto-deploys on every push to `main` by default — once this is set
up, there's no `make update`/SSH step for the demo backend specifically;
pushing code (like this session's OpenAI TTS work) is enough. `.env`-only
changes (a new `OPENAI_TTS_VOICE`, say) are edited directly in Render's
dashboard under the service's **Environment** tab, which redeploys
automatically on save.

## If you'd rather self-host this instead

Nothing above is required — you can point `VITE_DEMO_API_BASE` at any
publicly-reachable `homeschool-api` deployment, including a self-hosted one
following the main `README.md`'s Docker Compose instructions, with
`DEMO_PIN` set in its `.env`. Render is a recommendation for the demo
specifically because it removes server-maintenance overhead for a
public-facing, stateless service — not a requirement.
