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
