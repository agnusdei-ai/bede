#!/usr/bin/env bash
# Fixed-source Bede RC1 iPhone/iPad candidate, signed on the owner's Mac.
# Requires the personal Apple Account already added to Xcode.
# Never accepts Apple passwords or private signing keys as input.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" != 'Darwin' ]]; then
  echo 'ERROR: Apple iOS signing requires Xcode on macOS.' >&2
  exit 1
fi
for cmd in git node npm npx xcodebuild python3 codesign; do
  command -v "$cmd" >/dev/null || { echo "Missing required tool: $cmd" >&2; exit 1; }
done
if [[ ! "${BEDE_RC1_SOURCE_SHA:-}" =~ ^[0-9a-f]{40}$ ]]; then
  echo 'ERROR: Set BEDE_RC1_SOURCE_SHA to your approved 40-character source SHA.' >&2
  exit 1
fi
if [[ "$(git rev-parse HEAD)" != "$BEDE_RC1_SOURCE_SHA" ]]; then
  echo 'ERROR: Checkout differs from the immutable RC1 source SHA.' >&2
  exit 1
fi
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo 'ERROR: Build from a clean, approved RC1 checkout.' >&2
  exit 1
fi
if [[ -z "${BEDE_APPLE_TEAM_ID:-}" || -z "${BEDE_IOS_DEVICE_ID:-}" ]]; then
  echo 'ERROR: Supply BEDE_APPLE_TEAM_ID and BEDE_IOS_DEVICE_ID from Xcode.' >&2
  exit 1
fi

cd "$ROOT/homeschool-tutor"
npm ci
npm run build
npx cap sync ios

# Fail closed if someone reintroduces live web content or changes the bundle ID.
python3 - <<'PY'
import json
from pathlib import Path
config = json.loads(Path('ios/App/App/capacitor.config.json').read_text())
assert config['appId'] == 'ai.agnusdei.bede', 'wrong bundle ID'
assert not config.get('server', {}).get('url'), 'REMOTE FRONTEND FORBIDDEN IN RC1'
assert not config.get('server', {}).get('cleartext'), 'cleartext network forbidden'
assert Path('ios/App/App/public/index.html').is_file(), 'missing bundled frontend'
print('Local frontend and bundle ID verified')
PY

BUILD_ROOT="${BEDE_RC1_OUTPUT_DIR:-$HOME/Library/Developer/Bede/ios-rc1-${BEDE_RC1_SOURCE_SHA:0:12}}"
mkdir -p "$BUILD_ROOT"
# Development signing only: Xcode Personal Team is not Ad Hoc distribution.
xcodebuild \
  -project ios/App/App.xcodeproj \
  -scheme App \
  -configuration Release \
  -sdk iphoneos \
  -destination "id=$BEDE_IOS_DEVICE_ID" \
  -derivedDataPath "$BUILD_ROOT/DerivedData" \
  -allowProvisioningUpdates \
  DEVELOPMENT_TEAM="$BEDE_APPLE_TEAM_ID" \
  CODE_SIGN_STYLE=Automatic \
  MARKETING_VERSION=1.0.0 \
  CURRENT_PROJECT_VERSION=1 \
  build

APP_PATH="$BUILD_ROOT/DerivedData/Build/Products/Release-iphoneos/App.app"
test -d "$APP_PATH"
codesign --verify --deep --strict "$APP_PATH"
{
  printf 'source_sha=%s\n' "$BEDE_RC1_SOURCE_SHA"
  printf 'bundle_id=ai.agnusdei.bede\n'
  printf 'release_label=RC1\n'
  printf 'build_number=1\n'
  printf 'signing=personal-development-not-distribution\n'
  printf 'application_path=%s\n' "$APP_PATH"
  printf 'status=HOLD-backend-and-passkey-integration-not-yet-certified\n'
} > "$BUILD_ROOT/BUILD-METADATA.txt"
echo "Signed candidate: $APP_PATH"
echo "Metadata: $BUILD_ROOT/BUILD-METADATA.txt"
echo 'RELEASE HOLD: physical iPhone/iPad tests and native API/passkey integration are still required.'
echo 'Free Personal Team provisioning expires after seven days; it is not a stable release channel.'
