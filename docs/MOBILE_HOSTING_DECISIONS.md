# Running Bede directly on a tablet: a pre-implementation decision packet

> **Format borrowed from `docs/LOCUTO_CONNECTOR_DECISIONS.md`** — exact question, why it's
> open, options with cost and assessment, a recommendation that is an argument rather than a
> ruling. **Nothing here is decided.** No code in this repo ships or changes behavior on the
> strength of this document; a real platform decision (does Bede support Android as a hosting
> target at all) needs founder review, not just an engineering spike.

## What this answers

Bede's whole deployment model today is: one Docker Compose stack (Caddy → nginx → FastAPI,
+ Postgres) runs on *some* host — a family's own computer, a Raspberry Pi, a NUC — and every
tablet in the house, iOS or Android, is purely a **client**: a browser opening a bookmark/Home
Screen icon over the LAN. That already works, is already documented
(`docs/PRODUCTION_SETUP.md`), and needs nothing new.

This document is about a different, harder question: **can the Docker stack itself run
directly on a tablet**, with no separate host machine at all? And if so, at what level of
effort, and with what honest reliability ceiling?

## Platform split: iOS is a wall, not a level-of-effort question

iOS has no public API for a persistent background daemon or a general container runtime, and
App Store policy prohibits shipping one. The only ways around this are jailbreaking (not a
credible basis for a customer-facing self-install flow) or full CPU emulation (iSH and
similar) — too slow and fragile to run Postgres + FastAPI + any real ML dependency reliably.
**This is not pursued further in this document.** iOS tablets remain clients only, per the
existing, already-working model (`make ipad-profile`, `docs/PRODUCTION_SETUP.md`).

Everything below is Android-specific.

## 1. Can the actual dependency footprint shrink enough to matter?

**Verified yes**, with evidence, not just plausibility:

- **`resemblyzer`/`torch` are not a hard requirement.** `services/voice_auth.py` already tries
  `from resemblyzer import VoiceEncoder` and catches the ImportError, falling back to a
  librosa-based MFCC comparison — "reliable, no model download," per that module's own
  docstring. Not installing `resemblyzer` at all is choosing the existing fallback tier
  deliberately, not disabling a feature.
- **`faster-whisper`/`ctranslate2` are not needed once `TRANSCRIPTION_PROVIDER=openai`** (or
  another cloud provider) is set — `services/transcription.py`'s own docstring already states
  this ("On 'openai' NOTHING imports faster_whisper"), which is exactly the mobile use case:
  cloud STT/TTS instead of local inference.
- **`asyncpg` is only reachable via a `postgresql+asyncpg://` URL** — irrelevant once
  `DATABASE_URL` points at SQLite instead (see next question).

