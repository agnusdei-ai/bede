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
# Guided owner session (Homeschool or Campus DMG, read-only preflight first):
#   bash collect-g3-evidence.sh --session --candidate SHA --dmg PATH --license-file PATH ...
#   (bash collect-g3-evidence.sh --session --help for every option)
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
#   --local-model NAME    the model that server serves, written as LOCAL_LLM_MODEL;
#                         default: the one model this Mac's Ollama lists (refuses
#                         to guess when it lists several or none)
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

# ── Guided Mac acceptance session (--session) ─────────────────────────────────
#
#   bash collect-g3-evidence.sh --session --candidate SHA --dmg PATH \
#        --license-file PATH [--context homeschool|campus] [--model NAME] \
#        [--voice none|openai --openai-project ID --voice-max-usd N] \
#        [--approve-downloads] [--approve-voice] [--go] [--site] \
#        [--screenshots] [--work DIR] [--retest STEP]
#
# Without --go it only runs the read-only preflight. It installs, downloads,
# starts and stops nothing and never runs a model: it reads this Mac, checks
# the DMG against its .sha256, mounts it read-only to read RELEASE, ARCH and
# IMAGE_DIGESTS, checks the licence signature against the candidate's own
# public key, and fetches registry metadata (sizes and digests, never image
# or model data). It then lists what each later step will do and what is
# still unapproved, and stops on anything unresolved.
#
# With --go and nothing unresolved, it walks the owner through the physical
# steps. Each step: what to do, Enter when done, the collector's own checks
# (AUTOMATED rows), then the owner's answer to what was seen or heard (OWNER
# rows). An owner answer is never recorded as an automated result.
#
# Evidence goes to --work (default ~/Bede-Acceptance/<candidate>) with
# owner-only permissions and is never uploaded, emailed or committed.
# results.tsv is append-only: a retest adds an attempt and never erases the
# one before. A different candidate or DMG in the same folder keeps the host
# facts and reruns everything else.
#
# Never collected: the licence key, API keys, cookies, authentication headers,
# any .env file, learner records, or full logs (only counts of error lines).
# Screenshots only with --screenshots, one at a time, previewed, kept on yes.

SESSION_RESULTS=""; SESS_CANDIDATE=""; SESS_DMG_SHA=""

# Appends one row: utc, attempt, candidate, dmg digest, step, kind, result, note.
sess_rec() {
  local id="$1" kind="$2" res="$3" note="$4" n
  n=$(awk -F'\t' -v c="$SESS_CANDIDATE" -v d="$SESS_DMG_SHA" -v i="$id" -v k="$kind" \
      '$3==c && $4==d && $5==i && $6==k {n++} END {print n+1}' "$SESSION_RESULTS" 2>/dev/null || echo 1)
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(utc)" "$n" "$SESS_CANDIDATE" "$SESS_DMG_SHA" \
    "$id" "$kind" "$res" "$(printf '%s' "$note" | tr '\t\n' '  ')" >> "$SESSION_RESULTS"
  printf '  %-8s %-9s %s: %s\n' "$res" "$kind" "$id" "$note"
}

# The latest result of a step for the current candidate and DMG, or empty.
sess_last() {
  awk -F'\t' -v c="$SESS_CANDIDATE" -v d="$SESS_DMG_SHA" -v i="$1" -v k="$2" \
    '$3==c && $4==d && $5==i && $6==k {r=$7} END {print r}' "$SESSION_RESULTS" 2>/dev/null
}

# Which earlier results no longer count once the candidate or DMG changes.
sess_stale_report() {
  awk -F'\t' -v c="$SESS_CANDIDATE" -v d="$SESS_DMG_SHA" \
    '($3!=c || $4!=d) && $5!="host" {print $5}' "$SESSION_RESULTS" 2>/dev/null | sort -u
}

