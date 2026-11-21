# Linux and macOS installer (`install.sh`)

A single script for families who'd rather run one command than clone the
repo and run `setup-gui.sh`/`setup-gui.command` by hand — the same job
`docs/WINDOWS_INSTALLER.md`'s `Setup-Bede.ps1` does for Windows, adapted to
this platform's own tools. Source lives in `packaging/unix/`.

One script covers Linux (Ubuntu, Debian, Arch — x86_64 and arm64, including
a Raspberry Pi) **and** macOS (Apple Silicon and Intel), unlike the Windows
side. That's not laziness: Linux and macOS already share the same
shell/curl ecosystem, so the only real differences between them are which
official installer or package manager to reach for at each step — see "Why
a single script, not native per-distro packages" below.

**Running specifically on a Raspberry Pi?** This script gets Docker and the
stack installed the same way on any Linux target — see
`docs/PRODUCTION_SETUP.md`'s "Running on a Raspberry Pi" section afterward
for the reliability-specific follow-up (storage medium, memory limits, the
Linux OOM killer) that installation alone doesn't cover.

## What it actually does

Same shape as the Windows installer: get from "nothing installed" to the
existing browser setup wizard, without a manual Docker install or a manual
`git clone` first. It does not reimplement the wizard itself.

1. **Docker.** If not already installed:
   - **Debian/Ubuntu** (detected via `/etc/os-release`): Docker's own
     official convenience script, `curl -fsSL https://get.docker.com | sh`
     — already architecture-aware, covers x86_64 and arm64 in one command.
   - **Arch**: `pacman -Sy docker docker-compose` — Arch ships Docker in
     its own official repos, so there's no need for a third-party script
     the way Debian/Ubuntu need one.
   - **Other/undetected distro**: the script tells you to install Docker
     Engine + the Compose plugin yourself and stops, rather than guessing.
   - **macOS**: downloads Docker Desktop's official `.dmg` (arch-specific
     URL — Apple Silicon and Intel are different downloads), mounts it,
     copies `Docker.app` to `/Applications`, and launches it.
   - If your Linux user had to be freshly added to the `docker` group, the
     script says so and stops — group membership needs a fresh login
     session to take effect, so it asks you to log out and back in (or
     reboot) and run the script again, rather than trying to be clever
     with a re-exec.
2. **The app.** `git clone`s (or `git pull`s, on a re-run)
   `agnusdei-ai/bede` into `~/Bede/app`.
3. **The one question this installer asks.** "Run AI on this computer, or
   use a cloud account you already have?" — see "Local AI (Ollama)" below.
   Everything past this single choice is automatic.
4. **The wizard.** Runs the existing `setup-gui.sh` from inside that
   folder — the same browser-based setup form every platform gets. If
   step 3 chose local AI, the wizard's provider picker shows it as an
   already-configured, pre-selected option instead of the usual
   cloud-provider fields — see `docs/WINDOWS_INSTALLER.md`'s "Local AI
   (Ollama)" section for how that handoff file (`local-ai.json`) works;
   it's the exact same marker format on every platform, read by the same
   `scripts/setup_wizard/wizard.py` regardless of which installer wrote it.

## Parental Notice and Consent

