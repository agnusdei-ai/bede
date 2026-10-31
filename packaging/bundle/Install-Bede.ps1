#Requires -Version 5.1
# Source-free Bede Windows Standard operator launcher, installed by BedeRelease.iss.
# Not a trusted distribution or a declaration of Pilot GO.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$packageRoot = $PSScriptRoot
Set-Location -LiteralPath $packageRoot

function Stop-Install([string]$message) { throw ("Bede installation incomplete: " + $message) }
function Invoke-BedeDocker([string[]]$arguments) {
    & docker.exe @arguments
    if ($LASTEXITCODE -ne 0) { Stop-Install ("Docker command failed: " + $arguments[0]) }
}
function Read-BedeValue([string]$path) {
    $value = (Get-Content -LiteralPath $path -Raw).Trim()
    if (-not $value) { Stop-Install ("Missing metadata: " + $path) }
    return $value
}

# Validate immutable source identity and the complete digest-pinned payload
# BEFORE invoking any engine command or opening the browser.
foreach ($file in @('RELEASE','ARCH','IMAGE_DIGESTS','WIZARD_IMAGE','compose.yaml',
                   'compose.lan.yaml','Caddyfile','RELEASE_PROVENANCE.json','.env.example')) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        Stop-Install ("Missing sealed operator file: " + $file)
    }
}
$sourceSha = Read-BedeValue 'RELEASE'
if ($sourceSha -cnotmatch '^[a-f0-9]{40}$') { Stop-Install 'Invalid source SHA' }
if ((Read-BedeValue 'ARCH') -cne 'amd64') { Stop-Install 'Windows x64 requires an amd64 runtime' }
$wizard = Read-BedeValue 'WIZARD_IMAGE'
if ($wizard -cne ('ghcr.io/agnusdei-ai/bede-wizard:sha-' + $sourceSha + '-amd64')) {
    Stop-Install 'Wrong wizard image or unpinned source'
}
$provenance = Get-Content -LiteralPath 'RELEASE_PROVENANCE.json' -Raw | ConvertFrom-Json
if ($provenance.source_sha -cne $sourceSha -or $provenance.architecture -cne 'amd64' -or
    $provenance.pilot_go -cne 'HOLD') { Stop-Install 'Invalid package provenance' }

$entries = @(Get-Content -LiteralPath 'IMAGE_DIGESTS' | Where-Object { $_.Trim() -ne '' })
if ($entries.Count -ne 6) { Stop-Install 'Expected six pinned application/runtime images' }
$seen = @{}
$allowedThirdParty = @('postgres:16-alpine','caddy:2-alpine')
foreach ($line in $entries) {
    if ($line -cmatch '^(\S+) (sha256:[0-9a-f]{64})$') {
        $image = $Matches[1]
    } else {
        Stop-Install 'Invalid image digest manifest'
    }
    if ($seen.ContainsKey($image)) { Stop-Install 'Duplicate image manifest entry' }
    if (-not ($image -cin $allowedThirdParty) -and
        $image -cnotmatch ('^ghcr\.io/agnusdei-ai/bede-(api|ui|trust|wizard):sha-' + $sourceSha + '-amd64$')) {
        Stop-Install 'Unexpected image or wrong release SHA'
    }
    $seen[$image] = $true
}
foreach ($component in @('api','ui','trust','wizard')) {
    $name = 'ghcr.io/agnusdei-ai/bede-' + $component + ':sha-' + $sourceSha + '-amd64'
    if (-not $seen.ContainsKey($name)) { Stop-Install ("Missing pinned component: " + $component) }
}
foreach ($name in $allowedThirdParty) {
    if (-not $seen.ContainsKey($name)) { Stop-Install ("Missing pinned runtime: " + $name) }
}

if (-not (Get-Command docker.exe -ErrorAction SilentlyContinue)) {
    Stop-Install 'Install and start an approved container engine with Compose, then retry. No third-party installer is run automatically.'
}
$dockerArch = (& docker.exe info --format '{{.Architecture}}').Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0) { Stop-Install 'Container engine is not running' }
if ($dockerArch -eq 'x86_64') { $dockerArch = 'amd64' }
if ($dockerArch -cne 'amd64') { Stop-Install 'Container engine architecture does not match Windows package' }
Invoke-BedeDocker @('compose','version')