# Verifies an Ed25519 licence against the PEM public key in a source file.
# Prints tier, issued, expires, location_id, verified on separate lines.
# Exit 0 verified, 1 not verified, 2 cannot check (no usable python3).
sess_license_check() {
  local key="$1" source_file="$2" py=""
  for c in python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then py="$c"; break; fi
  done
  [ -n "$py" ] || return 2
  LICENSE_KEY_IN="$key" "$py" - "$source_file" <<'PY'
import base64, hashlib, json, os, re, sys

def b64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

# RFC 8032 Ed25519 verification, standard library only.
p = 2**255 - 19
q = 2**252 + 27742317777372353535851937790883648493
d = -121665 * pow(121666, p - 2, p) % p
I = pow(2, (p - 1) // 4, p)
def inv(x): return pow(x, p - 2, p)
def xrecover(y):
    xx = (y * y - 1) * inv(d * y * y + 1)
    x = pow(xx, (p + 3) // 8, p)
    if (x * x - xx) % p: x = x * I % p
    if (x * x - xx) % p: raise ValueError("not a point")
    return x
def add(P, Q):
    (x1, y1), (x2, y2) = P, Q
    t = d * x1 * x2 * y1 * y2
    return ((x1 * y2 + x2 * y1) * inv(1 + t) % p, (y1 * y2 + x1 * x2) * inv(1 - t) % p)
def mul(P, e):
    R = (0, 1)
    while e:
        if e & 1: R = add(R, P)
        P = add(P, P); e >>= 1
    return R
def decode(s):
    y = int.from_bytes(s, "little") & ((1 << 255) - 1)
    x = xrecover(y)
    if (x & 1) != (s[31] >> 7): x = p - x
    return (x, y)
By = 4 * inv(5) % p
Bx = xrecover(By)
B = (p - Bx if Bx & 1 else Bx, By)  # the base point's x is the even root
def verify(pub, msg, sig):
    if len(sig) != 64 or len(pub) != 32: return False
    try:
        A = decode(pub); R = decode(sig[:32])
    except ValueError:
        return False
    S = int.from_bytes(sig[32:], "little")
    if S >= q: return False
    h = int.from_bytes(hashlib.sha512(sig[:32] + pub + msg).digest(), "little") % q
    return mul(B, S) == add(R, mul(A, h))

src = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r"-----BEGIN PUBLIC KEY-----\s*([A-Za-z0-9+/=\s]+?)\s*-----END PUBLIC KEY-----", src)
key = os.environ["LICENSE_KEY_IN"].strip()
parts = key.split(".")
try:
    payload = json.loads(b64(parts[0]))
except Exception:
    payload = {}
for f in ("tier", "issued", "expires", "location_id"):
    print(f"{f}={payload.get(f, '')}")
ok = False
if m and len(parts) == 2:
    der = base64.b64decode("".join(m.group(1).split()))
    try:
        ok = verify(der[-32:], b64(parts[0]), b64(parts[1]))
    except Exception:
        ok = False
print(f"verified={'yes' if ok else 'no'}")
sys.exit(0 if ok else 1)
PY
}

# The pull reference for one IMAGE_DIGESTS line ("name[:tag] sha256:...").
sess_image_ref() {
  local name="${1%% *}" digest="${1##* }" last
  last="${name##*/}"
  case "$last" in *:*) name="${name%:*}" ;; esac
  printf '%s@%s' "$name" "$digest"
}

# Sum of the layer sizes in a registry manifest, or "unknown". Metadata only.
sess_manifest_bytes() {
  docker manifest inspect -v "$1" 2>/dev/null \
    | grep -oE '"size": *[0-9]+' | awk -F: '{s+=$2} END {if (s>0) print s; else print "unknown"}' || echo unknown
}

# Asks the owner. Prints PASS, FAIL or NOT RUN. Never answers on its own.
sess_ask() {
  local q="$1" a
  while :; do
    printf '%s [y = yes, n = no, s = not done] ' "$q" > /dev/tty
    read -r a < /dev/tty || a=s
    case "$a" in y|Y) echo PASS; return ;; n|N) echo FAIL; return ;; s|S) echo "NOT RUN"; return ;; esac
  done
}

sess_wait() {
  printf '\nNext: %s\nWhat you do:\n%s\nPress Enter when done (or type s to skip this step). ' "$1" "$2" > /dev/tty
  local a; read -r a < /dev/tty || a=s
  [ "$a" != s ] && [ "$a" != S ]
}

# One screenshot, only with consent, previewed before it is kept.
sess_screenshot() {
  [ "$SESS_SHOTS" = 1 ] || return 0
  local f="$SESS_EVIDENCE/screenshot-$1-$(date -u +%H%M%S).png" a
  printf 'Take a screenshot for this step? It selects an area you choose. [y/N] ' > /dev/tty
  read -r a < /dev/tty || a=n
  case "$a" in y|Y) ;; *) return 0 ;; esac
  screencapture -i -x "$f" 2>/dev/null || return 0
  [ -s "$f" ] || return 0
  open -a Preview "$f" 2>/dev/null || true
  printf 'Keep this screenshot in the evidence? It must show no real names. [y/N] ' > /dev/tty
  read -r a < /dev/tty || a=n
  case "$a" in y|Y) chmod 600 "$f"; sess_rec "$1" OWNER PASS "screenshot kept: ${f##*/}" >/dev/null ;; *) rm -f "$f" ;; esac
}

sess_curl() { curl -sS --max-time 10 --cacert "$SESS_APP/bede-root-ca.crt" "$@"; }

