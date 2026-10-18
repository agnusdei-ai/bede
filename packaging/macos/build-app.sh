#!/usr/bin/env bash
# Build the single Mac entry point around a sealed operator payload.
set -euo pipefail
if [[ $# -ne 2 ]]; then
  echo "Usage: build-app.sh <sealed-operator-directory> <output-directory>" >&2
  exit 2
fi
payload="$(cd "$1" && pwd)"
output="$2"
root="$(cd "$(dirname "$0")/../.." && pwd)"
[[ -f "$payload/RELEASE" && -f "$payload/ARCH" && -f "$payload/start.sh" ]] || {
  echo "Bede installation payload is incomplete." >&2
  exit 2
}
[[ "$(cat "$payload/ARCH")" = arm64 || "$(cat "$payload/ARCH")" = amd64 ]] || exit 2
[[ -f "$payload/images.tar" || -f "$payload/IMAGE_DIGESTS" ]] || {
  echo "No verified runtime images found." >&2
  exit 2
}
app="$output/Bede Installer.app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
target_arch="$(cat "$payload/ARCH")"
if [[ "$target_arch" = arm64 ]]; then target="arm64-apple-macos14.0"; else target="x86_64-apple-macos14.0"; fi
swiftc -target "$target" -parse-as-library -o "$app/Contents/MacOS/BedeInstaller" \
  "$root/packaging/macos/BedeInstallerApp.swift"
cp "$root/packaging/macos/BedeIcon.png" "$app/Contents/Resources/BedeIcon.png"
ditto "$payload" "$app/Contents/Resources/bede-operator"
# Legacy .command launchers are not distributed in the native Mac app.
rm -f "$app/Contents/Resources/bede-operator/Install-Bede.command" \
  "$app/Contents/Resources/bede-operator/Verify-Bede.command"
cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>ai.agnusdei.bede.installer</string>
<key>CFBundleExecutable</key><string>BedeInstaller</string>
<key>CFBundleName</key><string>Bede Installer</string>
<key>CFBundleDisplayName</key><string>Bede Installer</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.1.0</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>13.0</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
plutil -lint "$app/Contents/Info.plist"
chmod 755 "$app/Contents/MacOS/BedeInstaller"
echo "Built Bede Installer.app. This pilot build is not Developer ID signed or notarized."
