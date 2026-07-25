# Windows installer (Bede Setup.exe)

A native Windows installer for families who'd rather double-click an `.exe`
than clone a repo and run `setup-gui.bat` by hand. Source lives in
`packaging/windows/`; built by `.github/workflows/build-windows-installer.yml`
on a `windows-latest` GitHub Actions runner (Inno Setup's compiler,
`ISCC.exe`, is Windows-native). See [docs/UNIX_INSTALLER.md](UNIX_INSTALLER.md)
for the Linux/macOS counterpart, `install.sh` — same job, same overall
shape (chain-install Docker, optionally set up local AI, hand off to the
existing browser wizard), adapted to each platform's own tools.

Built with **Inno Setup**, not an MSI — chosen specifically for its default
wizard UI (License → Destination → Start Menu Folder → Additional Tasks →
Install progress, the familiar shape most commercial Windows installers
use) and because Bede's actual audience (a family, not an IT department)
has no use for MSI's enterprise-oriented features (GPO deployment,
SCCM/Intune management) that would have been the main reason to pick MSI
over a plain installer `.exe` in the first place.

## What it actually does

The installer itself is intentionally small. It installs exactly two
things, for the CURRENT USER only (no admin rights needed for the
installer itself — `PrivilegesRequired=lowest` in `BedeSetup.iss`):

