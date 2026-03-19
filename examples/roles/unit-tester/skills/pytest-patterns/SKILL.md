---
name: pytest-patterns
description: >
  Pytest best practices including fixtures, parametrize, markers, and
  assertion patterns for Python test suites.
requires:
  bins: [python]
---

Pytest patterns and best practices for Python test suites.

## When to activate

Use this skill when the project has pyproject.toml, setup.cfg, pytest.ini,
conftest.py, or a tests/ directory containing `*_test.py` or `test_*.py`
files.

## Test file structure

- Name test files `test_<module>.py` to mirror the source module they cover.
- Group related tests inside a class (`class TestParseConfig:`) when they
  share setup or conceptually belong together.
- Name test functions `test_<behavior_under_test>` -- the name should read
  like a specification (e.g. `test_parse_config_raises_on_missing_key`).

## Fixtures

- Place shared fixtures in `conftest.py` so they are automatically
  discovered by pytest.
- Scope controls lifetime: `function` (default, one per test), `class`,
  `module`, `session`.
- Use `yield` fixtures for setup/teardown -- code after yield runs as
  cleanup even if the test fails.
- Fixture factories (a fixture that returns a callable) let tests customize
  object creation per-call.
- Parametrized fixtures (`@pytest.fixture(params=[...])`) run every
  dependent test once per parameter value.

## Parametrize

- `@pytest.mark.parametrize("x,expected", [(1, 2), (3, 6)])` runs the
  test once per tuple.
- Multiple `@pytest.mark.parametrize` decorators stack -- pytest generates
  the cartesian product.
- Use `indirect=True` to route parameter values through a fixture before
  they reach the test.

## Markers

- `@pytest.mark.slow` -- tag long-running tests so they can be skipped with
  `pytest -m "not slow"`.
- `@pytest.mark.skip(reason="...")` -- unconditionally skip.
- `@pytest.mark.xfail(reason="...")` -- expect failure; test still runs but
  does not fail the suite.
- Register custom markers in `pyproject.toml` under `[tool.pytest.ini_options]`
  to avoid warnings.
- Filter with `pytest -m "marker_name"`.

## Assertions

- Use plain `assert` -- pytest rewrites it to show detailed diffs on failure.
- `with pytest.raises(ValueError, match=r"expected .* pattern"):` for
  exception type and message verification.
- `pytest.approx(0.1 + 0.2, abs=1e-9)` for floating-point comparisons.
- Use `match=` on `pytest.raises` to verify the error message, not just the
  exception type.

## Running

- `pytest -v` -- verbose output with one line per test.
- `pytest -x` -- fail fast, stop on first failure.
- `pytest -k "pattern"` -- run only tests whose name matches the pattern.
- `pytest --tb=short` -- shorter tracebacks for quick scanning.

## MUST

- Always use descriptive test names that explain the expected behavior.
- Test one behavior per function -- a test should have a single reason to
  fail.
- Use fixtures instead of setup/teardown methods.
- Parametrize repetitive test cases rather than copy-pasting test functions.

## MUST NOT

- Do not use `unittest.TestCase` unless the project already uses it.
- Do not hardcode file paths -- use `tmp_path` or `tmp_path_factory`.
- Do not use `sleep()` in tests -- use mocking or polling helpers.
- Do not leave `print()` statements in committed tests -- use logging or
  `capsys` if output matters.
