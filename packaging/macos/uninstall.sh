#!/usr/bin/env bash
# Remove one explicitly selected Bede installation, never the Docker engine.
set -euo pipefail
umask 077
context="${1:-}"
campus="${2:-}"
case "$context" in
  campus)
    [[ "$campus" =~ ^[a-z0-9][a-z0-9_-]{2,63}$ ]] || { echo "Invalid campus identifier" >&2; exit 2; }
    project="bede_campus_${campus//-/_}"
    installation="$HOME/Library/Application Support/Bede/Campus/$campus"
    ;;
  homeschool)
    [[ -z "$campus" ]] || exit 2
    project="bede_homeschool_local"
    installation="$HOME/Library/Application Support/Bede/Homeschool/local"
    ;;
  *) echo "Unknown Bede installation type" >&2; exit 2 ;;
esac
operator="$installation/bede-operator"
[[ -d "$installation" && ! -L "$installation" && -d "$operator" && ! -L "$operator" ]] || {
  echo "Selected Bede installation was not found" >&2; exit 2;
}
[[ -f "$operator/RELEASE" && -f "$operator/compose.yaml" && -f "$operator/.env" ]] || {
  echo "Installation metadata is incomplete. Nothing was deleted." >&2; exit 2;
}
command -v docker >/dev/null && docker info >/dev/null 2>&1 || {
  echo "Start Docker Desktop before removing Bede. Nothing was deleted." >&2; exit 2;
}
echo 'BEDE_REMOVE|Stopping and removing this Bede installation'
# Include the LAN compose file only when previously enabled.
compose=(-f "$operator/compose.yaml")
if grep -qx 'BEDE_LAN_ENABLED=true' "$operator/.env"; then
  [[ -f "$operator/compose.lan.yaml" ]] || { echo "Private-network settings are incomplete" >&2; exit 2; }
  compose+=(-f "$operator/compose.lan.yaml")
fi
(
  cd "$operator"
  docker compose --project-name "$project" --env-file .env "${compose[@]}" down --volumes --remove-orphans >/dev/null
) || { echo "Docker removal failed; local files are preserved for recovery." >&2; exit 1; }
# Confirm the selected project's resources are actually gone before deleting local metadata.
if [[ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ||
      -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ]]; then
  echo "Some Bede resources remain; local files are preserved for recovery." >&2; exit 1
fi
echo 'BEDE_REMOVE|Removing this installation files'
# Only delete the exact root CA previously generated for this installation.
ca="$operator/bede-root-ca.crt"
if [[ -f "$ca" && ! -L "$ca" ]] && openssl x509 -in "$ca" -noout -subject 2>/dev/null | grep -q 'Caddy Local Authority'; then
  sha1="$(openssl x509 -in "$ca" -noout -fingerprint -sha1 | sed -n 's/^.*=//p' | tr -d ':')"
  if security find-certificate -a -Z "$HOME/Library/Keychains/login.keychain-db" 2>/dev/null | grep -qi "$sha1"; then
    security delete-certificate -Z "$sha1" "$HOME/Library/Keychains/login.keychain-db" || {
      echo "Bede stopped, but its certificate could not be removed from the login keychain. Installation files are preserved." >&2; exit 1;
    }
  fi
  if security find-certificate -a -Z /Library/Keychains/System.keychain 2>/dev/null | grep -qi "$sha1"; then
    echo "A Bede certificate remains in the System keychain. Remove that exact certificate with administrator approval before finishing." >&2
    exit 1
  fi
fi
rm -rf -- "$installation"
[[ ! -e "$installation" ]] || { echo "Installation files could not be removed" >&2; exit 1; }
echo 'BEDE_REMOVE|Removal verified'
