# Release Preparation

Step-by-step runbook for cutting a release of InitRunner to PyPI.

## Pre-Release Checklist

### Version Bump

Update the version string in **both** locations — they must match exactly:

- `pyproject.toml` → `version = "X.Y.Z"`
- `initrunner/__init__.py` → `__version__ = "X.Y.Z"`

The CLI reads `__version__` in `initrunner/cli/main.py:version_callback` and the release workflow verifies the installed package version via `importlib.metadata.version('initrunner')` against the git tag.

### CHANGELOG.md

Add a new entry under `## [X.Y.Z] - YYYY-MM-DD` following [Keep a Changelog](https://keepachangelog.com/) format. Use the existing [CHANGELOG.md](../CHANGELOG.md) structure as a reference — group changes under `### Added`, `### Changed`, `### Fixed`, `### Removed`, etc.

### Dependency Audit

Review pinned minimums in `pyproject.toml`. The project has 11 core dependencies and 10 optional groups (`ingest`, `local-embeddings`, `safety`, `anthropic`, `google`, `groq`, `mistral`, `all-models`, `tui`, `dashboard`). Ensure no known CVEs exist for any pinned version.

### Documentation

Ensure [README.md](../README.md), files in `docs/`, and [CLAUDE.md](../CLAUDE.md) reflect any new features or breaking changes introduced since the last release.

## Quality Gates

All of the following must pass before tagging:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check initrunner/
uv run pytest tests/ -v
```

Tests run across Python 3.11, 3.12, and 3.13 in CI.

Build locally and inspect the artifacts:

```bash
uv build
ls dist/
```

Verify the sdist and wheel are present and the version in the filenames is correct.

## Tagging & Release

### Versioning Scheme

InitRunner uses [Semantic Versioning](https://semver.org/) with [PEP 440](https://peps.python.org/pep-0440/) pre-release suffixes:

- Beta: `0.2.0b1`
- Release candidate: `0.2.0rc1`
- Final: `0.2.0`

### Creating the Tag

Tags use a `v` prefix:

```bash
git tag v0.2.0
git push origin v0.2.0
```

Pushing the tag triggers `.github/workflows/release.yml`, which runs:

1. **Lint** — `ruff check`, `ruff format --check`, `ty check` (Python 3.13)
2. **Test** — `pytest tests/ -v` across Python 3.11, 3.12, 3.13
3. **Build** — tag-version verification (see below), then `uv build` with artifact upload
4. **Publish** — uploads to PyPI via OIDC trusted publisher (`pypa/gh-action-pypi-publish`)

## Tag-Version Verification

The release workflow's build job extracts the installed package version and compares it to the tag:

```bash
TAG="${GITHUB_REF#refs/tags/v}"
PKG_VERSION=$(uv run python -c "import importlib.metadata; print(importlib.metadata.version('initrunner'))")
if [ "$TAG" != "$PKG_VERSION" ]; then
  echo "Tag v$TAG does not match package version $PKG_VERSION"
  exit 1
fi
```

If the version in `pyproject.toml` does not exactly match the tag (minus the `v` prefix), the build fails. Always bump the version **before** tagging.

## Post-Release Verification

After the workflow publishes successfully:

```bash
# Install and verify version
pip install initrunner==X.Y.Z
initrunner --version
# Expected output: initrunner X.Y.Z

# Test optional extras
pip install initrunner[ingest]
pip install initrunner[anthropic]
pip install initrunner[all-models]
```

Check the [PyPI project page](https://pypi.org/project/initrunner/) for correct metadata: description, license (MIT), classifiers, and project URLs (Repository, Changelog, Issues).

## Hotfix / Patch Process

1. Branch from the release tag: `git checkout -b hotfix/X.Y.Z+1 vX.Y.Z`
2. Apply the fix and add tests.
3. Bump the patch version in `pyproject.toml` and `initrunner/__init__.py`.
4. Update `CHANGELOG.md`.
5. Tag and push: `git tag vX.Y.Z+1 && git push origin vX.Y.Z+1`

For security vulnerabilities, follow the process in [SECURITY.md](../SECURITY.md) — reports go to email only (not public issues), with a 48-hour acknowledgement SLA and 30-day fix target for critical issues.

## Rollback

If a critical defect is found after publishing:

1. **Prefer a patch release** — fix the issue and release a new version (see hotfix process above).
2. **User mitigation** — advise users to pin the previous version: `pip install initrunner==<previous>`
3. **PyPI yanking** (last resort) — yank the broken version via the [PyPI web UI](https://pypi.org/manage/project/initrunner/releases/) or CLI. Yanking hides the version from default installs but does not delete it.
