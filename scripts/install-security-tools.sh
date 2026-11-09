#!/usr/bin/env bash
# Install pinned Gitleaks and Trivy after verifying upstream checksums.
# Not part of scripts/setup.sh.
set -euo pipefail

if [ "${AISOOS_INSTALL_SECURITY_TOOLS:-}" != "1" ]; then
  echo "Refusing to install. Set AISOOS_INSTALL_SECURITY_TOOLS=1 to continue."
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/.tools"
mkdir -p "$DEST"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

install_one() {
  local base="$1"
  local archive="$2"
  local checksums="$3"
  curl -fsSL "$base/$checksums" -o "$TMP/$checksums"
  curl -fsSL "$base/$archive" -o "$TMP/$archive"
  (
    cd "$TMP"
    grep "  ${archive}$" "$checksums" | sha256sum -c -
  )
  tar -xzf "$TMP/$archive" -C "$DEST"
}

install_one \
  "https://github.com/gitleaks/gitleaks/releases/download/v8.28.0" \
  "gitleaks_8.28.0_linux_x64.tar.gz" \
  "gitleaks_8.28.0_checksums.txt"
install_one \
  "https://github.com/aquasecurity/trivy/releases/download/v0.76.2" \
  "trivy_0.76.2_Linux-64bit.tar.gz" \
  "trivy_0.76.2_checksums.txt"

echo "Installed gitleaks and trivy into .tools/"
