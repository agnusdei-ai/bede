#!/usr/bin/env bash
# Bede G3 evidence collector for a physical Mac (Mac mini or any Apple Silicon
# or Intel Mac with Docker Desktop).
#
# One command does every part of the G3 physical-Mac run that a machine can do
# by itself, and stops only where a person is genuinely needed (a Touch ID tap).
#
#   1. Records the Mac's hardware and software facts (record section A). It
#      never records a serial number, hardware UUID, user name or host name.
#   2. Fetches the offline operator bundle for one exact commit (or uses one you
#      downloaded), and verifies its checksum, RELEASE commit, ARCH and Docker
#      architecture (G3-01).
#   3. Installs Bede unattended on a fresh, disposable campus instance: it answers
#      the setup wizard itself, with a generated administrator password kept in a
#      private file, never in the evidence (G3-01).
#   4. Runs Verify-Bede.command, then checks which addresses Bede listens on and
#      that the served HTTPS certificate verifies against this instance's CA (G3-01).
#   5. Restarts the stack without touching its volumes and checks health and data
#      volumes survive (the automated part of G3-09).
#   6. Optionally (--mac-check) runs the real Touch ID teacher check,
#      scripts/qualification/mac_check.py, against a throwaway database. You tap
#      Touch ID and answer a few yes/no questions; everything else is automatic
#      (G3-02 and G3-03, source-checkout form).
#   7. Scans every evidence file for any secret this run created or used, writes
#      SHA256SUMS, packs the evidence, and writes a filled-in draft of the G3
#      record. It marks a row PASS only from something it measured; every other
#      row stays NOT RUN with the step that is still yours.
#
# Usage:
#   bash collect-g3-evidence.sh --license-file PATH (--run-id ID | --bundle PATH) [options]
#
#   --license-file PATH   campus_location activation key (from scripts/issue_license.py)
#   --run-id ID           GitHub Actions run of "Bede Standard and Offline operator
#                         bundles"; needs the GitHub CLI (`gh auth login` once)
#   --bundle PATH         bede-operator-<sha>-<arch>.tar.gz already downloaded, with
#                         its .sha256 file beside it
#   --arch arm64|amd64    defaults to this Mac's processor
#   --local-model-url URL OpenAI-compatible local model for the instance
#                         (default http://host.docker.internal:11434/v1, Ollama)
#   --work DIR            defaults to ~/Bede-G3/<UTC time>
#   --mac-check           also run the Touch ID teacher check (needs git, Python 3.12
#                         and Node 20+; installs its own dependencies in DIR)
#   --teardown            stop the instance afterwards (keeps its data volumes)
#
# Exit status: 0 every automated check passed, 1 a check failed, 2 blocked
# (something it needs is missing), 3 the secret scan found a secret in evidence.
#
# Written for macOS's own bash 3.2: no associative arrays, mapfile or ${x,,}.
set -Eeuo pipefail
umask 077

REPO_SLUG="agnusdei-ai/bede"
ARTIFACT_PREFIX="bede-offline-linux"
WIZARD="http://127.0.0.1:8765"

# ── Small helpers ─────────────────────────────────────────────────────────────

say()   { printf '%s\n' "$*"; }
step()  { printf '\n== %s\n' "$*"; }
utc()   { date -u +%Y-%m-%dT%H:%M:%SZ; }
die()   { printf 'BLOCKED: %s\n' "$*" >&2; exit 2; }

# Record one automated result. Writes "<id>|<PASS|FAIL|BLOCKED>|<note>".
RESULTS_FILE=""
result() {
  printf '%s|%s|%s\n' "$1" "$2" "$3" >> "$RESULTS_FILE"
  printf '  %-7s %s: %s\n' "$2" "$1" "$3"
}