`homeschool-api/requirements-mobile.in` is that reduced set, and it is **verified against this
repo's real test suite**, not a hand-picked subset: installed into a clean virtualenv with
`DATABASE_URL=sqlite+aiosqlite://...` and `TRANSCRIPTION_PROVIDER=openai`, `pytest tests/`
returned **2597 passed, 2 skipped-in-effect** — one is a positive-control test asserting that
`faster_whisper` gets imported on the `local` transcription path (true only when
`faster-whisper` is installed at all, which this profile deliberately doesn't), and the other
was a test-harness environment leak (an exported `LICENSE_KEY` bleeding into a `Settings()`
constructor test that expects it unset), not a code issue — confirmed by rerunning that one
test in isolation with the leak removed, where it passes. **Zero real regressions.** Also
verified directly: after a full `main.py` app import plus `services/transcription.py`'s
`preload()` with `TRANSCRIPTION_PROVIDER=openai`, `sys.modules` contains no `torch`,
`resemblyzer`, or `faster_whisper` at all.

## 2. Can Postgres itself be dropped in favor of SQLite for a single-device host?

**Verified yes, with the same rigor.** `core/database.py`'s schema already carries
`.with_variant(Integer(), "sqlite")` on every autoincrement primary key — the codebase was
already SQLite-conscious for testing — and a repo-wide grep for Postgres-only SQL (`ON
CONFLICT`, `RETURNING`, `JSONB`, raw `text()` queries) across `core/`, `services/`, and
`routers/` found **none**: every query goes through the SQLAlchemy ORM, which is dialect-agnostic
here. 18 of this repo's own test files already run the full production schema against a real
`sqlite+aiosqlite:///:memory:` engine via `Base.metadata.create_all()` — not a mock.

`_build_engine()` (`core/database.py`) needed **no code change at all**: SQLAlchemy 2.0.52's
async SQLite pool accepts the same `pool_size`/`max_overflow` kwargs the Postgres path already
passes, confirmed with a real read/write round-trip against a file-based (not in-memory)
SQLite database.

**What this actually buys a mobile host:** no separate database server process to install,
configure, or keep alive — one of the biggest sources of self-install failure on any
constrained device. A single file, backed up by copying it.

**What's NOT yet verified:** SQLite's single-writer lock under real concurrent load (a busy
household with siblings hitting the API at once) — untested here, and worth a deliberate check
before this is anything more than a proposal. For the target case (one appliance tablet, one
or two children using it, not a multi-tenant server), this is very likely a non-issue, but
"very likely" is not "verified," and this document says so rather than rounding up.

## 3. The reliability wall: Android will kill a background server regardless of the install script

This is the finding that actually shapes the recommendation below, and it is **current, not
theoretical** — checked directly against 2026 sources rather than assumed from general
knowledge of Android:

- Termux's own maintainers have an **open, unresolved issue** as of Android 15: even with
  `termux-wake-lock` held, battery optimization set to "Unrestricted," and `Termux:Boot`
  configured, the OS still kills long-running background processes
  ([termux/termux-app#5150](https://github.com/termux/termux-app/issues/5150)).
- Multiple 2026 community guides for keeping a Termux-hosted service alive exist precisely
  because this keeps recurring, and every one of them frames wake-locks/boot-scripts/tmux as
  *mitigations*, never a fix
  ([Turn an Old Android Into a 24/7 Agent](https://www.tryopenclaw.ai/blog/openclaw-android-termux-setup/),
  [The Persistence Protocol](https://sagartamang.com/blog/tmux-termux-wakelock)).
- Separately (a real but smaller obstacle): plain `pip install numpy`/`scipy` inside Termux is
  unreliable — the documented working pattern is Termux's own prebuilt `pkg install
  python-numpy` alongside `pip install --system-site-packages` for the rest, not a vanilla
  `pip install -r requirements-mobile.in`
  ([termux-packages#19126](https://github.com/termux/termux-packages/discussions/19126)).

**No install script can promise "error-free" against a background-kill failure mode that the
OS itself imposes hours or days after installation succeeds.** This is the reason this
document does not propose "install Bede directly on the child's own tablet" as a real option —
that's the worst case for backgrounding, since Android demotes the app the moment a kid
switches away to something else.

## Options

| Option | Cost | Assessment |
| --- | --- | --- |
| **A. Dedicated appliance tablet** — a spare/old Android tablet, never used interactively, screen off, always charging, running the reduced-footprint stack under Termux, functioning exactly like the Raspberry Pi option already documented for the Docker path — just repurposed hardware instead of a new purchase. | The engineering above (reduced deps, SQLite) plus a real Termux install script, `Termux:Boot` wiring, and a TLS/cert story for LAN-serving to sibling tablets — real work, but bounded. **Requires one genuine hardware validation pass** — see below. | Meaningfully reduces (does not eliminate) the background-kill risk, since the device is never backgrounded by a user's own interaction, only by Doze. The honest, buildable option — but "error-free" still can't be promised without real-device testing, which this sandbox cannot provide (see below). |
| **B. Same device the child uses** | Same engineering as A, plus real risk the server gets killed mid-lesson whenever the child leaves the app (which is normal, expected use) | **Not recommended.** The worst-case scenario for the exact failure mode documented above. Would need the user's own multi-day real-world validation before ever reaching a customer, contradicting the "don't need to be part of it" requirement. |
| **C. Stay client-only; recommend a Raspberry Pi (or similar always-on box) as the host** | Zero new engineering — already fully built and documented (`packaging/unix/install.sh` already supports Raspberry Pi arm64) | The only option with a genuinely proven reliability story today. Requires a family to have (or buy) one small dedicated device, which is the thing this whole document was asked to find an alternative to. |

## What's proven, and what still needs real hardware

**Proven, in this sandbox, without any Android device** — the backend engineering that makes
option A viable at all:
- The reduced dependency set (`requirements-mobile.in`) boots the full app and passes
  2597/2599 real tests.
- SQLite is a genuine drop-in replacement for Postgres at the ORM level, no code change needed.
- Voice auth's MFCC fallback and cloud-only transcription both work exactly as designed with
  nothing heavier installed.

**Not proven, and cannot be proven from this sandbox**, because it has no physical or emulated
Android device: whether Termux's own package resolution actually completes cleanly end-to-end
on real hardware (the `pkg install` vs. plain `pip install` distinction above), whether a
drafted `Termux:Boot` + wake-lock configuration survives a real reboot and a real multi-day
Doze cycle, and whether uvicorn terminating TLS directly (in place of Caddy, to avoid needing a
second process) actually works cleanly under Termux's networking stack.

**Recommendation:** build and land the backend piece now — it's real, tested, and useful
independent of the Android question (it also helps a Raspberry Pi Zero or any other
memory-constrained Docker host). Treat a Termux install script as a draft, not a deliverable,
until it has had one real-device validation pass. The concrete way to close that gap: a spare
Android tablet with Termux + `sshd` set up, reachable from this environment, would let this
work be genuinely finished rather than merely argued for.
