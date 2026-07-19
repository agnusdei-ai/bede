# Setting Up Bede — A Guide for Parents & Tutors

This walks through everything from "nothing installed" to "my child is having their
first lesson," including the parts that matter for keeping it secure once you hand
it off. No terminal or typed commands required — steps 2 and 3 below are answering
a form in your browser. The whole setup takes under 20 minutes either way.

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

## 2. Get the files onto your server machine

On GitHub, click the green **Code** button → **Download ZIP**, then unzip it
wherever you'd like on the server machine (no terminal needed for this part).

*(If you're comfortable with `git`, `git clone <this repository>` works too
— same result.)*

## 3. First-time setup

Open the unzipped folder and:

- **macOS**: double-click `setup-gui.command`.
- **Windows**: double-click `setup-gui.bat`.

A browser tab opens with a short form — fill in the items from step 1
above, click the button, and everything else happens automatically. When
it says Bede is running, open `https://localhost` on the same computer to
confirm.

*(Prefer a terminal? `make setup` or `bash setup.sh` asks the same
questions as typed prompts instead — see `docs/PRODUCTION_SETUP.md`.)*

> This browser-based setup is tested automatically on a regular schedule —
> the form, the file it produces, and Bede actually starting and answering
> requests from it are all checked end-to-end, not just by hand once. The
> one thing that check can't see is the literal double-click on your own
> macOS/Windows machine — if that ever behaves differently than described
> here, `make setup` / `bash setup.sh` is the terminal equivalent as a
> fallback.

## 4. Understanding the security model — read this before you hand anything to your child

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

**If a child expresses distress or danger**, Bede stops tutoring immediately —
regardless of subject or grade — and tells them to find a trusted adult right
now. This is a deterministic keyword/pattern check that runs before anything
reaches Claude, not a judgment call by the AI, and it works the same way
whether your child is typing in English or Spanish (if you've enabled the
Spanish toggle — see below), including the safety message itself, which
arrives in whichever language they're using. Every occurrence is written to
the encrypted audit log. If you set `PARENT_EMAIL` in your `.env` (see
`.env.example`), you'll also get an urgent email the moment it happens,
including a short excerpt of what triggered it — enough to know how to
follow up, without waiting for you to think to check the audit log
yourself. Leave `PARENT_EMAIL` unset if you'd rather rely on the audit log
alone; the safety stop itself always happens either way.

**That same `PARENT_EMAIL` also covers security alerts.** If Bede notices
a pattern like several failed login attempts, or a blocked attempt to pull
data out through the API, in a short window from one address, it emails
you the same way — once per pattern, so you'll hear about a real attempt
without your inbox filling up if it keeps happening. Every occurrence is
still recorded in the encrypted audit log regardless of whether
`PARENT_EMAIL` is set. See `docs/SECURITY.md` for the exact thresholds.