# The location_id inside a license key, read without verifying the signature
# (the API verifies it; this only fills in the campus ID the wizard needs).
license_field() {
  local key="$1" field="$2" payload pad
  payload="${key%%.*}"
  pad=$(( (4 - ${#payload} % 4) % 4 ))
  while [ "$pad" -gt 0 ]; do payload="${payload}="; pad=$((pad - 1)); done
  printf '%s' "$payload" | tr '_-' '/+' | base64 -d 2>/dev/null \
    | sed -n "s/.*\"$field\":\"\\([^\"]*\\)\".*/\\1/p"
}

# Fails (returns 1) when any value listed in $1 (one per line) appears in any
# file under directory $2, or when a private key block or bearer token does.
secret_scan() {
  local values="$1" dir="$2" hits=0 v wflag
  while IFS= read -r v; do
    [ "${#v}" -ge 6 ] || continue
    # Short values (a 6-7 digit PIN) must match as a whole word, or any
    # timestamp or size containing those digits would look like a leak.
    if [ "${#v}" -lt 8 ]; then wflag=-w; else wflag=; fi
    if grep -rqF $wflag -- "$v" "$dir" 2>/dev/null; then
      printf 'SECRET FOUND in evidence: a value from this run (%s characters)\n' "${#v}" >&2
      hits=$((hits + 1))
    fi
  done <<EOF
$values
EOF
  if grep -rqE -- '-----BEGIN [A-Z ]*PRIVATE KEY-----|[Bb]earer [A-Za-z0-9._-]{20,}' "$dir" 2>/dev/null; then
    printf 'SECRET FOUND in evidence: a private key block or bearer token\n' >&2
    hits=$((hits + 1))
  fi
  [ "$hits" -eq 0 ]
}

# A lockfile without its Linux-only GPU packages, which have no macOS builds.
mac_lock() {
  awk '
    /^[A-Za-z0-9]/ { skip = ($0 ~ /^(nvidia-|cuda-|triton)/) }
    !skip { print }
  ' "$1"
}

# The key from a file holding either the bare key or issue_license.py's whole
# output, which puts it on a "LICENSE_KEY=" line among others.
read_license_key() {
  if grep -q '^LICENSE_KEY=' "$1"; then
    sed -n 's/^LICENSE_KEY=//p' "$1" | head -n 1 | tr -d '\r\n '
  else
    tr -d '\r\n ' < "$1"
  fi
}

# The value of KEY in a dotenv file, or empty.
env_value() { sed -n "s/^$2=//p" "$1" | head -n 1; }

# Stop here when sourced for tests.
if [ "${G3_LIB_ONLY:-}" = "1" ]; then return 0 2>/dev/null || exit 0; fi

# ── Arguments ─────────────────────────────────────────────────────────────────

LICENSE_FILE=""; RUN_ID=""; BUNDLE=""; ARCH=""; WORK=""; MAC_CHECK=0; TEARDOWN=0
LOCAL_MODEL_URL="http://host.docker.internal:11434/v1"
while [ $# -gt 0 ]; do
  case "$1" in
    --license-file) LICENSE_FILE="$2"; shift 2 ;;
    --run-id) RUN_ID="$2"; shift 2 ;;
    --bundle) BUNDLE="$2"; shift 2 ;;
    --arch) ARCH="$2"; shift 2 ;;
    --work) WORK="$2"; shift 2 ;;
    --local-model-url) LOCAL_MODEL_URL="$2"; shift 2 ;;
    --mac-check) MAC_CHECK=1; shift ;;
    --teardown) TEARDOWN=1; shift ;;
    -h|--help) sed -n '2,48p' "$0"; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done
[ -n "$LICENSE_FILE" ] || die "--license-file is required"
[ -s "$LICENSE_FILE" ] || die "license file is empty or missing: $LICENSE_FILE"
[ -n "$RUN_ID" ] || [ -n "$BUNDLE" ] || die "give --run-id or --bundle"
[ "$(uname -s)" = "Darwin" ] || die "run this on the Mac being certified"

if [ -z "$ARCH" ]; then
  case "$(uname -m)" in arm64) ARCH=arm64 ;; x86_64) ARCH=amd64 ;; *) die "unknown CPU $(uname -m)" ;; esac
fi
case "$ARCH" in arm64|amd64) ;; *) die "--arch must be arm64 or amd64" ;; esac

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="${WORK:-$HOME/Bede-G3/$STAMP}"
EVIDENCE="$WORK/evidence"
PRIVATE="$WORK/private"
mkdir -p "$EVIDENCE" "$PRIVATE" "$WORK/download" "$WORK/bin"
chmod 700 "$WORK" "$EVIDENCE" "$PRIVATE"
RESULTS_FILE="$EVIDENCE/automated-results.txt"
: > "$RESULTS_FILE"
exec > >(tee -a "$PRIVATE/run.log") 2>&1
say "Bede G3 evidence run $STAMP. Work folder: $WORK"
say "Only sample data is used. Nothing here may be pointed at real student records."

