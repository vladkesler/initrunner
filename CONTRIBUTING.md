# Contributing to InitRunner

Thanks for your interest in contributing! This guide covers the basics.

## Reporting Issues

Open a GitHub issue with:

- A clear title and description
- Steps to reproduce (for bugs)
- Your Python version and OS
- The relevant role YAML (if applicable)

**Security vulnerabilities:** please see [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Development Setup

```bash
# Clone and install
git clone https://github.com/vladkesler/initrunner.git
cd initrunner
uv sync

# Run tests
uv run pytest tests/ -v

# Lint and format
uv run ruff check .
uv run ruff format .

# Type check
uv run ty check initrunner/
```

## PR Guidelines

1. Fork the repo and create a feature branch from `main`.
2. Keep changes focused — one logical change per PR.
3. Add tests for new functionality.
4. Ensure all checks pass: `uv run pytest tests/ -v && uv run ruff check . && uv run ruff format --check .`
5. Write a clear PR description explaining what and why.

## Architecture

See [CLAUDE.md](CLAUDE.md) for project structure, architecture decisions, and key conventions.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
