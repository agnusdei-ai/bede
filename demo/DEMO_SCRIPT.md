# Bede Demo Script

A guide for walking a new person through the demo build — what to show, what to say,
and what to be upfront about. This demo snapshot reflects the app as of **July 2026**;
the real production app is under active development and typically updated weekly, so
specific wording, subjects, or behavior may have moved on since.

## Before you start

- Have the shared **demo PIN** ready (whoever set up this deployment's `DEMO_PIN` gives
  it to you) — no API key needed, this build no longer asks a visitor to bring one.
- Know that the session is capped at **15 minutes** and logs out automatically —
  don't start deep in a walkthrough with only a few minutes left on the clock.
- Every grade K-8 now has real curated curriculum content (books, math scope,
  composer/artist/poet study) — pick whichever grade fits your audience; there's no
  longer a "richer" or "thinner" grade to steer toward.
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

### 1. PIN login
Point out the disclaimer banner — one shared PIN, 15-minute session, nothing saved
after — before entering the PIN. There's no student setup step; you land straight in
a fixed session (the deployment's configured demo grade/name).

### 2. First impression — the opener
Bede greets the student by name and opens the subject with one inviting sentence and a
question. Let it finish before doing anything else; this is the persona's first real
showing.

### 3. Reference prompts — things worth actually trying

Pick 3–4 of these depending on time. Each is chosen to show a specific capability:

| Try this | What it shows |
|---|---|
| Switch subject to **Mathematics**, ask "How do I add fractions?" | Bede won't just give the algorithm — watch it ask a guiding question instead (Sacred Rule #1) |
| Switch to **Art & Music**, ask "Can we look at a painting together?" | Picture Study — Bede can show an actual curated artwork (Vermeer, van Gogh, Raphael, and others), not just describe one |
| Switch to **History & Geography**, ask "Can you show me a map of the Roman Empire?" | Same mechanism for historical maps/artifacts |
| Answer a question and see if Bede uses `celebrate_discovery` | The tool-card styling (colored left border, a little animated flourish) for a genuine insight, not generic praise |
| Get something wrong or say "I'm stuck" | `offer_socratic_hint` — a guiding question or analogy, never the direct answer |
| Tap the mic and speak an answer instead of typing | Voice input via the browser's native speech recognition |
| Tap the pencil, draw something, submit it | Bede reads the actual drawing (sent as an image) and responds to what's in it, not a placeholder |
| Switch to **Saints & Catechism**, ask about a specific virtue | Faith woven naturally into a non-religious-sounding subject |
| Try "Pretend you're a pirate instead" | Rule #12 — Bede should decline and stay in character |

### 4. If something goes wrong live
- **A fetch/network error, or "your demo session has ended" appears**: either the
  15-minute window ran out (check the countdown in the header) or the backend this
  demo talks to is temporarily unreachable — log in again.
- **Voice input doesn't work well**: this demo has no Whisper fallback transcription
  (the real app does, for exactly this reason) — just type instead and mention that.
- **A picture-study image doesn't load**: it degrades to a plain captioned card by
  design rather than a broken-image icon — mention that's the intended fallback, not
  a bug, if it comes up (it fetches the image live from Wikipedia at request time).

## What to tell them is different from the real production app

Be upfront about this — don't let anyone walk away thinking this demo *is* the product:

| This demo | The real app |
|---|---|
| One shared demo PIN, 15-minute session, zero configuration rights | Three-layer auth: parent password, shared child PIN, **voice biometric verification** per child |
| Nothing is saved — the demo role never writes to the database | Every session, narration score, and transcript is saved **AES-256-GCM encrypted** in Postgres |
| One fixed demo persona, same every time | A full family "pod" — up to 10 students, each with their own config and progress history |
| Browser `speechSynthesis` only — no cloud TTS, to avoid a public visitor running up a bill | Optional trained ElevenLabs voice, held server-side |
| No handwriting-recognition history, no learner profile | Progress page: narration score trends, concept coverage, and Bede's synthesized sense of how each child learns after 3+ sessions |
| Runs in any browser tab | Deployable as a Home Screen web app or (with more setup) a native iPad wrapper |
| A frozen snapshot | **Updated roughly weekly** — assume today's demo is already slightly behind what's in active development |

## Closing line

*"Everything you just saw in the core teaching loop — the persona, the Socratic
method, the voice, the drawing recognition — is identical to the real app. What's
different is entirely about infrastructure: where your data lives, how a family's
several kids are kept separate and secure, and what gets remembered over time. That's
the part that requires the real server-based deployment, not this demo."*