for cmd in docker curl shasum tar openssl lsof base64 sed grep; do
  command -v "$cmd" >/dev/null 2>&1 || die "missing tool: $cmd"
done
docker info >/dev/null 2>&1 || die "start Docker Desktop first"
command -v zstd >/dev/null 2>&1 || die "the offline bundle needs zstd: run 'brew install zstd'"

LICENSE_KEY="$(read_license_key "$LICENSE_FILE")"
CAMPUS_ID="$(license_field "$LICENSE_KEY" location_id)"
LICENSE_TIER="$(license_field "$LICENSE_KEY" tier)"
[ "$LICENSE_TIER" = "campus_location" ] || die "the license is not a campus_location key"
[ -n "$CAMPUS_ID" ] || die "the license has no location_id"

# ── 1. Host facts (record section A) ──────────────────────────────────────────

step "1. This Mac"
{
  printf 'captured_utc=%s\n' "$(utc)"
  printf 'model=%s\n' "$(sysctl -n hw.model 2>/dev/null || echo unknown)"
  printf 'chip=%s\n' "$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo unknown)"
  printf 'cpu_arch=%s\n' "$(uname -m)"
  printf 'memory_bytes=%s\n' "$(sysctl -n hw.memsize 2>/dev/null || echo unknown)"
  printf 'macos=%s (%s)\n' "$(sw_vers -productVersion)" "$(sw_vers -buildVersion)"
  printf 'filevault=%s\n' "$(fdesetup status 2>/dev/null | head -n 1 || echo unknown)"
  printf 'disk_root=%s\n' "$(df -h / | awk 'NR==2 {print $2" total, "$4" free"}')"
  printf 'docker_server=%s\n' "$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo unknown)"
  printf 'docker_arch=%s\n' "$(docker info --format '{{.Architecture}}')"
  printf 'docker_cpus=%s docker_memory_bytes=%s\n' "$(docker info --format '{{.NCPU}}')" "$(docker info --format '{{.MemTotal}}')"
  printf 'compose=%s\n' "$(docker compose version --short 2>/dev/null || echo unknown)"
  for app in Safari "Google Chrome"; do
    v="$(defaults read "/Applications/$app.app/Contents/Info" CFBundleShortVersionString 2>/dev/null || echo 'not installed')"
    printf 'browser_%s=%s\n' "$(printf '%s' "$app" | tr ' ' '_')" "$v"
  done
  if curl -fsS --max-time 3 "http://127.0.0.1:11434/v1/models" >/dev/null 2>&1; then
    printf 'local_model_server=reachable on 127.0.0.1:11434\n'
  else
    printf 'local_model_server=not reachable on 127.0.0.1:11434 (inference not tested in this run)\n'
  fi
  printf 'serial_number=not recorded by design\n'
} > "$EVIDENCE/host.txt"
cat "$EVIDENCE/host.txt"

# ── 2. Bundle: fetch and verify (G3-01) ───────────────────────────────────────

step "2. Operator bundle"
if [ -n "$RUN_ID" ]; then
  command -v gh >/dev/null 2>&1 || die "--run-id needs the GitHub CLI: 'brew install gh' then 'gh auth login'"
  SHA="$(gh run view "$RUN_ID" -R "$REPO_SLUG" --json headSha -q .headSha)"
  conclusion="$(gh run view "$RUN_ID" -R "$REPO_SLUG" --json conclusion -q .conclusion)"
  [ "$conclusion" = "success" ] || die "run $RUN_ID did not succeed ($conclusion)"
  gh run download "$RUN_ID" -R "$REPO_SLUG" -n "$ARTIFACT_PREFIX-$ARCH-$SHA" -D "$WORK/download"
  BUNDLE="$WORK/download/bede-operator-$SHA-$ARCH.tar.gz"
