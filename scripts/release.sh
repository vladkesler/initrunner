#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:?Usage: scripts/release.sh <version>  (e.g. 0.6.0)}"

# Strip leading 'v' if provided
VERSION="${VERSION#v}"

# Validate semver-ish format (X.Y.Z or X.Y.ZrcN etc.)
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(.*)$ ]]; then
  echo "Error: '$VERSION' is not a valid version (expected X.Y.Z[suffix])" >&2
  exit 1
fi

# Ensure clean working tree
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Error: working tree is not clean. Commit or stash changes first." >&2
  exit 1
fi

# Read current version
CURRENT=$(python -c "
import re, pathlib
m = re.search(r'__version__\s*=\s*\"(.+?)\"', pathlib.Path('initrunner/__init__.py').read_text())
print(m.group(1))
")
echo "Bumping $CURRENT → $VERSION"

# Update __init__.py
sed -i "s/__version__ = \".*\"/__version__ = \"$VERSION\"/" initrunner/__init__.py

# Update CHANGELOG.md — add a new section header if one doesn't exist for this version
DATE=$(date +%Y-%m-%d)
if ! grep -q "## \[$VERSION\]" CHANGELOG.md; then
  sed -i "s/^# Changelog$/# Changelog\n\n## [$VERSION] - $DATE/" CHANGELOG.md
fi

# Commit and tag
git add initrunner/__init__.py CHANGELOG.md
git commit -m "chore: release $VERSION"
git tag "v$VERSION"

echo ""
echo "Done. Created commit and tag v$VERSION."
echo "Next steps:"
echo "  git push origin main && git push origin v$VERSION"
