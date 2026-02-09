#!/usr/bin/env bash
set -euo pipefail

MANIFEST="$(git rev-parse --show-toplevel)/manifest.yaml"

usage() {
  echo "Usage: $0 [patch|minor|major]"
  echo "  patch  - 0.0.5 -> 0.0.6 (default)"
  echo "  minor  - 0.0.5 -> 0.1.0"
  echo "  major  - 0.0.5 -> 1.0.0"
  exit 1
}

BUMP="${1:-patch}"

case "$BUMP" in
  patch|minor|major) ;;
  -h|--help) usage ;;
  *) echo "Error: unknown bump type '$BUMP'"; usage ;;
esac

# Read current version
CURRENT=$(grep -m1 '^version:' "$MANIFEST" | sed 's/version: *"\(.*\)"/\1/')
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"

case "$BUMP" in
  patch) PATCH=$((PATCH + 1)) ;;
  minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
  major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
esac

NEW_VERSION="${MAJOR}.${MINOR}.${PATCH}"
TODAY=$(date +%Y-%m-%d)

# Update manifest
sed -i '' "s/^version: \".*\"/version: \"${NEW_VERSION}\"/" "$MANIFEST"
sed -i '' "s/^released: \".*\"/released: \"${TODAY}\"/" "$MANIFEST"

echo "Bumped $CURRENT -> $NEW_VERSION (released: $TODAY)"
