# Testing & Dry Run

InitRunner includes a built-in eval framework for running prompt suites against agent roles and asserting on outputs. Combined with the `--dry-run` flag, this enables fast, offline iteration on prompts and role definitions without making any API calls.

## Quick Start

**1. Define a test suite:**

```yaml
# tests.yaml
apiVersion: initrunner/v1
kind: TestSuite
metadata:
  name: greeting-tests
cases:
  - name: says-hello
    prompt: "Hi there!"
    expected_output: "Hello! How can I help you today?"
    assertions:
      - type: contains
        value: "Hello"
      - type: not_contains
        value: "error"
```

**2. Run it in dry-run mode (no API calls):**

```bash
initrunner test role.yaml --suite tests.yaml --dry-run
```

**3. Run against a live model:**

```bash
initrunner test role.yaml --suite tests.yaml
```

## Dry Run

The `--dry-run` flag replaces the configured LLM with PydanticAI's `TestModel`. The entire pipeline (load role, build agent, execute run, render output) still runs — only the model call is simulated. No API keys are needed and no network requests are made.

### On the `run` command

```bash
initrunner run role.yaml -p "Hello" --dry-run
```

The simulated response is always:

```
[dry-run] Simulated response.
```

This is useful for validating that a role definition loads correctly, tools are wired up, and the CLI pipeline works end-to-end.

### On the `test` command

```bash
initrunner test role.yaml --suite tests.yaml --dry-run
```

In dry-run mode, the test runner uses each case's `expected_output` as the simulated model response. If `expected_output` is not set, the default `"[dry-run] Simulated response."` is used. Assertions are then evaluated against that simulated output.

This lets you write self-contained test suites that validate your assertion logic without calling an LLM.

## Test Suite Format

Test suites use the same YAML envelope pattern as role definitions:

```yaml
apiVersion: initrunner/v1
kind: TestSuite
metadata:
  name: my-tests       # suite name (displayed in output)
cases:
  - name: case-name     # unique name for this test case
    prompt: "..."        # prompt sent to the agent
    expected_output: "..." # optional — used as simulated output in dry-run
    assertions:          # optional — list of assertions to check
      - type: contains
        value: "expected text"
```

### Top-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `apiVersion` | `string` | yes | Must be `initrunner/v1`. |
| `kind` | `string` | yes | Must be `TestSuite`. |
| `metadata.name` | `string` | yes | Suite name, displayed in the results table. |
| `cases` | `list[TestCase]` | no | List of test cases. Defaults to `[]`. |

### Test Case Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string` | yes | Unique name for the test case. |
| `prompt` | `string` | yes | Prompt sent to the agent. |
| `expected_output` | `string` | no | Used as the simulated model output when `--dry-run` is set. Has no effect without `--dry-run`. |
| `assertions` | `list[Assertion]` | no | Assertions to evaluate against the agent's output. Defaults to `[]`. |

A case with no assertions passes as long as the agent run succeeds (no exceptions).

## Assertions

Assertions use a discriminated union on the `type` field. Three types are available:

### `contains`

Checks that the output includes a substring.

```yaml
assertions:
  - type: contains
    value: "hello"              # required — substring to look for
    case_insensitive: false     # default: false
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `value` | `string` | *(required)* | Substring that must be present in the output. |
| `case_insensitive` | `bool` | `false` | When `true`, comparison ignores case. |

### `not_contains`

Checks that the output does **not** include a substring.

```yaml
assertions:
  - type: not_contains
    value: "error"              # required — substring that must be absent
    case_insensitive: false     # default: false
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `value` | `string` | *(required)* | Substring that must **not** be present in the output. |
| `case_insensitive` | `bool` | `false` | When `true`, comparison ignores case. |

### `regex`

Checks that the output matches a regular expression (using `re.search`).