# Separate protected installation data and database volumes per context.
$choice = Read-Host 'Installation: [1] Homeschool (default) or [2] approved Campus'
$env:BEDE_INSTALL_CONTEXT = 'homeschool'
$env:BEDE_CAMPUS_ID = ''
$env:COMPOSE_PROJECT_NAME = 'bede_homeschool_local'
if ($choice -eq '2') {
    $campus = Read-Host 'Approved campus ID'
    if ($campus -cnotmatch '^[a-z0-9][a-z0-9_-]{2,63}$') { Stop-Install 'Invalid campus ID' }
    $env:BEDE_INSTALL_CONTEXT = 'campus'
    $env:BEDE_CAMPUS_ID = $campus
    $env:COMPOSE_PROJECT_NAME = 'bede_campus_' + $campus.Replace('-','_')
    $runtimeDir = Join-Path (Join-Path (Join-Path $env:LOCALAPPDATA 'Bede\Campus') $campus) 'bede-operator'
} elseif ($choice -eq '' -or $choice -eq '1') {
    $runtimeDir = Join-Path $env:LOCALAPPDATA 'Bede\Homeschool\local\bede-operator'
} else {
    Stop-Install 'Unknown installation context'
}
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$priorShaPath = Join-Path $runtimeDir 'RELEASE'
$priorConfig = Join-Path $runtimeDir '.env'
if (Test-Path -LiteralPath $priorShaPath -PathType Leaf) {
    $priorSha = (Get-Content -LiteralPath $priorShaPath -Raw).Trim()
    if ($priorSha -cne $sourceSha) {
        Stop-Install 'An existing installation uses another SHA. A separately authorized, non-destructive upgrade is required.'
    }
} elseif (Test-Path -LiteralPath $priorConfig -PathType Leaf) {
    Stop-Install 'Unidentified existing configuration: refusing to overwrite or adopt learner data'
}
foreach ($file in @('RELEASE','ARCH','IMAGE_DIGESTS','WIZARD_IMAGE','RELEASE_PROVENANCE.json',
                    'compose.yaml','compose.lan.yaml','Caddyfile','.env.example')) {
    Copy-Item -LiteralPath (Join-Path $packageRoot $file) -Destination (Join-Path $runtimeDir $file) -Force
}
Set-Location -LiteralPath $runtimeDir

# Docker pulls only digest-pinned images and tags them to the exact source SHA.
# No Git, floating image tags, build-from-source or unsigned installer downloads.
foreach ($line in $entries) {
    $parts = $line -split ' ', 2
    $image = $parts[0]
    $reference = $image + '@' + $parts[1]
    Invoke-BedeDocker @('pull',$reference)
    Invoke-BedeDocker @('tag',$reference,$image)
}
if (-not (Test-Path -LiteralPath '.env' -PathType Leaf)) {
    Write-Host 'Opening the Bede browser wizard. Refresh if it opens before the server.'
    Start-Process 'http://127.0.0.1:8765/'
    $mount = 'type=bind,src=' + (Get-Location).Path + ',dst=/repo'
    Invoke-BedeDocker @('run','--rm','--network','bridge','-p','127.0.0.1:8765:8765',
        '--env','BEDE_INSTALL_CONTEXT','--env','BEDE_CAMPUS_ID','--mount',$mount,$wizard)
}
if (-not (Test-Path -LiteralPath '.env' -PathType Leaf) -or
    (Get-Item -LiteralPath '.env').Length -eq 0) { Stop-Install 'Wizard did not save approved setup' }

$compose = @('-f','compose.yaml')
$envLines = @(Get-Content -LiteralPath '.env')
if ($envLines -ccontains 'BEDE_LAN_ENABLED=true') {
    $lanLine = @($envLines | Where-Object { $_ -cmatch '^BEDE_LAN_BIND_IP=' })
    $ip = if ($lanLine.Count -eq 1) { $lanLine[0].Substring(17) } else { '' }
    $octets = $ip -split '\.'
    if ($octets.Count -ne 4 -or @($octets | Where-Object { $_ -cnotmatch '^\d{1,3}$' }).Count -gt 0) {
        Stop-Install 'Invalid LAN address'
    }
    $o = @($octets | ForEach-Object { [int]$_ })
    if (@($o | Where-Object { $_ -gt 255 }).Count -gt 0) { Stop-Install 'Invalid LAN octet' }
    $private = ($o[0] -eq 10) -or ($o[0] -eq 192 -and $o[1] -eq 168) -or
        ($o[0] -eq 172 -and $o[1] -ge 16 -and $o[1] -le 31)
    if (-not $private) { Stop-Install 'Refusing public or wildcard LAN bind' }
    $compose += @('-f','compose.lan.yaml')
}
Invoke-BedeDocker (@('compose','--env-file','.env') + $compose + @('config','--quiet'))
Invoke-BedeDocker (@('compose','--env-file','.env') + $compose + @('up','-d','--no-build','--pull','never'))

# The first local probe only triggers certificate issuance; it is not health proof.
& curl.exe -k -s --max-time 5 https://localhost/api/health *> $null
$verified = $false
$certPath = Join-Path (Get-Location).Path 'bede-root-ca.crt'
$deadline = (Get-Date).AddMinutes(3)
while ((Get-Date) -lt $deadline) {
    $certificate = & docker.exe compose --env-file .env @compose exec -T caddy cat /data/caddy/pki/authorities/local/root.crt 2>$null
    if ($LASTEXITCODE -eq 0 -and $certificate) {
        [System.IO.File]::WriteAllText(
            $certPath, (($certificate -join [Environment]::NewLine) + [Environment]::NewLine),
            [System.Text.Encoding]::ASCII)
        & curl.exe -fsS --max-time 5 --cacert $certPath https://localhost/api/health *> $null
        if ($LASTEXITCODE -eq 0) { $verified = $true; break }
    }
    Start-Sleep -Seconds 2
}
if (-not $verified) { Stop-Install 'Bede did not become healthy with verified HTTPS' }
Write-Host ('Bede '+$sourceSha.Substring(0,12)+' is ready at https://localhost')
Start-Process 'https://localhost'