fi
[ -s "$BUNDLE" ] || die "bundle not found: $BUNDLE"
SIDE="$BUNDLE.sha256"
[ -s "$SIDE" ] || die "checksum file not found: $SIDE"
name="$(basename "$BUNDLE")"
SHA="$(printf '%s' "$name" | sed -n 's/^bede-operator-\([0-9a-f]\{40\}\)-.*/\1/p')"
[ -n "$SHA" ] || die "cannot read the commit from the bundle name: $name"
{
  printf 'bundle=%s\n' "$name"
  printf 'bundle_sha256=%s\n' "$(shasum -a 256 "$BUNDLE" | awk '{print $1}')"
  printf 'sidecar=%s\n' "$(cat "$SIDE")"
  [ -n "$RUN_ID" ] && printf 'workflow_run=https://github.com/%s/actions/runs/%s\n' "$REPO_SLUG" "$RUN_ID"
} > "$EVIDENCE/package.txt"
if (cd "$(dirname "$BUNDLE")" && shasum -a 256 -c "$(basename "$SIDE")" >/dev/null 2>&1); then
  result G3-01.checksum PASS "bundle matches its published SHA-256"
else
  result G3-01.checksum FAIL "bundle does not match its .sha256 file"
fi

INSTALL="$WORK/install"
mkdir -p "$INSTALL"
tar -xzf "$BUNDLE" -C "$INSTALL"
APP="$INSTALL/bede-operator"
[ -d "$APP" ] || die "the bundle did not contain bede-operator/"
release="$(tr -d '\r\n' < "$APP/RELEASE" 2>/dev/null || true)"
bundle_arch="$(tr -d '\r\n' < "$APP/ARCH" 2>/dev/null || true)"
docker_arch="$(docker info --format '{{.Architecture}}' | tr '[:upper:]' '[:lower:]')"
case "$docker_arch" in x86_64|amd64) docker_arch=amd64 ;; aarch64|arm64) docker_arch=arm64 ;; esac
{
  printf 'RELEASE=%s\n' "$release"
  printf 'ARCH=%s\n' "$bundle_arch"
  printf 'docker_arch=%s\n' "$docker_arch"
} >> "$EVIDENCE/package.txt"
for f in RELEASE_PROVENANCE.json IMAGE_DIGESTS PAYLOAD_METRICS.txt; do
  [ -f "$APP/$f" ] && cp "$APP/$f" "$EVIDENCE/$f"
done
if [ "$release" = "$SHA" ]; then result G3-01.release PASS "RELEASE is $SHA"
else result G3-01.release FAIL "RELEASE ($release) is not the bundle's commit ($SHA)"; fi
if [ "$bundle_arch" = "$ARCH" ] && [ "$docker_arch" = "$ARCH" ]; then
  result G3-01.arch PASS "bundle, Docker and requested architecture are all $ARCH"
else
  result G3-01.arch FAIL "bundle=$bundle_arch docker=$docker_arch requested=$ARCH"
fi

# ── 3. Unattended install (G3-01) ─────────────────────────────────────────────

step "3. Install a fresh sample campus instance"
[ ! -s "$APP/.env" ] || die "$APP/.env already exists; use a fresh --work folder"
ADMIN_PASSWORD="g3-$(openssl rand -hex 16)"
printf 'administrator_password=%s\ncampus_id=%s\nsource_sha=%s\n' "$ADMIN_PASSWORD" "$CAMPUS_ID" "$SHA" > "$PRIVATE/credentials.txt"
chmod 600 "$PRIVATE/credentials.txt"
# start.sh opens the setup page in a browser; this run answers it itself, so the
# browser opener is replaced for this one command.
printf '#!/bin/sh\nexit 0\n' > "$WORK/bin/open"
chmod 700 "$WORK/bin/open"
(
  cd "$APP"
  BEDE_INSTALL_CONTEXT=campus BEDE_CAMPUS_ID="$CAMPUS_ID" PATH="$WORK/bin:$PATH" ./start.sh
) > "$PRIVATE/install.log" 2>&1 &
installer=$!
t0=$(date +%s)
up=0
for _ in $(seq 1 600); do
  if curl -fsS --max-time 2 "$WIZARD/" -o "$PRIVATE/wizard-1.html" 2>/dev/null; then up=1; break; fi
  kill -0 "$installer" 2>/dev/null || break
  sleep 2
