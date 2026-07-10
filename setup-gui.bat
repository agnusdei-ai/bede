@echo off
REM Double-click this to set up Bede with no typing required — it opens a
REM form in your browser instead of a terminal. See docs/PRODUCTION_SETUP.md
REM if you'd rather use the terminal-based setup.sh (needs WSL/Git Bash).
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo Bede - Setup
echo.

where docker >nul 2>&1
if errorlevel 1 (
  echo Docker is not installed. Get Docker Desktop from https://docker.com/products/docker-desktop
  echo then run this again.
  pause
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo Docker doesn't seem to be running yet. Open Docker Desktop, wait for it
  echo to finish starting, then run this again.
  pause
  exit /b 1
)

REM Best-effort LAN IP for the "from tablets on your network" message —
REM falls back to blank (no tablet-URL line shown) if this doesn't parse.
set LAN_IP=
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4 Address"') do (
  if not defined LAN_IP set LAN_IP=%%a
)
set LAN_IP=%LAN_IP: =%

echo Preparing the setup wizard (first run only takes a minute)...
docker build -q -t bede-setup-wizard -f scripts\setup_wizard\Dockerfile .
if errorlevel 1 (
  echo Could not build the setup wizard. See the error above.
  pause
  exit /b 1
)

echo Opening the setup wizard in your browser...
start "" cmd /c "timeout /t 2 >nul & start http://localhost:8765"

REM Foreground on purpose — returns once the wizard container exits, which
REM it does itself right after a successful submission.
docker run --rm -p 8765:8765 -e HOST_LAN_IP=%LAN_IP% -v "%cd%":/repo bede-setup-wizard

if not exist .env (
  echo Setup wasn't completed ^(no configuration was saved^). Run this again when you're ready.
  pause
  exit /b 1
)

echo Configuration saved. Starting Bede - this can take a few minutes the first time...
docker compose up -d --build

echo Waiting for the API to become healthy...
set /a TRIES=0
:healthcheck
curl -skf https://localhost/api/health >nul 2>&1
if not errorlevel 1 goto healthy
set /a TRIES+=1
if %TRIES% geq 45 (
  echo.
  echo Bede is taking longer than expected to start. Run "make logs" to see what's happening.
  goto done
)
timeout /t 2 >nul
goto healthcheck

:healthy
echo.
echo Bede is running!

:done
echo   Open in your browser: https://localhost
if not "%LAN_IP%"=="" (
  echo   From tablets on your network: https://%LAN_IP%
  echo   ^(Run "make caddy-trust" to install the cert on each tablet - no more warnings^)
)
echo.
pause
