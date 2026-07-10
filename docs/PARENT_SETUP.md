# Setting Up Bede — A Guide for Parents & Tutors

This walks through everything from "nothing installed" to "my child is having their
first lesson," including the parts that matter for keeping it secure once you hand
it off. If you're comfortable with a terminal, the whole setup takes under 20 minutes.

## 1. What you'll need

- A computer, mini-PC, NAS, or Raspberry Pi to act as the "server" — it runs all the
  time your family uses Bede, and everyone's tablets connect to it over your home Wi-Fi.
- [Docker](https://docs.docker.com/get-docker/) installed on that machine.
- An [Anthropic API key](https://console.anthropic.com/) (this is what powers Bede's
  actual tutoring conversation).
- A database — `make setup` asks which you want:
  - **Local Postgres (recommended)** — nothing to sign up for. It runs
    alongside Bede in Docker on your own machine; nothing leaves your house.
    You're responsible for backing it up yourself (`make db-backup`).
  - **Managed Postgres** — [Neon](https://neon.tech) or [Supabase](https://supabase.com)
    both have generous free tiers. An extra account, but automatic backups.
- *(Optional)* Bede's spoken voice — see `docs/VOICE_SETUP.md`. A free,
  self-hosted option needs no account at all; a paid OpenAI option sounds
  meaningfully more natural if you'd rather pay a small per-use cost for it.

## 2. First-time setup

```bash
git clone <this repository>
cd bede
make setup
```

`make setup` asks you for the items above, generates the cryptographic secrets
automatically, and starts everything. When it finishes, open `https://localhost`
on the same computer to confirm it's running.

## 3. Understanding the security model — read this before you hand anything to your child

Bede uses **three separate layers**, and it matters which one you tell your child about:

| Credential | Who knows it | What it does |
|---|---|---|
| **Parent password** | You only — never the child | Full administrative access: configure students, view progress reports and transcripts, approve a session if voice check fails. |
| **Child PIN** | Every child in the household (it's shared, not per-child) | Gets to the "child" login screen — a low-stakes shared secret, like a house key. Must be 6+ digits and not an easily-guessable pattern — no sequential run (`123456`), repeated block (`111111`, `123123`), or palindrome (`669966`); repeated digits are otherwise fine, e.g. `602656` is a good PIN — `setup.sh` enforces this when you set it, and the app refuses to start in production mode with a weaker one. |
| **Voice passphrase** | Each child, for their own profile | The actual identity check — after entering the PIN, the child says *"I am ready to learn today!"* and Bede matches their voice against their enrolled profile. This is what personalizes their session, not the PIN. |

The PIN alone does **not** grant access to a specific child's lesson plan or history —
voice verification does. If voice check fails, the only way through is the parent
password (never a hidden bypass) — so a child can't skip their own verification
without you present.

## 4. Setting up each student

1. Log in with the **parent password** → you land on **Setup**.
2. Add each student: name, grade, and subjects. Grade is free text — use `K` for
   Kindergarten, or a number like `4` or `8`. The grade *stage* buttons (K–2 / 3–5 /
   6–8) set Bede's tone; the grade itself determines which curriculum content
   (books, math scope, composer/artist study) Bede draws from.
3. Toggle **voice required** off only for a student who can't do voice verification
   (e.g. a very young or non-verbal child) — this makes their login PIN-only.
4. Save, then from the **Pod Dashboard**, enroll each child's voice: they'll record
   the passphrase three times. This only needs to happen once per child.

## 5. Getting each child onto their own tablet

From the Pod Dashboard, **"Copy Link for Tablet"** gives you a link pre-filled with
that student's name — send it to their device (AirDrop, text, email) so they land
straight on their own login screen.

**For iPad specifically**, the first time only, each device needs to trust your
server's certificate:

```bash
make ipad-profile
```

This generates one file you AirDrop to the iPad (or serve locally and open in
Safari) that installs a Home Screen icon *and* trusts the certificate in a single
step. iOS still requires one manual toggle afterward — the tool prints the exact
path (Settings → General → About → Certificate Trust Settings). This works on
older iPads too (tested down to iOS 15.8).

## 6. *(Optional)* Giving Bede a real voice

By default, Bede speaks using your browser's built-in voice, which can sound
robotic. For a warm, dedicated voice instead — free, self-hosted, no account or
API key required — see `docs/VOICE_SETUP.md` for the full walkthrough.

If you skip this, everything still works — it just falls back to the browser voice
automatically.

## 7. Handing off to your child — what to actually tell them

Once a student is enrolled, that's genuinely all they need:

> "Open Bede on your tablet, enter **[the shared PIN]**, and say *'I am ready to
> learn today!'* when it asks. Talk to Bede like you'd talk to a patient teacher —
> you can type, tap the microphone and speak, or draw your answer."

Give them the **[docs/CHILD_GUIDE.md](CHILD_GUIDE.md)** page — it's written directly
to them. Do **not** share the parent password with your child; there's no legitimate
reason they'd need it day-to-day, and it's the one credential that can override
their voice check.

## 8. Checking in afterward

- **Progress page** (from the Pod Dashboard): narration scores, concept coverage,
  and — after 3+ sessions — Bede's synthesized sense of how that child learns best.
- Every session is saved as an encrypted transcript, viewable from the same place.
- If a child's voice changes enough that verification starts failing (common after
  a cold, or over months of growth), re-run enrollment from the Pod Dashboard.

## Troubleshooting

- **"Too many requests" on login** — the rate limiter (10 attempts/minute per
  device) tripped, usually from repeated rapid retries. Wait a minute.
- **A subject feels generic / not grade-appropriate** — only grades K, 4, and 8
  currently have curated curriculum content (books, math scope, composer/artist
  study). Other grades fall back to general guidance until more years are added.
- **Voice check keeps failing** — try re-enrolling; background noise and phone/tablet
  mic quality affect matching more than most people expect.