done
[ "$up" = 1 ] || { tail -n 20 "$PRIVATE/install.log"; die "the setup wizard did not start (see $PRIVATE/install.log)"; }
curl -fsS --max-time 10 -X POST "$WIZARD/consent" --data-urlencode "agree=yes" -o /dev/null
curl -fsS --max-time 10 "$WIZARD/" -o "$PRIVATE/wizard-2.html"
CHILD_PIN="$(sed -n 's/.*name="child_pin" value="\([0-9]\{6,\}\)".*/\1/p' "$PRIVATE/wizard-2.html" | head -n 1)"
if [ -z "$CHILD_PIN" ]; then
  CHILD_PIN="$(grep -o 'suggestion: [0-9]\{6,\}' "$PRIVATE/wizard-2.html" | head -n 1 | sed 's/[^0-9]//g')"
fi
[ -n "$CHILD_PIN" ] || die "could not read the wizard's generated student PIN"
printf 'student_pin=%s\n' "$CHILD_PIN" >> "$PRIVATE/credentials.txt"
curl -sS --max-time 20 -X POST "$WIZARD/submit" \
  --data-urlencode "provider=local" \
  --data-urlencode "local_base_url=$LOCAL_MODEL_URL" \
  --data-urlencode "db_choice=local" \
  --data-urlencode "parent_password=$ADMIN_PASSWORD" \
  --data-urlencode "child_pin=$CHILD_PIN" \
  --data-urlencode "license_key=$LICENSE_KEY" \
  --data-urlencode "location_id=$CAMPUS_ID" \
  -o "$PRIVATE/wizard-result.html" || true
install_status=0
wait "$installer" || install_status=$?
install_seconds=$(( $(date +%s) - t0 ))
grep -E '^BEDE_PROGRESS|^Bede is healthy|incomplete|Setup stopped' "$PRIVATE/install.log" > "$EVIDENCE/install-progress.txt" || true
printf 'install_exit=%s\ninstall_seconds=%s\n' "$install_status" "$install_seconds" >> "$EVIDENCE/install-progress.txt"
if [ "$install_status" = 0 ] && [ -s "$APP/.env" ]; then
  result G3-01.install PASS "unattended install finished in ${install_seconds}s"
else
  result G3-01.install FAIL "installer exit $install_status (private log: $PRIVATE/install.log)"
  if grep -qE 'class="err|error' "$PRIVATE/wizard-result.html" 2>/dev/null; then
    say "The wizard refused the form. Its reply is in $PRIVATE/wizard-result.html"
  fi
fi

# ── 4. Verify, listeners and TLS (G3-01) ──────────────────────────────────────

step "4. Verification"
compose_files="-f compose.yaml"
dc() { (cd "$APP" && BEDE_INSTALL_CONTEXT=campus BEDE_CAMPUS_ID="$CAMPUS_ID" \
        COMPOSE_PROJECT_NAME="bede_campus_$(printf '%s' "$CAMPUS_ID" | tr '-' '_')" \
        docker compose --env-file .env $compose_files "$@"); }