session_main() {
  local CANDIDATE="" DMG="" LICENSE_FILE="" CONTEXT="homeschool" CAMPUS_ID="" MODEL=""
  local VOICE="" OPENAI_PROJECT="" VOICE_MAX="" APPROVE_DL=0 APPROVE_VOICE=0 GO=0 SITE=0 RETEST=""
  SESS_SHOTS=0
  local WORKDIR=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --candidate) CANDIDATE="$2"; shift 2 ;;
      --dmg) DMG="$2"; shift 2 ;;
      --license-file) LICENSE_FILE="$2"; shift 2 ;;
      --context) CONTEXT="$2"; shift 2 ;;
      --campus-id) CAMPUS_ID="$2"; shift 2 ;;
      --model) MODEL="$2"; shift 2 ;;
      --voice) VOICE="$2"; shift 2 ;;
      --openai-project) OPENAI_PROJECT="$2"; shift 2 ;;
      --voice-max-usd) VOICE_MAX="$2"; shift 2 ;;
      --approve-downloads) APPROVE_DL=1; shift ;;
      --approve-voice) APPROVE_VOICE=1; shift ;;
      --go) GO=1; shift ;;
      --site) SITE=1; shift ;;
      --screenshots) SESS_SHOTS=1; shift ;;
      --work) WORKDIR="$2"; shift 2 ;;
      --retest) RETEST="$2"; shift 2 ;;
      -h|--help) sed -n '/^# ── Guided Mac acceptance session/,/^# Screenshots only/p' "$0" | sed 's/^# \{0,1\}//'; return 0 ;;
      *) die "unknown option: $1 (see --session --help)" ;;
    esac
  done
  [ "$(uname -s)" = "Darwin" ] || die "run this on the Mac being accepted"
  printf '%s' "$CANDIDATE" | grep -Eq '^[0-9a-f]{40}$' || die "--candidate must be the full 40-character commit"
  case "$CONTEXT" in homeschool|campus) ;; *) die "--context is homeschool or campus" ;; esac

  WORKDIR="${WORKDIR:-$HOME/Bede-Acceptance/$CANDIDATE}"
  SESS_EVIDENCE="$WORKDIR/evidence"
  mkdir -p "$SESS_EVIDENCE"; chmod 700 "$WORKDIR" "$SESS_EVIDENCE"
  SESSION_RESULTS="$SESS_EVIDENCE/results.tsv"; touch "$SESSION_RESULTS"; chmod 600 "$SESSION_RESULTS"
  SESS_CANDIDATE="$CANDIDATE"
  if [ "$CONTEXT" = campus ]; then
    SESS_APP="$HOME/Library/Application Support/Bede/Campus/${CAMPUS_ID:-unset}/bede-operator"
  else
    SESS_APP="$HOME/Library/Application Support/Bede/Homeschool/local/bede-operator"
  fi
  local blocked=0 plan="$SESS_EVIDENCE/plan.txt"; : > "$plan"
  block() { blocked=1; printf 'STOP  %s\n' "$*" | tee -a "$plan"; }

  say "Bede acceptance session for candidate $CANDIDATE"
  say "Evidence folder (private, stays on this Mac): $WORKDIR"

  # ── Preflight: read-only ──
  step "Checking this Mac (read-only)"
  {
    printf 'captured_utc=%s\n' "$(utc)"
    printf 'model=%s\nchip=%s\ncpu_arch=%s\nmemory_bytes=%s\n' "$(sysctl -n hw.model 2>/dev/null)" \
      "$(sysctl -n machdep.cpu.brand_string 2>/dev/null)" "$(uname -m)" "$(sysctl -n hw.memsize 2>/dev/null)"
    printf 'macos=%s (%s)\n' "$(sw_vers -productVersion)" "$(sw_vers -buildVersion)"
    printf 'disk_root=%s\n' "$(df -h / | awk 'NR==2 {print $4" free"}')"
    printf 'docker_desktop=%s\n' "$(defaults read /Applications/Docker.app/Contents/Info CFBundleShortVersionString 2>/dev/null || echo 'not installed')"
    printf 'docker_running=%s\n' "$(docker info >/dev/null 2>&1 && echo yes || echo no)"
    printf 'ollama=%s\n' "$( (command -v ollama >/dev/null 2>&1 && ollama --version 2>/dev/null | tail -n1) || echo 'not installed')"
    printf 'existing_bede_install=%s\n' "$([ -d "$SESS_APP" ] && echo yes || echo no)"
    printf 'serial_number=not recorded by design\n'
  } > "$SESS_EVIDENCE/host.txt"
  SESS_DMG_SHA="none"; sess_rec host AUTOMATED PASS "host facts recorded"
  local stale; stale="$(sess_stale_report)"
  if [ -n "$stale" ]; then
    say "Results from an earlier candidate or DMG are kept but no longer count:"
    printf '  %s\n' $stale
  fi
  [ -d "$SESS_APP" ] && printf 'PREVIOUS INSTALL present at %s: the upgrade step applies.\n' "$SESS_APP" >> "$plan"
  grep -q 'docker_desktop=not installed' "$SESS_EVIDENCE/host.txt" && block "Docker Desktop is not installed. Installing it is yours to approve and do (docker.com); it is not done here."
  grep -q 'docker_running=no' "$SESS_EVIDENCE/host.txt" && block "Start Docker Desktop, then run this again."

  step "Checking the installer (read-only)"
  if [ -z "$DMG" ] || [ ! -s "$DMG" ]; then
    block "Give the downloaded Bede-Engineering-Mac-arm64.dmg with --dmg (from the candidate's operator-bundle run)."
  elif [ ! -s "$DMG.sha256" ]; then
    block "The DMG's .sha256 file must sit beside it ($DMG.sha256)."
  else
    SESS_DMG_SHA="$(shasum -a 256 "$DMG" | awk '{print $1}')"
    if (cd "$(dirname "$DMG")" && shasum -a 256 -c "$(basename "$DMG").sha256" >/dev/null 2>&1); then
      sess_rec artifact AUTOMATED PASS "DMG SHA-256 $SESS_DMG_SHA matches its .sha256 file"
    else
      sess_rec artifact AUTOMATED FAIL "DMG SHA-256 $SESS_DMG_SHA does not match its .sha256 file"
      block "The DMG does not match its checksum. Download it again; do not open it."
    fi
    local mnt="$WORKDIR/mnt"; mkdir -p "$mnt"
    if hdiutil attach -readonly -nobrowse -noautoopen -mountpoint "$mnt" "$DMG" >/dev/null 2>&1; then
      local res="$mnt/Bede Installer.app/Contents/Resources/bede-operator"
      local rel arch; rel="$(cat "$res/RELEASE" 2>/dev/null || true)"; arch="$(cat "$res/ARCH" 2>/dev/null || true)"
      cp "$res/IMAGE_DIGESTS" "$SESS_EVIDENCE/IMAGE_DIGESTS" 2>/dev/null || true
      hdiutil detach "$mnt" >/dev/null 2>&1 || true
      if [ "$rel" = "$CANDIDATE" ]; then sess_rec artifact-release AUTOMATED PASS "DMG RELEASE is the candidate"
      else sess_rec artifact-release AUTOMATED FAIL "DMG RELEASE is ${rel:-missing}, not the candidate"; block "This DMG was built from a different commit."; fi
      local want; case "$(uname -m)" in arm64) want=arm64 ;; *) want=amd64 ;; esac
      if [ "$arch" = "$want" ]; then sess_rec artifact-arch AUTOMATED PASS "DMG is $arch, this Mac is $want"
      else sess_rec artifact-arch AUTOMATED FAIL "DMG is ${arch:-unknown}, this Mac is $want"; block "Wrong DMG for this Mac's processor."; fi
    else
      block "The DMG could not be mounted read-only to read its release files."
    fi
  fi

  step "Checking the licence (read-only; the key itself is never stored)"
  local src="$WORKDIR/licensing-$CANDIDATE.py"
  if [ -z "$LICENSE_FILE" ] || [ ! -s "$LICENSE_FILE" ]; then
    block "Give the licence file with --license-file. Licence issuance is outside this session."
  else
    [ -s "$src" ] || curl -fsS --max-time 20 -o "$src" \
      "https://raw.githubusercontent.com/$REPO_SLUG/$CANDIDATE/homeschool-api/core/licensing.py" 2>/dev/null || rm -f "$src"
    if [ ! -s "$src" ]; then
      block "Could not read the candidate's public licence key (public source at this commit)."
    else
      local out rc=0; out="$(sess_license_check "$(read_license_key "$LICENSE_FILE")" "$src")" || rc=$?
      local tier expires location
      tier="$(printf '%s\n' "$out" | sed -n 's/^tier=//p' || true)"; expires="$(printf '%s\n' "$out" | sed -n 's/^expires=//p' || true)"
      location="$(printf '%s\n' "$out" | sed -n 's/^location_id=//p' || true)"
      if [ "$rc" = 2 ]; then
        sess_rec licence AUTOMATED "NOT RUN" "no Python 3.8+ here to check the signature"
        block "Install Python 3 (Apple's command-line tools or Homebrew) to check the licence; that install is yours to approve."
      elif [ "$rc" != 0 ]; then
        sess_rec licence AUTOMATED FAIL "signature does not verify against the candidate's key (tier ${tier:-?})"
        block "This licence was not signed for this candidate's key, so Bede would start locked. A key signed for it is needed."
      else
        sess_rec licence AUTOMATED PASS "signature verifies against the candidate's key; tier $tier; expires ${expires:-never}"
        if [ -n "$expires" ] && [ "$expires" \< "$(date -u +%Y-%m-%d)" ]; then
          sess_rec licence-expiry AUTOMATED FAIL "expired on $expires"; block "The licence has expired."
        else
          sess_rec licence-expiry AUTOMATED PASS "valid until ${expires:-no expiry}"
        fi
        if [ "$CONTEXT" = campus ]; then
          if [ "$tier" = campus_location ] && [ "$location" = "$CAMPUS_ID" ]; then sess_rec licence-context AUTOMATED PASS "campus licence for $CAMPUS_ID"
          else sess_rec licence-context AUTOMATED FAIL "not a campus licence for ${CAMPUS_ID:-unset}"; block "The licence does not match the Campus context and --campus-id."; fi
        else
          if [ "$tier" != campus_location ]; then sess_rec licence-context AUTOMATED PASS "$tier licence suits Homeschool"
          else sess_rec licence-context AUTOMATED FAIL "a campus licence cannot run Homeschool"; block "Use --context campus --campus-id $location, or a family or trial licence."; fi
        fi
      fi
    fi
  fi

  step "Checking what would be downloaded (registry metadata only)"
  local missing=0 line ref bytes
  if [ -s "$SESS_EVIDENCE/IMAGE_DIGESTS" ] && docker info >/dev/null 2>&1; then
    : > "$SESS_EVIDENCE/downloads.txt"
    while IFS= read -r line; do
      [ -n "$line" ] || continue
      ref="$(sess_image_ref "$line")"
      if docker image inspect "$ref" >/dev/null 2>&1; then
        printf 'present  %s\n' "$ref" >> "$SESS_EVIDENCE/downloads.txt"
      else
        bytes="$(sess_manifest_bytes "$ref" || echo unknown)"; missing=$((missing + 1))
        if [ "$bytes" = unknown ]; then
          printf 'missing  %s  size=unknown (the registry did not answer: offline, or it needs a sign-in the install step would also need)\n' "$ref" >> "$SESS_EVIDENCE/downloads.txt"
        else
          printf 'missing  %s  compressed_bytes=%s\n' "$ref" "$bytes" >> "$SESS_EVIDENCE/downloads.txt"
        fi
      fi
    done < "$SESS_EVIDENCE/IMAGE_DIGESTS"
  fi
  if [ -z "$MODEL" ]; then
    local mem; mem="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
    if [ "$mem" -ge 17179869184 ]; then MODEL="ministral-3:3b"; else MODEL="granite3.3:2b"; fi
  fi
  if curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags 2>/dev/null | grep -q "\"name\":\"$MODEL\""; then
    printf 'present  ollama model %s\n' "$MODEL" >> "$SESS_EVIDENCE/downloads.txt"
  else
    missing=$((missing + 1))
    local mname="${MODEL%%:*}" mtag="${MODEL##*:}" man
    [ "$mtag" = "$MODEL" ] && mtag=latest
    man="$(curl -fsS --max-time 15 -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
      "https://registry.ollama.ai/v2/library/$mname/manifests/$mtag" 2>/dev/null || true)"
    bytes="$(printf '%s' "$man" | grep -oE '"size": *[0-9]+' | awk -F: '{s+=$2} END {print (s>0 ? s : "unknown")}' || true)"
    local mdigest=unknown
    [ -n "$man" ] && mdigest="sha256:$(printf '%s' "$man" | shasum -a 256 | awk '{print $1}')"
    printf 'missing  ollama model %s  source=registry.ollama.ai  bytes=%s  manifest=%s\n' "$MODEL" "$bytes" "$mdigest" \
      >> "$SESS_EVIDENCE/downloads.txt"
    if ! command -v ollama >/dev/null 2>&1; then
      missing=$((missing + 1))
      printf 'missing  Ollama app (from ollama.com; you install it and its version is recorded after)\n' >> "$SESS_EVIDENCE/downloads.txt"
    fi
  fi
  if [ -s "$SESS_EVIDENCE/downloads.txt" ]; then cat "$SESS_EVIDENCE/downloads.txt"; fi
  if [ "$missing" -gt 0 ] && [ "$APPROVE_DL" != 1 ]; then
    block "$missing download(s) listed above need your approval: rerun with --approve-downloads. Nothing is downloaded by this script."
  elif [ "$missing" -gt 0 ]; then
    sess_rec downloads OWNER PASS "owner approved the $missing listed download(s) for this candidate"
  fi

  step "Checking the voice plan"
  if [ "$VOICE" = none ]; then
    sess_rec voice OWNER "NOT RUN" "owner chose text-first for this session; no paid speech requests"
  elif [ "$VOICE" = openai ]; then
    local cfg="$WORKDIR/config-$CANDIDATE.py" tmodel tvoice
    [ -s "$cfg" ] || curl -fsS --max-time 20 -o "$cfg" \
      "https://raw.githubusercontent.com/$REPO_SLUG/$CANDIDATE/homeschool-api/core/config.py" 2>/dev/null || rm -f "$cfg"
    tmodel="$(sed -n 's/^ *openai_tts_model: str = "\(.*\)"/\1/p' "$cfg" 2>/dev/null || true)"
    tvoice="$(sed -n 's/^ *openai_tts_voice: str = "\(.*\)"/\1/p' "$cfg" 2>/dev/null || true)"
    {
      printf 'Reference voice: OpenAI %s, voice "%s" (the candidate'"'"'s defaults).\n' "${tmodel:-unknown}" "${tvoice:-unknown}"
      printf 'Account/project: %s (identifier only; the key is typed into Bede'"'"'s setup, never here).\n' "${OPENAI_PROJECT:-not given}"
      printf 'Fixed phrase: the first spoken line of one Number Time "Watch" step, shown on screen.\n'
      printf 'Requests: at most 8 (one Watch step; the app retries a failed line once, on your next tap).\n'
      printf 'Estimated cost: under US$0.03 at about US$0.015 per minute of speech; check OpenAI'"'"'s current price.\n'
      printf 'Ceiling you set: US$%s. Narration stays muted for the rest of the session.\n' "${VOICE_MAX:-not set}"
    } | tee "$SESS_EVIDENCE/voice-plan.txt"
    if [ -z "$OPENAI_PROJECT" ] || [ -z "$VOICE_MAX" ] || [ "$APPROVE_VOICE" != 1 ]; then
      block "The paid voice check needs --openai-project, --voice-max-usd and --approve-voice."
    fi
  else
    block "Choose the voice: --voice none (text-first, no paid calls) or --voice openai (paid, see the plan it prints)."
  fi

  {
    printf '\nWhat happens next, with --go:\n'
    printf '  1 install   You open the DMG and finish setup; the collector checks the release, images, HTTPS and listeners.\n'
    printf '  2 licence   The collector checks Bede is unlocked (no sign-in needed).\n'
    printf '  3 learner   You add "Sample Learner", grade 1.\n'
    printf '  4 lesson    The learner does two Mathematics turns and one Number Time round; the collector counts error lines.\n'
    if [ "$VOICE" = openai ]; then printf '  5 voice     You unmute for one Watch step and listen; only you can pass it.\n'; fi
    printf '  6 progress  You check the round and the work on the Progress page.\n'
    printf '  7 restart   You quit and reopen Bede; the collector checks health and data volumes.\n'
    printf '  8 upgrade   Only if an earlier Bede was installed here.\n'
    if [ "$SITE" = 1 ]; then printf '  9 site      You check the public pages from the list it shows.\n'; fi
  } | tee -a "$plan"

  if [ "$blocked" = 1 ]; then
    say ""; say "STOPPED before anything changed. Resolve the STOP lines, then run the same command again."
    sess_finish; return 2
  fi
  if [ "$GO" != 1 ]; then
    say ""; say "Preflight complete; nothing was changed. Add --go to start the session."
    sess_finish; return 0
  fi

  # ── Physical steps ──
  local s r
  run_step() {
    s="$1"
    if [ -n "$(sess_last "$s" OWNER)" ] && [ "$(sess_last "$s" OWNER)" = PASS ] && [ "$RETEST" != "$s" ]; then
      say "  (step $s already passed for this candidate; --retest $s to repeat it)"; return 1
    fi
    return 0
  }
  fail_stop() {
    say ""; say "Stopped at $1. Everything so far is kept in $WORKDIR."
    say "After the fix, rerun with --work \"$WORKDIR\" --retest $1. The failed attempt stays in the record."
    sess_finish; exit 1
  }

  if run_step install; then
    if sess_wait "Install Bede" "  - Open the DMG. Control-click Bede Installer.app, choose Open.
  - Choose $( [ "$CONTEXT" = campus ] && echo "Campus ($CAMPUS_ID)" || echo Homeschool ).
  - In the browser setup: accept the notice, set the adult password, keep the suggested child PIN,
    choose Local (Ollama) with $MODEL, set the voice as planned, paste the licence."; then
      if [ "$(cat "$SESS_APP/RELEASE" 2>/dev/null)" = "$CANDIDATE" ]; then sess_rec install AUTOMATED PASS "installed RELEASE is the candidate"
      else sess_rec install AUTOMATED FAIL "installed RELEASE is $(cat "$SESS_APP/RELEASE" 2>/dev/null || echo missing)"; fi
      if sess_curl -o /dev/null -w '%{http_code}' https://localhost/api/health 2>/dev/null | grep -q 200; then
        sess_rec install-https AUTOMATED PASS "https://localhost/api/health answers, verified against this install's CA"
      else sess_rec install-https AUTOMATED FAIL "health did not answer over verified HTTPS"; fi
      lsof -nP -iTCP:443 -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $9}' | sort -u > "$SESS_EVIDENCE/listeners.txt"
      if [ -s "$SESS_EVIDENCE/listeners.txt" ] && ! grep -vqE '^(127\.0\.0\.1|\[::1\]):443$' "$SESS_EVIDENCE/listeners.txt"; then
        sess_rec install-listen AUTOMATED PASS "port 443 listens on loopback only"
      else sess_rec install-listen AUTOMATED FAIL "port 443 listeners: $(tr '\n' ' ' < "$SESS_EVIDENCE/listeners.txt")"; fi
      docker ps --format '{{.Image}} {{.Status}}' > "$SESS_EVIDENCE/containers.txt" 2>/dev/null || true
      r="$(sess_ask "Did setup finish and say Bede is ready?")"; sess_rec install OWNER "$r" "owner: setup finished"
      sess_screenshot install
      [ "$r" = FAIL ] || [ "$(sess_last install AUTOMATED)" = FAIL ] || [ "$(sess_last install-https AUTOMATED)" = FAIL ] && fail_stop install
    else sess_rec install OWNER "NOT RUN" "skipped"; fi
  fi

  if run_step licence-unlocked; then
    local code; code="$(sess_curl -o /dev/null -w '%{http_code}' https://localhost/api/pod/configs 2>/dev/null || true)"
    case "$code" in
      401) sess_rec licence-unlocked AUTOMATED PASS "Bede is unlocked (sign-in required, no licence refusal)" ;;
      403) sess_rec licence-unlocked AUTOMATED FAIL "Bede refuses with license_required"; fail_stop licence-unlocked ;;
      *) sess_rec licence-unlocked AUTOMATED FAIL "unexpected answer $code"; fail_stop licence-unlocked ;;
    esac
  fi

  if run_step learner; then
    if sess_wait "Add a sample learner" "  - Sign in as the adult. Add a learner named \"Sample Learner\", grade 1. Save. No real names."; then
      r="$(sess_ask "Was Sample Learner saved?")"; sess_rec learner OWNER "$r" "owner: sample learner saved"
      sess_screenshot learner; [ "$r" = FAIL ] && fail_stop learner
    else sess_rec learner OWNER "NOT RUN" "skipped"; fi
  fi

  if run_step lesson; then
    local since; since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if sess_wait "First lesson" "  - Open Sample Learner on this Mac and sign in with the child PIN.
  - Keep narration muted. Start Mathematics, answer two turns, then finish one Number Time round."; then
      local api errs; api="$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '_api(-|_)1$|-api-1$' | head -n1 || true)"
      if [ -n "$api" ]; then
        errs="$(docker logs --since "$since" "$api" 2>&1 | grep -cE 'Traceback|ai_backend_failure|AI_BACKEND_FAILURE' || true)"
        if [ "${errs:-0}" = 0 ]; then sess_rec lesson AUTOMATED PASS "no backend error lines during the lesson"
        else sess_rec lesson AUTOMATED FAIL "$errs backend error line(s) during the lesson (counted, not copied)"; fi
      else sess_rec lesson AUTOMATED "NOT RUN" "API container not found"; fi
      r="$(sess_ask "Did Bede answer both turns and did the round finish?")"; sess_rec lesson OWNER "$r" "owner: lesson and round completed"
      sess_screenshot lesson; [ "$r" = FAIL ] && fail_stop lesson
    else sess_rec lesson OWNER "NOT RUN" "skipped"; fi
  fi

  if [ "$VOICE" = openai ] && run_step voice; then
    if sess_wait "Reference voice (paid, ceiling US\$$VOICE_MAX)" "  - Start one Number Time round. Unmute for its Watch step only, listen to the first line, then mute again."; then
      r="$(sess_ask "Did you hear Bede's voice read the line on screen clearly?")"
      sess_rec voice OWNER "$r" "owner listening check; model and plan in voice-plan.txt"
      [ "$r" = FAIL ] && fail_stop voice
    else sess_rec voice OWNER "NOT RUN" "skipped"; fi
  fi

  if run_step progress; then
    if sess_wait "Saved progress" "  - As the adult, open Progress for Sample Learner."; then
      r="$(sess_ask "Do the round and the lesson's work appear?")"; sess_rec progress OWNER "$r" "owner: progress shown"
      sess_screenshot progress; [ "$r" = FAIL ] && fail_stop progress
    else sess_rec progress OWNER "NOT RUN" "skipped"; fi
  fi

  if run_step restart; then
    docker volume ls --format '{{.Name}}' | grep -i bede | sort > "$SESS_EVIDENCE/volumes-before.txt" 2>/dev/null || true
    if sess_wait "Restart" "  - Quit Bede and Docker Desktop (or restart the Mac). Open Docker Desktop, then Bede, and sign in."; then
      docker volume ls --format '{{.Name}}' | grep -i bede | sort > "$SESS_EVIDENCE/volumes-after.txt" 2>/dev/null || true
      if cmp -s "$SESS_EVIDENCE/volumes-before.txt" "$SESS_EVIDENCE/volumes-after.txt" && [ -s "$SESS_EVIDENCE/volumes-after.txt" ]; then
        sess_rec restart AUTOMATED PASS "same data volumes before and after"
      else sess_rec restart AUTOMATED FAIL "data volumes changed across the restart"; fi
      if sess_curl -o /dev/null -w '%{http_code}' https://localhost/api/health 2>/dev/null | grep -q 200; then
        sess_rec restart-https AUTOMATED PASS "health answers after restart"
      else sess_rec restart-https AUTOMATED FAIL "health did not answer after restart"; fi
      r="$(sess_ask "After the restart, are Sample Learner, the settings and Progress still there?")"
      sess_rec restart OWNER "$r" "owner: state kept across restart"
      [ "$r" = FAIL ] || [ "$(sess_last restart AUTOMATED)" = FAIL ] && fail_stop restart
    else sess_rec restart OWNER "NOT RUN" "skipped"; fi
  fi

  if grep -q 'existing_bede_install=yes' "$SESS_EVIDENCE/host.txt"; then
    if run_step upgrade && sess_wait "Upgrade over the earlier install" "  - This Mac had Bede before. Note whether the installer refused the cross-version upgrade or kept your earlier data."; then
      r="$(sess_ask "Did the installer refuse the upgrade (or keep the earlier data) rather than overwrite it?")"
      sess_rec upgrade OWNER "$r" "owner: upgrade behaviour over an earlier install"
    fi
  else
    sess_rec upgrade OWNER "NOT RUN" "first install on this Mac; nothing to upgrade or roll back"
  fi

  if [ "$SITE" = 1 ]; then
    local item
    for item in \
      "site-home|https://agnusdei.ai/ : desktop and narrow window both lay out cleanly; the menu links work; the release banner shows" \
      "site-homeschool|https://agnusdei.ai/homeschool/ : loads; the Sound Time, Number Time and Map Practice links work; nothing is cut off" \
      "site-faq|https://agnusdei.ai/faq/ : sections open and close; Print FAQ opens the print preview; Cancel returns with the same sections open" \
      "site-demo-print|https://agnusdei.ai/bede/ : grade 2, Number Time to the end, Print or save as PDF: one sheet, pictures drawn, plates of counters, nothing cut off" \
      "site-privacy|https://agnusdei.ai/privacy/ : loads; its beta dates match the home page and the FAQ"; do
      if sess_wait "Public site: ${item%%|*}" "  - ${item#*|}"; then
        r="$(sess_ask "Was it as described?")"; sess_rec "${item%%|*}" OWNER "$r" "${item#*|}"
        sess_screenshot "${item%%|*}"
      else sess_rec "${item%%|*}" OWNER "NOT RUN" "skipped"; fi
    done
  fi

  sess_finish
  say ""; say "Session complete. Copy SUMMARY.md's table into the release packet when you choose."
}

