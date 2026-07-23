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
   - `LICENSE_KEY` — leave this **unset**. `core/config.py`'s
     `Settings.is_demo_deployment` exempts any deployment with `DEMO_PIN` set
     (this one) from the license-validity check that a real family instance
     must pass under `PRODUCTION=true` — the public demo is meant to be
     zero-friction for prospective customers to try, not gated behind the
     same paid-license check it exists to sell. See **Licensing** below.
     Pasting something into this field anyway (a stray API key, a copy-paste
     mistake) fails startup with `LICENSE_KEY is invalid: signature
     verification failed`, not anything CORS- or Anthropic-key-shaped, even
     though the resulting Render deploy failure can look similar at a
     glance — the fix there is simply to clear the field, not to hunt for a
     valid license.
4. Everything else in `render.yaml` is either auto-generated
   (`SECRET_KEY`, `MASTER_SECRET`, `PARENT_PASSWORD` — random, nobody needs
   to remember them) or a fixed non-secret value, including `CORS_ORIGINS`
   (already lists `https://agnusdei-ai.github.io` and
   `https://bede.agnusdei.workers.dev` — a browser's CORS `Origin` header is
   always just `scheme://host[:port]`, never a path, so listing the origin
   is correct even though the demo itself is actually at
   `https://bede.agnusdei.workers.dev/bede/`; `agnusdei-ai.github.io` no
   longer needs it — see "GitHub Pages now redirects" below — but leaving an
   unused origin here is inert, not worth a separate cleanup).
5. Click deploy. First build takes a few minutes (installing
   `faster-whisper`, `librosa`, etc., and pre-downloading the fallback-STT
   model weights into the image — see docs/VOICE_SETUP.md). Once it's up,
   copy the service URL Render gives you — looks like
   `https://bede-demo-api-XXXX.onrender.com`.

## Licensing

`bede-demo-api` runs `PRODUCTION=true` (see `render.yaml`), but it is
**exempt** from the `LICENSE_KEY` requirement a real family instance must
satisfy: `core/config.py`'s `reject_missing_or_invalid_license_in_production`
validator skips the check entirely whenever `Settings.is_demo_deployment`
is true, which it is for any deployment with `DEMO_PIN` set (this one). The
demo is a stateless, zero-seat instance meant to be frictionless for
prospective customers to try — gating it behind the same paid-license check
it exists to sell would be self-defeating, and there's no per-family seat
count to enforce here in the first place. Just leave `LICENSE_KEY` unset in
Render.

A real family's self-hosted instance is not exempt — see
`docs/PRODUCTION_SETUP.md#licensing` for how to issue one of those (requires
the Ed25519 private key from `scripts/generate_license_keypair.py`, which is
deliberately never stored in this repo).

## Spanish beta testing

`render.yaml` sets `LOCALE: es` as a fixed (non-secret) value on
`bede-demo-api`, so a fresh Blueprint deploy — or a synced redeploy of an
existing one — offers the English/Español toggle on the demo's `CodeScreen`
out of the box, exactly the same per-login mechanism documented in
`docs/LOCALIZATION.md`. Nothing else needs configuring: `POST /auth/login`
already embeds whatever locale was chosen into every role's JWT, `demo_code`
included, and `_locale_directive` (`services/ai_service.py`) has Bede
converse with the visitor natively in Spanish from that point on, not a
translated-after-the-fact reply.

**If your `bede-demo-api` predates this**, Render's Blueprint sync applies
`render.yaml` changes to fixed-value env vars automatically on the next
deploy triggered by a push to `main` — no dashboard step needed. If you want
to confirm sooner, or your Render dashboard has auto-sync turned off for
this service, check the **Environment** tab for `LOCALE=es` and add it by
hand if it's missing.

**To verify:** open the deployed demo, confirm an English/Español toggle
renders above the "Generate my code" form, click **Español**, and confirm
the whole screen re-renders live (title, field labels, privacy notice,
button text — not just the toggle labels themselves). Generate a code and
confirm Bede's own replies come back in Spanish, not English.

