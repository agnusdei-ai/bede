#Requires -Version 5.1
<#
.SYNOPSIS
  Bede Setup launcher — installed by the Bede Setup .msi (packaging/windows/).

  This script is deliberately the ONLY place Windows-installer-specific logic
  lives. Everything past step 2 below just hands off to setup-gui.bat, the
  same double-click browser-wizard flow macOS/Linux users already get (see
  docs/PRODUCTION_SETUP.md) — the installer's job is getting to that point
  without a manual Docker Desktop install or a manual `git clone` first, not
  reimplementing the wizard.

.NOTES
  Why Docker Desktop is chain-installed HERE (a plain download + silent
  install in this script) rather than as a WiX Burn <ExePackage> with a
  RemotePayload hash: Docker ships new installer builds continuously, and
  Burn's RemotePayload model requires this bundle to pin an exact file size
  + hash for whatever version it downloads — every Docker release would
  silently break the bundle until someone re-pins it. A plain download-and-
  run in a maintained script always fetches Docker's current installer from
  their own stable download URL, at the cost of losing Burn's native
  resume/rollback for that one step — an acceptable trade for a fast-moving
  external dependency. See docs/WINDOWS_INSTALLER.md.
#>

$ErrorActionPreference = 'Stop'

$RepoUrl     = 'https://github.com/agnusdei-ai/bede.git'
$InstallRoot = Join-Path $env:LOCALAPPDATA 'Bede'
$AppDir      = Join-Path $InstallRoot 'app'
$DockerInstallerUrl = 'https://desktop.docker.com/win/main/amd64/Docker Desktop Installer.exe'

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Warn2($msg) { Write-Host "    $msg" -ForegroundColor Yellow }

function Test-DockerDesktopInstalled {
    $exe = Join-Path ${env:ProgramFiles} 'Docker\Docker\Docker Desktop.exe'
    if (Test-Path $exe) { return $true }
    return [bool](Get-Command docker.exe -ErrorAction SilentlyContinue)
}

function Install-DockerDesktop {
    Write-Step 'Docker Desktop is not installed — downloading it now (this can take a few minutes)'
    $installerPath = Join-Path $env:TEMP 'DockerDesktopInstaller.exe'
    Invoke-WebRequest -Uri $DockerInstallerUrl -OutFile $installerPath -UseBasicParsing

    Write-Step 'Installing Docker Desktop (you may see a Windows admin prompt — approve it)'
    # Docker Desktop's own installer requests elevation itself; -Verb RunAs
    # here ensures OUR process waits for that whole elevated install to
    # finish rather than returning immediately.
    $proc = Start-Process -FilePath $installerPath -ArgumentList 'install', '--quiet', '--accept-license' -Verb RunAs -PassThru -Wait
    Remove-Item $installerPath -ErrorAction SilentlyContinue

    if ($proc.ExitCode -eq 3010 -or $proc.ExitCode -eq 1641) {
        Write-Warn2 'Docker Desktop needs a restart to finish setting up WSL2.'
        Write-Warn2 'Restart your computer, then run "Bede Setup" from the Start Menu again.'
        exit 0
    }
    if ($proc.ExitCode -ne 0) {
        throw "Docker Desktop's installer exited with code $($proc.ExitCode) — see %TEMP% for its own logs."
    }
}

function Wait-ForDockerToBeReady {
    Write-Step 'Waiting for Docker Desktop to finish starting'
    $dockerExe = Join-Path ${env:ProgramFiles} 'Docker\Docker\Docker Desktop.exe'
    if (-not (Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue)) {
        Start-Process -FilePath $dockerExe
    }
    $deadline = (Get-Date).AddMinutes(5)
    while ((Get-Date) -lt $deadline) {
        docker info *> $null
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 5
    }
    throw 'Docker Desktop did not become ready within 5 minutes. Open it manually, wait for it to finish starting, then run this again.'
}

function Sync-BedeApp {
    if (Test-Path (Join-Path $AppDir '.git')) {
        Write-Step "Updating Bede ($AppDir)"
        Push-Location $AppDir
        try { git pull --ff-only } finally { Pop-Location }
        return
    }

    if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) {
        Write-Warn2 'Git is required to download Bede and was not found.'
        Write-Warn2 'Install it from https://git-scm.com/download/win, then run "Bede Setup" again.'
        Start-Process 'https://git-scm.com/download/win'
        exit 1
    }

    Write-Step "Downloading Bede to $AppDir"
    New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
    git clone --depth 1 $RepoUrl $AppDir
}

# ── 1. Docker Desktop ─────────────────────────────────────────────────────────
if (-not (Test-DockerDesktopInstalled)) {
    Install-DockerDesktop
}
Wait-ForDockerToBeReady

# ── 2. The app itself ───────────────────────────────────────────────────────────
Sync-BedeApp

# ── 3. Hand off to the already-shipped browser setup wizard ────────────────────
Write-Step 'Handing off to the Bede setup wizard'
Push-Location $AppDir
try {
    & cmd.exe /c setup-gui.bat
} finally {
    Pop-Location
}