if [ -s "$APP/.env" ]; then
  verify_status=0
  (cd "$APP" && COMPOSE_PROJECT_NAME="bede_campus_$(printf '%s' "$CAMPUS_ID" | tr '-' '_')" \
     ./Verify-Bede.command < /dev/null) > "$PRIVATE/verify.log" 2>&1 || verify_status=$?
  latest="$(ls -1d "$APP"/bede-evidence/*/ 2>/dev/null | tail -n 1)"
  if [ -n "$latest" ]; then mkdir -p "$EVIDENCE/verify" && cp "$latest"* "$EVIDENCE/verify/"; fi
  if [ "$verify_status" = 0 ] && grep -q '^PASS: HTTPS health verified' "$PRIVATE/verify.log"; then
    result G3-01.verify PASS "Verify-Bede.command: Compose valid and HTTPS health verified against this CA"
  else
    result G3-01.verify FAIL "Verify-Bede.command exit $verify_status"
  fi

  # Docker Desktop publishes container ports from its own backend process
  # (lsof shows it as "com.docke"); other apps on this Mac are not Bede's.
  lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null \
    | awk 'NR==1 || ($1 ~ /^(com\.docke|vpnkit)/ && /:(443|80) /)' > "$EVIDENCE/listeners.txt" || true
  if grep -E '(\*|0\.0\.0\.0|\[::\]):(443|80) ' "$EVIDENCE/listeners.txt" >/dev/null; then
    result G3-01.listener FAIL "port 443 or 80 is open on all interfaces"
  elif grep -E '127\.0\.0\.1:443 ' "$EVIDENCE/listeners.txt" >/dev/null; then
    result G3-01.listener PASS "HTTPS listens on 127.0.0.1 only"
  else
    result G3-01.listener FAIL "no loopback HTTPS listener found"
  fi

  if [ -s "$APP/bede-root-ca.crt" ]; then
    {
      printf 'ca_fingerprint_'; openssl x509 -in "$APP/bede-root-ca.crt" -noout -fingerprint -sha256
      openssl x509 -in "$APP/bede-root-ca.crt" -noout -subject -enddate | sed 's/^/ca_/'
      openssl s_client -connect 127.0.0.1:443 -servername localhost -CAfile "$APP/bede-root-ca.crt" \
        < /dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -enddate -fingerprint -sha256 | sed 's/^/served_/'
      printf 'verify_line='
      openssl s_client -connect 127.0.0.1:443 -servername localhost -CAfile "$APP/bede-root-ca.crt" \
        < /dev/null 2>&1 | grep -m1 'Verify return code' || echo none
    } > "$EVIDENCE/tls.txt"
    if grep -q 'Verify return code: 0 (ok)' "$EVIDENCE/tls.txt"; then
      result G3-01.tls PASS "served certificate verifies against this instance's CA"
    else
      result G3-01.tls FAIL "served certificate does not verify against this instance's CA"
    fi
  else
    result G3-01.tls FAIL "bede-root-ca.crt was not exported"
  fi
fi

# ── 5. Restart with data preserved (G3-09, automated part) ────────────────────

step "5. Restart"
if [ -s "$APP/.env" ]; then
  vols_before="$(docker volume ls -q | sort | shasum -a 256 | awk '{print $1}')"
  r0=$(date +%s)
  dc restart > "$PRIVATE/restart.log" 2>&1 || true
  healthy=0
  for _ in $(seq 1 90); do
    if curl -fsS --max-time 5 --cacert "$APP/bede-root-ca.crt" https://localhost/api/health -o "$EVIDENCE/health-after-restart.json" 2>/dev/null; then
      healthy=1; break
    fi
    sleep 2
  done
  vols_after="$(docker volume ls -q | sort | shasum -a 256 | awk '{print $1}')"
  printf 'restart_seconds=%s\nvolumes_unchanged=%s\n' "$(( $(date +%s) - r0 ))" \
    "$([ "$vols_before" = "$vols_after" ] && echo yes || echo no)" > "$EVIDENCE/restart.txt"
  if [ "$healthy" = 1 ] && [ "$vols_before" = "$vols_after" ]; then
    result G3-09.restart PASS "healthy after restart, data volumes unchanged"
  else
    result G3-09.restart FAIL "health after restart=$healthy, volumes unchanged=$([ "$vols_before" = "$vols_after" ] && echo yes || echo no)"
  fi
fi

# ── 6. Touch ID teacher check (G3-02/G3-03, optional) ─────────────────────────