The first screen of the browser wizard this installer hands off to is the
Parental Notice and Consent. Declining ("I Do Not Consent") ends setup: the
wizard exits non-zero, no `.env` is written and Bede is not started (`setup-gui.sh` (via `scripts/setup-gui-common.sh`)
stops on the wizard's exit status). Docker and, if chosen, Ollama are
installed before the wizard runs, because the wizard itself needs Docker;
they hold no child information. The wording is a draft for counsel. See
`docs/PRODUCTION_SETUP.md`.

## Local AI (Ollama)

Same hardware-tiering logic as `Setup-Bede.ps1`, deliberately kept in sync
(that script's `$OllamaModelTiers` table and this script's
`ollama_model_for_tier`, checked against each other by
`homeschool-api/tests/test_local_model_default.py`): checks GPU VRAM via
`nvidia-smi` first, falling back to system RAM when there's no usable
NVIDIA GPU.

**Default lineup** (docs/DECISIONS.md entry 43: developers based outside
China, permissive licences, native tool calling in Ollama):

| VRAM (or RAM, no GPU) | Model | Developer, licence | Approximate download |
|---|---|---|---|
| ≥20GB VRAM | `mistral-small3.2:24b` | Mistral AI, Apache-2.0 | ~15GB |
| ≥10GB VRAM | `ministral-3:14b` | Mistral AI, Apache-2.0 | ~9.1GB |
| ≥5GB VRAM | `granite3.3:8b` | IBM, Apache-2.0 | ~4.9GB |
| GPU present but <5GB VRAM | `ministral-3:3b` | Mistral AI, Apache-2.0 | ~3.0GB |
| No usable GPU, ≥16GB RAM | `ministral-3:3b` | Mistral AI, Apache-2.0 | ~3.0GB |
| No usable GPU, <16GB RAM | `granite3.3:2b` | IBM, Apache-2.0 | ~1.5GB |

**Qwen lineup (optional)**, chosen only when asked for (see "Choosing the
Qwen models" below). Same tiers as before entry 43:

| VRAM (or RAM, no GPU) | Model | Developer, licence | Approximate download |
|---|---|---|---|
| ≥20GB VRAM | `qwen3:32b` | Alibaba (Qwen team), Apache-2.0 | ~20GB |
| ≥10GB VRAM | `qwen3:14b` | Alibaba (Qwen team), Apache-2.0 | ~9GB |
| ≥5GB VRAM | `qwen3:8b` | Alibaba (Qwen team), Apache-2.0 | ~5GB |
| GPU present but <5GB VRAM | `qwen3:4b` | Alibaba (Qwen team), Apache-2.0 | ~2.5GB |
| No usable GPU, ≥16GB RAM | `qwen3:4b` | Alibaba (Qwen team), Apache-2.0 | ~2.5GB |
| No usable GPU, <16GB RAM | `qwen3:1.7b` | Alibaba (Qwen team), Apache-2.0 | ~1.4GB |

Download sizes are Ollama's quantised builds as of this writing, not
pinned: Ollama's library can update a tag's actual weights over time, and
the installer pulls whatever the tag currently resolves to. The
`ministral-3` models need Ollama 0.13.1 or later. A fresh install gets the
current Ollama; on an older Ollama the download stops with Ollama's own
"needs a newer version" message, and the installer tells you to update
Ollama and run it again.

**Spanish.** Every default model lists Spanish among its languages except
that Ollama's page for `mistral-small3.2` lists none (Mistral's own card for
Mistral Small 3.1, the model 3.2 updates, lists Spanish). Nobody has yet run
these models through Bede's Spanish tutoring prompts on real hardware:
`homeschool-api/scripts/spanish_local_model_probe.py` is the check for that,
and entry 43 records its result as not run until someone runs it.

**An existing installation keeps its model.** Running the installer again
(to update Bede, or after changing your mind) does not switch a family to the
new lineup. If `.env` already names a `LOCAL_LLM_MODEL` that Ollama still has,
the installer keeps it, pulls nothing and deletes nothing. Updating Bede
(`git pull`, `make update`) never touches the model either. Only an explicit
model-family choice (below) picks from a lineup again.

**Choosing the Qwen models.** The Qwen lineup stays available. Ask for it in
any of these ways:

```bash
bash install.sh --model-family qwen
BEDE_MODEL_FAMILY=qwen bash install.sh
curl -fsSL https://raw.githubusercontent.com/agnusdei-ai/bede/main/packaging/unix/install.sh | bash -s -- --model-family qwen
```

`--model-family default` (or leaving it out) uses the default lineup. Any
other value stops the installer before it changes anything.

**Choosing your own model.** When you run the installer at a keyboard and have
not asked for a model, and this computer has no model Bede already uses, it
asks which open-weight model should run Bede:

1. the recommended model for this computer (Mistral AI or IBM, sized to your
   hardware), the default if you just press Enter;
2. Qwen, sized to your hardware;
3. any other open-weight model you name, for example `llama3.1:8b`,
   `gemma3:12b` or `phi4`.

You can skip the question: `--model-family qwen`, or `--model <name>` /
`BEDE_MODEL=<name>` for a model you name (it cannot be combined with
`--model-family`). A name must be one Ollama can pull (letters, digits and
`. _ : / -`). Bede needs a model that supports tool calling; the installer
does not check this, and a model that cannot use tools will tutor poorly. With
no terminal (for example a piped install in automation) nothing is asked and
the default lineup is used, as before. A model you choose is downloaded once and
is then kept on later runs like any other.

Options 2 and 3 are advanced choices. The recommended model in option 1 is
the existing lineup and stays the default; nothing chosen here becomes a
default or a recommendation until it has been qualified against Bede's capacity
and learning-quality requirements (`docs/design/AFFORDABLE_OPEN_WEIGHT_PATH.md`).

Not covered here: the Windows installer still takes `-ModelFamily default|qwen`
only, and no model other than the two lineups has been run through Bede's
tutoring or Spanish prompts (`spanish_local_model_probe.py` is the check).

On Apple Silicon there's no discrete VRAM concept at all — memory is
unified, so the RAM-based fallback tier is the *correct* path there, not a
lesser fallback the way it is on a discrete-GPU machine. On a Raspberry Pi
or other low-RAM ARM board, expect the smallest tier (`granite3.3:2b`) and
correspondingly modest quality — see `docs/PARENT_SETUP.md`'s "Choosing
your server machine" and `docs/VOICE_SETUP.md`'s low-power-host section for
the honest expectations on that class of hardware (voice transcription in
particular, which is a separate, always-local piece regardless of which AI
provider you pick).

**Installing Ollama itself:**
- **Linux**: `curl -fsSL https://ollama.com/install.sh | sh` — Ollama's own
  official installer, already covers both x86_64 and arm64 with one command
  (unlike Docker, there's no separate Arch-specific path needed here).
- **macOS**: downloads `Ollama-darwin.zip` from Ollama's own site, unzips
  it into `/Applications`, and launches it.

`host.docker.internal` is Docker Desktop's own DNS name for the host
machine on Windows/Mac. Native Linux (Docker Engine, no Docker Desktop)
does **not** provide that mapping automatically — `docker-compose.yml`'s
`api` service now declares `extra_hosts: ["host.docker.internal:host-gateway"]`
specifically so the same marker file (and the same `LOCAL_LLM_BASE_URL`)
works unmodified on all three platforms. Harmless no-op on Docker Desktop,
which already provides the mapping natively; required on Linux.

### The Mac app (`Bede Installer.app`, the DMG) path

The native Mac app does not run `install.sh`. It runs the operator bundle's
`start.sh`, and it does **not** install Ollama or download a model. Before
this was fixed, it also wrote no `local-ai.json`, so `.env` never named a
model and `LOCAL_LLM_MODEL` fell back to `docker-compose.yml`'s default
(a vLLM name no Ollama serves; there is no default name any more, see
`docs/PROVIDER_ADAPTERS.md`). Campus
tutoring uses only the local model, so every lesson failed on that install.

Now, on macOS and only while no `.env` exists yet, `start.sh` runs
`packaging/bundle/record-local-ai.sh`. It asks the Mac's own Ollama
(`http://127.0.0.1:11434/api/tags`) which models are installed and writes
the same `local-ai.json` marker described above. It chooses the model
`install.sh` would pull for this Mac (`ministral-3:3b` at 16 GB or more,
else `granite3.3:2b`) if it is installed. If not, but the Qwen model for
this Mac is (`qwen3:4b`, else `qwen3:1.7b`), it records that one, so a Mac
already running a Qwen model keeps it; `BEDE_MODEL_FAMILY=qwen` makes the
Qwen model the first choice. Otherwise it uses the one model installed, if
there is exactly one. With no Ollama, no models, or several and none of them
a recommended one, it writes nothing and the wizard shows its ordinary
choices. It never downloads anything. So for a Mac pilot:

1. Install Ollama on the Mac and run `ollama pull ministral-3:3b` (or the
   model your pilot approved) **before** opening the Bede app.
2. Open the app. The wizard shows "Run AI on this computer", using that
   model, already selected.

An existing `.env` is never changed: the helper only runs before the first
setup, so an upgrade keeps whatever model was saved. The wizard's "A
tutoring model hosted by my school" choice also has an optional **Model
name** field now, written to `LOCAL_LLM_MODEL` when filled in, for a model
service the helper did not find.

## Verifying this script

This script is **not code-signed** — see "Why unsigned, and what verifying
it actually buys you" below for why that's a deliberate, not merely
deferred, choice for a shell script specifically. Instead, this repo
publishes a SHA-256 checksum (`packaging/unix/install.sh.sha256`) alongside
it, and CI (`verify-unix-installer-checksum.yml`) fails any push or PR that
lets the two drift apart — the checked-in checksum is guaranteed to match
the checked-in script at every commit on `main`.

**Recommended: download, verify, then run** (not a blind pipe):

```bash
curl -fsSL -o install.sh https://raw.githubusercontent.com/agnusdei-ai/bede/main/packaging/unix/install.sh
curl -fsSL -o install.sh.sha256 https://raw.githubusercontent.com/agnusdei-ai/bede/main/packaging/unix/install.sh.sha256
sha256sum -c install.sh.sha256 && bash install.sh
```

(macOS has no `sha256sum` by default — use `shasum -a 256 -c install.sh.sha256` instead.)

If the checksum doesn't match, **stop** — don't run the script. That means
either the download was corrupted (re-download and try again) or something
altered it in transit, and either way the safe move is the same: don't run
it, and open an issue against this repo if a fresh re-download still fails
to verify.

**Quick path** (skips the manual verification step — fine for a low-stakes
throwaway VM, not recommended for a machine your family's data will live
on):

```bash
curl -fsSL https://raw.githubusercontent.com/agnusdei-ai/bede/main/packaging/unix/install.sh | bash
```

### Why unsigned, and what verifying it actually buys you

Windows and macOS both have a real code-signing story (Azure Artifact
Signing for the `.exe`, Apple's notarization for a `.app`/`.pkg`) because
both platforms' own OS-level gatekeeping (SmartScreen, Gatekeeper) treats
an unsigned *binary* as suspicious and warns or blocks accordingly. A
shell script run via `bash` or piped from `curl` never goes through that
gatekeeping at all on either OS — there is no signature Linux or macOS's
shell would check even if this script had one, so signing it would add
ceremony without adding a real trust boundary. The checksum is the
correct tool here instead: it lets you confirm the exact bytes you're
about to execute are the exact bytes this repo's CI verified match what's
committed on `main`, which is the actual property worth verifying for a
plain-text script you can also just... read, before running, since nothing
in it is obfuscated or compiled.

## Why a single script, not native per-distro packages

A real `.deb` (Ubuntu/Debian) plus a separate Arch/AUR `PKGBUILD` would
feel more idiomatic (`apt install`/`pacman -S`) but roughly triples the
build/CI/maintenance surface for a family-facing tool that still needs
Docker installed as a runtime dependency either way — native packaging
doesn't remove that step, it just changes how the *installer itself* gets
onto the machine. The single-script approach mirrors how Docker and Ollama
themselves ship for Linux (`get.docker.com`, `ollama.com/install.sh`) —
established, trusted precedent for exactly this kind of tool. Native
`.deb`/AUR packages remain a reasonable follow-up if there's real demand
for them later; this is deliberately the fast, low-maintenance first step,
not a permanent ceiling.

## Testing this locally

```bash
shellcheck packaging/unix/install.sh
bash -n packaging/unix/install.sh   # syntax only, doesn't run anything
```

There's no CI job that runs the script's actual install flow end-to-end
(it needs real root/sudo and a real Docker daemon, which isn't something a
hosted CI runner should be doing on every PR) — `verify-unix-installer-checksum.yml`
covers what CI reasonably can: the checksum staying accurate, and
ShellCheck passing. If you change this script, actually run it on a real
Ubuntu, Debian, Arch, or Mac machine before merging; don't rely on CI alone
to catch a broken install path.

## Scope cuts in this first version (follow-ups, not blockers)

- **Private-repo cloning is a live condition, not a hypothetical.**
  `sync_bede_app` clones `agnusdei-ai/bede` over plain HTTPS with no
  embedded credential — `docs/WINDOWS_INSTALLER.md` flagged this exact risk
  for `Setup-Bede.ps1` before the repo was ever made private; now that
  `main` genuinely is private, both installers hit it for real. Run in a
  real interactive terminal (Terminal.app, a real TTY — not piped into a
  non-interactive context like CI), `git clone` will prompt for a GitHub
  username and a Personal Access Token (GitHub retired password auth for
  git operations in 2021) the same way any private-repo clone does outside
  this script, and that works. It is not frictionless, and this script does
  nothing to smooth it — no embedded token, no distribution-specific
  credential helper. How families are actually meant to get read access to
  a private repo (individual GitHub invites, a shared deploy token, a
  separate public distribution mirror) is a product decision this script
  doesn't make for you; it just inherits whatever `git clone` already does.
- **Uninstalling** isn't a thing this script does at all — there's no
  installed-package manifest to remove the way `BedeSetup.exe` has an
  uninstaller entry in Add/Remove Programs. Deleting `~/Bede` by hand is
  the whole story today; Docker, Ollama, and any pulled model are left
  alone regardless, same reasoning as the Windows installer's own
  uninstall scope cut (don't take a family's running deployment or data
  with you).
- **`install.sh` itself is not executed by CI end to end**, same as
  `Setup-Bede.ps1` — see "Testing this locally" above for what CI does and
  doesn't cover here. Two pieces are run: its `local-model-tiers` region
  (the model table, hardware tiers and keep-the-existing-model logic) and
  its refusal of an unknown `--model-family`, both by
  `homeschool-api/tests/test_local_model_default.py`.
- **Ollama model tag names** (`granite3.3:8b`, etc.) are current Ollama
  library tags as of this writing — if a tag is renamed or retired,
  `ollama pull` fails with Ollama's own error message rather than silently
  doing nothing; update `ollama_model_for_tier` (and `$OllamaModelTiers` in
  `Setup-Bede.ps1`, plus the tables above) if that happens. The test named
  above fails until all of them agree.

## Branding / future work

No custom icon or desktop-shortcut integration yet (unlike the Windows
`.exe`, which gets a Start Menu entry with `bede.ico`). A `.desktop` file
for Linux desktop environments (GNOME/KDE — not every Linux install has
one, e.g. a headless Pi or a minimal Arch/tiling-WM setup) and a signed
`.pkg`/notarized `.app` for macOS are both reasonable follow-ups once
there's a purpose-made icon and, for macOS, an Apple Developer Program
enrollment — see `docs/WINDOWS_INSTALLER.md`'s own "Scope cuts in this
first version" for the same kind of deliberate-not-forgotten framing.