# Writes SUMMARY.md and SHA256SUMS, checks for secrets, and locks permissions.
sess_finish() {
  local sum="$SESS_EVIDENCE/SUMMARY.md"
  {
    printf '# Bede acceptance session\n\nCandidate `%s`, DMG SHA-256 `%s`.\n\n' "$SESS_CANDIDATE" "$SESS_DMG_SHA"
    printf 'Latest result of each step for this candidate and DMG. Every attempt is in results.tsv.\n\n'
    printf '| Step | Checked by | Result | Attempt | Note |\n| --- | --- | --- | --- | --- |\n'
    awk -F'\t' -v c="$SESS_CANDIDATE" -v d="$SESS_DMG_SHA" '
      ($3==c && ($4==d || $5=="host")) { k=$5"|"$6; if (!(k in seen)) order[++n]=k; seen[k]=1; row[k]="| "$5" | "$6" | "$7" | "$2" | "$8" |" }
      END { for (i=1;i<=n;i++) print row[order[i]] }' "$SESSION_RESULTS"
    printf '\nOWNER rows are what the owner saw or heard; AUTOMATED rows are what the collector measured.\n'
  } > "$sum"
  local key=""
  [ -n "${LICENSE_FILE:-}" ] && [ -s "${LICENSE_FILE:-/nonexistent}" ] && key="$(read_license_key "$LICENSE_FILE")"
  if ! secret_scan "$key" "$SESS_EVIDENCE" || grep -rqE 'sk-[A-Za-z0-9_-]{20,}|LICENSE_KEY=|[Cc]ookie:|[Aa]uthorization:' "$SESS_EVIDENCE" 2>/dev/null; then
    say "STOPPED: something secret-looking is in $SESS_EVIDENCE. Remove it before sharing anything."
    return 3
  fi
  (cd "$SESS_EVIDENCE" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 shasum -a 256 > SHA256SUMS)
  chmod -R go-rwx "$(dirname "$SESS_EVIDENCE")"
  say "Summary: $sum"
}