**Every message your child sends is also screened before Bede sees it.**
Beyond the distress/danger check above, a second, broader check looks for
content categories a fixed keyword list can't catch — things like violence
or content that isn't appropriate for the grade you've set. If something
trips this, your child sees a gentle redirect back to the lesson (not the
"find a trusted adult" message — that's reserved for the distress check),
and it's recorded in the audit log; three or more in a short window from
one address triggers the same security-alert email as above. This runs on
every single message (not just flagged ones), which means a small, real
cost on your Anthropic bill per message and a brief pause (well under a
second, typically) before Bede's reply starts — there's no setting to turn
it off, the same way the distress check isn't optional either.

**Want to test or explore how Bede responds, without a real tutoring session?**
Set `SANDBOX_PIN` in your `.env` and a **Sandbox** button appears on your Pod
Dashboard. It's a direct-answer chat just for you — Bede answers plainly
instead of Socratically, you can switch topics freely, and you can even try
your own draft lesson instructions to see how Bede would run with them.
Nothing said there is ever saved — no transcript, no student record. Leave
`SANDBOX_PIN` unset to skip this entirely (default).

## 5. Setting up each student

1. Log in with the **parent password** → you land on **Setup**.
2. Add each student: name and grade. Grade is free text — use `K` for
   Kindergarten, or a number like `4` or `8`. The grade *stage* buttons (K–2 / 3–5 /
   6–8) set Bede's tone; the grade itself determines which curriculum content
   (books, math scope, composer/artist study) Bede draws from.
3. Choose **how you'd like to start with Bede** — this is a starting point, not
   a lock, and every part of it stays editable afterward:
   - **Book Companion** — the lightest touch. Bede joins whatever books your
     family is already reading together, with nothing new to plan. Meant for
     families new to homeschooling, or easing into AI deliberately and
     cautiously, who want Bede anchored on their own physical books rather
     than driving the day.
   - **A Bit More Structure** — book-based discussion plus a few core
     subjects, a middle ground between the two.
   - **Full Daily Plan** — Bede covers the full Mater Amabilis subject
     rotation (the previous, and still the default, behavior).

   Picking one fills in a sensible subject list and session length below —
   you can still add, remove, or adjust either afterward using their own
   controls. This doesn't limit *which* subjects are available to pick from,
   only what's pre-selected to start.
4. Toggle **voice required** off only for a student who can't do voice verification
   (e.g. a very young or non-verbal child) — this makes their login PIN-only.
5. If your deployment offers a language other than English at login (`LOCALE`
   set in `.env` — see `docs/LOCALIZATION.md`), a **Sex** field appears for
   each student — Male or Female. This isn't optional once the toggle is
   enabled: Spanish, Italian, and Polish all require it to address your
   child correctly (the difference between "bienvenido" and "bienvenida,"
   for instance), and any student could be logged into in that language on
   any given day — not just the ones you expect to use it — so setup won't
   let you save a student without it set. On an English-only deployment
   (the default, no toggle offered at all), you'll never see this field at
   all.
6. Set the **session length** if the starting point you chose doesn't quite
   suit. Every session ends on its own when this time is up. The overall
   ceiling is four hours — that's built in and cannot be raised, whichever
   starting point you picked.
7. Decide whether to **lock chat appearance**. The chat has a small palette where
   a learner can pick a background theme and the color of their own speech
   bubbles. If choices like that pull your child away from the lesson (children
   with attention challenges especially), turn the lock on: the palette
   disappears from their sessions entirely. You can still open a session
   yourself as the parent, set a look you both like, and leave it locked.
8. Save, then from the **Pod Dashboard**, enroll each child's voice: they'll record
   the passphrase three times. This only needs to happen once per child.

**The language choice lives on the login screen, not on a student's profile.**
Once you've set `LOCALE` (step 5 above), everyone who logs in — you or any of
your children — sees an English/Español toggle right on the login screen
itself, chosen fresh every time. It isn't tied to which child is logging in:
the same child can be in English one day and Spanish the next, and a
bilingual household doesn't need separate profiles for each language.
Whichever is picked, Bede's own conversation (and the weekly prayer, see
below) switches immediately, in that language, for that login. The rest of
the screens — Setup, Dashboard, Progress — are still in English regardless
of the toggle for now; only the login screen and Bede's own words to your
child are translated so far.

**Sessions have a built-in rhythm of work and rest.** After every hour of
learning, a mandatory ten-minute break appears: the screen pauses and invites
your child to step away — be with nature, rest their eyes, or spend a quiet
moment with God — with a small suggestion each time. Nobody can skip it, and
the session picks up where it left off when the break ends. Grades K-3 also
pace each subject in twenty-minute blocks, which suits shorter attention
spans; grades 4-8 work in the hour-long stretches between breaks. You'll see
a countdown in the header shortly before each transition. On top of all
this, you can still set a stricter total screen-time cap per student, with a
longer eye-rest break, from the student's settings.

**Morning Time includes a weekly prayer, word for word.** Once a week, Bede leads
your child through one of the Church's own traditional prayers — the Our Father,
the Hail Mary, and similar universally-known texts — in whichever language was
chosen at login (English, or Spanish if your deployment offers the toggle and it
was selected for that login — see `docs/LOCALIZATION.md`). The wording is fixed
ahead of time rather than improvised in the moment, the same way Bede already
handles the week's poem, so your child hears and learns the same correct words
every time it comes up. This is separate from — and doesn't replace —
Bede's own freshly-worded opening and closing prayer each day (rule 10 of Bede's
persona), which stays personal to that day rather than a fixed recitation.

**The term selector (in "Term & mastery outcomes") does more than track mastery
topics.** Art & Music picture study follows the Mater Amabilis practice of one
composer or artist per term — which artist is showing is tied directly to the
**Term** dropdown you set there, not to the calendar or how many sessions
you've run. If you never advance it, your child sees the same handful of
pictures for that one artist indefinitely — nothing rotates it for you.
Advance the term yourself each time your family's own term/quarter turns
over. (The weekly poem and prayer above are different — those rotate
automatically off the calendar and need no action from you.)

