#!/usr/bin/env bash
# Build native macOS application payloads. Never mark this as release-ready
# until the full identity, model, runtime and installer gates are implemented.
set -euo pipefail
root="$(cd "$(dirname "$0")/../../.." && pwd)"
out="${1:?usage: build-native-payload.sh OUTPUT_DIRECTORY}"
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || { echo "Apple Silicon macOS required" >&2; exit 2; }
for tool in python3 npm swiftc shasum; do command -v "$tool" >/dev/null || { echo "Missing $tool" >&2; exit 2; }; done
mkdir -p "$out/bin" "$out/api" "$out/teacher"
# Compile standalone native management and local diagnostic components.
swiftc -target arm64-apple-macos14.0 -parse-as-library "$root/packaging/macos/native/BedeNativeControl.swift" -o "$out/bin/bede-native-control"
swiftc -target arm64-apple-macos14.0 -parse-as-library "$root/packaging/macos/native/BedeNativeSmokeService.swift" -o "$out/bin/bede-native-smoke"
# Existing application assets are built, never replaced with a demo UI.
(cd "$root/homeschool-tutor" && npm ci --ignore-scripts && npm run build)
ditto "$root/homeschool-tutor/dist" "$out/teacher/dist"
# Keep application code and dependencies in a private venv, not system Python.
python3 -m venv "$out/api/venv"
"$out/api/venv/bin/python" -m pip install --require-hashes -r "$root/homeschool-api/requirements.lock.txt"
ditto "$root/homeschool-api" "$out/api/source"
# The production tutor cannot be activated without local inference,
# identity configuration, model verification, and a signed payload.
cat > "$out/QUALIFICATION.json" <<'EOF'
{"architecture":"arm64","pilot_go":"HOLD","native_release_ready":false,"missing":["verified_local_inference_model","identity_configuration","signed_runtime_manifest","native_service_lifecycle","G1_G2_G3_physical_acceptance"]}
EOF
echo "Native application assets staged; production installation remains blocked."
