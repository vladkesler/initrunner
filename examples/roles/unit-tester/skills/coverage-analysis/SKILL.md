---
name: coverage-analysis
description: >
  Running coverage tools, interpreting coverage reports, identifying
  high-risk gaps, and prioritizing which uncovered code to test first.
requires:
  bins: [python]
---

Coverage analysis for identifying and prioritizing untested code.

## When to activate

Use this skill after tests pass, or when asked to analyze coverage gaps
and determine which untested code should be covered next.

## Python coverage

- Run: `pytest --cov=<package> --cov-report=term-missing`
- The `MISS` column shows uncovered line ranges (e.g. `45-52, 78`).
- Configure in `.coveragerc` or `pyproject.toml` under `[tool.coverage]`:
  set `omit` to exclude vendored code, migrations, and test files from
  the report.
- Branch coverage: add `--cov-branch` to detect branches where only one
  path is tested.
- HTML report: `--cov-report=html` generates `htmlcov/index.html` for
  visual inspection.

## JavaScript coverage

- Jest: `npx jest --coverage` -- outputs a table and generates `coverage/`
  directory.
- Vitest: `npx vitest run --coverage` -- requires `@vitest/coverage-v8` or
  `@vitest/coverage-istanbul`.
- Interpret the table: `% Stmts`, `% Branch`, `% Funcs`, `% Lines`, and
  `Uncovered Line #s`.
- Configure in `jest.config.*` or `vitest.config.*` with
  `coverageThreshold` to enforce minimums.

## Interpreting results

- Focus on uncovered branches, not just uncovered lines -- a line can be
  "covered" while half its branches are not.
- Identify high-risk uncovered code: error handlers, input validators,
  authentication checks, and security-sensitive paths.
- Ignore generated code, `__init__.py` files that only re-export, and
  vendored third-party code.
- Look for patterns: if every error handler is uncovered, that signals a
  systematic gap in error-path testing.

## Gap prioritization

Rank uncovered code by risk, not by line count:

1. **Security-sensitive** -- authentication, authorization, input
   sanitization, cryptographic operations.
2. **Business logic** -- core domain rules, financial calculations, state
   transitions.
3. **Utilities** -- parsing, formatting, data transformation helpers.
4. **Boilerplate** -- logging setup, CLI argument wiring, import guards.

## Running

Python:
```
pytest --cov=mypackage --cov-branch --cov-report=term-missing
```

JavaScript (Jest):
```
npx jest --coverage --coverageReporters=text
```

JavaScript (Vitest):
```
npx vitest run --coverage
```

## MUST

- Report coverage percentage before and after adding tests so progress is
  measurable.
- Prioritize gaps by risk -- security-sensitive code first, boilerplate
  last.
- Test branches, not just line coverage -- a covered line with an untested
  else-branch is still a gap.

## MUST NOT

- Do not aim for 100% coverage blindly -- some code (e.g. platform-specific
  branches, debug-only paths) may not be worth covering.
- Do not count generated or vendored code in coverage metrics.
- Do not write meaningless tests just to hit coverage targets -- every test
  should verify a real behavior.
