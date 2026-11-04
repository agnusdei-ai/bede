#!/usr/bin/env bash
# Package the already-verified source-free Bede Standard operator archive as
# native Linux .deb and .rpm (not new Docker images or a source checkout).
# Requires dpkg-deb and rpmbuild on an official matching-architecture runner.
set -euo pipefail
if [[ "$#" -ne 3 ]]; then
  echo "Usage: build-native-packages.sh <operator-dir> <sha> <outdir>" >&2
  exit 2
fi
operator="$(cd "$1" && pwd)"
sha="$2"
outdir="$3"
[[ "$sha" =~ ^[a-f0-9]{40}$ ]] || { echo "Invalid source SHA" >&2; exit 2; }
[[ "$(tr -d '\r\n' < "$operator/RELEASE")" = "$sha" ]] || { echo "Operator SHA mismatch" >&2; exit 2; }
arch="$(tr -d '\r\n' < "$operator/ARCH")"
case "$arch" in
  amd64)
    [[ "$(uname -m)" = x86_64 ]] || exit 2
    rpm_arch=x86_64
    ;;
  arm64)
    [[ "$(uname -m)" = aarch64 ]] || exit 2
    rpm_arch=aarch64
    ;;
  *) echo "Unsupported Linux architecture $arch" >&2; exit 2 ;;
esac
command -v dpkg-deb >/dev/null
command -v rpmbuild >/dev/null
[[ -s "$operator/IMAGE_DIGESTS" && -s "$operator/RELEASE_PROVENANCE.json" ]] || {
  echo "Missing pinned operator manifest" >&2; exit 2;
}
python3 - "$operator" "$sha" "$arch" <<'PY'
import json, pathlib, re, sys
root, sha, arch = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
prov = json.loads((root / "RELEASE_PROVENANCE.json").read_text())
assert prov["source_sha"] == sha and prov["architecture"] == arch and prov["pilot_go"] == "HOLD"
assert not (root / "images.tar").exists()
assert not (root / "images.tar.zst").exists()
assert not (root / ".env").exists()
assert (root / "WIZARD_IMAGE").read_text().strip() == f"ghcr.io/agnusdei-ai/bede-wizard:sha-{sha}-{arch}"
lines = (root / "IMAGE_DIGESTS").read_text().splitlines()
assert len(lines) == 6 and len(set(x.split()[0] for x in lines)) == 6
for entry in lines:
    m = re.fullmatch(r"(\S+) (sha256:[a-f0-9]{64})", entry)
    assert m, "Unpinned digest"
    name = m.group(1)
    assert name in {"postgres:16-alpine", "caddy:2-alpine"} or re.fullmatch(
        rf"ghcr\.io/agnusdei-ai/bede-(api|ui|trust|wizard):sha-{sha}-{arch}", name
    ), "Unexpected image"
PY
repo="$(cd "$(dirname "$0")/../.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$outdir"
outdir="$(cd "$outdir" && pwd)"
stage="$work/root"
mkdir -p "$stage/opt/bede/standard" "$stage/usr/bin" \
  "$stage/usr/share/applications" "$stage/usr/share/pixmaps"
cp -a "$operator/." "$stage/opt/bede/standard/"
install -m 0755 "$repo/packaging/linux/bede-installer" "$stage/usr/bin/bede-installer"
cp "$repo/packaging/macos/BedeIcon.png" "$stage/usr/share/pixmaps/bede.png"
cat > "$stage/usr/share/applications/bede-installer.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Bede Installer
Comment=Install Bede using a reviewed local operator package
Exec=/usr/bin/bede-installer
Icon=bede
Terminal=true
Categories=Education;
StartupNotify=false
DESKTOP
chmod 0644 "$stage/usr/share/applications/bede-installer.desktop"
short="${sha:0:12}"
version="0.1.0+sha.$short"
mkdir -p "$stage/DEBIAN"
cat > "$stage/DEBIAN/control" <<CONTROL
Package: bede-installer
Version: $version
Section: education
Priority: optional
Architecture: $arch
Maintainer: Agnus Dei Technologies <bede@agnusdei.ai>
Depends: bash, coreutils, curl, ca-certificates
Description: Bede Standard guided installer (source-pinned engineering candidate)
 Installs a native Linux desktop entry and source-free operator payload.
 A suitable Docker-compatible engine with Compose is an explicit prerequisite.
 Not a release or Pilot GO authorization.
CONTROL
chmod 0755 "$stage/DEBIAN"
dpkg-deb --build --root-owner-group "$stage" "$outdir/Bede-Engineering-Linux-$arch.deb" >/dev/null

# RPM packages share exactly the same source/payload directory as DEB.
# rpmbuild runs as the unprivileged GitHub runner; no postinstall actions.
rm -rf "$stage/DEBIAN"
top="$work/rpmbuild"
mkdir -p "$top"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
mkdir -p "$top/SOURCES/root"
cp -a "$stage/." "$top/SOURCES/root/"
cat > "$top/SPECS/bede-installer.spec" <<SPEC
Name: bede-installer
Version: 0.1.0
Release: 0.$short
Summary: Bede source-pinned Standard guided installer
License: Proprietary
BuildArch: $rpm_arch
AutoReqProv: no
Requires: /bin/bash
%description
Native Linux launcher for the source-free SHA-pinned Bede Standard
operator. Requires an approved Docker-compatible engine with Compose.
This engineering candidate is not approved for release or Pilot GO.
%prep
%build
%install
mkdir -p %{buildroot}
cp -a %{_sourcedir}/root/. %{buildroot}/
%files
/opt/bede/standard
/usr/bin/bede-installer
/usr/share/applications/bede-installer.desktop
/usr/share/pixmaps/bede.png
SPEC
rpmbuild -bb --define "_topdir $top" "$top/SPECS/bede-installer.spec" >/dev/null
rpm_file="$(find "$top/RPMS/$rpm_arch" -maxdepth 1 -name '*.rpm' -print -quit)"
[[ -n "$rpm_file" ]] || { echo "RPM build did not produce a file" >&2; exit 2; }
cp "$rpm_file" "$outdir/Bede-Engineering-Linux-$arch.rpm"
for ext in deb rpm; do
  file="$outdir/Bede-Engineering-Linux-$arch.$ext"
  sha256sum "$file" > "$file.sha256"
done
cp "$operator/RELEASE_PROVENANCE.json" "$outdir/RELEASE_PROVENANCE.json"
cp "$operator/IMAGE_DIGESTS" "$outdir/IMAGE_DIGESTS"
printf 'ENGINEERING CANDIDATE ONLY: source=%s architecture=%s; no external distribution, real learner data or Pilot GO.\n' \
  "$sha" "$arch" > "$outdir/NOT_FOR_DISTRIBUTION.txt"
echo "Native DEB/RPM candidates built for $sha / $arch"
