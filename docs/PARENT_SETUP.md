# Setting Up Bede: A Guide for Parents & Tutors

> **New here?** Read [MASTERY.md](MASTERY.md) first — ten minutes on what Bede
> measures, what it deliberately refuses to, and how to tell whether it is
> working. This guide is the field-by-field walkthrough; that one is the why.

This walks through everything from "nothing installed" to "my child is having their
first lesson," including the parts that matter for keeping it secure once you hand
it off. No terminal or typed commands required: steps 2 and 3 below are answering
a form in your browser. The whole setup takes under 20 minutes either way.

## 1. What you'll need

- A computer, mini-PC, NAS, or Raspberry Pi to act as the "server". It runs all the
  time your family uses Bede, and everyone's tablets connect to it over your home Wi-Fi.
  Any of these is genuinely fine; see "Choosing your server machine" below if you're
  buying something for this or wondering whether what you already own is enough.
- [Docker](https://docs.docker.com/get-docker/) installed on that machine.
- An AI provider for Bede's actual tutoring conversation. Pick whichever
  fits your family, `make setup` asks and there's no default forced on you:
  an [Anthropic](https://console.anthropic.com/), [OpenAI](https://platform.openai.com/api-keys),
  or [Mistral](https://console.mistral.ai/) account (cloud, pay-as-you-go),
  or a self-hosted open-weight model on your own GPU server (no account,
  no per-message cost: see `docs/PROVIDER_ADAPTERS.md`).
- A database: `make setup` asks which you want:
  - **Local Postgres (recommended)**: nothing to sign up for. It runs
    alongside Bede in Docker on your own machine; nothing leaves your house.
    You're responsible for backing it up yourself (`make db-backup`).
  - **Managed Postgres**: [Neon](https://neon.tech) or [Supabase](https://supabase.com)
    both have generous free tiers. An extra account, but automatic backups.
- *(Optional)* Bede's spoken voice: see `docs/VOICE_SETUP.md`. A free,
  self-hosted option needs no account at all; a paid OpenAI option sounds
  meaningfully more natural if you'd rather pay a small per-use cost for it.

### Choosing your server machine

Bede's server does less heavy lifting than you might expect. For most of a
lesson it's relaying the conversation to whichever AI provider you picked and
storing your child's work encrypted, not doing the thinking itself. That's why
a modest always-on machine, including a Raspberry Pi, is a perfectly reasonable
choice, and why you don't need a powerful or expensive computer to run this well.

Two things genuinely depend on how strong that machine is, and one that doesn't:

- **The AI provider you can choose.** The self-hosted open-weight model option
  (the one with no account and no per-message cost) needs a dedicated NVIDIA
  GPU on Linux. A Raspberry Pi, a NAS, a Mac, or an ordinary laptop **cannot**
  run it. That's not a limitation of Bede. It's what that class of model
  requires. On those machines, pick one of the cloud providers (Anthropic,
  OpenAI, or Mistral) instead; everything else about Bede works identically.
  Full hardware tiers are in `docs/PROVIDER_ADAPTERS.md`.
- **How fast the microphone feels.** When your child speaks, your server's own
  processor turns that recording into text. This is always done on your own
  machine. There is no cloud option for it, by design, so your child's voice
  never leaves your house. On a low-power machine like a Pi, expect each spoken
  answer to take noticeably longer to come back than it would on a modern
  desktop. It works; it's just slower per turn, and typing an answer instead is
  always available if a child would rather not wait. (The paid OpenAI voice
  option affects *Bede's* spoken voice, not this. It won't speed the
  microphone up. See `docs/VOICE_SETUP.md`.)
- **Encryption is not something you need to worry about here.** Protecting your
  child's data costs almost nothing per lesson: the actual encrypting and
  decrypting of saved work is far too fast to notice on any machine on this
  list. There is one deliberately slow step: deriving the key that protects
  everything else, but it runs *once, when Bede starts up*, not during
  lessons, and it's intentionally slow because that's what makes your master
  secret hard to crack. On a Pi that means a few extra seconds at boot and
  nothing more. You never trade security for speed by choosing modest hardware.

### How much disk space and memory this actually needs

**Disk.** Docker downloads/builds a handful of images (the app itself, plus
Postgres if you picked local storage), and each grows a little over time as
your family's lessons accumulate. Budget **at least 5GB free** as a
comfortable floor for the app images plus room to grow; add the AI model's
own size on top if you're running AI locally (table below). That's the one
genuinely large download here. For the exact current size of each image
this build actually produces, see the "Report built image sizes" step's
summary on any recent run of `production-regression.yml` in this repo's
GitHub Actions tab: deliberately not hand-typed here as a fixed number,
since dependency updates shift it over time and a stale number in a doc is
worse than no number.

**Memory.** A comfortable floor is **4GB RAM** for the app stack itself
(FastAPI, nginx, Caddy, and Postgres if running locally). This is not a
hard technical minimum measured on real hardware, it's a reasonable
planning floor for a multi-container stack doing real work (encryption,
audio processing) alongside a database. If you're running AI locally, add
that model's own RAM/VRAM requirement on top (see the Local AI table
below). That's almost always the larger number by far, and effectively
sets your machine's real floor once local AI is in the picture.

**If you're running AI locally**, the model itself is the number that
actually matters, both for download size and for RAM/VRAM while it runs:
see `docs/UNIX_INSTALLER.md`'s and `docs/WINDOWS_INSTALLER.md`'s "Local AI
(Ollama)" tables for which model tier your hardware lands in. Roughly, as
of this writing (Ollama's library can update these: the installers pull
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
this RAM/VRAM cost entirely: the model runs on their servers, not yours.
That's the real tradeoff behind the installer's one question: no account
and no per-message cost, in exchange for a real download and a real chunk
of your machine's memory while Bede is running; or an account and a small
per-message cost, in exchange for needing none of that.

### One server, or a server plus a separate display?

Two different things can both reasonably be called "the machine Bede runs
on," and it's worth being clear about which one you're choosing hardware
for:

1. **The always-on server**: runs Docker, holds the encrypted database,
   answers every tablet's requests. This is the machine this whole page is
   about, and it never needs a monitor or keyboard attached at all once
   it's set up; a Raspberry Pi tucked behind a router is a completely normal
   way to run this role.
2. **The device your child actually sits at**: a tablet, laptop, or
   desktop browser that connects to the server over your home Wi-Fi (see
   `docs/CHILD_GUIDE.md` and the "child session URL flow" families use to
   hand a tablet to a child). This is a *separate* device from the server in
   Bede's normal design. That's the whole point of "self-hosted, LAN-deployed":
   one server, many tablets, none of which need to be powerful themselves.

**Where families sometimes get this wrong**: wanting the SAME low-power box
(a Raspberry Pi, or a mini PC built around a Celeron-class chip) to be
*both* the Docker server *and* something with a monitor plugged directly
into it for a child to use, especially while also running AI locally on
that same box. Each of those three things (serving Docker containers,
running a full browser well enough for a child's actual lesson, and running
a local LLM) is individually fine on modest hardware; stacking all three
onto one Raspberry-Pi-or-Celeron-class board at once is the combination
that will actually feel slow. If you want one physical box to do everything,
meaning server, local AI, *and* a screen attached to it, that is the point where
"modest hardware is fine" stops applying, and something closer to a Mac
Mini or a mid-range mini PC (more RAM, a real CPU, ideally a discrete or
capable integrated GPU if local AI is part of the plan) is the honest
recommendation. Splitting the roles: a Raspberry Pi as the headless
server, a separate tablet or laptop as the screen a child actually uses.
Is both the cheaper path and the one this app was actually designed around.

## 2. Get the files onto your server machine

On GitHub, click the green **Code** button → **Download ZIP**, then unzip it
wherever you'd like on the server machine (no terminal needed for this part).

*(If you're comfortable with `git`, `git clone <this repository>` works too,
same result.)*

**Prefer one command instead?** A native installer exists for each platform
that also installs Docker for you if it's missing, and can optionally set
up a local AI model with no account needed: see
[docs/WINDOWS_INSTALLER.md](WINDOWS_INSTALLER.md) or
[docs/UNIX_INSTALLER.md](UNIX_INSTALLER.md) (Linux: Ubuntu, Debian, Arch,
x86_64 or arm64/Raspberry Pi, and macOS). If you use one of these, skip
ahead to step 4 below; the installer already did steps 2 and 3 for you.

## 3. First-time setup

Open the unzipped folder and:

- **macOS**: double-click `setup-gui.command`.
- **Windows**: double-click `setup-gui.bat`.

A browser tab opens with a short form: fill in the items from step 1
above, click the button, and everything else happens automatically. When
it says Bede is running, open `https://localhost` on the same computer to
confirm.

One question on that form is worth a moment's thought, because it is the
only one you cannot change later without editing a file by hand.

**"Should Bede remember what your child has mastered between sessions?"**

- **Yes (recommended)** keeps an encrypted estimate on your own machine, so
  Bede's sense of where your child is gets steadier week by week and the
  Progress page can show a whole term.
- **No** runs exactly the same assessment and still reports what Bede saw
  at the end of each session, but keeps no lasting estimate of your child
  anywhere at all.

The trade is real and worth understanding before you pick. Judgements get
steadier with evidence, and one sitting produces only a handful, so with
**No** you will see "still getting to know your learner" more often and the
Progress page will not show a term's picture. Your record of the work your
child actually completed is kept either way; what stops being stored is
Bede's opinion about them.

Either way, nothing goes to us. On your own machine, on your own hardware,
this is a choice about what exists in your house, not about what anyone
else can see.

*(Prefer a terminal? `make setup` or `bash setup.sh` asks the same
questions as typed prompts instead: see `docs/PRODUCTION_SETUP.md`.)*

> This browser-based setup is tested automatically on a regular schedule:
> the form, the file it produces, and Bede actually starting and answering
> requests from it are all checked end-to-end, not just by hand once. The
> one thing that check can't see is the literal double-click on your own
> macOS/Windows machine. If that ever behaves differently than described
> here, `make setup` / `bash setup.sh` is the terminal equivalent as a
> fallback.

## 4. Understanding the security model. Read this before you hand anything to your child

Bede uses **three separate layers**, and it matters which one you tell your child about:

| Credential | Who knows it | What it does |
|---|---|---|
| **Parent password** | You only — never the child | Full administrative access: configure students, view progress reports and transcripts, approve a session if voice check fails. |
| **Child PIN** | Every child in the household (it's shared, not per-child) | Gets to the "child" login screen — a low-stakes shared secret, like a house key. Must be 6+ digits and not an easily-guessable pattern — no sequential run (`123456`), repeated block (`111111`, `123123`), or palindrome (`669966`); repeated digits are otherwise fine. Both installers offer you a freshly generated PIN if you'd rather not think one up, and neither prints a fixed example, because a PIN printed in Bede's own instructions would be public. The app refuses to start in production mode with a weak one, or with any PIN published in this repository. |
| **Voice passphrase** | Each child, for their own profile | The actual identity check — after entering the PIN, the child says *"I am ready to learn today!"* and Bede matches their voice against their enrolled profile. This is what personalizes their session, not the PIN. |

The PIN alone does **not** grant access to a specific child's lesson plan or history:
voice verification does. If voice check fails, the only way through is the parent
password (never a hidden bypass), so a child can't skip their own verification
without you present.

**If a child expresses distress or danger**, Bede stops tutoring immediately:
regardless of subject or grade, and tells them to find a trusted adult right
now. This is a deterministic keyword/pattern check that runs before anything
reaches Claude, not a judgment call by the AI, and it works the same way
whether your child is typing in English or Spanish (if you've enabled the
Spanish toggle: see below), including the safety message itself, which
arrives in whichever language they're using. Every occurrence is written to
the encrypted audit log. If you set `PARENT_EMAIL` in your `.env` (see
`.env.example`), you'll also get an urgent email the moment it happens,
including a short excerpt of what triggered it: enough to know how to
follow up, without waiting for you to think to check the audit log
yourself. Leave `PARENT_EMAIL` unset if you'd rather rely on the audit log
alone; the safety stop itself always happens either way.

**That same `PARENT_EMAIL` also covers security alerts.** If Bede notices
a pattern like several failed login attempts, or a blocked attempt to pull
data out through the API, in a short window from one address, it emails
you the same way: once per pattern, so you'll hear about a real attempt
without your inbox filling up if it keeps happening. Every occurrence is
still recorded in the encrypted audit log regardless of whether
`PARENT_EMAIL` is set. See `docs/SECURITY.md` for the exact thresholds.

**Every message your child sends is also screened before Bede sees it.**
Beyond the distress/danger check above, a second, broader check looks for
content categories a fixed keyword list can't catch: things like violence
or content that isn't appropriate for the grade you've set. If something
trips this, your child sees a gentle redirect back to the lesson (not the
"find a trusted adult" message. That's reserved for the distress check),
and it's recorded in the audit log; three or more in a short window from
one address triggers the same security-alert email as above. This runs on
every single message (not just flagged ones), which means a small, real
cost per message with your chosen AI provider (free if you're running the
self-hosted local model) and a brief pause (well under a second,
typically) before Bede's reply starts. There's no setting to turn it off,
the same way the distress check isn't optional either.

**Protecting your parent password, and what to do if you lose it.** Your
parent password can now be changed from inside the app: log in as
parent, then on the "Plan Today's Pod" screen open **Security keys &
authenticator app**, which also has a Change password option, rather
than editing `.env` on the server and restarting. Changing it (or
recovering access, below) immediately signs out every other device that
was logged in as parent, so a stolen session doesn't linger alongside
your new one.

For extra protection, the same Security panel lets you add a hardware
security key or an authenticator app (TOTP) as a second login factor, and
set up a recovery option. Pick a **recovery PIN** (a PIN you choose
yourself, same idea as your child's PIN: 6 digits by default, or use up to
12 for extra security) or, if you'd rather have something longer and
don't mind storing it, generate a **recovery code** instead (a one-time
random code, shown once). You can only have one active at a time:
setting up the PIN replaces a code and vice versa. Either way, write it
down somewhere safe as a backup, even the PIN: the app will remind you
to before letting you move on. Where and how you store that backup is
entirely your call; an encrypted password manager is recommended over a
plain note or file. If you ever forget
your password *and* lose access to your second factor, the login screen's
"Forgot password?" link lets you back in by proving **any two** of: your
recovery PIN/code, your authenticator app, or your security key, never
just one. This only works if you've enrolled at least two of those three
ahead of time, so it's worth setting up now, before you actually need it,
not after. Ten wrong password attempts in a
row locks parent login for 15 minutes (you'll get a warning email well
before that point): the recovery flow above is the way back in if that's
because you've genuinely forgotten, not just mistyped once.

**Want to test or explore how Bede responds, without a real tutoring session?**
Set `SANDBOX_PIN` in your `.env` and a **Sandbox** button appears on your Pod
Dashboard. It's a direct-answer chat just for you: Bede answers plainly
instead of Socratically, you can switch topics freely, and you can even try
your own draft lesson instructions to see how Bede would run with them.
Bede speaks its answers here too, the same voice your child would hear: a
speaker icon in the header mutes it if you'd rather read silently. Nothing
said there is ever saved: no transcript, no student record. Leave
`SANDBOX_PIN` unset to skip this entirely (default).

## 5. Setting up each student

1. Log in with the **parent password** → you land on **Setup**.
2. Add each student: name and grade. Grade is free text: use `K` for
   Kindergarten, or a number like `4` or `8`. The grade *stage* buttons (K–2 / 3–5 /
   6–8) set Bede's tone; the grade itself determines which curriculum content
   (books, math scope, composer/artist study) Bede draws from.
3. Choose **how you'd like to start with Bede**. This is a starting point, not
   a lock, and every part of it stays editable afterward:
   - **Book Companion**: the lightest touch. Bede joins whatever books your
     family is already reading together, with nothing new to plan. Meant for
     families new to homeschooling, or easing into AI deliberately and
     cautiously, who want Bede anchored on their own physical books rather
     than driving the day.
   - **A Bit More Structure**: book-based discussion plus a few core
     subjects, a middle ground between the two.
   - **Full Daily Plan**: Bede covers the full Mater Amabilis subject
     rotation (the previous, and still the default, behavior).

   Picking one fills in a sensible subject list and session length below.
   You can still add, remove, or adjust either afterward using their own
   controls. This doesn't limit *which* subjects are available to pick from,
   only what's pre-selected to start.

   Note that "Full Daily Plan" means the full Mater Amabilis **core**
   rotation. The three electives, Latin, Greek, and Logic, are never
   pre-selected by any preset, so you always add them on purpose rather
   than discovering them already in your child's day. (Logic additionally
   doesn't appear at all for a K–2 student; see below.)

   **Mathematics is in every preset, including the lightest one.** It is
   foundational, and it is also the only subject carrying Bede's full
   diagnostic engine: a plan without math gives you no real mastery signal
   at all. You can still remove it, but no preset will ever leave it out
   for you.

### How often you get an honest read: the mastery cycle

Under the term topics you'll see one checkbox: **"We travel, so our weeks
aren't always regular."** Most families never need to touch it. Here is what
it changes, and why it exists at all.

Your term topics are scored over a whole term, nine to twelve weeks. That's
a long time to wait to find out whether something is working, and the
learner's guarantee is written in thirty days, so the Progress page also
reports **movement over the last four actual weeks**. Not four weeks of
school: four weeks of calendar, whatever happened in them.

Against that window each topic reads one of three ways:

- **Moved**. There is real evidence your child advanced on it recently.
- **(no mark)**: worked on, no visible movement yet. This is normal and it
  is not a warning. Plenty of real learning looks like this for weeks.
- **"had no notes in the last 4 weeks"**: nothing was recorded at all.
  **This is a note about the plan, not about your child.** It almost always
  means the subject isn't coming up often enough for that topic to surface,
  and the fix is in your schedule rather than in anything they need to do.

**What this deliberately is not.** There is no deadline attached to the
window, no target, and nothing your child has to finish inside it. It bounds
*how far back we look*, never how fast anyone has to be, and your child
never sees it. Nothing resets when four weeks are up; it simply rolls, the
way the last four weeks always does.

**So what is travel mode for?** If your family is away often, four calendar
weeks may not hold enough lessons for anything to show, and you'd see "no
notes" for topics that are genuinely fine. Ticking it reveals a second
control, **"Report movement over"**, where you choose three, four, five, or
six weeks so the same evidence has room to accumulate. It changes nothing whatsoever about how your child is taught:
only how far back the Progress page looks. Turn it off when you're home and
the window returns to four weeks on its own; you don't have to remember what
it was.

### The stated time commitment, and what it is meant to buy

This is deliberate and worth reading before you commit a term to it. A
mastery-based outcome is a claim about *consistency over time*, so the time
has to be named rather than left to whatever fits.

| Preset | Instruction | Session length | Breaks |
|---|---|---|---|
| Book Companion | 65 min | 75 min | 10 min |
| A Bit More Structure | 100 min | 110 min | 10 min |
| **Full Daily Plan** | **185 min** | **215 min** | **30 min** |

Session length is wall-clock and includes the mandatory 10-minute break
after every hour. That's why it always exceeds the instruction figure.
Each preset's session length is now **derived from its own subject list**,
so what you're scheduled to teach and what the day can actually hold are
the same number by construction. (Before this they were set independently
and had drifted: the Full Daily Plan asked for 185 minutes of subjects
inside a 120-minute session, so roughly 75 minutes of it were never
reachable and the day simply stopped mid-subject.)

The setup page now shows both figures together, `185 min / 185 min`, and
warns you if your subject choices exceed what your session length allows,
telling you exactly how much longer the session would need to be.

**What 185 minutes a day is intended to produce.** Run consistently, five
days a week:

- **Mathematics**: real, evidenced per-skill mastery. This is the one
  subject where "mastery-based" is literally true rather than a manner of
  speaking. Expect a first honest read within about a week of daily work,
  and a meaningful picture within a term.
- **Written composition**: a real rubric rollup from narration
  assessment, and the fastest to calibrate of anything Bede measures.
- **Phonics** (K–2 only): real but opportunistic; it accumulates slowly
  because it is woven into Language Arts rather than drilled.
- **Latin, Greek, and other language exposure**: a *readiness* signal,
  deliberately coarse. It tells you whether a child picks up and retains a
  phrase, not whether they are proficient.
- **Everything else**: history, science, nature study, art & music,
  saints, scripture, living books, and logic. Is measured the Charlotte
  Mason way: by whether your child can narrate back what they met. That is
  your judgment, not a number, and it is not a gap in the software.

**Two honest caveats.**

First, Bede's calibration thresholds are not yet tuned against real
family outcomes: the code says so. Treat early mastery figures as
directional rather than precise.

Second, **185 minutes is a grades 6–8 figure.** Mater Amabilis is explicit
that young children get short lessons, and a Kindergartener should not be
sitting three hours of instruction. For K–2, shorten the day deliberately:
pick fewer subjects, or lower the session length and let the preset warning
tell you what won't fit. The app enforces a 4-hour structural ceiling and a
break every hour for every child, but it will not tell you that your
5-year-old's day is too long. That judgment stays yours.

   Whichever you pick, Bede is a partner in your family's teaching, not a
   replacement for it: see **[docs/SOCRATIC_METHOD.md](SOCRATIC_METHOD.md)**
   for what "Socratic" actually means in practice and how to ask the same
   kind of question yourself, alongside Bede.

   **Faith content is two separate, optional subjects. Pick whichever fits
   your own church.** Morning Time always includes Bible reading, hymns, and
   prayer for every family. Beyond that, the subject list offers **Scripture
   & Bible Study** (Bible heroes, memory verses, and doctrine in Bede's own
   denomination-neutral voice: Bede teaches Scripture itself and the moral
   law it plainly teaches, without asserting one church's specific doctrine
   as settled fact) and **Saints & Catechism** (hagiography and the Catholic
   Church's teaching, drawing on the Ignatius Press *Faith and Life* series).
   Enable either one, both, or neither: whichever matches how your own
   family and church already teach the faith. Bede never treats either
   module as a substitute for your own pastor, priest, or church's teaching.

   **Latin & Christian Foundations is a third, separate optional subject,
   and it's for every Christian family, whatever your tradition.** It
   teaches real Latin K–8, built around the vocabulary all Christians hold
   in common: *Fides* (faith), *Spes* (hope), *Caritas* (love), *Sapientia*
   (wisdom), *Veritas* (truth), and *Ora et Labora* (prayer and work): all
   hanging on Christ's own summary of the whole law, in the Latin of the
   Vulgate:

   > *Diliges Dominum Deum tuum ex toto corde tuo...*
   > *Diliges proximum tuum sicut teipsum.*
   >
   > "Thou shalt love the Lord thy God with thy whole heart...
   > Thou shalt love thy neighbour as thyself."

   Nothing specific to one tradition is taught in this subject: no
   devotion to the saints or to Mary, no sacramental theology, no prayers
   for the dead, no particular church's structure or authority. A family
   that doesn't hold those can run this subject start to finish and never
   meet them; a family that wants them has Saints & Catechism available as
   its own separate subject. If your child asks Bede a doctrinal question
   that divides Christian traditions, Bede answers the *language* part if
   there is one and sends the rest to you and your own pastor, priest, or
   minister: same rule as every other faith content in Bede.

   How much Latin your child actually does depends on their stage, and it
   is deliberately unhurried:

   - **K–2**: ear only. Your child hears a word, says it back, and learns
     what it means in one short sentence. Nothing is written, spelled,
     parsed, or translated, and there's no grammar at all. Two or three
     words is a full lesson.
   - **3–5**: words and roots. The same spoken habit, plus what the word
     means and which English words grew out of it (*veritas* → verify,
     verdict; *fides* → fidelity, confide). Short Latin copywork by hand
     starts here.
   - **6–8**: sentences. Your child meets a whole Vulgate verse, works out
     who's doing what to whom from the word endings, and translates it into
     their own English before comparing with a printed translation.

   The lesson block is 10 minutes: the shortest in the curriculum on
   purpose. A few words met properly beats six words drilled.

   Two things worth knowing:

   - **Bede never improvises Latin.** Every Latin word, phrase, and verse
     Bede shows your child is quoted from a fixed, pre-reviewed catalog
     checked against published Vulgate editions, never recalled from
     memory. In an inflected language a single wrong ending changes the
     grammar, and a child can't catch the error. If your child asks for
     Latin Bede wasn't given, Bede says honestly that it would want to
     check rather than guess.
   - **Pronunciation is Ecclesiastical (Church) Latin**: the pronunciation
     used with sung and prayed Latin, and the one most Christian-classical
     programs teach. If your family uses a program teaching Classical
     (restored) pronunciation, Bede will not correct your child for saying a
     word the other way; your own program is the authority.

   **Greek & New Testament Foundations is the companion subject to Latin,
   and for some families it's the more compelling of the two.** Where the
   Vulgate is a *translation*, Koine Greek is the language the New
   Testament was actually written in. If reading Scripture in its own words
   matters to your family, that's the whole argument. It's also the one
   classical language that serves Orthodox families, who aren't served by
   Saints & Catechism (Catholic in scope) or by Latin.

   It teaches the same six virtues as Latin, in the original: **πίστις**
   (faith), **ἐλπίς** (hope), **ἀγάπη** (love), **σοφία** (wisdom),
   **ἀλήθεια** (truth), and **λόγος** (word, reason), and four of them use
   the *same anchor verse* Latin does. A child taking both subjects meets
   one verse in two languages and can see for themselves that Latin's
   *caritas* is translating Greek's *ἀγάπη*. That's the payoff of running
   them together, and it's built in deliberately.

   The stages differ from Latin's in one important way, because Greek has
   its own alphabet:

   - **K–2**: **the alphabet is the whole subject**, and that's a feature.
     Two or three letters a session: their names, sounds, and shapes,
     traced in the air or on paper. The payoff lands immediately: the word
     *alphabet* is alpha plus beta, and Christ calls himself the first
     letter and the last (Revelation 22:13). Concrete and delightful in a
     way abstract vocabulary isn't at that age.
   - **3–5**: reading and transliterating. Your child turns λόγος into
     "logos" and back. Then the roots: a child who owns *logos* owns every
     *-ology* word they'll ever meet.
   - **6–8**: reading short New Testament phrases, the definite article,
     and translating the Great Commandment from Matthew's own Greek.

   Also 10 minutes, like Latin. A family running both gets 20 minutes of
   classical language a day: already more than most K–8 homeschool days
   give it.

   Three things worth knowing:

   - **Bede never shows bare Greek.** The transliteration and the English
     always appear beside it, so a child who can't yet read the alphabet is
     never handed a wall of letters with no way in.
   - **Bede takes no side on Greek manuscripts.** The Textus Receptus
     (behind the KJV) and the modern critical text (behind the ESV and NIV)
     differ in places, and Christians differ about which to prefer. Every
     Greek text in this subject was chosen because *both traditions read it
     identically*, so the question never has to come up in front of your
     child. If your student raises it, Bede says Christians differ and
     sends them to you and your pastor.
   - **Pronunciation is Erasmian, and Bede is honest that it's a
     convention**: the system classical schools and Memoria Press use,
     not a reconstruction of how Greek actually sounded. If your child says
     these words the way your own parish or program says them (Modern or
     Byzantine pronunciation, as an Orthodox or Greek-heritage family
     would), Bede will not correct them.

   **Logic is the second art of the trivium, taught directly, and it is
   deliberately not offered before 3rd grade.** Clear thinking is what the
   subject gives your child, not part of its name. Formal
   reasoning at K–2 is exactly the premature abstraction classical
   education warns against: a Grammar-stage child is gathering the world,
   not auditing it. The card simply doesn't appear for a K–2 student, and
   if one somehow reaches the server it's dropped.

   - **3–5**: informal and entirely spoken. No fallacy names, no
     syllogisms, no technical vocabulary. Just a handful of questions your
     child learns to ask out loud: *"Is that true always, or just
     sometimes?"* *"How do you know?"* *"Did it happen because of that, or
     just after it?"* If your child starts asking "how do you know?"
     unprompted, the stage has done its whole job.
   - **6–8**: formal. Premises and conclusions, the two safe argument
     forms and the two classic mistakes, and the named fallacies (ad
     hominem, straw man, false dilemma, circular reasoning, and the rest).
     The idea Bede returns to most: **valid and true are not the same
     thing.** An argument can be built perfectly and still reach a false
     conclusion, because a premise was false.

   15 minutes: longer than the language blocks, because a single argument
   judged properly needs your child to reason out loud, be wrong, and be
   walked back through it.

   **Three things this subject is built to protect**, and you should know
   about them because they're the real risk of teaching a child logic:

   - **Logic is for finding what's true *with* someone, never for winning
     against them.** A child newly able to say "that's a straw man" has
     been handed a weapon. Bede says this often and means it.
   - **Bede will not coach your child in arguing against you.** If your
     student starts turning these tools on your instructions or your
     church, Bede redirects, warmly, but firmly, and points out that the
     first person to test an argument on is yourself. A disagreement at
     home belongs to your family, not to a logic lesson.
   - **Bede takes no side on contested political, moral, or religious
     disputes**, however logically the question is dressed up. It teaches
     the *form* using deliberately dull examples (weather, animals,
     chores) and sends the substance back to you and your own pastor,
     priest, or minister. Your student also learns something worth
     knowing here: naming a fallacy in someone's argument does not show
     their conclusion is false.

   Bede also never invents arguments for this subject: every syllogism and
   fallacy example is fixed and worked out in advance. An invalid argument
   can look perfectly sound, and catching that is precisely what your child
   is still learning to do.

   Once you enable Scripture & Bible Study or Saints & Catechism, a
   **Church Tradition** field appears under that student's "session context"
   panel (the same collapsible section as Current Unit and Faith/Virtue
   Focus): an optional short label like "Baptist," "Catholic," or
   "Non-denominational." It doesn't change which subjects are taught; it
   just helps Bede avoid assuming devotional practices or doctrine outside
   your own tradition (e.g. not assuming Marian devotion or a specific
   catechism's structure for a family that hasn't enabled Saints &
   Catechism). Leave it blank and Bede simply won't assume any particular
   tradition beyond what your subject choices already signal.

   One boundary on that field: Bede teaches Scripture, saints, and faith
   content from the historic Christian faith shared across the Catholic,
   Orthodox, and Protestant traditions. It won't adapt its own teaching to
   a group built on a modern individual's claimed revelation alongside or
   in place of the Bible, such as Jehovah's Witnesses or Mormonism/the
   Book of Mormon. If you type one of those into the field, Bede simply
   keeps teaching from that shared historic ground, the same as if you'd
   left the field blank. It never says anything about this to your child,
   and it is not a judgment on your family's own beliefs. It is only a
   decision about what Bede itself teaches from.

   The same panel also offers a **Primary Bible Translation** dropdown
   (KJV, NKJV, ESV, NIV, NASB, NLT, CSB, RSV-CE, NABRE, NRSV-CE, or
   Douay-Rheims) whenever Morning Time, Scripture & Bible Study, Saints
   & Catechism, Latin & Christian Foundations, or Greek & New Testament
   Foundations is enabled. (Latin and Greek are included because they show
   the English alongside their own text; neither is included in the Church
   Tradition field above, since their content is the shared Christian
   inheritance and never needs a denominational label.)
   This is narrower than Church Tradition. It
   doesn't say what your family believes, just which translation's wording
   Bede should favor when it quotes or paraphrases a Bible passage, so it
   sounds like the same Bible your child already reads at home. Leave it
   on "No preference" and Bede quotes Scripture from its own knowledge
   without favoring any particular translation's phrasing.

   The panel also has a **What Helps This Child** field: always available,
   not tied to any subject. Type in (or tap a chip for) anything you
   already know makes a lesson go better for this particular child — more
   time to answer, shorter passages, answering out loud instead of
   writing, one step at a time, frequent short breaks.

   **Bede teaches the same material to the same standard.** This changes
   *how* a lesson is delivered, never *what* is taught and never how the
   work is judged. Removing an obstacle between your child and the
   material is help; removing the material is not, and Bede is told so
   explicitly. A child given more time is still expected to do real work,
   and what they produce is still measured against what the task actually
   asked for.

   **Bede never mentions it to your child, and never guesses at a reason
   for it.** Your child experiences a lesson that fits them, not a lesson
   they can tell has been adjusted. "Let's take this one step at a time"
   is something Bede will say. "Because reading is hard for you" is
   something it will not, ever. And Bede will not name, guess at, or imply
   a diagnosis — to your child or to you. You have told it what helps; you
   have not told it why, that isn't its question to answer, and it isn't
   qualified to answer it.

   You don't need a diagnosis to use this. If you have one, you don't need
   to share it — describe what helps and that is enough. If you suspect
   something and don't know, that is a conversation for your pediatrician
   or an educational specialist, and this field works perfectly well in the
   meantime.

   The panel also has a **Curriculum Resources You Already Use** field:
   always available, not tied to any one subject, since a family's
   curriculum choices span math, writing, phonics, and more, not just
   faith content. Type in (or click a quick-pick chip for) any publisher
   or program your family already uses: Memoria Press, Classical Academic
   Press, Well-Trained Mind Press, Institute for Excellence in Writing,
   RightStart Mathematics, Logic of English, or your own entry for
   anything else. Bede will lean into familiar terms and general approach
   where they naturally overlap with how that resource teaches something
   (for instance, RightStart's abacus-based math, or Logic of English's
   phonogram approach), but it never claims to know or reproduce that
   publisher's actual lesson content, since Bede was never given their
   materials to draw from.
4. Toggle **voice required** off only for a student who can't do voice verification
   (e.g. a very young or non-verbal child). This makes their login PIN-only.
5. If your deployment offers a language other than English at login (`LOCALE`
   set in `.env`: see `docs/LOCALIZATION.md`), a **Sex** field appears for
   each student: Male or Female. This isn't optional once the toggle is
   enabled: Spanish, Italian, and Polish all require it to address your
   child correctly (the difference between "bienvenido" and "bienvenida,"
   for instance), and any student could be logged into in that language on
   any given day, not just the ones you expect to use it, so setup won't
   let you save a student without it set. On an English-only deployment
   (the default, no toggle offered at all), you'll never see this field at
   all.
6. Set the **session length** if the starting point you chose doesn't quite
   suit. Every session ends on its own when this time is up. The overall
   ceiling is four hours. That's built in and cannot be raised, whichever
   starting point you picked.
7. Decide whether to **lock chat appearance**. The chat has a small palette where
   a learner can pick a background theme and the color of their own speech
   bubbles. If choices like that pull your child away from the lesson (children
   with attention challenges especially), turn the lock on: the palette
   disappears from their sessions entirely. You can still open a session
   yourself as the parent, set a look you both like, and leave it locked.
8. Fill in **Pick up where we left off** for any lesson that got interrupted:
   see the section below. Skip it for a subject that's starting fresh.
9. Save, then from the **Pod Dashboard**, enroll each child's voice: they'll record
   the passphrase three times. This only needs to happen once per child.

**Setup opens on the plan you saved last time.** You don't rebuild the pod from a
blank page every morning. When you log in as a parent, Setup loads each student
exactly as you last saved them: subjects, term topics, session length, notes and
all, so a normal school day is a matter of adjusting the one or two things that
changed and saving again.

**Picking up an interrupted lesson: "meet me where I am."** Life interrupts
lessons. A chapter ends halfway, a math page gets abandoned when a sibling needs
something, a day just runs out. Without being told, Bede would open that subject
the next morning as though it were brand new: introducing it, then spending your
child's first few minutes asking where they got to and what they remember. That's
the seam this removes.

On each student's card there's a **Pick up where we left off** panel. Add a note
for each subject that needs one:

- **Subject**: chosen from the subjects you've selected for that student, and
  nothing else. There's deliberately no free-text topic box: a resume note can
  only ever point at one of the subjects Bede teaches, so it can't be used to
  introduce material that isn't already part of the curriculum. (If you pick a
  subject and later remove it from the student's list, the panel warns you and the
  note is simply not used.)
- **Where we stopped**: the one thing Bede genuinely needs. Write it the way
  you'd tell a tutor stepping in for you: *"We read to the end of chapter 4:
  Christian has just reached the Palace Beautiful."* Be specific; a vague note
  produces a vague opening.
- **Take it up here** *(optional)*: what you want done next, if you have
  something particular in mind: *"Chapter 5, then a written narration."* Leave it
  blank and Bede chooses the next step himself.
- **What was hard** *(optional)*: where your child struggled last time: *"Kept
  mixing up Christian and Faithful."* Bede will slow down there instead of
  rediscovering the difficulty from scratch.
- **Date** *(optional)*: the day of the lesson you're resuming, so Bede can tell
  a thread picked up this morning from one dropped three weeks ago.

You can add one note per subject. Once saved, that subject opens mid-thread: Bede
names where you left off in a sentence and goes straight to his first real
question. He won't ask your child what they were reading or how far they got.
You've already told him. (If Bede has also quietly noticed its own resume point
from a past session: see the "picking back up automatically" note elsewhere in
this guide: your own note always wins; Bede follows yours instead.)

Three things worth knowing about how Bede treats these notes:

- **He's honest about where the note came from.** If it comes up, Bede will say
  plainly that you told him where they stopped. He won't pretend to remember the
  lesson himself. He wasn't there, and he keeps no memory of past sessions.
- **Your child's own account wins.** If your child says they already finished that
  chapter, or never got that far, Bede believes them, adjusts, and carries on from
  where they actually are, without arguing and without putting your child in the
  middle of a disagreement with you.
- **A note is context, not a command.** Your notes shape the lesson. You're the
  curriculum director, but they can't change how Bede teaches. Anything in a note
  that reads as an instruction to set a rule aside, hand over answers, or be
  someone other than Bede is ignored, and the lesson goes on. Nothing you type
  here can override Bede's constitution.

Notes stay saved until you change them, so it's worth clearing or updating one
when the lesson actually moves on: otherwise Bede will keep resuming from the
same place.

**The language choice lives on the login screen, not on a student's profile.**
Once you've set `LOCALE` (step 5 above), everyone who logs in. You or any of
your children: sees an English/Español toggle right on the login screen
itself, chosen fresh every time. It isn't tied to which child is logging in:
the same child can be in English one day and Spanish the next, and a
bilingual household doesn't need separate profiles for each language.
Whichever is picked, Bede's own conversation (and the weekly prayer, see
below) switches immediately, in that language, for that login. The rest of
the screens, Setup, Dashboard, Progress, are still in English regardless
of the toggle for now; only the login screen and Bede's own words to your
child are translated so far.

**Sessions have a built-in rhythm of work and rest.** After every hour of
learning, a mandatory ten-minute break appears: the screen pauses and invites
your child to step away: be with nature, rest their eyes, or spend a quiet
moment with God, with a small suggestion each time. Nobody can skip it, and
the session picks up where it left off when the break ends. Grades K-3 also
pace each subject in twenty-minute blocks, which suits shorter attention
spans; grades 4-8 work in the hour-long stretches between breaks. You'll see
a countdown in the header shortly before each transition. On top of all
this, you can still set a stricter total screen-time cap per student, with a
longer eye-rest break, from the student's settings.

**Younger children are also *offered* a break every twenty minutes, but
never forced to take one.** A younger child's attention is shorter, but it
isn't uniformly shorter: some six-year-olds genuinely settle into a good
forty-minute stretch, and stopping them dead at twenty wastes the best part
of their morning. So for grades K-3, a small banner appears at the twenty-
and forty-minute marks asking whether they'd like a quick break. Two
choices, one tap each:

- **"Yes, let's pause"**: a full break screen with an off-screen activity
  suggestion, which your child ends themselves when they're ready. There's
  no countdown and no pressure.
- **"No thanks, keep going"**: the banner disappears and doesn't come back
  until the next mark.

This is a suggestion only. **The hourly break remains mandatory for every
grade, and nothing about these suggestions can shorten it, skip it, delay
it, or extend a working stretch past an hour.** A child who waves off both
suggestions simply works to the hour and then gets the same compulsory
ten-minute break everyone else does. Grades 4-8 don't see the suggestion at
all: the hourly rhythm already is their pacing.

**A break that's never returned to logs itself out.** If nobody touches the
tablet for 5 minutes while a break screen is showing, the session ends
automatically and returns to the login screen: whether it's your child's
session or your own. This is separate from (and much shorter than) the
general 30-minute inactivity timeout that applies the rest of the time,
which stays generous so a child reading or thinking through a question
isn't logged out just for sitting still: a break screen is the one moment
there's genuinely nothing left to do on-screen, so a device left unattended
there doesn't need to stay signed in.

**Either way, the screen says so.** Before the 30-minute timeout fires, a
notice appears asking whether you're still there: touching the screen
anywhere clears it and the full window starts over. If the session does end,
the login screen states plainly why: *"Logged out due to inactivity"*, or a
separate message naming the break if that's what happened. Bede is also no
longer counted as idle while it's the one doing the work: a child listening
to a passage read aloud, or waiting on a reply that's still arriving,
counts as active even though nobody is touching anything. Nothing is lost
in any of these cases; signing back in resumes the day's plan.

**Morning Time includes a weekly prayer, word for word.** Once a week, Bede leads
your child through one of the Church's own traditional prayers: the Our Father,
the Hail Mary, and similar universally-known texts: in whichever language was
chosen at login (English, or Spanish if your deployment offers the toggle and it
was selected for that login: see `docs/LOCALIZATION.md`). The wording is fixed
ahead of time rather than improvised in the moment, the same way Bede already
handles the week's poem, so your child hears and learns the same correct words
every time it comes up. This is separate from, and doesn't replace:
the short prayer Bede opens and closes each day's session with (rule 10 of
Bede's persona). That daily opening/closing prayer is also fixed, word for
word, not composed by Bede in the moment: it's picked from a rotating
library of traditional Catholic and wider Christian prayers (the Doxology,
the Serenity Prayer, a Scripture blessing, and others alongside Catholic
devotions like the Prayer of St. Francis), the same "quote it exactly,
never improvise" rule the weekly prayer and poem already follow, so no
prayer your child hears from Bede, on any day, is one Bede made up itself.

**The term selector (in "Term & mastery outcomes") does more than track mastery
topics.** Art & Music picture study follows the Mater Amabilis practice of one
composer or artist per term: which artist is showing is tied directly to the
**Term** dropdown you set there, not to the calendar or how many sessions
you've run. If you never advance it, your child sees the same handful of
pictures for that one artist indefinitely: nothing rotates it for you.
Advance the term yourself each time your family's own term/quarter turns
over. (The weekly poem and prayer above are different: those rotate
automatically off the calendar and need no action from you.)

**Composition is encouraged, never required.** At least once per session,
Bede invites your child to spend about ten minutes on a piece of their own
handwritten work: a written narration, a nature journal entry, math worked
out on paper. That pulls the day's learning together and helps it stick.
He waits for a natural pause rather than interrupting whatever your child
is in the middle of, and if the child declines, he accepts that and moves
on. If you'd like the composition pointed somewhere particular, mention it
in the student's lesson note and Bede will fold it in.

**For K-2 students, Bede occasionally weaves in a quick phonics check
during Language Arts.** This is new, and worth knowing about: Bede does
not teach phonics or decoding directly: your family's own phonics
program (or however you're teaching reading) stays the primary
instruction, exactly as before. What's new is that, at most once a
session, Bede may playfully check in on something like a letter sound, a
simple word to sound out, or a sight word, never announced as a "test,"
never a drill, and never anything Bede corrects harshly if the child
misses it. It's woven naturally into whatever's already happening (a word
from a living book, or the day's copywork), and if your child struggles,
Bede simply moves on warmly. This exists purely so the Progress page can
show you a real, evidence-based read on reading foundations, the same way
it already does for math and composition: see the Phonics Mastery
Snapshot below.

**Bede also occasionally teaches a brief foreign word or phrase during
History, Saints, or Art & Music: for every age, not just K-2.** This is
not a language class, and Bede is not teaching your child to speak
another language: think of it as setting the stage, not Duolingo. When
today's lesson genuinely offers a natural opening (studying Rome might
bring up a Latin phrase, the French Revolution a French word, a
composer's biography an Italian musical term, a saint's story their
homeland's language), Bede may teach one brief word or phrase, then
casually check back later in the same conversation whether your child
remembered it: at most once a session, never announced, never a
vocabulary drill. If today's content doesn't offer a real opening, Bede
simply won't force one. Over time this builds a light, honest picture of
which languages your child responds to most readily: useful evidence if
you're ever deciding whether and when to start formal instruction in a
particular language: visible on the Progress page's Language Exposure
Snapshot.

**Bede remembers where each subject left off, on its own, without you having
to retype anything.** After a session ends, Bede quietly notes, for each
subject that was covered, roughly where the lesson stood, not a score, not
a tracked metric, just a short factual reminder for itself. The next time
that subject comes up, Bede briefly reorients your child to that point
before asking its next question, instead of starting the subject cold, so
a new day can pick a history lesson back up mid-thread rather than
re-introducing the topic from scratch. This is entirely internal to Bede's
own prompting: there's nothing to view, edit, or manage, and nothing about
it is shown on the Progress page: the same reasoning that keeps the
phonics and language check-ins above from becoming a scored signal about
your child applies here too, there's simply nothing being measured. Your
own **lesson note** or **current unit** for the day (in the student's
settings) always wins if it points somewhere different: typing a fresh
note is a deliberate redirect, and Bede treats it as one. If a subject
hasn't come up in a couple of weeks, Bede will say so honestly ("a while
back...") rather than pretending it was yesterday.

**The very first time you save a student here, you'll see one extra, fully
optional prompt**: "What are you most hoping Bede helps with?", asked
before you're taken on to the session or pod dashboard. This is a one-time beta
check-in, not part of ordinary setup: it helps whoever runs this deployment
understand what new families are hoping for, before they've used Bede at
all. Skip it with no consequence if you'd rather get straight to the
lesson. It never appears again once you've added your first student. (It
only appears at all if the deployment has feedback collection turned on; if
you don't see it, that's why.) You can always share feedback later too, any
time, from the message-bubble icon in a session's own header.

## 6. Getting each child onto their own tablet

**First, each new device needs to trust your server's certificate**: a
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
install by hand: same one-time result.)*

**iPhone and iPad shortcut:** `make ipad-profile` (requires a terminal)
generates one file that installs a Home Screen icon *and* trusts the
certificate in a single step, instead of doing both separately. The profile
payloads are identical on iPhone and iPad — the target keeps its original
name, but nothing in it is iPad-specific. iOS still requires one manual
toggle afterward either way (Settings → General → About → Certificate Trust
Settings). Bede does not name a minimum iOS version — it supports whatever
Apple itself still supports, so the answer stays current as Apple's own list
moves. Older devices are never turned away either way: nothing checks a
version, and any feature a device lacks simply isn't offered on it. See
`docs/RELEASE_QUALITY_GATES.md` for which versions have actually been run on.

**Then**, from the Pod Dashboard, **"Copy Link for Tablet"** gives you a link
pre-filled with that student's name: send it to their device (AirDrop, text,
email) so they land straight on their own login screen.

## 7. *(Optional)* Giving Bede a real voice

By default, Bede speaks using your browser's built-in voice, which can sound
robotic. Two options for something better: see `docs/VOICE_SETUP.md` for
the full walkthrough: a paid option (OpenAI, small per-use cost) that
sounds meaningfully more natural, or a free, self-hosted option with no
account needed but a lower quality ceiling.

If you skip this, everything still works. It just falls back to the browser voice
automatically.

## 8. Handing off to your child: what to actually tell them

Once a student is enrolled, that's genuinely all they need:

> "Open Bede on your tablet, enter **[the shared PIN]**, and say *'I am ready to
> learn today!'* when it asks. Talk to Bede like you'd talk to a patient teacher:
> you can type, tap the microphone and speak, or draw your answer."

Give them the **[docs/CHILD_GUIDE.md](CHILD_GUIDE.md)** page. It's written directly
to them. Do **not** share the parent password with your child; there's no legitimate
reason they'd need it day-to-day, and it's the one credential that can override
their voice check.

**Press-and-hold vs. hands-free voice.** By default the mic works like a
walkie-talkie. Press and hold to talk, let go to send. If pressing and
holding is getting in the way (a common request from parents of younger
children especially), tap the small radio-icon button next to the
microphone to switch to **Voice on**: Bede starts listening on its own
whenever it's your child's turn, no button press needed. This is entirely
opt-in and stays off unless someone taps it. It's a per-device setting
(stored on that tablet, not tied to the student), so switching it on one
tablet doesn't change any other. If the microphone has trouble hearing
reliably in this mode, Bede switches back to press-and-hold on its own
after a few failed attempts and says so in the chat: nothing gets stuck.
Tapping the microphone itself at any time also switches straight back to
press-and-hold.

The writing pad (the pencil icon in a session) has a print button if your child
prefers a real pencil to a stylus. It prints at true page size on any printer
connected to their tablet, with every paper style scaled to their `GradeStage`
the way real classroom paper is: composition ruling (wide 5/8" primary for K-2,
standard 3/8" for 3-5, narrower 1/4" for 6-8), graph/dot grid (big 1" squares
for K-2, standard 1/2" for 3-5, tighter 1/4" for 6-8), and music staff paper
("big note" beginner spacing for K-2, standard manuscript spacing for 3-8),
so what comes out matches the actual paper a parent would buy at that grade.

## 9. Renewing or upgrading your license

You never need to touch the server for this. When your renewal or upgrade
email arrives with a new license key, log in with the parent password, open
**Setup**, and find the **License** card near the bottom. It shows your
current license (who it's for, how many students, when it renews) and a box
to paste the new key into. Press **Apply** and it takes effect right away.

If a license ever lapses before you renew, Bede pauses tutoring and says
why, but your login and the License card keep working, so pasting the new
key is all it takes to pick back up. Nothing is lost while paused.

## 10. Switching AI providers

If you've set up more than one AI provider for Bede (for example, a
self-hosted model on a home computer as your everyday choice, plus a cloud
provider like Mistral or OpenAI as a backup), you can switch which one Bede
actually uses right from your browser: no server access needed.

Log in with the parent password, open **Setup**, and find the **AI
Provider** card (only shown if two or more providers are set up). It lists
each one, with the one currently in use marked. Tap another to make it
primary. It takes effect on Bede's very next reply, not the next time you
restart anything. If you'd rather go back to the automatic default, use
"Revert to this deployment's default order."

This is separate from what happens automatically if a provider *errors out*
mid-conversation (Bede already retries the next one on its own, without
missing a beat). This card is for when you've decided a different provider
should be the everyday choice, for example because your home computer's
local model is running slowly or giving weaker answers than usual.

Setting up a second provider in the first place is a one-time, technical
step (see `docs/PROVIDER_ADAPTERS.md`). This card only lets you choose
among providers that are already set up, it doesn't add a new one.

## 11. Managing devices

Every tablet or computer that has ever logged in as a parent or a child
leaves a trace — not what was said or done, just "this device exists and
was last seen on this date." Log in with the parent password, open
**Setup**, and find the **Devices** card. It lists every device that's
logged in, with the one you're using right now marked "This device."

If a tablet is lost, stolen, or you're retiring an old one, tap
**Revoke** next to it. That device stops working immediately — the next
time anyone tries to use it, whether they're mid-login or already sitting
in a lesson, they're told plainly that the device's access was revoked
and to see the parent. Nothing about any other device changes: revoking
one tablet never logs out the rest of the family. If you ever revoke the
device you're using yourself, Bede asks you to confirm first, since
that one logs *you* out too.

You don't need to do anything here for this to work in the background —
revoking is the only action this card offers, and only matters when a
specific piece of hardware actually needs to be cut off. Revoking a
device is treated the same as the other sensitive actions on this page
(changing a password, switching AI providers, viewing the audit log): if
you haven't recently re-entered your password this session, Bede will
ask for it again before the revoke goes through.

## 12. Agentic loop insights (a technical card, safe to skip)

Bede occasionally needs a second, internal reply from the AI model within
the same turn: for example, if it tries to show a picture-study image
that isn't available, it gets told that and can recover with a real answer
instead of leaving the child looking at nothing. This never adds an extra
message for your child to wait through, doesn't affect session length or
break timing at all, and doesn't change anything about what Bede is or
isn't allowed to do. It's purely about how many behind-the-scenes replies
one turn takes.

If you're curious how often this actually happens, log in as parent, open
**Setup**, and find the **Agentic Loop Insights** card (below AI Provider).
Pick a time window (7, 30, or 90 days) to see how many tutoring turns
needed a second reply, how much longer those took, and a rough estimate of
the extra cost. These numbers are approximate, not an exact bill or log:
the card says so itself, since there's no simple date it can read this off
of exactly.

This card is meant for anyone curious about how Bede works under the hood,
not something you need to check regularly: everything about your child's
actual learning still lives on the Progress page in the next section.

## 12a. How Bede would order the day (a suggestion, not a change)

Bede can suggest an order for the subjects you have already chosen, and tell
you why it picked that order. It is a suggestion only: your Progress page can
show it, and nothing about your child's session changes unless you rearrange
the list yourself.

The rules it uses are deliberately dull, and all of them are about the
schedule rather than about your child:

- Morning Time opens the day.
- Anything you left a "pick this up here" note on comes next — your own
  instruction outranks any preference of Bede's.
- Subjects that ask for sustained attention (maths, Latin, Greek, logic,
  language arts) sit earlier, while the day is fresh.
- Anything that hasn't come up in a couple of weeks gets nudged forward
  before it drifts further.
- Child-directed free study closes the day.

**Bede never adds a subject, removes one, or shortens one.** What is in your
child's day is your decision, and the planner only ever reorders the list you
built.

**Scripture, Saints, and Morning Time keep the position you gave them.** Bede
will not move a faith subject because of anything it has observed. Deciding
that your child "needs more Scripture this week" is not a judgment Bede is
willing to make, and quietly rescheduling it would be that judgment wearing a
timetable.

You will not see any reason that says your child is behind, weak, or slow,
because none of the reasons are about your child at all. And your child never
sees this page.

## 12b. Asking about progress from somewhere else (optional, technical)

If you already use an AI assistant — Claude Desktop, Claude Code, or anything
else that supports MCP — you can let it read your own family's progress data,
so you can ask "how is Ada doing in math?" wherever you already work instead of
opening this dashboard.

It can only read, never change anything, and it cannot reach a child's
tutoring session. It registers itself as a device, so you can revoke it from
your device settings exactly like a tablet you'd lost.

The same feature works the other way too: Bede can consult MCP servers you run
(your own book library, say) while you are testing ideas in "Ask Bede" — never
during a child's lesson.

Both are off until you set them up, and neither changes anything about how
Bede tutors. Setup instructions and the full reasoning are in
[docs/MCP.md](MCP.md).

## 13. Checking in afterward

- **Progress page** (from the Pod Dashboard): narration scores, concept coverage, and
  Bede's sense of how that child learns best: available from the very first session
  (an initial, tentative read that sharpens as more sessions accumulate), not just
  after 3+. If Bede profiles your child as a kinesthetic ("learns by doing"),
  reading/writing, or visual learner, the same page shows a small observation
  confirming how often Bede has actually followed through (hands-on drawing/writing,
  written narration, or a shown visual aid, respectively): a sanity check on the
  adaptation itself, not a claim that the label makes your child learn better. An
  auditory profile changes how Bede teaches (favoring oral narration and discussion)
  but has no equivalent counter. There's no single tool call that cleanly signals
  it the way the other three have. Alongside the math mastery snapshot, a
  **Composition Mastery Snapshot** tracks how your child's narrations: oral or
  written, across every subject. Are coming along on five dimensions (covering the
  main ideas, logical order, richness of detail, their own words and voice, and
  connecting to prior learning). It builds from Bede's own silent scoring after
  every narration, so it can show a first, tentative read after as few as 2
  narrations rather than waiting on a larger sample the way math's snapshot does.
  For students in grades K-2, a third **Phonics Mastery Snapshot** appears too,
  built from the light check-ins described in §5 above, six reading-foundations
  areas in their real developmental order (rhyming and sound play, letter sounds,
  blending simple words, blends and digraphs, long vowel patterns, and sight
  words), so you can see which comes next for your child rather than a jumbled
  list. Since these check-ins are occasional by design, this snapshot may take a
  little longer to show a settled read than the composition one does: an early,
  tentative label appears until enough check-ins have accumulated. Every student,
  at every grade, also gets a **Language Exposure Snapshot**: a light read on
  how they respond to the brief foreign-language moments described in §5 above,
  across six languages (Latin, Greek, French, Italian, German, Spanish). Unlike
  phonics' snapshot, there's no "next" language to work toward in a fixed order.
  This simply shows which languages your child has responded to most confidently
  so far, since it's meant as a signal for you, not a curriculum Bede is walking
  through.
- **End-of-session summary** (shown after a session ends, and optionally emailed to
  you): highlights, narrations, areas to revisit, tomorrow's suggestion, and a
  virtue observed. If your child worked on Mathematics that session, and the
  diagnostic engine recorded any skill movement, a **Math Skill Growth** section
  is added automatically: a plain-language before/after ("Multi-digit
  multiplication: 42% → 61%, moved from developing to secure") built from the
  same real evidence behind the Progress page's math mastery snapshot below, not
  a guess. It only appears when there's something real to report; a session with
  no math, or no measurable movement, gets the same five sections as before.
- Every session is saved as an encrypted transcript, viewable from the same place.
- If a child's voice changes enough that verification starts failing (common after
  a cold, or over months of growth), re-run enrollment from the Pod Dashboard.
- **Deleting a child's data:** Pod Dashboard → that student's card → **Delete all
  data…**, then type their name to confirm. This permanently removes everything
  Bede has stored for them: narration history, learner profile, mastery tracking,
  session transcripts, voice enrollment, all of it, not just today's plan. It
  cannot be undone. See `docs/DATA_RETENTION.md` for the full, table-by-table list
  of what's kept and for how long.

## 14. The beta survey (during the beta only)

Once your child has a few sessions behind them, the Progress page may ask
you five short questions: how many days Bede has actually been used, what
it did to your own teaching time, whether what Bede does with a narration
is better or worse than what you would have done, whether Bede has ever
said something you had to correct, and the one thing that would make it
genuinely useful to you.

Some things worth knowing about it:

- **It never asks you to rate your child.** Every question is about the
  software or about your own day. That is a rule, not a coincidence: this
  product does not score children, and a survey is not an exception to it.
- **Nothing about your child is sent.** Your answers go to us as one
  email and are not stored on any server. No names, no scores, no
  transcripts travel with them.
- **"Not now" is honoured.** Dismissing it asks again in a fortnight;
  "Don't ask me again" means never, on that device.
- **It only appears if the person running your deployment configured a
  feedback address** (`FEEDBACK_EMAIL`). On a deployment without one you
  will never see it.

There is a longer version at [agnusdei.ai/survey](https://agnusdei.ai/survey/),
including questions about what a year of this should cost. If you help
run a homeschool co-op, there is a separate one for that at
[agnusdei.ai/educators](https://agnusdei.ai/educators/).

## Troubleshooting

- **"Too many requests" on login**: the rate limiter (10 attempts/minute per
  device) tripped, usually from repeated rapid retries. Wait a minute.
- **A subject feels generic / not grade-appropriate**: only grades K, 4, and 8
  currently have curated curriculum content (books, math scope, composer/artist
  study). Other grades fall back to general guidance until more years are added.
- **Voice check keeps failing**: try re-enrolling; background noise and phone/tablet
  mic quality affect matching more than most people expect.


## Reading and spelling (grades 3-8)

Bede measured reading only up to 2nd grade. Phonics covers decoding for
K-2, and composition measures your child's *writing* from their narrations.
Between them there was nothing for reading in grades 3-8, and no
spelling measurement at any grade. A 5th grader could work with Bede for a
year and you'd learn nothing about how they read.

There is now a **Reading & Spelling** picture on the Progress page for
grades 3-8, built from ten areas in the order reading actually develops:

| | Area |
|---|---|
| **Word recognition** | Reading longer words · Spelling patterns & rules · Prefixes, suffixes & word roots · Homophones & tricky spellings · Reading smoothly and with expression |
| **Understanding** | Word meanings · Retelling what the text said · Reading between the lines · How a text is built · The author's craft & purpose |

**It is built by noticing, not by testing.** Bede never sets your child a
reading test. The evidence comes from what an ordinary lesson already
reveals: a long word they stall on, a homophone chosen wrongly in
copywork, a narration that reorders events, an inference they reach without
being asked. At most one observation per session, and your child is never
told any of it is happening.

**Next steps follow the order reading develops, not the lowest number.** If
your child is still working at decoding longer words, that's what Bede
points you to: even if a later area scores lower. A child still sounding
out *disappointment* has no attention left over for the author's purpose,
and pointing you at the latter first would be advice you couldn't use.

**Why spelling gets its own explicit attention.** Three of the ten areas
touch spelling directly, which is deliberate for English specifically.
Languages with regular spelling: Finnish is the standard example, with
close to one letter per sound: let children decode fluently within months,
so their curricula move to comprehension almost immediately. English hides
meaning behind spelling that pronunciation actively contradicts (*sign* →
*signature*), so explicit work on patterns and word roots does more for an
English-speaking child than it would for a Finnish one. More structure
here, not less.


## If you already use your own Latin or Greek programme

Bede is the practice beside your course, never the course itself. Whenever
you list your curriculum in **Curriculum Resources You Already Use** (in the
session-context panel), the Latin and Greek subjects change how they behave:

- **Your sequence wins.** If your child brings vocabulary, a paradigm, or a
  phrase from their own lessons, Bede drops its own weekly term and works
  with what they brought.
- **Your terminology wins.** Bede will not tell your child their programme
  teaches something in the wrong order or uses the wrong word for a form.
  Where your course's wording differs from Bede's, Bede uses yours.
- **Bede stops presenting its term as "the lesson."** It's offered as
  something extra to enjoy alongside the real course, not as what your child
  ought to be covering this week.
- **Bede defers rather than pre-empting.** If your child asks something
  their own course will cover later, Bede will say their teacher or book
  will get to it rather than answering it badly first.

This applies to Latin and Greek only. Mathematics, Logic and the other
subjects relate to your curriculum resources differently: see §5.

## What your child works on in mathematics, year by year

The maths scope now targets what an independent or classical preparatory
school expects, which means **grade 8 is a full Algebra I year** rather than
the lighter grade-8 scope a conventional curriculum sets. That has knock-on
effects earlier:

| Year | Scope |
|---|---|
| K-1 | Counting, number bonds, skip counting, shapes, measurable attributes |
| 2 | Addition/subtraction within 100, place value to 1,000, arrays as the bridge to multiplication, money, time |
| 3 | Multiplication and division fluency, factors and multiples, order of operations, unit fractions, area and perimeter |
| 4 | Multi-digit multiplication and long division, primes and factorization, mixed numbers, angles, multi-step problems |
| 5 | All four decimal operations, multiplying **and dividing** fractions, volume, coordinate plane — **the last year of pure arithmetic** |
| 6 | Pre-algebra begins: ratios and percent, negatives and absolute value, expressions and one/two-step equations |
| 7 | Pre-algebra completed and **Algebra I begun**: exponent laws, multi-step equations, variables on both sides, inequalities, factoring linear expressions |
| 8 | **Algebra I**: roots and irrationals, scientific notation, polynomials, factoring, quadratics by factoring, systems, slope-intercept form, Pythagorean theorem |

If that pace doesn't suit your child, adjust their grade level rather than
pushing: the whole point of a mastery-based approach is that the child sets
the pace and the map stays honest about where they are.


## The work ledger: what your child has actually done

Bede keeps two different kinds of record about each student, and it's worth
knowing which is which.

The **mastery snapshots** on the Progress page are an *inference*: "how
likely is it that this child has this skill." They're useful, and they're
still a judgment Bede is making about your child.

The **work ledger** is not a judgment at all. It records what actually
happened: on this date, in this subject, a task in this skill was
completed, and it took no help / a hint / real help. Counts and dates,
nothing more. There is deliberately no score, no level, no average and no
percentage anywhere in it, because each of those would quietly turn a
record of work back into a verdict on the child.

Two things it will not do:

- **A missed attempt is never logged as work.** If your child tried
  something and didn't get it, that belongs in the mastery picture, not in
  a ledger of what they finished. This is a record of accomplishment, not
  of failure.
- **It never ranks your children against each other.** The pod view shows,
  per skill, *who has done the work and how often*: a roster, not a
  league table. There is no per-child total, students are listed
  alphabetically so the order can't shift with the numbers, and a child who
  hasn't done a piece of work simply isn't on that skill's list rather than
  appearing at zero beside a sibling.

**What it's for.** If you're running your pod as a team, this is how you
arrange one child to help another without measuring either of them against
the other. "Ada has finished long division fourteen times unaided; Wren is
just starting it. Ask Ada to show her" is a decision made from evidence of
work done, and the age of either child is irrelevant to it. That's the
whole idea: a more experienced team member trains a less experienced one,
and what makes them more experienced is what they've actually done.

Parent-facing only. Your children never see any of it, their own or each
other's.


### What Bede notices about the work

**Bede is a guide, not the teacher.** You teach. Bede sits alongside your
child during the lesson and afterwards tells you plainly what it saw: the
way one adult describes a piece of work to the adult responsible for it.
None of what follows is a grade, a level, or a judgment about whether your
child is doing well enough. It's one observation, handed to the person who
decides what it means.

Everything Bede notes is measured against **what the task asked for**,
never against another child, never against what a child that age "should"
be doing, and never against how your own child did last week. That last one
sounds like encouragement and isn't: it turns an observation into a running
comparison your child can lose.

Three things, and Bede leaves out any of them it didn't actually see.

**How well the work was done**

| On the card | What Bede saw |
|---|---|
| *(no note)* | It did what was asked, and nothing was wrong with it. Perfectly good work — it just doesn't need pointing out. |
| *(no note)* | It did what was asked and the thinking was visible: you could follow how they got there. |
| **One to show** | It's good enough to hand another child as the example. |

**How far past the task they went**: the one to watch

| On the card | What Bede saw |
|---|---|
| *(no note)* | They answered the question they were asked. |
| **Went further** | They went past it without being told to: connected it to something else, asked what would happen if, or checked their own answer a second way. |
| **Their own idea** | They brought a genuine idea, question, or method of their own. Bede keeps this rare on purpose — if it's handed out for enthusiasm, it stops meaning anything. |

Correctness can't tell apart a child who answered the question from a child
who answered it *and then asked a better one*. This is the only column that
can, and it's where initiative actually shows up.

**How much the work still costs them**

| On the card | What Bede saw |
|---|---|
| *(no note)* | It took real effort and full attention. That's normal, and it's *good*, for work that's new to them. |
| *(no note)* | They worked without strain. |
| **Came easily** | It barely costs them anything now. |

**This one is about effort, not speed.** Bede never times your child, never
hurries them, and never mentions pace to them: a child who feels raced does
worse work and enjoys it less. What's worth knowing is that a skill has
stopped costing them everything they've got, because that's what frees up
room for the next thing. A quick answer that skipped the thinking doesn't
count as *came easily*; it doesn't count as good work at all.

**And separately, how much help it took**: on their own, after a nudge, or
worked through together. This describes what the *work* needed, not what
your child is capable of. Every piece of real teaching involves help; the
useful signal is watching how much of it a skill needs over time.

Four things Bede will not do:

- **It won't note what it didn't see.** Anything it didn't genuinely
  observe is left blank, and the card tells you how much it noted and how
  much it didn't, so a blank never quietly reads as a poor result.
- **It won't count anything down.** You'll notice the tables above have
  gaps: solid, ordinary, careful work simply doesn't get a note, because
  putting "adequate" or "deliberate" on screen would read as a mark against
  it. Nothing here has a "poor" or a "slow" at the bottom of it.
- **It won't judge your child, only their work.** "That narration was one to
  show" is something Bede saw. "That child is exemplary" is a claim about a
  person, and Bede has no standing to make it.
- **It won't average anything.** You get counts, never a mean, a grade or a
  percentage: those turn a record of work back into a verdict.

**Where you can see initiative.** Pull those three together and a pattern
shows up: work done well, taken further than it was set, and no longer
costing much, and which skills that happened in. There's no badge, no
threshold, no "is/isn't" attached to it. Whether your child is a learning
entrepreneur isn't a call Bede is competent to make. What it can do is
notice the evidence and put it in front of you.


### What's been taught lately

A card on the Progress page, above the ledger, answering a question you
couldn't previously ask.

You could always see that History had produced almost nothing. What you
couldn't see was **which of two completely different situations you were
in**: History was never actually on the plan, or History was on the plan
for six weeks and got opened twice. The first is a scheduling fix. The
second is a conversation. They look identical from a blank column.

So the card lists each subject on that student's plan and when it was last
*actually taught* — anything untouched for a fortnight or more first, then
a short line naming the subjects that are being kept up. "Not yet started"
is its own state, separate from "not lately," because a subject you haven't
got to isn't a subject you're neglecting.

**This is about the plan, not your child.** There is no score on this card,
nothing about how well anything went, and no measure of interest or effort.
A subject goes untaught for all sorts of reasons — the hour it's scheduled,
the book, a hard fortnight, or a child who needs it approached a different
way. You know which. Bede genuinely doesn't, and won't pretend to.

Parent-only, like everything else built on the ledger. A child shown "you
haven't done History in three weeks" has been handed a reproach.

### Where you'll see the ledger

Two cards on the Progress page, both parent-only.

**What's Been Done**: per student, for the last 90 days. Every skill they
worked, how many times, how much help it took, and anything Bede thought
worth pointing out. Under it, a short **Where you can see initiative**
panel: work done well, taken further, and no longer costing much, plus the
skills that happened in. A "what do these mean?" link on the card explains
every phrase on it, so you never have to come back here to read it.

**Nothing on this card ever counts down.** Only the notable end of each
scale ever appears, and a count that would read zero isn't shown at all. If
a week's work was solid but ordinary. Did what was asked, at a pace that
took real effort, all of which is perfectly good work. You'll see the work
itself and how much of it Bede noted, and the initiative panel simply won't
appear. It shows up when there's something in it to show you and stays away
otherwise. A row of zeros under a heading about initiative would be a
verdict on your child dressed up as a count, which is precisely what this
card exists not to do.

Each skill also says how much of its work Bede **noted** and how much went
by **without notes**. That difference matters in both directions: Bede
leaves things blank when it didn't see enough to say, so "without notes"
must never be read as a poor result, and ordinary work that Bede *did*
watch closely must never be mistaken for work nobody looked at.

You'll notice this card looks nothing like the mastery snapshots above it.
That's deliberate. Those show bars, because they're estimating how far
along your child is. This shows counts, because it's recording what
happened. Giving them the same look would blur two quite different claims.

**Who's Done This Work**: only appears when you have more than one
student. Organised **by skill**, with the children who've worked each one
listed underneath, alphabetically. That shape is chosen on purpose: a list
of children with numbers beside them would read as a table of who's ahead
no matter what the numbers meant. There's no total per child anywhere, the
order never changes with the counts, and a child who hasn't worked a skill
simply isn't listed under it rather than appearing at zero next to a
sibling.

Use it the way you'd use any record of completed work on a team: to spot
that one of your children has finished something another is just starting,
and ask the first to show the second. Your children never see either card.

## The writing pad: drawings, and where they go

When Bede invites your child to write or draw by hand, a full-screen
writing pad opens over the chat: a real sheet of letter paper (composition,
graph, dots, staff, nature journal, or blank), ruled to your child's grade,
with a pen, a pencil, and an eraser. Nothing here needs setting up, and
there is no parent control to configure. What is worth knowing is where the
work goes.

**A page waits while your child talks to Bede.** Going back to the
conversation and returning to the pad finds the same drawing, the same
paper, the same colors. Your child does not have to finish in one sitting,
and does not have to send a half-finished drawing to Bede just to keep it.
This lasts for as long as the tablet stays signed in to that session: it
survives switching to the chat and back, and a page refresh. It does not
survive signing out, closing the tab, or a different device. Sending a
drawing to Bede does not clear the pad either: the page stays exactly as it
is until your child starts a new one, so they can carry on with the same
piece of work or add to it.

**Nothing about this reaches the server.** The page is held by the browser
on your child's own tablet, in the storage that browsers throw away when the
tab closes. It is not sent to Bede's server, not written to your database,
and not part of anything you would delete from the Pod Dashboard. The one
exception is the same one as before: a drawing your child deliberately
*sends* to Bede, with the **Done** button, travels as part of that message
exactly as it always did.

**A fresh page is your child's own decision.** The **New page** button puts
the current page away and gives them a clean sheet. Bede asks first when
there is work on the page, and offers to save it before it goes. Nothing
else clears a page: no timer, no rule, no hidden limit they can't see.

**Keeping a drawing.** **Save** downloads it to the tablet as an ordinary
image, like a photo. **Print** puts it on real paper at true size. Both
happen entirely on the device; neither sends anything anywhere.

**There is one limit, and your child is told about it.** A single page can
hold about 2 MB of drawing, which is on the order of twenty minutes of
unbroken scribbling: far more than a normal lesson produces, and small
enough that it can never fill up the tablet. Past about four-fifths of that,
a quiet line appears saying the page is nearly full. If a page does pass the
limit, Bede says so plainly, in words, while the drawing is still on the
screen: this page can't be kept, save it to your device if you want it, then
start a fresh page. The drawing is never taken away mid-sentence, and it is
never silently truncated into half a picture.
