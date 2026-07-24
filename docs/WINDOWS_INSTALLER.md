# Windows installer (Bede Setup.msi)

A native Windows installer for families who'd rather double-click a `.msi`
than clone a repo and run `setup-gui.bat` by hand. Source lives in
`packaging/windows/`; built by `.github/workflows/build-windows-installer.yml`
on a `windows-latest` GitHub Actions runner (WiX's MSI/CAB tooling doesn't
cross-build from Linux).

## What it actually does

The `.msi` itself is intentionally small. It installs exactly two things,
for the CURRENT USER only (no admin rights needed for the MSI itself):

1. `Setup-Bede.ps1` → `%LOCALAPPDATA%\Bede\Setup-Bede.ps1`
2. A **Bede Setup** shortcut in the Start Menu that runs it

Everything else — installing Docker Desktop if it's missing, downloading
Bede, and running the setup wizard — happens inside `Setup-Bede.ps1` when
the parent runs that shortcut, in three steps:

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
3. **The wizard.** Runs the existing `setup-gui.bat` from inside that
   folder — the same browser-based setup form macOS/Linux users already get
   (`setup-gui.command`/`setup-gui.sh`, see `docs/PRODUCTION_SETUP.md`). This
   installer does not reimplement any of that flow.

## Why Docker Desktop is chain-installed in PowerShell, not as a WiX Burn `<ExePackage>`

The "proper" WiX way to chain-install a prerequisite is a **Burn bundle**
(`<ExePackage DownloadUrl="..." />` inside a `<Chain>`), but Burn's
`RemotePayload` model requires pinning the exact file size and hash of
whatever it downloads. Docker ships new installer builds continuously —
every Docker release would silently break the bundle until someone noticed
and re-pinned the hash. A plain `Invoke-WebRequest` + silent install inside
a maintained script always fetches Docker's current installer from their
own stable download URL, at the cost of losing Burn's native resume/rollback
for that one step. For a single fast-moving external dependency, that's a
reasonable trade — see `Setup-Bede.ps1`'s own header comment.

## Building it locally

Needs a Windows machine (or VM) with the .NET SDK (8.0+) — WiX v4 is an
MSBuild SDK, resolved automatically via NuGet:

```powershell
dotnet build packaging\windows\BedeSetup.wixproj -c Release
# → packaging\windows\bin\Release\BedeSetup.msi
```

## Current status: UNSIGNED

This installer is **not code-signed**. Windows SmartScreen will show an
"Unknown Publisher" warning the first time a parent runs it — expected, not
a bug, until a certificate is added. Deferred deliberately rather than
blocking the installer itself on sourcing one. When ready to sign:

- **Recommended:** [Azure Trusted Signing](https://learn.microsoft.com/en-us/azure/trusted-signing/) —
  Microsoft's newer cloud-signing service, roughly $10/month vs. $300–500/year
  for a traditional EV certificate, no USB HSM to manage.
- Add the signing step to `build-windows-installer.yml` after the `dotnet build`
  step (`signtool sign` or the Trusted Signing GitHub Action, depending on
  which path is chosen), gated on a repo secret so an unsigned build stays
  possible for local testing.

## Scope cuts in this first version (follow-ups, not blockers)

- **No custom installer UI/EULA dialog.** Uses the plain default Windows
  Installer UI (progress bar + finish) rather than WiX's `WixUI` extension —
  fewer moving parts to get right without a Windows machine to interactively
  test dialog flow on. A branded UI + an in-installer EULA step (surfacing
  Docker Desktop's own license terms before silently installing it — see
  below) is a reasonable follow-up once the base installer is confirmed
  working.
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
- **Uninstalling the `.msi`** removes only the launcher script and Start Menu
  shortcut — deliberately NOT the downloaded `%LOCALAPPDATA%\Bede\app`
  folder or Docker Desktop itself, so a family doesn't lose their running
  deployment or its data by uninstalling the installer.

## Relationship to the existing installers

This doesn't replace `setup-gui.bat`/`.command`/`.sh` — those still work
exactly as before for anyone who prefers cloning the repo directly. The
`.msi` is an additional, more familiar entry point specifically for Windows
users who'd rather not use a terminal at all before Docker Desktop is even
installed.
