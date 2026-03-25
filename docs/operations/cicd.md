# CI / CD

InitRunner uses GitHub Actions for continuous integration. Every push to `main` and every pull request triggers two jobs: **lint** and **test**.

## Jobs

### Lint

Runs on Python 3.13 and checks code quality with three tools in sequence:

```bash
uv run ruff check .          # linting (pycodestyle, pyflakes, isort, pyupgrade, bugbear, ruff)
uv run ruff format --check . # formatting (double quotes, 100-char line length)
uv run ty check initrunner/  # type checking (scoped to the main package)
```

The lint job fails on any Ruff violation or ty type error.

### Test

Runs `pytest` across a Python version matrix:

| Python | Runner |
|--------|--------|
| 3.11   | `ubuntu-latest` |
| 3.12   | `ubuntu-latest` |
| 3.13   | `ubuntu-latest` |

```bash
uv sync --dev
uv run pytest tests/ -v
```

All three versions must pass for the job to succeed.

## Running Locally

Run the same checks locally before pushing:

```bash
uv run ruff check .              # lint
uv run ruff format --check .     # format check (or omit --check to auto-fix)
uv run ty check initrunner/      # type check
uv run pytest tests/ -v          # tests
```

## Tooling Reference

| Tool | Version Constraint | Purpose |
|------|--------------------|---------|
| Ruff | `>=0.15` | Linting and formatting (`target-version = "py313"`, `line-length = 100`) |
| ty | `>=0.0.15` | Type checking (`python-version = "3.13"`) |
| pytest | `>=9.0` | Test runner |
| pytest-asyncio | `>=1.3` | Async test support |

All four are declared in the `[dependency-groups] dev` section of `pyproject.toml` and installed via `uv sync --dev`.

## Security Scanning

A standalone **Security** workflow (`.github/workflows/security.yml`) runs on PRs that touch dependency files, on a weekly schedule (Wednesday), and on manual dispatch. It runs three parallel jobs:

### Trivy Repository Scan

Scans the full repository filesystem for known CVEs in `uv.lock` and `pnpm-lock.yaml`, plus Dockerfile misconfigurations. Filters to CRITICAL and HIGH severity. Results are uploaded as SARIF to the GitHub Security tab.

### pip-audit

Exports Python dependencies via `uv export` and audits them against the PyPI advisory database using `pip-audit`.

### pnpm audit

Runs `pnpm audit --prod` against the dashboard's frontend dependencies. This job uses `continue-on-error` since pnpm audit exits non-zero even for low-severity advisories with no available fix.

### Container Image Scan

The Docker publish workflow (`.github/workflows/docker-publish.yml`) includes a post-publish Trivy scan of the container image. This detects OS-level CVEs in the `python:3.13-slim` base image and installed system packages. Results appear in the Security tab under the `trivy-image` category.

## Dependabot

Dependabot is configured in `.github/dependabot.yml` for three ecosystems:

| Ecosystem | Directory | Schedule | Grouping |
|-----------|-----------|----------|----------|
| `pip` | `/` | Weekly (Monday) | pydantic, AI providers, observability |
| `npm` | `/dashboard` | Weekly (Monday) | svelte, tailwind |
| `github-actions` | `/` | Weekly (Monday) | -- |

Related packages are grouped to reduce PR noise (e.g., all pydantic packages update in a single PR).

## Python Version Support

The project declares `requires-python = ">=3.11"` and CI tests against 3.11, 3.12, and 3.13. Ruff and ty are both configured to target Python 3.13 for lint and type-check rules.