**Composition is encouraged, never required.** At least once per session,
Bede invites your child to spend about ten minutes on a piece of their own
handwritten work — a written narration, a nature journal entry, math worked
out on paper — that pulls the day's learning together and helps it stick.
He waits for a natural pause rather than interrupting whatever your child
is in the middle of, and if the child declines, he accepts that and moves
on. If you'd like the composition pointed somewhere particular, mention it
in the student's lesson note and Bede will fold it in.

## 6. Getting each child onto their own tablet

**First, each new device needs to trust your server's certificate** — a
one-time step per device, no terminal required. On the tablet (Android,
iPad, or otherwise), open:

```
http://<your-server's-address>/trust
```

or scan the QR code shown on that page from another device already on your
network. Tap through the one confirmation step your platform asks for
(the page shows exactly what to tap for Android, iPad, Windows, and macOS),
then tap **"Continue to Bede"** on the same page. After this, the tablet
stops showing certificate warnings for this server.

*(Prefer a terminal? `make caddy-trust` prints the same certificate to
install by hand — same one-time result.)*

**iPad shortcut:** `make ipad-profile` (requires a terminal) generates one
file that installs a Home Screen icon *and* trusts the certificate in a
single step, instead of doing both separately. iOS still requires one
manual toggle afterward either way (Settings → General → About →
Certificate Trust Settings). Works on older iPads too (tested down to
iOS 15.8).

**Then**, from the Pod Dashboard, **"Copy Link for Tablet"** gives you a link
pre-filled with that student's name — send it to their device (AirDrop, text,
email) so they land straight on their own login screen.

## 7. *(Optional)* Giving Bede a real voice

By default, Bede speaks using your browser's built-in voice, which can sound
robotic. Two options for something better — see `docs/VOICE_SETUP.md` for
the full walkthrough: a paid option (OpenAI, small per-use cost) that
sounds meaningfully more natural, or a free, self-hosted option with no
account needed but a lower quality ceiling.

If you skip this, everything still works — it just falls back to the browser voice
automatically.

## 8. Handing off to your child — what to actually tell them

Once a student is enrolled, that's genuinely all they need:

> "Open Bede on your tablet, enter **[the shared PIN]**, and say *'I am ready to
> learn today!'* when it asks. Talk to Bede like you'd talk to a patient teacher —
> you can type, tap the microphone and speak, or draw your answer."

Give them the **[docs/CHILD_GUIDE.md](CHILD_GUIDE.md)** page — it's written directly
to them. Do **not** share the parent password with your child; there's no legitimate
reason they'd need it day-to-day, and it's the one credential that can override
their voice check.

The writing pad (the pencil icon in a session) has a print button if your child
prefers a real pencil to a stylus — it prints at true page size on any printer
connected to their tablet, with handwriting ruling scaled to their `GradeStage`
(wide 5/8" primary ruling for K-2, standard 3/8" for 3-5, narrower 1/4" for 6-8),
so what comes out matches ordinary classroom handwriting paper.

## 9. Checking in afterward

- **Progress page** (from the Pod Dashboard): narration scores, concept coverage, and
  Bede's sense of how that child learns best — available from the very first session
  (an initial, tentative read that sharpens as more sessions accumulate), not just
  after 3+. If Bede profiles your child as a kinesthetic ("learns by doing"),
  reading/writing, or visual learner, the same page shows a small observation
  confirming how often Bede has actually followed through (hands-on drawing/writing,
  written narration, or a shown visual aid, respectively) — a sanity check on the
  adaptation itself, not a claim that the label makes your child learn better. An
  auditory profile changes how Bede teaches (favoring oral narration and discussion)
  but has no equivalent counter — there's no single tool call that cleanly signals
  it the way the other three have.
- Every session is saved as an encrypted transcript, viewable from the same place.
- If a child's voice changes enough that verification starts failing (common after
  a cold, or over months of growth), re-run enrollment from the Pod Dashboard.
- **Deleting a child's data:** Pod Dashboard → that student's card → **Delete all
  data…**, then type their name to confirm. This permanently removes everything
  Bede has stored for them — narration history, learner profile, mastery tracking,
  session transcripts, voice enrollment, all of it — not just today's plan. It
  cannot be undone. See `docs/DATA_RETENTION.md` for the full, table-by-table list
  of what's kept and for how long.

## Troubleshooting

- **"Too many requests" on login** — the rate limiter (10 attempts/minute per
  device) tripped, usually from repeated rapid retries. Wait a minute.
- **A subject feels generic / not grade-appropriate** — only grades K, 4, and 8
  currently have curated curriculum content (books, math scope, composer/artist
  study). Other grades fall back to general guidance until more years are added.
- **Voice check keeps failing** — try re-enrolling; background noise and phone/tablet
  mic quality affect matching more than most people expect.
