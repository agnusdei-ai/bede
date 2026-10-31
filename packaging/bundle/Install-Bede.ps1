# Bede source-free Windows Standard installer entry point.
# This file is included in an exact-source-SHA native Inno Setup EXE.
# No Git, floating main checkout, unverified prerequisite download, or Docker build.
# Offline packages are separate and require a qualified native decompression path.
# Engineering packaging is not a release / student-data / pilot GO.
#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location -LiteralPath $PSScriptRoot

function Stop-Install([string]$message) {
    throw "Bede installation incomplete: $message"
}
function Invoke-BedeDocker([string[]]$arguments) {
    & docker.exe @arguments
    if ($LASTEXITCODE -ne 0) { Stop-Install ("Docker command failed: " + $arguments[0]) }
}
function Read-BedeValue([string]$name) {
    $value = (Get-Content -LiteralPath $name -Raw).Trim()
    if (-not $value) { Stop-Install ("Missing package metadata: " + $name) }
    return $value
}

# The payload must be a sealed, traceable build; no live source checkout.
foreach ($name in @('RELEASE','ARCH','IMAGE_DIGESTS','WIZARD_IMAGE','compose.yaml','Caddyfile','RELEASE_PROVENANCE.json')) {
    if (-not (Test-Path -LiteralPath $name -PathType Leaf)) { Stop-Install ("Incomplete release package: " + $name) }
}
$sourceSha = Read-BedeValue 'RELEASE'
if ($sourceSha -cnotmatch '^[a-f0-9]{40}$') { Stop-Install 'Invalid source SHA' }
$requiredArch = Read-BedeValue 'ARCH'
if ($requiredArch -cne 'amd64') { Stop-Install 'The Windows x64 installer needs an amd64 image package' }
$wizard = Read-BedeValue 'WIZARD_IMAGE'
if ($wizard -cne ('ghcr.io/agnusdei-ai/bede-wizard:sha-' + $sourceSha + '-amd64')) {
    Stop-Install 'Wizard image does not match the sealed release'
}
$provenance = Get-Content -LiteralPath 'RELEASE_PROVENANCE.json' -Raw | ConvertFrom-Json
if ($provenance.source_sha -cne $sourceSha -or $provenance.architecture -cne 'amd64' -or $provenance.pilot_go -cne 'HOLD') {
    Stop-Install 'Release provenance does not match the package'
}
$entries = @(Get-Content -LiteralPath 'IMAGE_DIGESTS' | Where-Object { $_.Trim() -ne '' })
if ($entries.Count -ne 6) { Stop-Install 'Expected six pinned application/runtime images' }
$allowedThirdParty = @('postgres:16-alpine','caddy:2-alpine')
$seen = @{}
foreach ($line in $entries) {
    if ($line -cnotmatch '^(\S+) (sha256:[0-9a-f]{64})$') { Stop-Install 'Malformed image digest entry' }
    $image = $Matches[1]
    if ($seen.ContainsKey($image)) { Stop-Install 'Duplicate image in digest manifest' }
    $seen[$image] = $true
    if (-not ($image -cin $allowedThirdParty) -and $image -cnotmatch ('^ghcr\.io/agnusdei-ai/bede-(api|ui|trust|wizard):sha-' + $sourceSha + '-amd64$')) {
        Stop-Install 'Unexpected image in release manifest'
    }
}
foreach ($component in @('api','ui','trust','wizard')) {
    if (-not $seen.ContainsKey(('ghcr.io/agnusdei-ai/bede-' + $component + ':sha-' + $sourceSha + '-amd64'))) {
        Stop-Install ("Missing pinned " + $component + " image")
    }
}
foreach ($thirdParty in $allowedThirdParty) {
    if (-not $seen.ContainsKey($thirdParty)) { Stop-Install 'Missing pinned runtime dependency' }
}
if (-not (Get-Command docker.exe -ErrorAction SilentlyContinue)) {
    Stop-Install 'A supported container engine with Docker Compose is required. Install and start it with administrator approval, then relaunch Bede Setup.'
}
Invoke-BedeDocker @('info','--format','{{.Architecture}}')
$dockerArch = (& docker.exe info --format '{{.Architecture}}').Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0) { Stop-Install 'Start the container engine and retry' }
if ($dockerArch -eq 'x86_64') { $dockerArch = 'amd64' }
if ($dockerArch -ne 'amd64') { Stop-Install ('Docker architecture mismatch: ' + $dockerArch) }
Invoke-BedeDocker @('compose','version')

