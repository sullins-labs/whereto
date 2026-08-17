#!/usr/bin/env sh
# One-way sync: this repo -> the sullinslabs repo's deployed copy.
#
# This repo is authoritative for the whole app: the markup, the scoring code,
# the Sullins Labs theming and the built data. sullinslabs/public/whereto is a
# deployed copy and nothing should ever be hand-edited there, because the next
# run of this script would silently discard it.
#
# Direction is deliberately not configurable. A two-way sync is how the two
# copies diverged in the first place.
#
# Usage, from the repo root, in Git Bash:
#   sh scripts/sync-to-sullinslabs.sh            # dry run, shows what differs
#   sh scripts/sync-to-sullinslabs.sh --apply    # actually copy
#   sh scripts/sync-to-sullinslabs.sh --apply /path/to/sullinslabs
#
# Publishing is still a separate, deliberate step:
#   cd ../sullinslabs && netlify deploy --prod

set -eu

APPLY=0
TARGET_REPO=""

for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) TARGET_REPO="$arg" ;;
  esac
done

SRC_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -n "$TARGET_REPO" ] || TARGET_REPO="$SRC_ROOT/../sullinslabs"
DEST="$TARGET_REPO/public/whereto"

if [ ! -d "$DEST" ]; then
  echo "error: $DEST does not exist." >&2
  echo "Pass the sullinslabs repo path as an argument if it lives elsewhere." >&2
  exit 1
fi

# src:dest pairs. places.json is the build output and the only file that has
# to move after a routine ETL run; the other two change only when the app does.
set -- \
  "site/index.html:index.html" \
  "site/theme-tokens.css:theme-tokens.css" \
  "data/dist/places.json:data/places.json"

changed=0
for pair in "$@"; do
  src="$SRC_ROOT/${pair%%:*}"
  dst="$DEST/${pair#*:}"

  if [ ! -f "$src" ]; then
    echo "error: missing source file $src" >&2
    exit 1
  fi

  # Compare with line endings normalized, so a CRLF/LF difference alone is not
  # reported as a change. site/ is CRLF in git; the deployed copy has been LF.
  # If the source is already LF the sed is a no-op and this is a plain compare.
  if [ -f "$dst" ] && sed 's/\r$//' "$src" | diff -q - "$dst" >/dev/null 2>&1; then
    same=1
  else
    same=0
  fi

  if [ "$same" = "1" ]; then
    echo "  unchanged  ${pair#*:}"
    continue
  fi

  changed=$((changed + 1))
  if [ "$APPLY" = "1" ]; then
    mkdir -p "$(dirname "$dst")"
    # Write LF, matching what is already committed in the sullinslabs repo.
    sed 's/\r$//' "$src" > "$dst"
    echo "  copied     ${pair#*:}"
  else
    echo "  would copy ${pair#*:}"
  fi
done

echo
if [ "$changed" = "0" ]; then
  echo "Deployed copy already matches this repo. Nothing to do."
elif [ "$APPLY" = "1" ]; then
  echo "$changed file(s) copied into $DEST"
  echo "Next: cd $TARGET_REPO && netlify deploy --prod"
else
  echo "$changed file(s) differ. Re-run with --apply to copy them."
fi
