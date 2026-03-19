# Unit Tester

Reads your source code, detects the testing framework, generates test files that follow your project's conventions, runs them, and iterates until they pass. Learns your patterns across runs via memory.

## Quick start

```bash
# Install
initrunner install vladkesler/unit-tester

# Set your API key
export OPENAI_API_KEY="your-api-key"

# Generate tests for a specific file
initrunner run role.yaml -p "Generate tests for src/utils.py"

# Autonomous mode -- writes, runs, and fixes tests iteratively
initrunner run role.yaml -p "Write tests for all changed files" --autonomous
```

## Prerequisites

1. **Test framework** -- pytest (Python), jest/vitest (JavaScript), or go test (Go). The agent detects which one your project uses.
2. **Coverage tools** (optional) -- pytest-cov, jest --coverage, or equivalent. Used for gap analysis after tests pass.

## How it works

1. Detects your test framework from project config files
2. Reads existing tests to learn your conventions (naming, fixtures, structure)
3. Reads the target source code and identifies functions, branches, error paths
4. Uses git diff to prioritize testing recently changed code
5. Generates a test file following your project's conventions
6. Runs the test suite and iterates on failures (up to 5 retries)
7. Runs coverage analysis and reports gaps

## Example session

```
> initrunner run role.yaml -p "Generate tests for src/utils.py" --autonomous

[detecting framework] Found pyproject.toml with [tool.pytest], conftest.py, tests/

> activate_skill("pytest-patterns")
> activate_skill("edge-case-generation")
> activate_skill("mocking-strategies")

> recall("project test conventions")
Found: "this project uses pytest fixtures from conftest.py, factory_boy for
model factories, responses library for HTTP mocking"

> read_file("tests/test_api.py")
[notes: imports from conftest, uses @pytest.mark.parametrize, assertion style
uses plain assert, fixtures via dependency injection]

> read_file("tests/conftest.py")
[notes: db_session fixture, mock_redis fixture, tmp_config fixture]

> read_file("src/utils.py")
[identifies 4 public functions: parse_duration, slugify, retry_with_backoff,
merge_configs]

> think:
  parse_duration("2h30m") -> 9000 seconds
    happy path: "1h", "30m", "2h30m", "1d"
    error path: "abc", "", None, negative values
    edge cases: "0s", very large values, mixed case "2H30M"
  slugify("Hello World!") -> "hello-world"
    happy path: normal strings
    error path: empty string, None
    edge cases: unicode, consecutive special chars, leading/trailing hyphens
  retry_with_backoff -- needs mock for time.sleep and the target callable
  merge_configs -- needs nested dict fixtures

> write_file("tests/test_utils.py"):

  import pytest
  from src.utils import parse_duration, slugify, retry_with_backoff, merge_configs

  class TestParseDuration:
      @pytest.mark.parametrize("input_str,expected", [
          ("1h", 3600),
          ("30m", 1800),
          ("2h30m", 9000),
          ("1d", 86400),
          ("45s", 45),
      ])
      def test_parses_valid_duration_strings(self, input_str, expected):
          assert parse_duration(input_str) == expected

      def test_raises_on_invalid_format(self):
          with pytest.raises(ValueError):
              parse_duration("abc")

      def test_returns_zero_for_zero_duration(self):
          assert parse_duration("0s") == 0

  class TestSlugify:
      ...

> shell: pytest tests/test_utils.py -v
tests/test_utils.py::TestParseDuration::test_parses_valid_duration_strings[1h-3600] PASSED
tests/test_utils.py::TestParseDuration::test_parses_valid_duration_strings[30m-1800] PASSED
tests/test_utils.py::TestParseDuration::test_parses_valid_duration_strings[2h30m-9000] PASSED
tests/test_utils.py::TestParseDuration::test_parses_valid_duration_strings[1d-86400] PASSED
tests/test_utils.py::TestParseDuration::test_parses_valid_duration_strings[45s-45] PASSED
tests/test_utils.py::TestParseDuration::test_raises_on_invalid_format PASSED
tests/test_utils.py::TestParseDuration::test_returns_zero_for_zero_duration PASSED
tests/test_utils.py::TestSlugify::test_slugifies_simple_string PASSED
8 passed in 0.12s

> shell: pytest --cov=src/utils --cov-report=term-missing tests/test_utils.py
Name             Stmts   Miss  Cover   Missing
src/utils.py        47      4    92%   78-81

> activate_skill("coverage-analysis")
> think: Lines 78-81 are the retry_with_backoff timeout branch. Adding a test
  that triggers the max-retries path.

> record_episode: tested src/utils.py, 8 passed, 0 failed, 92% coverage

{
  "tests_generated": [
    {
      "file": "tests/test_utils.py",
      "source_file": "src/utils.py",
      "test_count": 8,
      "framework": "pytest"
    }
  ],
  "test_results": {
    "passed": 8,
    "failed": 0,
    "skipped": 0,
    "errors": 0
  },
  "coverage": {
    "percentage": 92,
    "uncovered_lines": ["src/utils.py:78", "src/utils.py:79", "src/utils.py:80", "src/utils.py:81"],
    "gaps": ["retry_with_backoff timeout branch when max retries exceeded"]
  },
  "framework": "pytest",
  "suggestions": [
    "Add a test for retry_with_backoff that exceeds max retries to cover lines 78-81",
    "Consider adding property-based tests for parse_duration with hypothesis",
    "merge_configs has nested dict edge cases worth parametrizing"
  ]
}
```

## Example prompts

```
Generate tests for src/utils.py
Write tests for the files changed in the last commit
Add edge case tests for the UserService class
Improve test coverage for the auth module to above 90%
What's untested in src/api/routes.py?
```

## What's inside

- **Auto-discovered skills** -- pytest patterns, jest patterns, mocking strategies, edge case generation, and coverage analysis. The agent activates the relevant ones based on your project.
- **Convention learning** -- Existing tests are indexed as a RAG corpus. The agent reads your tests to learn naming, fixture, and assertion patterns.
- **Memory across runs** -- Remembers your project's mock patterns, fixture conventions, and test run history. Gets smarter over time.
- **Iterative fixing** -- When tests fail, the agent reads the error, fixes the test, and re-runs. Up to 5 iterations in autonomous mode.
- **Structured JSON output** -- Returns test counts, pass/fail results, coverage percentage, and further suggestions.

## Customization

### Shell commands

```yaml
tools:
  - type: shell
    allowed_commands: [pytest, python, uv, npm, npx, jest, vitest, go, cargo, make]
```

### Test file patterns (RAG corpus)

```yaml
ingestion:
  sources:
    - type: directory
      glob_patterns: ["tests/**/*.py", "**/*.test.ts"]
```

### Memory limits

```yaml
memory:
  semantic:
    max_memories: 500    # project conventions
  episodic:
    max_episodes: 200    # test run history
  procedural:
    max_procedures: 100  # learned mock patterns
```

## Changing the model

Edit `spec.model` in `role.yaml`. Memory uses embeddings that inherit from the model provider -- Anthropic falls back to OpenAI embeddings (`OPENAI_API_KEY` needed).

```yaml
spec:
  model:
    provider: anthropic
    name: claude-sonnet-4-5-20250929
  memory:
    embeddings:
      provider: google
      model: text-embedding-004
```
