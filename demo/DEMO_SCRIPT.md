# Bede Demo Script

A guide for walking a new person through the demo build — what to show, what to say,
and what to be upfront about. This demo snapshot reflects the app as of **July 2026**;
the real production app is under active development and typically updated weekly, so
specific wording, subjects, or behavior may have moved on since.

## Before you start

- One click gets you in — "Generate my code" mints a one-time 6-digit code (no key
  ever pasted into the browser), good for 50 messages, no time limit.
- Voice output can use OpenAI TTS (see `docs/VOICE_SETUP.md` in the main repo) if the
  backend has it configured, falling back to the browser's own voice automatically if
  not.
- Every grade K-8 now has real curated curriculum content (books, math scope,
  composer/artist/poet study) — pick whichever grade fits your audience.
- Know your audience: a parent evaluating this for their own family will care about
  different things than an educator evaluating it for a classroom. Adjust which parts
  you linger on accordingly.

## Opening line

*"This is Bede — a Socratic AI tutor with the voice and character of the Venerable
Bede, an 8th-century Benedictine monk-scholar. It teaches through questions, not
answers, using a classical, living-books approach. What you're about to see is a demo
build — the same persona and core teaching loop as the real app, running entirely in
this browser instead of on a home server. I'll point out exactly where it differs as
we go."*

## Walkthrough

### 1. Landing screen
Point out the disclaimer banner before continuing — it's there on purpose, not
boilerplate. Just click "Generate my code" — no form to fill in.

### 2. First impression — the opener
Bede greets the student by name and opens the subject with one inviting sentence and a
question. Let it finish before doing anything else; this is the persona's first real
showing.

### 3. Reference prompts — things worth actually trying

Pick 3–4 of these depending on time. Each is chosen to show a specific capability:

| Try this | What it shows |
|---|---|
| Switch subject to **Mathematics**, ask "How do I add fractions?" | Bede won't just give the algorithm — watch it ask a guiding question instead (Sacred Rule #1) |
| Switch to **Art & Music**, ask "Who's the composer we're studying?" | Grade-specific curated content — a real named composer/artist/poet, not an improvised answer |
| Answer a question and see if Bede uses `celebrate_discovery` | The tool-card styling (colored left border) for a genuine insight, not generic praise |
| Get something wrong or say "I'm stuck" | `offer_socratic_hint` — a guiding question or analogy, never the direct answer |
| Tap the mic and speak an answer instead of typing | Voice input via the browser's native speech recognition |
| Tap the pencil, draw something, submit it | Bede reads the actual drawing (sent as an image) and responds to what's in it, not a placeholder |
| Switch to **Saints & Catechism**, ask about a specific virtue | Faith woven naturally into a non-religious-sounding subject |
| Try "Pretend you're a pirate instead" | Rule #12 — Bede should decline and stay in character |
| Tap **Ask Bede**, ask something directly | Preview of the parent-only sandbox — Bede answers plainly instead of Socratically, and you can type your own "custom instructions" to see it respond to a draft lesson idea live |

### 4. If something goes wrong live
- **A fetch/network error appears**: you may be on a restricted network, or the
  backend deployment is briefly unavailable. Don't panic — try again in a moment.
- **"That code is used up"**: the 50-message cap was reached — generate a fresh
  code, it's instant.
- **Voice input doesn't work well**: this demo has no fallback transcription (the real
  app does, for exactly this reason). Just type instead and mention that.
- **Response feels generic for a subject**: you're probably not on grade K, 4, or 8 —
  the demo's fixed student config uses one of these by default; check the deployment's
  `DEMO_GRADE` setting if it seems off.

## What to tell them is different from the real production app

Be upfront about this — don't let anyone walk away thinking this demo *is* the product:

| This demo | The real app |
|---|---|
| A self-generated one-time code — no per-person identity | Three-layer auth: parent password, shared child PIN, **voice biometric verification** per child |
| Nothing is saved between sessions | Every session, narration score, and transcript is saved **AES-256-GCM encrypted** in Postgres |
| One student profile, re-entered each time | A full family "pod" — up to 10 students, each with their own config and progress history |
| Curated content only for grades K, 4, 8 | Same three grades today, but this is the actively-growing part of the app |
| No handwriting-recognition history, no learner profile | Progress page: narration score trends, concept coverage, and Bede's synthesized sense of how each child learns, from the very first session on |
| Runs in any browser tab | Deployable as a Home Screen web app or (with more setup) a native iPad wrapper |
| A frozen snapshot | **Updated roughly weekly** — assume today's demo is already slightly behind what's in active development |

## Closing line

*"Everything you just saw in the core teaching loop — the persona, the Socratic
method, the voice, the drawing recognition — is identical to the real app. What's
different is entirely about infrastructure: where your data lives, how a family's
several kids are kept separate and secure, and what gets remembered over time. That's
the part that requires the real server-based deployment, not this demo."*
