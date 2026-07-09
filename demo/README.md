# Bede — Demo Build

A standalone, client-only version of Bede for trying it out on an iPad (or any
device) without setting up the full server stack. No Docker, no Postgres, no
separate host machine — it runs entirely in the browser.

**This is a demo, not the real app.** See `DEMO_SCRIPT.md` for a guided walkthrough
with reference prompts, and the table there for exactly what's different from the
production version in `docs/PARENT_SETUP.md` at the repo root.

## Running it

```bash
cd demo
npm install
npm run dev       # http://localhost:5173
```

On first load it asks for an Anthropic API key (required) and optionally an
ElevenLabs key + voice ID for a trained voice instead of the browser default. Both
are stored only in that browser's local storage — never committed, never sent
anywhere but directly to Anthropic/ElevenLabs.

## Building for deployment

```bash
npm run build     # outputs to demo/dist
```

The build uses a relative base path, so the output works whether it's served from a
domain root or a subpath (e.g. a GitHub Pages project site).

## What's included vs. left out

Ported from the real backend (`homeschool-api/services/ai_service.py`): the Bede
persona, grade-stage guidance, the four interactive tools (narration, hints,
celebration, faith connections), the deterministic safeguarding check, and — for
grades K, 4, and 8 specifically — the same curated book catalogs and subject term
plans (math scope, composer/artist/poet study) as the real `data/catalog/` files.

Left out because they need a real backend: voice-biometric login, encrypted
persistent storage, multi-student pods, progress tracking, and Whisper-based voice
fallback (this demo relies on the browser's native speech recognition only).
