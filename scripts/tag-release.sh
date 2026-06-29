#!/usr/bin/env bash
# Create a semver release tag locally. Pushing the tag (which is what triggers
# the release workflow) is a separate, explicit operator step — this script does
# NOT push unless you pass --push.
#
# Usage: scripts/tag-release.sh vX.Y.Z[-pre] [--push]
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${1:-}"
PUSH=0
[ "${2:-}" = "--push" ] && PUSH=1

if [[ ! "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
  echo "Usage: scripts/tag-release.sh vX.Y.Z[-pre] [--push]" >&2
  echo "  (got: '${VERSION:-<none>}' — must be a semver tag like v1.2.3)" >&2
  exit 2
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "Working tree is dirty — commit or stash before tagging." >&2
  exit 1
fi

if git rev-parse "$VERSION" >/dev/null 2>&1; then
  echo "Tag $VERSION already exists." >&2
  exit 1
fi

echo "Creating annotated tag $VERSION at $(git rev-parse --short HEAD) on $(git rev-parse --abbrev-ref HEAD)"
git tag -a "$VERSION" -m "Release $VERSION"
echo "✓ tag $VERSION created locally"

if [ "$PUSH" -eq 1 ]; then
  echo "Pushing $VERSION to origin (this triggers the release workflow)…"
  git push origin "$VERSION"
  echo "✓ pushed $VERSION"
else
  echo "Not pushed. To trigger the release pipeline: git push origin $VERSION"
fi