**What beta testers will and won't see in Spanish**, per
`docs/LOCALIZATION.md`'s disclosed scope: `CodeScreen` (the entry screen)
and Bede's own conversational replies are localized; `ChatScreen`'s chrome,
parent controls, and the sandbox/diagnostic previews past login stay
English regardless of which language was picked at the code screen — a
known, disclosed gap, not something to file as a bug during this round of
testing.

**One more expected quirk worth flagging to testers up front:** the demo
never collects a student's sex (see `_demo_session_config` in
`routers/tutor.py` — it's a zero-friction, name/grade-only flow by design),
so Bede will use gender-neutral Spanish phrasing with every demo visitor
rather than the grammatically-agreeing "bienvenido"/"bienvenida" a real
family's session produces once `SessionConfig.sex` is on file (see
`docs/LOCALIZATION.md`'s "Sex, not gender-neutral hedging" section). That's
correct, intended behavior for the demo specifically, not a regression.

The Spanish strings shipped so far are AI-drafted and reviewed for
naturalness across multiple passes, not yet reviewed by a native speaker —
treat this beta round as a chance to surface exactly that kind of feedback
(phrasing that reads as awkward or overly literal, register that feels off)
via the beta feedback form (`FEEDBACK_EMAIL`, `routers/feedback.py`) rather
than assuming the translation is launch-final.

To turn Spanish back off for this deployment — say, to isolate whether an
issue is locale-specific — set `LOCALE=en` (or delete the var entirely,
same effect) on `bede-demo-api` in Render's dashboard and let it redeploy;
no code change required either way.

## Wiring the demo frontend to it

The live deployment is the Cloudflare Worker (`bede.agnusdei.workers.dev`),
built via Git integration rather than the GitHub Actions workflow — GitHub
Pages only redirects to it now (see "GitHub Pages now redirects" below) and
never runs the demo's own build, so `VITE_DEMO_API_BASE` has to be set on
the Cloudflare side:

1. **Workers & Pages → `bede` → Settings**, scroll to the **Build** section
   → its own **Variables and secrets** (a `+` button, currently showing
   "None") — this is a *build-time* variable, distinct from the runtime
   "Variables and secrets" section higher up the page, which is disabled
   entirely for this Worker ("Variables cannot be added to a Worker that
   only has static assets") since there's no `main` script to read them at
   request time.
2. Add `VITE_DEMO_API_BASE` = the Render URL from step 5 above (no trailing
   slash).
3. Trigger a new deployment (Deployments tab → retry, or push any commit) —
   Vite bakes this in at build time, so the existing deployment won't pick
   it up on its own.
4. Open `https://bede.agnusdei.workers.dev/bede/`, click **"Generate my
   code"**, and confirm Bede's voice comes through.

Once `agnusdei.ai` is live on this same Worker (see the custom domain setup
below), these steps and the resulting variable apply there too — it's the
same Worker answering on both hostnames, not a separate deployment to wire
up again.

## GitHub Pages now redirects

The canonical live deployment is a **Cloudflare Worker**
(`bede.agnusdei.workers.dev`), built by `scripts/build_pages_site.sh`: `site/`
(the company's own home page — a small, hand-written static page,
`site/index.html`, no build step, no framework, with a "Meet Bede →" link to
`/bede/`) at the root, and the interactive demo nested under `/bede/`
beneath it, matching that link. So `bede.agnusdei.workers.dev` shows the
marketing page and `bede.agnusdei.workers.dev/bede/` shows the demo.

GitHub Pages (`.github/workflows/deploy-demo.yml`) no longer serves a live
copy of that build — it publishes two tiny redirect stubs instead
(`scripts/build_github_pages_redirect.sh`), so `agnusdei-ai.github.io`
forwards to `bede.agnusdei.workers.dev/` and `agnusdei-ai.github.io/bede/`
forwards to `bede.agnusdei.workers.dev/bede/`. This keeps any link already
shared or bookmarked against the old GitHub Pages URLs landing somewhere
real, without this repo having to keep two independently live copies from
drifting apart. GitHub Pages has no server-side redirect support (no
`_redirects` file, no rewrite rules), so these are client-side
(`<meta http-equiv="refresh">` + a JS `location.replace()`, with a plain
link as a no-JS fallback) — the standard workaround for a GitHub Pages
redirect.

Once `agnusdei.ai`'s nameservers are pointed at Cloudflare and the custom
domain is attached to this same Worker (see the one-time setup below), that
domain serves the identical build directly — no redirect needed between
`bede.agnusdei.workers.dev` and `agnusdei.ai`, since Cloudflare's Custom
Domains feature lets one Worker answer on both hostnames at once.

**Why Cloudflare Pages and not a GitHub Pages custom domain** (the
originally-planned approach): a first attempt at exactly this apex/subpath
split on GitHub Pages caused a real near-outage. **GitHub Pages
auto-detects a `CNAME` file anywhere in the published artifact and silently
turns on the custom-domain setting from it** — no visit to Settings → Pages
required. Publishing `site/CNAME` (which held `agnusdei.ai`) as part of the
artifact quietly pointed the whole deployment at that domain, and since DNS
was never pointed at GitHub Pages for it, the result wasn't "shows the
wrong page," it was the site becoming unreachable entirely — on top of a
*second*, independent bug in the same attempt (the demo itself moving to a
doubled `/bede/bede/` path). Cloudflare Pages has no equivalent
auto-detection footgun: a custom domain is attached explicitly, in the
dashboard or via API, never inferred from a file in the build output. The
old `site/CNAME` file has been removed from the repo entirely rather than
carried forward inert — Cloudflare doesn't read it, and leaving a
GitHub-Pages-specific trigger file lying around after deliberately moving
away from GitHub Pages custom domains is exactly the kind of thing that
causes this same class of mistake again later.

`scripts/build_pages_site.sh` does the assembly (`site/` at the output
root, a fresh `demo/dist` build nested under `<output>/bede/`) — a plain
shell script rather than logic duplicated per platform, so it runs
identically whether GitHub Actions invokes it (`deploy-demo.yml`),
Cloudflare invokes it, or you run it locally to preview.

**One-time Cloudflare Pages setup:**

1. Create a Cloudflare account if you don't have one, and add `agnusdei.ai`
   as a site (**Add a site** → enter the domain). Cloudflare will show you
   two nameservers to set at your domain registrar — this is the one step
   only you can do (registrar access, not something scriptable from here).
   DNS propagation after the nameserver change can take anywhere from
   minutes to about 24 hours.
2. **Workers & Pages → Create → Pages → Connect to Git**, select
   `agnusdei-ai/bede`. Configure the build:
   - **Build command**: `bash scripts/build_pages_site.sh`
   - **Build output directory**: `publish`
   - **Root directory**: `/` (repo root — the script itself `cd`s into
     `demo/` as needed)
3. **Environment variables** (Pages project → Settings → Environment
   variables): add `VITE_DEMO_API_BASE` = your Render backend URL (no
   trailing slash) — same value the old GitHub Actions `vars.VITE_DEMO_API_BASE`
   held. Vite bakes this in at build time, so it must be set here, not just
   on the backend.
4. **Custom domains** (Pages project → Custom domains): add `agnusdei.ai`
   (and `www.agnusdei.ai` if you want that to resolve too — Cloudflare
   offers a one-click redirect rule for it). Cloudflare issues and manages
   the TLS certificate automatically once the domain's nameservers are
   actually pointed at Cloudflare from step 1.
5. **While you're already touching DNS for this domain**, add Resend's
   domain-verification records (TXT/DKIM, from Resend's dashboard → your
   domain → DNS records) for `agnusdei.ai` too, if you haven't — this is
   what `RESEND_FROM_ADDRESS` needs to actually be able to send mail (see
   "Wiring the demo frontend to it" above and `services/email_service.py`'s
   `email_configured()`), and doing it in the same DNS session avoids a
   second round of propagation waiting later.
6. **Backend CORS** — `render.yaml`'s `CORS_ORIGINS` already lists
   `agnusdei.ai` and `bede.ai` (plus `www` variants) ahead of time, so this
   needs no backend redeploy. Trim it back to just whichever domain is
   actually in use once settled, and drop the `agnusdei-ai.github.io`
   fallback once the custom domain is confirmed working end to end.
7. **Confirm** — open `agnusdei.ai` (the home page) and `agnusdei.ai/bede/`
   (the demo), generate a code, and confirm the chat works. A CORS mismatch
   here shows up as every `/tutor/chat` request silently failing in the
   browser console, not a visible error banner.
8. GitHub Pages doesn't need retiring the way an earlier version of this
   plan assumed — it's already just a redirect to
   `bede.agnusdei.workers.dev` (see "GitHub Pages now redirects" above), not
   a second live copy. Once `agnusdei.ai` is confirmed working, update
   `scripts/build_github_pages_redirect.sh`'s `MARKETING_URL`/`DEMO_URL` to
   point at `agnusdei.ai` instead, so old GitHub Pages links forward to the
   final domain rather than the workers.dev one.

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

The demo page also helps itself: the moment it loads, it fires a
fire-and-forget ping to `/health` (`warmDemoBackend` in `demo/src/api.ts`),
so a sleeping backend starts waking while the visitor is still reading the
consent notice and typing a name. And if "Generate my code" still runs
long, the form says plainly that Bede is waking up rather than leaving an
unexplained spinner. Neither replaces the keep-alive above — they just
soften the one cold start it doesn't cover.

## Memory limits (free plan)

Distinct from the cold-start problem above: Render's free web-service plan
caps RAM at **512MB**, and `bede-demo-api`'s own dependencies sit close to
that ceiling from imports alone, before a single request is served —
`resemblyzer`'s speaker-verification model pulls in the full PyTorch
runtime (~480MB just to import), and `services/transcription.py`'s
faster-whisper fallback STT (`ctranslate2`) opportunistically imports torch
itself the moment it's installed in the environment, regardless of whether
`resemblyzer` ever runs. A real incident confirmed this: Render's
"exceeded its memory limit" alert fired for `bede-demo-api`, triggering an
automatic restart that made the demo briefly unreachable.

`main.py`'s `_warm_voice_models()` now skips preloading `resemblyzer`
entirely on a demo deployment (`settings.is_demo_deployment`) — voice
biometric auth (`/voice/enroll`, `/voice/verify`, `/voice/override`) is
parent-only and structurally unreachable by the demo's `demo_code` role
either way, so preloading it was pure waste on this deployment shape. Be
clear-eyed about what this buys, though: measured directly, it only trims
~30MB of live RSS. The dominant cost (torch, ~480MB) loads regardless,
because the demo genuinely does need faster-whisper for its own STT
fallback, and `ctranslate2` pulls torch in the moment it's present in the
environment — this fix doesn't eliminate that.

If OOM restarts recur, the real fix is more RAM, not just no-spin-down:
confirm current specs on Render's pricing page before upgrading — the
Starter plan historically matches the free plan's RAM (it buys no
spin-down, not more memory), so eliminating this specific failure mode
needs whichever tier actually raises the memory allocation, not just the
next plan up.