if [ "$MAC_CHECK" = 1 ]; then
  step "6. Touch ID teacher check"
  for cmd in git python3 node npm; do command -v "$cmd" >/dev/null 2>&1 || die "--mac-check needs $cmd"; done
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' || die "--mac-check needs Python 3.12 or newer"
  # Two pinned packages ship as source only (typing, webrtcvad); webrtcvad is a
  # small C extension, so pip needs Apple's compiler to build it.
  xcode-select -p >/dev/null 2>&1 && command -v clang >/dev/null 2>&1 \
    || die "--mac-check needs Apple's command-line tools: run 'xcode-select --install'"
  SRC="$WORK/src"
  git init -q "$SRC"
  git -C "$SRC" remote add origin "https://github.com/$REPO_SLUG.git"
  git -C "$SRC" fetch -q --depth 1 origin "$SHA"
  git -C "$SRC" checkout -q FETCH_HEAD
  say "Installing the check's dependencies (first run takes several minutes)."
  python3 -m venv "$WORK/venv"
  # The lockfile pins Linux-only GPU packages (nvidia-*, cuda-*, triton) with no
  # platform markers; torch's macOS build does not use them. Drop those blocks
  # and keep every other pin and hash.
  mac_lock "$SRC/homeschool-api/requirements-dev.lock.txt" > "$WORK/requirements-mac.lock.txt"
  "$WORK/venv/bin/pip" install -q --require-hashes -r "$WORK/requirements-mac.lock.txt" > "$PRIVATE/pip.log" 2>&1 \
    || die "dependency install failed (see $PRIVATE/pip.log)"
  (cd "$SRC" && npm install -q --no-save playwright@1.56.0 > "$PRIVATE/npm.log" 2>&1 && npx -y playwright@1.56.0 install chromium >> "$PRIVATE/npm.log" 2>&1) \
    || die "browser driver install failed (see $PRIVATE/npm.log)"
  PG_PASS="$(openssl rand -hex 16)"
  printf 'throwaway_postgres_password=%s\n' "$PG_PASS" >> "$PRIVATE/credentials.txt"
  docker rm -f bede-g3-check-db >/dev/null 2>&1 || true
  docker run -d --rm --name bede-g3-check-db -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD="$PG_PASS" postgres:16-alpine >/dev/null
  for _ in $(seq 1 60); do docker exec bede-g3-check-db pg_isready -q && break; sleep 1; done
  say "A browser page opens. Tap Touch ID when asked and answer each question; the rest is automatic."
  check_status=0
  (cd "$SRC" && QUAL_OUT_DIR="$EVIDENCE/mac-check" QUAL_CANDIDATE_SHA="$SHA" \
     QUAL_DB_ADMIN_URL="postgresql://postgres:$PG_PASS@127.0.0.1:55432/postgres" \
     "$WORK/venv/bin/python" scripts/qualification/mac_check.py --browser safari) || check_status=$?
  docker rm -f bede-g3-check-db >/dev/null 2>&1 || true
  case "$check_status" in
    0) result G3-02.mac-check PASS "real Touch ID teacher check: every item passed (source checkout)" ;;
    1) result G3-02.mac-check FAIL "real Touch ID teacher check: an item failed (see mac-check/)" ;;
    *) result G3-02.mac-check BLOCKED "the Touch ID check could not complete (exit $check_status)" ;;
  esac
fi

# ── 7. Secret scan, checksums, record draft ───────────────────────────────────

step "7. Evidence"
secrets_list="$(cut -d= -f2- "$PRIVATE/credentials.txt"; printf '%s\n' "$LICENSE_KEY")"
if [ -s "$APP/.env" ]; then
  secrets_list="$secrets_list
$(grep -E '^(SECRET_KEY|MASTER_SECRET|PARENT_PASSWORD|CHILD_PIN|LICENSE_KEY|DATABASE_URL|POSTGRES_PASSWORD)=' "$APP/.env" | cut -d= -f2-)"
fi

