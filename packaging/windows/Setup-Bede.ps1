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

  Local AI (Ollama) follows the same "one question, then automatic" shape
  as everything else here: the ONLY thing a family decides is step 3 below
  (run AI on this computer, or use a cloud account they already have) —
  which model to pull, installing Ollama, and cleaning up afterward are
  all handled without further prompts. See docs/WINDOWS_INSTALLER.md's
  "Local AI (Ollama)" section for the hardware-tiering rationale.
#>

$ErrorActionPreference = 'Stop'

$RepoUrl     = 'https://github.com/agnusdei-ai/bede.git'
$InstallRoot = Join-Path $env:LOCALAPPDATA 'Bede'
$AppDir      = Join-Path $InstallRoot 'app'
$DockerInstallerUrl = 'https://desktop.docker.com/win/main/amd64/Docker Desktop Installer.exe'
$OllamaInstallerUrl = 'https://ollama.com/download/OllamaSetup.exe'
$LocalAiMarkerName  = 'local-ai.json'  # read by scripts/setup_wizard/wizard.py — keep this name in sync

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

function Get-RecommendedOllamaModel {
    # GPU VRAM first (via nvidia-smi, if there's an NVIDIA card at all) —
    # the same tiering a developer would reason through by hand: a small
    # laptop GPU gets a small model, a serious card gets a serious one.
    # Falls back to system RAM as a rough proxy for CPU-only inference
    # headroom when no usable NVIDIA GPU is found.
    $vramMB = $null
    if (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue) {
        try {
            $raw = & nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>$null
            if ($raw) { $vramMB = [int]($raw | Select-Object -First 1) }
        } catch {
            $vramMB = $null
        }
    }
    if ($vramMB -ge 20000) { return 'qwen3:32b' }
    if ($vramMB -ge 10000) { return 'qwen3:14b' }
    if ($vramMB -ge 5000)  { return 'qwen3:8b' }
    if ($vramMB)           { return 'qwen3:4b' }  # a GPU was found but it's small

    $ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
    if ($ramGB -ge 16) { return 'qwen3:4b' }
    return 'qwen3:1.7b'
}

function Test-OllamaInstalled {
    if (Get-Command ollama.exe -ErrorAction SilentlyContinue) { return $true }
    return Test-Path (Join-Path ${env:LOCALAPPDATA} 'Programs\Ollama\ollama.exe')
}

function Wait-ForOllamaToBeReady {
    $deadline = (Get-Date).AddMinutes(2)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-RestMethod -Uri 'http://localhost:11434/api/tags' -TimeoutSec 3 | Out-Null
            return
        } catch {
            Start-Sleep -Seconds 3
        }
    }
    throw 'Ollama did not become ready within 2 minutes. Open it manually and try again.'
}

function Install-Ollama {
    Write-Step 'Downloading Ollama'
    $installerPath = Join-Path $env:TEMP 'OllamaSetup.exe'
    Invoke-WebRequest -Uri $OllamaInstallerUrl -OutFile $installerPath -UseBasicParsing

    Write-Step 'Installing Ollama'
    # Ollama's Windows installer is Inno Setup-based and per-user (no admin
    # prompt) — unlike Docker Desktop above, no -Verb RunAs needed.
    $proc = Start-Process -FilePath $installerPath -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -PassThru -Wait
    Remove-Item $installerPath -ErrorAction SilentlyContinue
    if ($proc.ExitCode -ne 0) {
        throw "Ollama's installer exited with code $($proc.ExitCode)."
    }
    Wait-ForOllamaToBeReady
}

function Set-LocalAI {
    param([Parameter(Mandatory)][string]$AppDir)

    if (Test-OllamaInstalled) {
        Wait-ForOllamaToBeReady
    } else {
        Install-Ollama
    }

    $model = Get-RecommendedOllamaModel
    Write-Step "Downloading the $model AI model (first time only — can take a while, several GB)"
    & ollama pull $model
    if ($LASTEXITCODE -ne 0) {
        throw "Downloading the $model model failed — check your internet connection and try again."
    }

    # host.docker.internal is Docker Desktop's own DNS name for the host
    # machine, reachable from any container — Bede's actual FastAPI
    # container (started later by setup-gui.bat's `docker compose up`)
    # reaches Ollama through this, not through localhost (which inside a
    # container means the container itself).
    $marker = [ordered]@{
        base_url = 'http://host.docker.internal:11434/v1'
        model    = $model
    } | ConvertTo-Json -Compress
    Set-Content -Path (Join-Path $AppDir $LocalAiMarkerName) -Value $marker -NoNewline -Encoding utf8
    Write-Step "Local AI ready ($model)"
}

# ── 1. Docker Desktop ─────────────────────────────────────────────────────────
if (-not (Test-DockerDesktopInstalled)) {
    Install-DockerDesktop
}
Wait-ForDockerToBeReady

# ── 2. The app itself ───────────────────────────────────────────────────────────
Sync-BedeApp

# ── 3. The one decision this installer asks: where should Bede's AI run? ───────
# Everything past this point (which model, installing Ollama, cleaning up
# afterward) is automatic — see this file's own header comment.
$localAiMarker = Join-Path $AppDir $LocalAiMarkerName
Write-Step 'How should Bede get its AI?'
Write-Host '  [1] Run AI on this computer (free, private, no account needed — recommended)'
Write-Host '  [2] Use a cloud AI service you already have an account with (Anthropic, OpenAI, or Mistral)'
$aiChoice = Read-Host 'Choose 1 or 2'
if ($aiChoice -eq '1') {
    Set-LocalAI -AppDir $AppDir
} else {
    # A family that changes their mind on a re-run shouldn't have a stale
    # local-AI marker steer the wizard back to it.
    Remove-Item $localAiMarker -ErrorAction SilentlyContinue
}

# ── 4. Hand off to the already-shipped browser setup wizard ────────────────────
Write-Step 'Handing off to the Bede setup wizard'
Push-Location $AppDir
try {
    & cmd.exe /c setup-gui.bat
} finally {
    Pop-Location
    # Clean up install-time files a family never needed to know existed —
    # the wizard already removes $localAiMarker itself on a normal
    # successful run (scripts/setup_wizard/wizard.py); this is the
    # belt-and-suspenders sweep for an abandoned/failed run (e.g. the
    # browser tab was closed before submitting).
    Remove-Item $localAiMarker -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $env:TEMP 'DockerDesktopInstaller.exe') -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $env:TEMP 'OllamaSetup.exe') -ErrorAction SilentlyContinue
}