## Expecting a crowd? (public events, ~100 simultaneous users)

The frontend is static files on Cloudflare's edge network — it scales to
any audience without you doing anything, and its first load is small
(roughly 100 KB of compressed code plus under 100 KB of images). The
backend is the part to prepare:

1. **Upgrade `bede-demo-api` off the free plan for the event window**
   (Starter or above). The free instance is small and spins down when
   idle; a paid instance is always on and meaningfully faster. You can
   downgrade again afterward.
2. **Mind the per-IP rate limits**: 10 auth requests and 120 API calls
   per minute *per IP address* by default. A hundred visitors on their
   own homes/phones are nowhere near this. But a single venue where
   everyone shares one Wi-Fi (one public IP) WILL trip the auth bucket at
   the "Generate my code" step. For that scenario, raise the limits from
   Render's dashboard — set `RATE_LIMIT_AUTH_PER_MINUTE` (and, for a
   large room, `RATE_LIMIT_API_PER_MINUTE`) as environment variables on
   `bede-demo-api` and let it restart; no code change involved. Or have
   attendees use cellular data.
3. **Anthropic rate limits are the real concurrency ceiling** for chat:
   each active conversation is a streaming request against your API key's
   tier. Check your organization's limits before the event; the demo
   persists nothing, so the backend itself (async FastAPI, SSE) is not
   the bottleneck.

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
