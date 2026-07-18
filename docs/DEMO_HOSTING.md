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
   (already set to `https://agnusdei-ai.github.io` — a browser's CORS
   `Origin` header is always just `scheme://host[:port]`, never a path, so
   this is correct even though the demo itself lives at
   `https://agnusdei-ai.github.io/bede/`).
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
2. **Repo** — `site/CNAME` already contains the target domain, but nothing
   publishes it yet (see "Why the apex isn't just the demo" below) — do this
   step and the next one together, not this one in advance. Restore the
   "Assemble Pages site" step in `.github/workflows/deploy-demo.yml` (or
   rewrite the workflow to publish `site/` some other way) so the deployed
   artifact actually includes `site/CNAME`, and push that once DNS is live,
   not before.
3. **GitHub Pages settings** — once DNS has propagated (can take anywhere
   from minutes to a few hours) *and* the CNAME-carrying deploy from step 2
   has run at least once, go to `agnusdei-ai/bede` → **Settings → Pages**
   and confirm the **Custom domain** field shows the right value (GitHub
   usually fills it in automatically from the published `CNAME` file; enter
   it by hand if it didn't). GitHub verifies the DNS and provisions a free
   TLS certificate automatically — this can't succeed before DNS is live,
   since verification fails against a domain that isn't pointed at GitHub
   yet.
4. **Backend CORS** — `render.yaml`'s `CORS_ORIGINS` already lists both
   `agnusdei.ai` and `bede.ai` (plus their `www` variants) ahead of time, so
   switching the live domain later needs no backend redeploy. Trim it back
   to just whichever domain is actually in use once that's settled, and drop
   the `agnusdei-ai.github.io` fallback once the custom domain is confirmed
   working end to end. The demo living under `/bede/` rather than at the
   domain root doesn't affect this at all — a browser's CORS `Origin` header
   is always just `scheme://host[:port]`, never a path.
5. **Confirm** — open the new domain, generate a code, and confirm the chat
   works (a CORS mismatch here shows up as every `/tutor/chat` request
   silently failing in the browser console, not a visible error banner).

### Why the apex isn't just the demo (and why that's not deployed yet)

The domain's root (`agnusdei.ai`) is meant to eventually be the company's
home page, not the interactive demo — Bede is meant to be the first of
several products, not the only thing the domain will ever host. The repo
has the pieces for that: `site/` (a small, hand-written static page,
`site/index.html`, no build step, no framework, with a "Meet Bede →" link)
and `site/CNAME` (`agnusdei.ai`).

**But the live workflow does not publish `site/` yet — it deploys `demo/dist`
directly, exactly as it did before this idea existed.** That's deliberate,
learned the hard way: a first attempt published `site/`'s contents at the
artifact root and nested `demo/dist` under `/bede/` within it. That broke
the *only* URL that's actually live right now, `agnusdei-ai.github.io/bede/`
(the `/bede/` segment there comes from the repo being named `bede` — it has
nothing to do with the subpath restructuring). Two separate problems, either
one enough to cause an outage on its own:

1. The demo moved to `agnusdei-ai.github.io/bede/bede/` — the doubled path
   nobody would guess or already has linked.
2. Worse: **GitHub Pages auto-detects a `CNAME` file in whatever gets
   published and silently turns on the custom-domain setting from it** —
   no visit to Settings → Pages required. Publishing `site/CNAME` as part of
   the artifact quietly pointed the whole deployment at `agnusdei.ai`, and
   since DNS was never pointed at GitHub Pages for that domain, the result
   wasn't "shows the wrong page," it was the site becoming unreachable
   entirely.

**If you're reading this after that happened once already:** check
`agnusdei-ai/bede` → **Settings → Pages** — if **Custom domain** shows
`agnusdei.ai`, clear that field now (leave it blank) and save. It'll stay
that way until you deliberately redo the steps below.

**To actually do the apex/subpath split, do it as one coordinated change,**
not two separate ones — reintroducing the "Assemble Pages site" step
(`site/` at the artifact root, `demo/dist` copied to `<root>/bede/`, matching
what's already written in `site/index.html`'s `/bede/` link) at the same
time as the DNS + GitHub Pages steps below, so there's no window where a
CNAME is live in the deployed artifact but DNS isn't ready to answer for it.
The commit history has the original "Assemble Pages site" step if you want
to restore it verbatim rather than rewrite it.

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

## Expecting a crowd? (public events, ~100 simultaneous users)

The frontend is static files on GitHub Pages — it scales to any audience
without you doing anything, and its first load is small (roughly 100 KB of
compressed code plus under 100 KB of images). The backend is the part to
prepare:

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
