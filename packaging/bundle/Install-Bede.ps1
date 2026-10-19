# Double-click via the packaged Bede Setup shortcut on Windows.
# Runs entirely from the extracted installer folder; no Git or source checkout.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
function Stop-Install([string]$msg) { throw "Bede installation incomplete: $msg" }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Stop-Install 'Install and start Docker Desktop first.' }
& docker info *> $null
if ($LASTEXITCODE -ne 0) { Stop-Install 'Docker Desktop must be running.' }
if (!(Test-Path 'images.tar')) { Stop-Install 'The self-contained application image archive is missing.' }
if (!(Test-Path 'WIZARD_IMAGE')) { Stop-Install 'The setup wizard image reference is missing.' }
if (!(Test-Path 'ARCH')) { Stop-Install 'CPU architecture metadata is missing.' }
$requiredArch = (Get-Content 'ARCH' -Raw).Trim()
$dockerArch = (& docker info --format '{{.Architecture}}').Trim().ToLower()
if ($dockerArch -eq 'x86_64') { $dockerArch = 'amd64' }
if ($dockerArch -eq 'aarch64') { $dockerArch = 'arm64' }
if ($requiredArch -ne $dockerArch) { Stop-Install "Choose the $dockerArch package; this archive contains $requiredArch images." }
& docker load -i images.tar
if ($LASTEXITCODE -ne 0) { Stop-Install 'Could not load the included application images.' }
if (!(Test-Path '.env')) {
  $wizard = (Get-Content WIZARD_IMAGE -Raw).Trim()
  Start-Process 'http://localhost:8765'
  $mountPath = (Get-Location).Path
  & docker run --rm -p '127.0.0.1:8765:8765' --mount "type=bind,src=$mountPath,dst=/repo" $wizard
  if ($LASTEXITCODE -ne 0 -or !(Test-Path '.env')) { Stop-Install 'The browser wizard was not completed.' }
}
& docker compose --env-file .env -f compose.yaml config --quiet
if ($LASTEXITCODE -ne 0) { Stop-Install 'The saved configuration was rejected.' }
& docker compose --env-file .env -f compose.yaml up -d --no-build --pull never
if ($LASTEXITCODE -ne 0) { Stop-Install 'The Bede containers did not start.' }
# Certificate issuance is triggered locally, then verification is done with
# the exported CA. Never consider the bootstrap probe a passed health check.
& curl.exe -k -s --max-time 5 https://localhost/api/health *> $null
$verified = $false
$healthDeadline = (Get-Date).AddMinutes(3)
while ((Get-Date) -lt $healthDeadline) {
  $caTmp = Join-Path (Get-Location).Path 'bede-root-ca.crt.tmp'
  & docker compose --env-file .env -f compose.yaml exec -T caddy cat /data/caddy/pki/authorities/local/root.crt 2>$null | Out-File -Encoding ascii $caTmp
  if ($LASTEXITCODE -eq 0 -and (Test-Path $caTmp) -and (Get-Item $caTmp).Length -gt 0) {
    Move-Item -Force $caTmp 'bede-root-ca.crt'
    & curl.exe -fsS --max-time 5 --cacert bede-root-ca.crt https://localhost/api/health *> $null
    if ($LASTEXITCODE -eq 0) { $verified = $true; break }
  } else {
    Remove-Item $caTmp -ErrorAction SilentlyContinue
  }
  Start-Sleep -Seconds 2
}
if (-not $verified) { Stop-Install 'Verified HTTPS did not become healthy within three minutes. Check Docker Desktop and restart Bede Setup.' }
Write-Host 'Bede is running with verified HTTPS at https://localhost.'
Start-Process 'https://localhost'