# Operator chooses a tenant context before running the existing browser wizard.
$choice = Read-Host 'Choose installation: [1] Homeschool (default) or [2] Campus'
$env:BEDE_INSTALL_CONTEXT = 'homeschool'
$env:BEDE_CAMPUS_ID = ''
$env:COMPOSE_PROJECT_NAME = 'bede_homeschool_local'
if ($choice -eq '2') {
    $campus = Read-Host 'Enter the approved campus ID'
    if ($campus -cnotmatch '^[a-z0-9][a-z0-9_-]{2,63}$') { Stop-Install 'Campus ID must be a valid approved identifier' }
    $env:BEDE_INSTALL_CONTEXT = 'campus'
    $env:BEDE_CAMPUS_ID = $campus
    $env:COMPOSE_PROJECT_NAME = 'bede_campus_' + $campus.Replace('-','_')
} elseif ($choice -ne '' -and $choice -ne '1') {
    Stop-Install 'Unknown installation choice'
}

# Standard package downloads only *digest-pinned* published images.
# A failure must not fall back to an unsigned or floating image/tag.
foreach ($line in $entries) {
    $parts = $line -split ' ', 2
    $image = $parts[0]
    $digest = $parts[1]
    $reference = $image + '@' + $digest
    Invoke-BedeDocker @('pull', $reference)
    Invoke-BedeDocker @('tag', $reference, $image)
}

if (-not (Test-Path -LiteralPath '.env' -PathType Leaf)) {
    Write-Host 'Opening the setup wizard. If it opens before the server is ready, refresh the browser.'
    Start-Process 'http://127.0.0.1:8765/'
    $mount = 'type=bind,src=' + (Get-Location).Path + ',dst=/repo'
    Invoke-BedeDocker @('run','--rm','--network','bridge','-p','127.0.0.1:8765:8765',
        '--env','BEDE_INSTALL_CONTEXT','--env','BEDE_CAMPUS_ID',
        '--mount',$mount,$wizard)
}
if (-not (Test-Path -LiteralPath '.env' -PathType Leaf) -or (Get-Item -LiteralPath '.env').Length -eq 0) {
    Stop-Install 'The authorized setup wizard did not save configuration'
}
$compose = @('-f','compose.yaml')
# Never publish a wide-open listener. Only an explicitly configured private LAN
# address may invoke the separately shipped overlay.
$envLines = Get-Content -LiteralPath '.env'
if ($envLines -ccontains 'BEDE_LAN_ENABLED=true') {
    if (-not (Test-Path -LiteralPath 'compose.lan.yaml' -PathType Leaf)) { Stop-Install 'Missing LAN security overlay' }
    $lanLine = @($envLines | Where-Object { $_ -match '^BEDE_LAN_BIND_IP=' })
    $lanIP = if ($lanLine.Count -eq 1) { $lanLine[0].Substring(17) } else { '' }
    $octets = $lanIP -split '\.'
    if ($octets.Count -ne 4 -or ($octets | Where-Object { $_ -cnotmatch '^\d{1,3}$' }).Count -ne 0) {
        Stop-Install 'Invalid LAN IPv4 address'
    }
    $o = @($octets | ForEach-Object { [int]$_ })
    if (@($o | Where-Object { $_ -gt 255 }).Count -gt 0) { Stop-Install 'Invalid LAN IPv4 octet' }
    $private = ($o[0] -eq 10) -or ($o[0] -eq 192 -and $o[1] -eq 168) -or ($o[0] -eq 172 -and $o[1] -ge 16 -and $o[1] -le 31)
    if (-not $private) { Stop-Install 'Refusing public or wildcard LAN listener' }
    $compose += @('-f','compose.lan.yaml')
}
Invoke-BedeDocker (@('compose','--env-file','.env') + $compose + @('config','--quiet'))
Invoke-BedeDocker (@('compose','--env-file','.env') + $compose + @('up','-d','--no-build','--pull','never'))

# The first probe is solely local certificate issuance; it is not trusted health.
& curl.exe -k -s --max-time 5 https://localhost/api/health *> $null
$verified = $false
$certPath = Join-Path (Get-Location).Path 'bede-root-ca.crt'
$deadline = (Get-Date).AddMinutes(3)
while ((Get-Date) -lt $deadline) {
    $certificate = & docker.exe compose --env-file .env @compose exec -T caddy cat /data/caddy/pki/authorities/local/root.crt 2>$null
    if ($LASTEXITCODE -eq 0 -and $certificate) {
        [System.IO.File]::WriteAllText($certPath, (($certificate -join [Environment]::NewLine) + [Environment]::NewLine), [System.Text.Encoding]::ASCII)
        & curl.exe -fsS --max-time 5 --cacert $certPath https://localhost/api/health *> $null
        if ($LASTEXITCODE -eq 0) { $verified = $true; break }
    }
    Start-Sleep -Seconds 2
}
if (-not $verified) { Stop-Install 'Bede did not become healthy with verified HTTPS' }
Write-Host ('Bede '+$sourceSha.Substring(0,12)+' is running with verified HTTPS at https://localhost')
Start-Process 'https://localhost'
