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

## Python Version Support

The project declares `requires-python = ">=3.11"` and CI tests against 3.11, 3.12, and 3.13. Ruff and ty are both configured to target Python 3.13 for lint and type-check rules.
