# CI / CD

InitRunner uses GitHub Actions for continuous integration. Every push to `main` and every pull request triggers two jobs: **lint** and **test**.

## Jobs

### Lint

Runs on Python 3.12 and checks code quality with three tools in sequence. The job syncs `--dev --extra dashboard --extra a2a` so type checking sees optional A2A imports.

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
uv sync --dev --extra dashboard --extra a2a --extra mcp --extra vector
uv run pytest tests/ -v
```

All three versions must pass for the job to succeed.

### `test-lean`

A second job installs the core package only (`uv sync --dev`) and runs
`tests/test_core_footprint.py` and `tests/test_lean_extras.py`. Those files assert
that a plain install never imports the MCP stack or LanceDB, and that a role needing
either fails at load with an install command. They pass trivially when the extras are
present, so this job is the one that actually enforces them.

## Running Locally

Run the same checks locally before pushing:

```bash
uv sync --dev --extra dashboard --extra a2a --extra mcp --extra vector
uv run ruff check .              # lint
uv run ruff format --check .     # format check (or omit --check to auto-fix)
uv run ty check initrunner/      # type check
uv run pytest tests/ -v          # tests
```

## Tooling Reference

| Tool | Version Constraint | Purpose |
|------|--------------------|---------|
| Ruff | `>=0.15.7` | Linting and formatting (`target-version = "py311"`, `line-length = 100`) |
| ty | `>=0.0.24` | Type checking (`python-version = "3.13"`) |
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

The Docker publish workflow (`.github/workflows/docker-publish.yml`) builds a multi-arch image (`linux/amd64`, `linux/arm64`) from the root `Dockerfile`. A Node stage compiles the SvelteKit dashboard on `$BUILDPLATFORM` (native to the runner) and the Python stage fails the build if `_static/index.html` is missing from the installed wheel. A post-publish Trivy scan of the container image detects OS-level CVEs in the `python:3.13-slim` base image and installed system packages. Results appear in the Security tab under the `trivy-image` category.

## Audit Chain Verification

If your pipeline produces an audit database (e.g. a fleet of agents writing to a shared `audit.db` that's archived by CI), run `initrunner audit verify-chain` as a job step. It exits 0 on a clean chain and 1 on any tamper or key problem:

```yaml
- name: Verify audit chain
  env:
    INITRUNNER_AUDIT_HMAC_KEY: ${{ secrets.INITRUNNER_AUDIT_HMAC_KEY }}
  run: uv run initrunner audit verify-chain --audit-db artifacts/audit.db
```

See [`docs/security/audit-chain.md`](../security/audit-chain.md) for what the chain proves and the limits of the guarantee.

## Dependabot

Dependabot is configured in `.github/dependabot.yml` for three ecosystems:

| Ecosystem | Directory | Schedule | Grouping |
|-----------|-----------|----------|----------|
| `pip` | `/` | Weekly (Monday) | pydantic, AI providers, observability |
| `npm` | `/dashboard` | Weekly (Monday) | svelte, tailwind |
| `github-actions` | `/` | Weekly (Monday) | -- |

Related packages are grouped to reduce PR noise (e.g., all pydantic packages update in a single PR).

## Python Version Support

The project declares `requires-python = ">=3.11"` and CI tests against 3.11, 3.12, and 3.13. Ruff lints against Python 3.11 (`target-version = "py311"`, the lowest supported version) while ty type-checks against Python 3.13 (`[tool.ty.environment] python-version = "3.13"`).
