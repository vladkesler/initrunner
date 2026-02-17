# PyPI Publishing

InitRunner publishes to PyPI via two GitHub Actions workflows using OIDC trusted publishers — no API tokens are stored in the repository. Production releases are triggered by pushing a `v*` tag, while pre-release versions can be tested on TestPyPI via manual dispatch.

## Workflows

| Workflow | File | Trigger | Target |
|----------|------|---------|--------|
| Release | `.github/workflows/release.yml` | Push `v*` tag | [pypi.org](https://pypi.org/project/initrunner/) |
| TestPyPI | `.github/workflows/testpypi.yml` | Manual dispatch | [test.pypi.org](https://test.pypi.org/project/initrunner/) |

Both workflows share the same lint and test gates before building or publishing.

## Bumping the Version

Run the release script to prepare a version bump:

    scripts/release.sh 0.6.0

This updates `initrunner/__init__.py`, adds a CHANGELOG section header, commits, and creates the `v0.6.0` tag. Then push to trigger the release pipeline:

    git push origin main && git push origin v0.6.0

## Production Publish (`release.yml`)

Triggered when a `v*` tag is pushed to the repository. The pipeline runs five jobs in sequence:

1. **Lint** — Ruff check, Ruff format check, and ty type check on Python 3.13.
2. **Test** — `pytest tests/ -v` across Python 3.11, 3.12, and 3.13. All three must pass.
3. **Build** — Verifies the git tag matches the installed package version, then runs `uv build` and uploads the sdist and wheel as artifacts.
4. **Publish** — Downloads the build artifacts and publishes to PyPI via OIDC using `pypa/gh-action-pypi-publish`. Runs in the `pypi` environment.
5. **GitHub Release** — Extracts release notes from `CHANGELOG.md` for the tagged version, creates a GitHub Release, and attaches the dist artifacts.

The publish and GitHub Release jobs run in parallel after build completes.

## TestPyPI Publish (`testpypi.yml`)

Triggered manually via GitHub Actions workflow dispatch. Used to validate packaging before a production release.

1. **Lint** — Same checks as production (Ruff + ty).
2. **Test** — Same Python matrix (3.11, 3.12, 3.13).
3. **Build** — Enforces that the package version contains a pre-release suffix (`rc`, `a`, `b`, or `dev`). Rejects stable versions to prevent accidental TestPyPI pollution. Then runs `uv build`.
4. **Publish** — Uploads to `https://test.pypi.org/legacy/` via OIDC. Runs in the `testpypi` environment.
5. **Verify Install** — After a 30-second index delay, downloads the published wheel from TestPyPI, installs it with all extras (`tui`, `ingest`, `dashboard`), and runs smoke tests across Python 3.11, 3.12, and 3.13:
   - CLI: `initrunner --version` and `initrunner --help`
   - Core imports: `initrunner`, `initrunner.agent`, `initrunner.cli`, `initrunner.runner`
   - Extra imports: `initrunner.tui`, `initrunner.ingestion`, `initrunner.api`

## OIDC Trusted Publisher

Both workflows authenticate to PyPI using OpenID Connect (OIDC) — no manual API tokens are needed. The mechanism works as follows:

1. The GitHub Actions runner requests a short-lived OIDC token from GitHub's identity provider.
2. The `pypa/gh-action-pypi-publish` action presents this token to PyPI (or TestPyPI).
3. PyPI verifies the token against a trusted publisher configuration that ties a specific GitHub repository, workflow file, and environment together.

Two GitHub environments are configured on the repository:

| Environment | PyPI Registry | Workflow |
|-------------|---------------|----------|
| `pypi` | `pypi.org` | `release.yml` |
| `testpypi` | `test.pypi.org` | `testpypi.yml` |

The workflow jobs request the `id-token: write` permission, which is required to mint the OIDC token. No secrets or API keys are stored in the repository.

For setup details, see the [PyPI trusted publisher documentation](https://docs.pypi.org/trusted-publishers/).

## README on PyPI

The package description shown on PyPI comes from `README.md`, embedded at build time by `hatchling`. This means:

- Changes to `README.md` only appear on PyPI after a new version is published.
- **Images must use absolute URLs.** Relative paths (e.g., `docs/images/screenshot.png`) break on PyPI because the file is rendered outside the repository context. Use full `https://raw.githubusercontent.com/...` URLs for any images in the README.
- PyPI caches rendered descriptions aggressively. If an image URL hasn't changed but the image content has, append a cache-busting query parameter (e.g., `?v=2`).

## Troubleshooting

### Tag/version mismatch

The build job fails with `Tag vX.Y.Z does not match package version ...`. This means the version in `initrunner/__init__.py` was not bumped before tagging. Use `scripts/release.sh <version>` to avoid this — it updates the version, commits, and tags in one step. To fix manually: delete the tag, bump the version in `initrunner/__init__.py`, commit, then re-tag.

### Broken images on PyPI

Images using relative paths or GitHub-specific URLs (like `github.com/.../blob/...`) won't render on PyPI. Use `raw.githubusercontent.com` URLs. Verify by checking the PyPI project page after publishing.

### Stale description on PyPI

PyPI only updates the package description when a new version is uploaded. If you fixed a README typo, you must publish a new release (even a patch bump) for the change to appear.

### OIDC permission errors

If the publish job fails with authentication errors:

- Verify the trusted publisher is configured on PyPI for the correct repository, workflow filename, and environment name.
- Ensure the job has `permissions: id-token: write` set.
- Check that the GitHub environment (`pypi` or `testpypi`) exists and has no pending approval requirements blocking the job.

### TestPyPI version conflicts

TestPyPI rejects uploads of versions that already exist. Unlike production PyPI, you cannot re-upload the same version even after deletion. Bump the pre-release suffix (e.g., `0.3.0rc1` → `0.3.0rc2`) and try again.

### Pre-release version rejected

The TestPyPI workflow enforces that the version contains `rc`, `a`, `b`, or `dev`. If the build fails with `Package version is not a pre-release version`, add a pre-release suffix to the version in `initrunner/__init__.py` before dispatching the workflow.