```yaml
assertions:
  - type: regex
    pattern: "\\b\\d{3}-\\d{4}\\b"   # required — regex pattern
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `pattern` | `string` | *(required)* | Python regex pattern. Matched with `re.search` (not `re.match`), so it can match anywhere in the output. |

Remember that YAML requires escaping backslashes in double-quoted strings (`"\\d+"`) or using single quotes (`'\d+'`).

## CLI Reference

### `initrunner test`

```
initrunner test <role.yaml> --suite <suite.yaml> [--dry-run] [-v]
```

| Option | Short | Required | Description |
|--------|-------|----------|-------------|
| `--suite` | `-s` | yes | Path to the test suite YAML file. |
| `--dry-run` | | no | Use `TestModel` instead of the configured LLM. No API calls. |
| `--verbose` | `-v` | no | Show per-assertion pass/fail details in the output table. |

**Exit codes:**

| Code | Meaning |
|------|---------|
| `0` | All test cases passed. |
| `1` | One or more test cases failed, or an error occurred. |

This makes `initrunner test` CI-friendly — add it to your pipeline and fail the build on assertion failures.

**Output:**

The command prints a Rich table with one row per test case:

```
Running greeting-tests (3 cases) against hello-world (dry-run)
┏━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┓
┃ Case        ┃ Status ┃ Duration ┃
┡━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━┩
│ says-hello  │ PASS   │ 2ms      │
│ no-errors   │ PASS   │ 1ms      │
│ has-number  │ FAIL   │ 1ms      │
└─────────────┴────────┴──────────┘

2/3 passed ✗ Some tests failed
```

With `--verbose`, an additional **Details** column shows each assertion result:

```
┏━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Case       ┃ Status ┃ Duration ┃ Details                         ┃
┡━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ says-hello │ PASS   │ 2ms      │ ✓ Output contains 'Hello'       │
│            │        │          │ ✓ Output does not contain 'error'│
│ has-number │ FAIL   │ 1ms      │ ✗ Output does not match '\d+'   │
└────────────┴────────┴──────────┴─────────────────────────────────┘
```

### `initrunner run --dry-run`

```
initrunner run <role.yaml> -p "prompt" --dry-run
```

Runs the agent with a `TestModel` that always returns `"[dry-run] Simulated response."`. All other flags (`-i`, `--resume`, `--no-audit`, etc.) work as usual.

## Examples

### Validate greeting behavior

```yaml
apiVersion: initrunner/v1
kind: TestSuite
metadata:
  name: greeting-suite
cases:
  - name: basic-greeting
    prompt: "Hello!"
    expected_output: "Hi there! How can I help you today?"
    assertions:
      - type: contains
        value: "help"
        case_insensitive: true
      - type: not_contains
        value: "error"
      - type: not_contains
        value: "sorry"
```

```bash
initrunner test examples/roles/hello-world.yaml \
  --suite greeting-suite.yaml --dry-run -v
```

### Validate math output with regex

```yaml
apiVersion: initrunner/v1
kind: TestSuite
metadata:
  name: math-suite
cases:
  - name: addition
    prompt: "What is 2+2?"
    expected_output: "The answer is 4."
    assertions:
      - type: regex
        pattern: '\b4\b'
      - type: not_contains
        value: "I don't know"
  - name: multiplication
    prompt: "What is 7 times 8?"
    expected_output: "7 times 8 is 56."
    assertions:
      - type: regex
        pattern: '\b56\b'
```

### CI pipeline integration

```yaml
# .github/workflows/test-agent.yml
name: Agent Tests
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run initrunner test role.yaml --suite tests.yaml --dry-run
```

The `--dry-run` flag ensures CI runs are fast, free, and deterministic — no API keys or network access required.

### Live model testing

For integration tests that run against a real LLM:

```bash
# Set your API key
export OPENAI_API_KEY=sk-...

# Run without --dry-run to use the configured model
initrunner test role.yaml --suite tests.yaml -v
```

Note that live tests are non-deterministic — LLM outputs vary between runs. Use broad assertions (`contains`, `not_contains`) rather than exact matches. The `expected_output` field is ignored when `--dry-run` is not set.

## Architecture

The eval framework lives in `initrunner/eval/`:

| Module | Purpose |
|--------|---------|
| `schema.py` | Pydantic models: `TestSuiteDefinition`, `TestCase`, assertion types |
| `assertions.py` | Pure functions: `evaluate_assertion()`, `evaluate_assertions()` |
| `runner.py` | `load_suite()`, `run_suite()`, `CaseResult`, `SuiteResult` |

The `--dry-run` flag is powered by a `model_override` parameter threaded through the execution pipeline:

```
CLI (--dry-run)
  → creates TestModel
  → runner.run_single(model_override=...)
    → executor.execute_run(model_override=...)
      → agent.run_sync(model=model_override)
```

When `model_override` is `None` (the default), the agent uses its configured model as usual.
