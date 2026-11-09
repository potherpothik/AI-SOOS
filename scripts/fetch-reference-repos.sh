#!/usr/bin/env bash
# Clone the repositories marked "study" in vendor/manifest.yaml into vendor/reference/.
# Read-only review copies: nothing is built, installed, or executed from them.
# Each clone is shallow and its commit SHA is printed so it can be pinned after review.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$(cd "$ROOT/.." && pwd)/Clone-Repositories"
MANIFEST="$ROOT/vendor/manifest.yaml"
mkdir -p "$DEST"

python3 - "$MANIFEST" <<'PY' | while IFS=$'\t' read -r name url; do
import sys, yaml
data = yaml.safe_load(open(sys.argv[1]))
for r in data["repositories"]:
    if r["disposition"] == "study":
        print(f'{r["name"].replace(" ", "_").replace("(", "").replace(")", "")}\t{r["url"]}')
PY
  target="$DEST/$name"
  if [ -d "$target/.git" ]; then
    echo "skip   $name (already present)"
    continue
  fi
  if git clone --depth 1 --quiet "$url" "$target" 2>/dev/null; then
    sha="$(git -C "$target" rev-parse HEAD)"
    echo "clone  $name @ $sha"
  else
    echo "FAIL   $name ($url)"
  fi
done

echo
echo "Reference copies are read-only. Do not build or run them. Record reviewed SHAs in vendor/manifest.yaml."