1. `Setup-Bede.ps1` → `%LOCALAPPDATA%\Bede\Setup-Bede.ps1` (default install
   location — changeable on the wizard's Destination page like any Inno
   Setup install, though there's rarely a reason to)
2. A **Bede Setup** shortcut in the Start Menu (and, if the optional
   "Create a desktop shortcut" task is checked, one on the Desktop too)

Everything else — installing Docker Desktop if it's missing, downloading
Bede, optionally setting up a local AI model, and running the setup wizard —
happens inside `Setup-Bede.ps1` when the parent runs that shortcut:

1. **Docker Desktop.** If not already installed (checked via
   `%ProgramFiles%\Docker\Docker\Docker Desktop.exe` / `docker.exe` on
   `PATH`), downloads Docker's official installer and runs it silently
   (`install --quiet --accept-license`), requesting admin elevation only for
   that one step. Then waits (up to 5 minutes) for Docker to actually finish
   starting.
2. **The app.** `git clone`s (or `git pull`s, on a re-run) `agnusdei-ai/bede`
   into `%LOCALAPPDATA%\Bede\app`. Requires Git for Windows — if it's
   missing, the script says so and opens the download page rather than
   silently chain-installing a second prerequisite.
3. **The one question this installer asks.** "Run AI on this computer, or
   use a cloud account you already have?" — see "Local AI (Ollama)" below.
   Everything past this single choice is automatic; no further prompts.
4. **The wizard.** Runs the existing `setup-gui.bat` from inside that
   folder — the same browser-based setup form macOS/Linux users already get
   (`setup-gui.command`/`setup-gui.sh`, see `docs/PRODUCTION_SETUP.md`). This
   installer does not reimplement any of that flow; if step 3 chose local
   AI, the wizard's own provider picker just shows it as an already-
   configured, pre-selected option instead of the usual cloud-provider
   fields — see below for how that handoff works.

## Local AI (Ollama)

The one thing this installer decides FOR the family, once they've said
"run AI on this computer": which model. `Setup-Bede.ps1`'s
`Get-RecommendedOllamaModel` checks GPU VRAM via `nvidia-smi` (falling back
to system RAM as a rough proxy when there's no usable NVIDIA GPU) and picks
accordingly:

| VRAM (or RAM, no GPU) | Model |
|---|---|
| ≥20GB VRAM | `qwen3:32b` |
| ≥10GB VRAM | `qwen3:14b` |
| ≥5GB VRAM | `qwen3:8b` |
| GPU present but <5GB VRAM | `qwen3:4b` |
| No usable GPU, ≥16GB RAM | `qwen3:4b` |
| No usable GPU, <16GB RAM | `qwen3:1.7b` |

This is the exact same reasoning a developer would do by hand (see the
"Ollama vs OpenAI/Claude" conversation this installer feature grew out of —
a 6GB GTX 1060 lands on `qwen3:8b` here too) — just automated so a
non-technical family never sees VRAM numbers or model names at all.

**How the choice reaches the wizard without asking twice:** `Set-LocalAI`
installs Ollama if needed (Ollama's own Windows installer happens to also
be Inno Setup-based — unrelated coincidence, `/VERYSILENT /SUPPRESSMSGBOXES`
are Inno's own silent-install switches, no admin prompt since Ollama
installs per-user too), pulls the chosen model, then writes
`%LOCALAPPDATA%\Bede\app\local-ai.json`:

```json
{"base_url": "http://host.docker.internal:11434/v1", "model": "qwen3:8b"}
```

`host.docker.internal` is Docker Desktop's own DNS name for the host
machine — Bede's actual FastAPI container (started later by the wizard's
`docker compose up`) reaches Ollama through that, not `localhost` (which
inside a container means the container itself). `scripts/setup_wizard/
wizard.py` checks for this file on every page render: if present, it shows
"Run AI on this computer (recommended)" as a pre-selected provider option
with no fields to fill in — `LOCAL_LLM_BASE_URL`/`LOCAL_LLM_MODEL` are read
straight from the marker, not typed by the family — and deletes the marker
once `.env` is written (whether they kept that choice or switched to a
cloud provider instead). This is entirely additive: on every OTHER launch
path (`setup.sh`, `setup-gui.command`/`.sh`, or this installer when the
family picks the cloud option), no marker file ever exists, so the wizard's
provider picker is byte-for-byte what it was before this feature.

**Cleanup.** Downloaded installer executables (`OllamaSetup.exe`,
`DockerDesktopInstaller.exe`) are deleted from `%TEMP%` immediately after
each install completes, and `Setup-Bede.ps1`'s handoff step sweeps for both
plus the marker file again afterward as a belt-and-suspenders pass (in case
the browser tab was closed before the wizard could clean up after itself) —
a family should never find installer leftovers to clean up themselves.

## Why Docker Desktop is chain-installed in PowerShell, not scripted into the wizard directly

Inno Setup supports running arbitrary code at install time (`[Code]`
sections, Pascal Script), so it would be possible to drive the Docker
Desktop download/install from inside the wizard itself rather than handing
off to `Setup-Bede.ps1` afterward. Deliberately not done that way: Docker
ships new installer builds continuously, and anything that has to download
and run a fast-moving external installer benefits from being a plain,
easily-editable PowerShell script rather than Pascal Script embedded in the
`.iss` — easier to read, test, and fix without recompiling the installer.
See `Setup-Bede.ps1`'s own header comment.

## Building it locally

Needs a Windows machine (or VM) with [Inno Setup](https://jrsoftware.org/isinfo.php)
installed:

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\windows\BedeSetup.iss
# → packaging\windows\Output\BedeSetup.exe
```

## Code signing — Azure Artifact Signing (Basic tier)

Chosen over a traditional CA certificate because Microsoft holds the
signing key in their own HSM — there's no PFX file or USB token that could
leak from a compromised build machine or a mishandled CI secret, which is
the actual highest-risk failure mode for code signing in practice. Note:
this service was renamed from "Azure Trusted Signing" to **"Azure Artifact
Signing"** in 2026 — same service, same pricing, new name; you may still
see the old name in some Microsoft docs and search results.

`build-windows-installer.yml` already has the signing step wired in
(`azure/login` + `azure/artifact-signing-action@v2`, both gated on the
config below being present) — it's a no-op, graceful fallback to an
unsigned `.exe` until the Azure-side setup is done. Signing only runs on
pushes to `main`, never on a pull request or a workflow_dispatch off a
feature branch — the federated credential below is deliberately scoped to
just `main`, so no PR's code can ever authenticate to sign anything.

**One-time setup (only a human with real identity/billing can do this —
not something that can be automated in a PR):**

1. **Confirm eligibility first, before anything else.** Start the identity
   validation step in the [Azure Portal](https://portal.azure.com) (search
   "Artifact Signing" → create an account) — Public Trust certs currently
   require organizations in the USA/Canada/EU/UK, or individual developers
   in the USA/Canada specifically. This step is free to attempt even if it
   ends up rejected, so verify it before relying on the rest of this plan.
2. **Azure subscription**: needs to be pay-as-you-go or an enterprise
   agreement — free/trial/sponsored-credit subscriptions are explicitly
   rejected by this service.
3. **Create the Artifact Signing Account** — **Basic** SKU ($9.99/month, up
   to 5,000 signatures — far more than this project's release cadence
   needs). This is what triggers identity validation from step 1 for real.
4. **Create a Certificate Profile** under that account, type **Public
   Trust** (not Private Trust — Private Trust doesn't get public SmartScreen
   trust, which defeats the purpose here).
5. **Create a Microsoft Entra app registration** (or a user-assigned
   managed identity) for GitHub Actions to authenticate as, with:
   - A **federated credential** trusting GitHub's OIDC issuer, scoped to
     `repo:agnusdei-ai/bede:ref:refs/heads/main` specifically — not the
     whole repo, not other branches. This is what makes the workflow's
     `github.ref == 'refs/heads/main'` gate actually enforceable at the
     Azure side too, not just in the YAML.
   - The **"Artifact Signing Certificate Profile Signer"** RBAC role,
     scoped to the certificate profile from step 4.
6. **Add to this repo's GitHub settings** (Settings → Secrets and
   variables → Actions):
   - Secrets: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`
     (the app registration's IDs — not passwords; OIDC means no client
     secret ever needs to exist).
   - Variables: `TRUSTED_SIGNING_ENDPOINT` (the region-specific endpoint
     shown on the Artifact Signing Account, e.g.
     `https://eus.codesigning.azure.net/`), `TRUSTED_SIGNING_ACCOUNT`
     (the account name from step 3), `TRUSTED_SIGNING_CERT_PROFILE` (the
     profile name from step 4). These aren't secret, hence `vars` not
     `secrets` — easier to read back in logs when debugging.

Once all six secrets/vars exist, the very next push to `main` that touches
`packaging/windows/**` signs automatically — nothing else to change in this
repo. Until then, `build-windows-installer.yml` keeps producing (and this
doc keeps describing) an unsigned `.exe`, exactly as it does today.

## Branding assets

`packaging/windows/assets/bede.ico` (the installer's own icon, shown in
Explorer/the taskbar/Add-or-Remove-Programs) and `bede-wizard-small.bmp`
(the small image shown top-right on every wizard page, `WizardStyle=modern`)
are both generated from `site/assets/favicon.png` — a placeholder, not
purpose-made installer artwork (the favicon is only 64×64, so the `.ico`'s
larger sizes are upscaled and will look soft). Regenerate from a proper
source image whenever one exists:

```python
from PIL import Image
src = Image.open("site/assets/favicon.png").convert("RGBA")
src.save("packaging/windows/assets/bede.ico", sizes=[(s, s) for s in (16, 32, 48, 64, 128, 256)])
small = src.resize((96, 96), Image.LANCZOS)
bg = Image.new("RGB", small.size, (255, 255, 255))
bg.paste(small, mask=small.split()[3])
bg.save("packaging/windows/assets/bede-wizard-small.bmp")
```

## Scope cuts in this first version (follow-ups, not blockers)

- **Docker Desktop's EULA.** `Setup-Bede.ps1` installs Docker Desktop with
  `--accept-license` on the parent's behalf. Docker Desktop is free for
  personal use and small businesses under its current terms, but a
  commercial/larger-organization deployer should review
  [Docker's subscription terms](https://www.docker.com/pricing/) themselves
  before relying on this — this installer doesn't evaluate which license
  tier applies to a given household or business.
- **Private-repo cloning.** `Setup-Bede.ps1` clones `agnusdei-ai/bede` over
  plain HTTPS. If that repository is or becomes private, `git clone` will
  prompt for credentials (or fail non-interactively) — not currently handled
  with, say, an embedded token prompt.
- **Uninstalling** removes only the launcher script and shortcuts —
  deliberately NOT the downloaded `%LOCALAPPDATA%\Bede\app` folder, Docker
  Desktop, Ollama, or any pulled model, so a family doesn't lose their
  running deployment or its data by uninstalling the installer.
- **`Setup-Bede.ps1` itself is not executed by CI.** `build-windows-installer.yml`
  builds and verifies the installer `.exe` itself, but nothing in this
  repo's CI actually runs the PowerShell script end to end on a real Windows
  machine — Docker Desktop/Ollama installs, hardware detection, and the
  wizard handoff are reviewed carefully but not exercised by an automated
  test. If you're the first to run this for real, please report back
  anything that doesn't match this doc.
- **Ollama model tag names.** `qwen3:8b` etc. are current Ollama library tags
  as of this writing — if Ollama's library renames or retires a tag,
  `ollama pull` will just fail with their own error message (surfaced
  as-is by `Set-LocalAI`'s exit-code check) rather than silently doing
  nothing; update `Get-RecommendedOllamaModel` if that happens.
- **Branding assets are placeholders** — see "Branding assets" above.

## Relationship to the existing installers

This doesn't replace `setup-gui.bat`/`.command`/`.sh` — those still work
exactly as before for anyone who prefers cloning the repo directly. This
installer is an additional, more familiar entry point specifically for
Windows users who'd rather not use a terminal at all before Docker Desktop
is even installed.