# Stop here when sourced for tests.
if [ "${G3_LIB_ONLY:-}" = "1" ]; then return 0 2>/dev/null || exit 0; fi

# The guided owner session for one candidate DMG (see the section above).
if [ "${1:-}" = "--session" ]; then shift; session_main "$@"; exit $?; fi

# ── Arguments ─────────────────────────────────────────────────────────────────

LICENSE_FILE=""; RUN_ID=""; BUNDLE=""; ARCH=""; WORK=""; MAC_CHECK=0; TEARDOWN=0
LOCAL_MODEL_URL="http://host.docker.internal:11434/v1"
LOCAL_MODEL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --license-file) LICENSE_FILE="$2"; shift 2 ;;
    --run-id) RUN_ID="$2"; shift 2 ;;
    --bundle) BUNDLE="$2"; shift 2 ;;
    --arch) ARCH="$2"; shift 2 ;;
    --work) WORK="$2"; shift 2 ;;
    --local-model-url) LOCAL_MODEL_URL="$2"; shift 2 ;;
    --local-model) LOCAL_MODEL="$2"; shift 2 ;;
    --mac-check) MAC_CHECK=1; shift ;;
    --teardown) TEARDOWN=1; shift ;;
    -h|--help) sed -n '2,/^# Written for macOS/p' "$0"; exit 0 ;;
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
# The wizard requires a model name for a local choice (docs/DECISIONS.md
# entry 43). Without --local-model, use the one model Ollama lists; never guess.
if [ -z "$LOCAL_MODEL" ]; then
  LOCAL_MODEL="$(curl -fsS --max-time 3 "http://127.0.0.1:11434/api/tags" 2>/dev/null \
    | grep -oE '"name"[[:space:]]*:[[:space:]]*"[^"]*"' \
    | sed -E 's/^"name"[[:space:]]*:[[:space:]]*"([^"]*)"$/\1/' || true)"
  [ -n "$LOCAL_MODEL" ] && [ "$(printf '%s\n' "$LOCAL_MODEL" | wc -l | tr -d ' ')" = 1 ] \
    || die "pass --local-model NAME: this Mac's Ollama does not list exactly one model"
fi
curl -sS --max-time 20 -X POST "$WIZARD/submit" \
  --data-urlencode "provider=local" \
  --data-urlencode "local_base_url=$LOCAL_MODEL_URL" \
  --data-urlencode "local_model=$LOCAL_MODEL" \
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
  (cd "$SRC" && npm install -q --no-save playwright@1.63.0 > "$PRIVATE/npm.log" 2>&1 && npx -y playwright@1.63.0 install chromium >> "$PRIVATE/npm.log" 2>&1) \
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
