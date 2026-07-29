# Setting Up Bede — A Guide for Parents & Tutors

This walks through everything from "nothing installed" to "my child is having their
first lesson," including the parts that matter for keeping it secure once you hand
it off. No terminal or typed commands required — steps 2 and 3 below are answering
a form in your browser. The whole setup takes under 20 minutes either way.

## 1. What you'll need

- A computer, mini-PC, NAS, or Raspberry Pi to act as the "server" — it runs all the
  time your family uses Bede, and everyone's tablets connect to it over your home Wi-Fi.
  Any of these is genuinely fine; see "Choosing your server machine" below if you're
  buying something for this or wondering whether what you already own is enough.
- [Docker](https://docs.docker.com/get-docker/) installed on that machine.
- An AI provider for Bede's actual tutoring conversation — pick whichever
  fits your family, `make setup` asks and there's no default forced on you:
  an [Anthropic](https://console.anthropic.com/), [OpenAI](https://platform.openai.com/api-keys),
  or [Mistral](https://console.mistral.ai/) account (cloud, pay-as-you-go),
  or a self-hosted open-weight model on your own GPU server (no account,
  no per-message cost — see `docs/PROVIDER_ADAPTERS.md`).
- A database — `make setup` asks which you want:
  - **Local Postgres (recommended)** — nothing to sign up for. It runs
    alongside Bede in Docker on your own machine; nothing leaves your house.
    You're responsible for backing it up yourself (`make db-backup`).
  - **Managed Postgres** — [Neon](https://neon.tech) or [Supabase](https://supabase.com)
    both have generous free tiers. An extra account, but automatic backups.
- *(Optional)* Bede's spoken voice — see `docs/VOICE_SETUP.md`. A free,
  self-hosted option needs no account at all; a paid OpenAI option sounds
  meaningfully more natural if you'd rather pay a small per-use cost for it.

### Choosing your server machine

Bede's server does less heavy lifting than you might expect. For most of a
lesson it's relaying the conversation to whichever AI provider you picked and
storing your child's work encrypted — not doing the thinking itself. That's why
a modest always-on machine, including a Raspberry Pi, is a perfectly reasonable
choice, and why you don't need a powerful or expensive computer to run this well.

Two things genuinely depend on how strong that machine is, and one that doesn't:

- **The AI provider you can choose.** The self-hosted open-weight model option
  (the one with no account and no per-message cost) needs a dedicated NVIDIA
  GPU on Linux. A Raspberry Pi, a NAS, a Mac, or an ordinary laptop **cannot**
  run it. That's not a limitation of Bede — it's what that class of model
  requires. On those machines, pick one of the cloud providers (Anthropic,
  OpenAI, or Mistral) instead; everything else about Bede works identically.
  Full hardware tiers are in `docs/PROVIDER_ADAPTERS.md`.
- **How fast the microphone feels.** When your child speaks, your server's own
  processor turns that recording into text. This is always done on your own
  machine — there is no cloud option for it, by design, so your child's voice
  never leaves your house. On a low-power machine like a Pi, expect each spoken
  answer to take noticeably longer to come back than it would on a modern
  desktop. It works; it's just slower per turn, and typing an answer instead is
  always available if a child would rather not wait. (The paid OpenAI voice
  option affects *Bede's* spoken voice, not this — it won't speed the
  microphone up. See `docs/VOICE_SETUP.md`.)
- **Encryption is not something you need to worry about here.** Protecting your
  child's data costs almost nothing per lesson: the actual encrypting and
  decrypting of saved work is far too fast to notice on any machine on this
  list. There is one deliberately slow step — deriving the key that protects
  everything else — but it runs *once, when Bede starts up*, not during
  lessons, and it's intentionally slow because that's what makes your master
  secret hard to crack. On a Pi that means a few extra seconds at boot and
  nothing more. You never trade security for speed by choosing modest hardware.

### How much disk space and memory this actually needs

**Disk.** Docker downloads/builds a handful of images (the app itself, plus
Postgres if you picked local storage), and each grows a little over time as
your family's lessons accumulate. Budget **at least 5GB free** as a
comfortable floor for the app images plus room to grow; add the AI model's
own size on top if you're running AI locally (table below) — that's the one
genuinely large download here. For the exact current size of each image
this build actually produces, see the "Report built image sizes" step's
summary on any recent run of `production-regression.yml` in this repo's
GitHub Actions tab — deliberately not hand-typed here as a fixed number,
since dependency updates shift it over time and a stale number in a doc is
worse than no number.

**Memory.** A comfortable floor is **4GB RAM** for the app stack itself
(FastAPI, nginx, Caddy, and Postgres if running locally) — this is not a
hard technical minimum measured on real hardware, it's a reasonable
planning floor for a multi-container stack doing real work (encryption,
audio processing) alongside a database. If you're running AI locally, add
that model's own RAM/VRAM requirement on top (see the Local AI table
below) — that's almost always the larger number by far, and effectively
sets your machine's real floor once local AI is in the picture.

**If you're running AI locally**, the model itself is the number that
actually matters, both for download size and for RAM/VRAM while it runs —
see `docs/UNIX_INSTALLER.md`'s and `docs/WINDOWS_INSTALLER.md`'s "Local AI
(Ollama)" tables for which model tier your hardware lands in. Roughly, as
of this writing (Ollama's library can update these — the installers pull
whatever `ollama pull qwen3:<tag>` currently resolves to, not a pinned
snapshot):

| Model tier | Approximate download |
|---|---|
| `qwen3:1.7b` (weakest tier — e.g. a Pi with under 16GB RAM) | ~1.4GB |
| `qwen3:4b` | ~2.5GB |
| `qwen3:8b` | ~5GB |
| `qwen3:14b` | ~9GB |
| `qwen3:32b` (strongest tier — a real GPU) | ~20GB |

A cloud AI provider (Anthropic, OpenAI, Mistral) skips this download and
this RAM/VRAM cost entirely — the model runs on their servers, not yours.
That's the real tradeoff behind the installer's one question: no account
and no per-message cost, in exchange for a real download and a real chunk
of your machine's memory while Bede is running; or an account and a small
per-message cost, in exchange for needing none of that.

### One server, or a server plus a separate display?

Two different things can both reasonably be called "the machine Bede runs
on," and it's worth being clear about which one you're choosing hardware
for:

1. **The always-on server** — runs Docker, holds the encrypted database,
   answers every tablet's requests. This is the machine this whole page is
   about, and it never needs a monitor or keyboard attached at all once
   it's set up; a Raspberry Pi tucked behind a router is a completely normal
   way to run this role.
2. **The device your child actually sits at** — a tablet, laptop, or
   desktop browser that connects to the server over your home Wi-Fi (see
   `docs/CHILD_GUIDE.md` and the "child session URL flow" families use to
   hand a tablet to a child). This is a *separate* device from the server in
   Bede's normal design — that's the whole point of "self-hosted, LAN-deployed":
   one server, many tablets, none of which need to be powerful themselves.

**Where families sometimes get this wrong**: wanting the SAME low-power box
(a Raspberry Pi, or a mini PC built around a Celeron-class chip) to be
*both* the Docker server *and* something with a monitor plugged directly
into it for a child to use, especially while also running AI locally on
that same box. Each of those three things (serving Docker containers,
running a full browser well enough for a child's actual lesson, and running
a local LLM) is individually fine on modest hardware; stacking all three
onto one Raspberry-Pi-or-Celeron-class board at once is the combination
that will actually feel slow. If you want one physical box to do everything
— server, local AI, *and* a screen attached to it — that's the point where
"modest hardware is fine" stops applying, and something closer to a Mac
Mini or a mid-range mini PC (more RAM, a real CPU, ideally a discrete or
capable integrated GPU if local AI is part of the plan) is the honest
recommendation. Splitting the roles — a Raspberry Pi as the headless
server, a separate tablet or laptop as the screen a child actually uses —
is both the cheaper path and the one this app was actually designed around.

## 2. Get the files onto your server machine

On GitHub, click the green **Code** button → **Download ZIP**, then unzip it
wherever you'd like on the server machine (no terminal needed for this part).

*(If you're comfortable with `git`, `git clone <this repository>` works too
— same result.)*

**Prefer one command instead?** A native installer exists for each platform
that also installs Docker for you if it's missing, and can optionally set
up a local AI model with no account needed — see
[docs/WINDOWS_INSTALLER.md](WINDOWS_INSTALLER.md) or
[docs/UNIX_INSTALLER.md](UNIX_INSTALLER.md) (Linux — Ubuntu, Debian, Arch,
x86_64 or arm64/Raspberry Pi — and macOS). If you use one of these, skip
ahead to step 4 below; the installer already did steps 2 and 3 for you.

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
cost per message with your chosen AI provider (free if you're running the
self-hosted local model) and a brief pause (well under a second,
typically) before Bede's reply starts — there's no setting to turn it off,
the same way the distress check isn't optional either.

**Protecting your parent password, and what to do if you lose it.** Your
parent password can now be changed from inside the app — log in as
parent, then on the "Plan Today's Pod" screen open **Security keys &
authenticator app**, which also has a Change password option — rather
than editing `.env` on the server and restarting. Changing it (or
recovering access, below) immediately signs out every other device that
was logged in as parent, so a stolen session doesn't linger alongside
your new one.

For extra protection, the same Security panel lets you add a hardware
security key or an authenticator app (TOTP) as a second login factor, and
set up a recovery option — pick a **recovery PIN** (a PIN you choose
yourself, same idea as your child's PIN: 6 digits by default, or use up to
12 for extra security) or, if you'd rather have something longer and
don't mind storing it, generate a **recovery code** instead (a one-time
random code, shown once). You can only have one active at a time —
setting up the PIN replaces a code and vice versa. Either way, write it
down somewhere safe as a backup, even the PIN — the app will remind you
to before letting you move on. Where and how you store that backup is
entirely your call; an encrypted password manager is recommended over a
plain note or file. If you ever forget
your password *and* lose access to your second factor, the login screen's
"Forgot password?" link lets you back in by proving **any two** of: your
recovery PIN/code, your authenticator app, or your security key — never
just one. This only works if you've enrolled at least two of those three
ahead of time, so it's worth setting up now, before you actually need it,
not after. Ten wrong password attempts in a
row locks parent login for 15 minutes (you'll get a warning email well
before that point) — the recovery flow above is the way back in if that's
because you've genuinely forgotten, not just mistyped once.

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

   Whichever you pick, Bede is a partner in your family's teaching, not a
   replacement for it — see **[docs/SOCRATIC_METHOD.md](SOCRATIC_METHOD.md)**
   for what "Socratic" actually means in practice and how to ask the same
   kind of question yourself, alongside Bede.
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

**A break that's never returned to logs itself out.** If nobody touches the
tablet for 5 minutes while a break screen is showing, the session ends
automatically and returns to the login screen — whether it's your child's
session or your own. This is separate from (and much shorter than) the
general 30-minute inactivity timeout that applies the rest of the time,
which stays generous so a child reading or thinking through a question
isn't logged out just for sitting still — a break screen is the one moment
there's genuinely nothing left to do on-screen, so a device left unattended
there doesn't need to stay signed in.

**Morning Time includes a weekly prayer, word for word.** Once a week, Bede leads
your child through one of the Church's own traditional prayers — the Our Father,
the Hail Mary, and similar universally-known texts — in whichever language was
chosen at login (English, or Spanish if your deployment offers the toggle and it
was selected for that login — see `docs/LOCALIZATION.md`). The wording is fixed
ahead of time rather than improvised in the moment, the same way Bede already
handles the week's poem, so your child hears and learns the same correct words
every time it comes up. This is separate from — and doesn't replace —
the short prayer Bede opens and closes each day's session with (rule 10 of
Bede's persona). That daily opening/closing prayer is also fixed, word for
word, not composed by Bede in the moment: it's picked from a rotating
library of traditional Catholic and wider Christian prayers (the Doxology,
the Serenity Prayer, a Scripture blessing, and others alongside Catholic
devotions like the Prayer of St. Francis), the same "quote it exactly,
never improvise" rule the weekly prayer and poem already follow — so no
prayer your child hears from Bede, on any day, is one Bede made up itself.

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

**For K-2 students, Bede occasionally weaves in a quick phonics check
during Language Arts.** This is new, and worth knowing about: Bede does
not teach phonics or decoding directly — your family's own phonics
program (or however you're teaching reading) stays the primary
instruction, exactly as before. What's new is that, at most once a
session, Bede may playfully check in on something like a letter sound, a
simple word to sound out, or a sight word — never announced as a "test,"
never a drill, and never anything Bede corrects harshly if the child
misses it. It's woven naturally into whatever's already happening (a word
from a living book, or the day's copywork), and if your child struggles,
Bede simply moves on warmly. This exists purely so the Progress page can
show you a real, evidence-based read on reading foundations, the same way
it already does for math and composition — see the Phonics Mastery
Snapshot below.

**Bede also occasionally teaches a brief foreign word or phrase during
History, Saints, or Art & Music — for every age, not just K-2.** This is
not a language class, and Bede is not teaching your child to speak
another language — think of it as setting the stage, not Duolingo. When
today's lesson genuinely offers a natural opening (studying Rome might
bring up a Latin phrase, the French Revolution a French word, a
composer's biography an Italian musical term, a saint's story their
homeland's language), Bede may teach one brief word or phrase, then
casually check back later in the same conversation whether your child
remembered it — at most once a session, never announced, never a
vocabulary drill. If today's content doesn't offer a real opening, Bede
simply won't force one. Over time this builds a light, honest picture of
which languages your child responds to most readily — useful evidence if
you're ever deciding whether and when to start formal instruction in a
particular language — visible on the Progress page's Language Exposure
Snapshot.

**Bede remembers where each subject left off, on its own, without you having
to retype anything.** After a session ends, Bede quietly notes, for each
subject that was covered, roughly where the lesson stood — not a score, not
a tracked metric, just a short factual reminder for itself. The next time
that subject comes up, Bede briefly reorients your child to that point
before asking its next question, instead of starting the subject cold — so
a new day can pick a history lesson back up mid-thread rather than
re-introducing the topic from scratch. This is entirely internal to Bede's
own prompting: there's nothing to view, edit, or manage, and nothing about
it is shown on the Progress page — the same reasoning that keeps the
phonics and language check-ins above from becoming a scored signal about
your child applies here too, there's simply nothing being measured. Your
own **lesson note** or **current unit** for the day (in the student's
settings) always wins if it points somewhere different — typing a fresh
note is a deliberate redirect, and Bede treats it as one. If a subject
hasn't come up in a couple of weeks, Bede will say so honestly ("a while
back...") rather than pretending it was yesterday.

**The very first time you save a student here, you'll see one extra, fully
optional prompt** — "What are you most hoping Bede helps with?" — before
you're taken on to the session or pod dashboard. This is a one-time beta
check-in, not part of ordinary setup: it helps whoever runs this deployment
understand what new families are hoping for, before they've used Bede at
all. Skip it with no consequence if you'd rather get straight to the
lesson — it never appears again once you've added your first student. (It
only appears at all if the deployment has feedback collection turned on; if
you don't see it, that's why.) You can always share feedback later too, any
time, from the message-bubble icon in a session's own header.

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

**Press-and-hold vs. hands-free voice.** By default the mic works like a
walkie-talkie — press and hold to talk, let go to send. If pressing and
holding is getting in the way (a common request from parents of younger
children especially), tap the small radio-icon button next to the
microphone to switch to **Voice on**: Bede starts listening on its own
whenever it's your child's turn, no button press needed. This is entirely
opt-in and stays off unless someone taps it — it's a per-device setting
(stored on that tablet, not tied to the student), so switching it on one
tablet doesn't change any other. If the microphone has trouble hearing
reliably in this mode, Bede switches back to press-and-hold on its own
after a few failed attempts and says so in the chat — nothing gets stuck.
Tapping the microphone itself at any time also switches straight back to
press-and-hold.

The writing pad (the pencil icon in a session) has a print button if your child
prefers a real pencil to a stylus — it prints at true page size on any printer
connected to their tablet, with every paper style scaled to their `GradeStage`
the way real classroom paper is: composition ruling (wide 5/8" primary for K-2,
standard 3/8" for 3-5, narrower 1/4" for 6-8), graph/dot grid (big 1" squares
for K-2, standard 1/2" for 3-5, tighter 1/4" for 6-8), and music staff paper
("big note" beginner spacing for K-2, standard manuscript spacing for 3-8) —
so what comes out matches the actual paper a parent would buy at that grade.

## 9. Renewing or upgrading your license

You never need to touch the server for this. When your renewal or upgrade
email arrives with a new license key, log in with the parent password, open
**Setup**, and find the **License** card near the bottom. It shows your
current license (who it's for, how many students, when it renews) and a box
to paste the new key into. Press **Apply** and it takes effect right away.

If a license ever lapses before you renew, Bede pauses tutoring and says
why — but your login and the License card keep working, so pasting the new
key is all it takes to pick back up. Nothing is lost while paused.

## 10. Switching AI providers

If you've set up more than one AI provider for Bede (for example, a
self-hosted model on a home computer as your everyday choice, plus a cloud
provider like Mistral or OpenAI as a backup), you can switch which one Bede
actually uses right from your browser — no server access needed.

Log in with the parent password, open **Setup**, and find the **AI
Provider** card (only shown if two or more providers are set up). It lists
each one, with the one currently in use marked. Tap another to make it
primary — it takes effect on Bede's very next reply, not the next time you
restart anything. If you'd rather go back to the automatic default, use
"Revert to this deployment's default order."

This is separate from what happens automatically if a provider *errors out*
mid-conversation (Bede already retries the next one on its own, without
missing a beat) — this card is for when you've decided a different provider
should be the everyday choice, for example because your home computer's
local model is running slowly or giving weaker answers than usual.

Setting up a second provider in the first place is a one-time, technical
step (see `docs/PROVIDER_ADAPTERS.md`) — this card only lets you choose
among providers that are already set up, it doesn't add a new one.

## 11. Agentic loop insights (a technical card, safe to skip)

Bede occasionally needs a second, internal reply from the AI model within
the same turn — for example, if it tries to show a picture-study image
that isn't available, it gets told that and can recover with a real answer
instead of leaving the child looking at nothing. This never adds an extra
message for your child to wait through, doesn't affect session length or
break timing at all, and doesn't change anything about what Bede is or
isn't allowed to do — it's purely about how many behind-the-scenes replies
one turn takes.

If you're curious how often this actually happens, log in as parent, open
**Setup**, and find the **Agentic Loop Insights** card (below AI Provider).
Pick a time window (7, 30, or 90 days) to see how many tutoring turns
needed a second reply, how much longer those took, and a rough estimate of
the extra cost. These numbers are approximate, not an exact bill or log —
the card says so itself, since there's no simple date it can read this off
of exactly.

This card is meant for anyone curious about how Bede works under the hood,
not something you need to check regularly — everything about your child's
actual learning still lives on the Progress page in the next section.

## 12. Checking in afterward

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
  it the way the other three have. Alongside the math mastery snapshot, a
  **Composition Mastery Snapshot** tracks how your child's narrations — oral or
  written, across every subject — are coming along on five dimensions (covering the
  main ideas, logical order, richness of detail, their own words and voice, and
  connecting to prior learning). It builds from Bede's own silent scoring after
  every narration, so it can show a first, tentative read after as few as 2
  narrations rather than waiting on a larger sample the way math's snapshot does.
  For students in grades K-2, a third **Phonics Mastery Snapshot** appears too,
  built from the light check-ins described in §5 above — six reading-foundations
  areas in their real developmental order (rhyming and sound play, letter sounds,
  blending simple words, blends and digraphs, long vowel patterns, and sight
  words), so you can see which comes next for your child rather than a jumbled
  list. Since these check-ins are occasional by design, this snapshot may take a
  little longer to show a settled read than the composition one does — an early,
  tentative label appears until enough check-ins have accumulated. Every student,
  at every grade, also gets a **Language Exposure Snapshot** — a light read on
  how they respond to the brief foreign-language moments described in §5 above,
  across six languages (Latin, Greek, French, Italian, German, Spanish). Unlike
  phonics' snapshot, there's no "next" language to work toward in a fixed order —
  this simply shows which languages your child has responded to most confidently
  so far, since it's meant as a signal for you, not a curriculum Bede is walking
  through.
- **End-of-session summary** (shown after a session ends, and optionally emailed to
  you): highlights, narrations, areas to revisit, tomorrow's suggestion, and a
  virtue observed. If your child worked on Mathematics that session, and the
  diagnostic engine recorded any skill movement, a **Math Skill Growth** section
  is added automatically — a plain-language before/after ("Multi-digit
  multiplication: 42% → 61%, moved from developing to secure") built from the
  same real evidence behind the Progress page's math mastery snapshot below, not
  a guess. It only appears when there's something real to report; a session with
  no math, or no measurable movement, gets the same five sections as before.
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