overall="PASS"
grep -q '|FAIL|' "$RESULTS_FILE" && overall="FAIL"
grep -q '|BLOCKED|' "$RESULTS_FILE" && [ "$overall" = PASS ] && overall="BLOCKED"
g301="$(grep '^G3-01\.' "$RESULTS_FILE" | grep -vc '|PASS|' || true)"
row() { # id requirement outcome note
  printf '| %s | %s | %s | %s |\n' "$1" "$2" "$3" "$4"
}
{
  printf '# G3 record draft, %s\n\n' "$(utc)"
  printf 'Generated by scripts/mac/collect-g3-evidence.sh. Copy what applies into\n'
  printf 'docs/institutional/MAC_G3_CERTIFICATION_RECORD.md. A row is PASS here only\n'
  printf 'when this script measured it; everything else is still yours to run.\n\n'
  printf '## A. Build and device\n\n'
  printf '| Field | Value |\n| --- | --- |\n'
  printf '| Source commit | `%s` |\n' "$SHA"
  [ -n "$RUN_ID" ] && printf '| Operator workflow run | https://github.com/%s/actions/runs/%s |\n' "$REPO_SLUG" "$RUN_ID"
  printf '| Bundle and SHA-256 | `%s` / `%s` |\n' "$name" "$(shasum -a 256 "$BUNDLE" | awk '{print $1}')"
  while IFS='=' read -r k v; do printf '| %s | %s |\n' "$k" "$v"; done < "$EVIDENCE/host.txt"
  printf '\n## B. Rows\n\n| ID | What | Outcome | Evidence |\n| --- | --- | --- | --- |\n'
  if [ "$g301" = 0 ]; then
    row G3-01 "Package identity, architecture, clean install, trusted HTTPS, health, private listener" "PASS (automated)" "package.txt, install-progress.txt, verify/, listeners.txt, tls.txt"
  else
    row G3-01 "Package identity, architecture, clean install, trusted HTTPS, health, private listener" "FAIL" "automated-results.txt"
  fi
  if [ "$MAC_CHECK" = 1 ]; then
    row G3-02 "Real passkey enrollment and sign-in" "$(grep '^G3-02' "$RESULTS_FILE" | cut -d'|' -f2) on source checkout; installed-package passkey NOT RUN" "mac-check/"
    row G3-03 "Same-named learners on two campuses: access and uniform denial" "Covered by the mac-check items above (source checkout); installed package NOT RUN" "mac-check/"
  else
    row G3-02 "Real passkey enrollment and sign-in" "NOT RUN" "rerun with --mac-check"
    row G3-03 "Same-named learners on two campuses" "NOT RUN" "rerun with --mac-check"
  fi
  for r in "G3-04|Evidence, recommendation, approve/edit/reject, ledger" "G3-05|Plan stays NOT_REQUESTED; revoked teacher refused after restart" \
           "G3-06|Lost-device recovery with a second real passkey" "G3-07|Roster revoke, membership and account disable end live access" \
           "G3-08|Recovery plane independent of campus directory and backup admins"; do
    row "${r%%|*}" "${r#*|}" "NOT RUN" "operator step"
  done
  if grep -q '^G3-09.restart|PASS|' "$RESULTS_FILE"; then
    row G3-09 "Restart keeps state, revoked access stays revoked, DNS/TLS valid" "PARTIAL: restart health and volume preservation PASS; revoked-access and open-stream checks NOT RUN" "restart.txt, health-after-restart.json"
  else
    row G3-09 "Restart keeps state" "FAIL or NOT RUN" "restart.txt"
  fi
  row G3-10 "Encrypted backup and isolated restore rehearsal" "NOT RUN" "operator step"
  row G3-11 "Operator observation: safe failure, secret-free evidence" "Secret scan: see below" "this run"
  printf '\n## Still yours\n\n'
  printf -- '- Sign in as the administrator (password in the private credentials file) and run G3-04 to G3-08 and G3-10 on sample data, following docs/institutional/MAC_G3_CERTIFICATION_RUNBOOK.md.\n'
  printf -- '- Enroll a real passkey on the installed instance for the installed-package half of G3-02.\n'
  printf -- '- Review and sign section F of the record.\n'
} > "$EVIDENCE/G3-RECORD-DRAFT.md"

if secret_scan "$secrets_list" "$EVIDENCE"; then
  result G3-11.secret-scan PASS "no secret from this run appears in the evidence folder"
  printf '\nSecret scan: PASS. No value from this run appears in the evidence.\n' >> "$EVIDENCE/G3-RECORD-DRAFT.md"
else
  result G3-11.secret-scan FAIL "a secret appeared in evidence; the evidence was not packed"
  say "STOPPED: a secret was found in $EVIDENCE. It was not packed. Remove it before sharing anything."
  exit 3
fi

(cd "$EVIDENCE" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 shasum -a 256 > SHA256SUMS)
PACK="$WORK/bede-g3-evidence-$SHA-$STAMP.tar.gz"
tar -czf "$PACK" -C "$WORK" evidence
shasum -a 256 "$PACK" > "$PACK.sha256"

if [ "$TEARDOWN" = 1 ] && [ -s "$APP/.env" ]; then
  step "Stopping the instance (data volumes kept)"
  dc down > /dev/null 2>&1 || true
fi

step "Done: $overall"
cat "$RESULTS_FILE" | awk -F'|' '{printf "  %-7s %s: %s\n", $2, $1, $3}'
say ""
say "Evidence pack:      $PACK"
say "Its checksum:       $PACK.sha256"
say "Record draft:       $EVIDENCE/G3-RECORD-DRAFT.md"
say "Private (do not share): $PRIVATE (administrator password, PIN, install log)"
say "Bede is running at https://localhost for the remaining operator steps."
case "$overall" in PASS) exit 0 ;; BLOCKED) exit 2 ;; *) exit 1 ;; esac
