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

Assertions use a discriminated union on the `type` field. Output-based types
(`contains`, `not_contains`, `regex`, `max_tokens`, `max_latency`, `tool_calls`,
`llm_judge`) check the final result. Timeline- and span-based types
(`tool_order`, `reasoning_budget`, `memory_consulted`, `span`) inspect the
structured run-event timeline and OTel spans, so they can assert on *how* the
agent reached its answer, not just the answer itself.

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

### `tool_calls`

Checks which tools the agent called, comparing the observed set against an
expected set.

```yaml
assertions:
  - type: tool_calls
    expected: ["web_search", "calculator"]
    mode: subset        # subset (default) | exact | superset
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `expected` | `list[string]` | *(required)* | Tool names the agent is expected to call. |
| `mode` | `string` | `subset` | `subset`: all expected appear; `exact`: sets match exactly; `superset`: no tools beyond expected. |

### `max_tokens` and `max_latency`

```yaml
assertions:
  - type: max_tokens
    limit: 4000           # total tokens must be <= this
  - type: max_latency
    limit_ms: 5000        # wall-clock duration must be <= this
```

### `llm_judge`

Scores the output against natural-language criteria using an LLM judge. Skipped
in `--dry-run`.

```yaml
assertions:
  - type: llm_judge
    criteria:
      - "The response is polite"
      - "The response answers the question"
    model: "openai:gpt-4o-mini"   # default
```

### Timeline- and span-based assertions

These read the structured run-event timeline (`RunResult.event_timeline`) and,
on the pydantic-evals path, the OTel span tree. They let you assert on the
agent's process: did it call tools in the right order, stay within a reasoning
budget, or consult memory?

The timeline is the always-available source, so these assertions work without
Logfire or an OTLP backend configured. When you run via `--pydantic-evals`
against an instrumented agent, span-based checks additionally query a real OTel
`SpanTree`.

#### `tool_order`

Asserts the relative or exact order of tool calls.

```yaml
assertions:
  - type: tool_order
    sequence: ["web_search", "summarize"]
    strict: false        # false: relative order (gaps allowed); true: exact sequence
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sequence` | `list[string]` | *(required)* | Tool names in the order they must appear. |
| `strict` | `bool` | `false` | `false`: names appear in this relative order, other calls allowed in between. `true`: the observed tool-call sequence equals `sequence` exactly. |

#### `reasoning_budget`

Asserts the agent stayed within a thinking-token budget. A run that reports zero
reasoning tokens is treated as within any budget, so models that do not emit
thinking are never penalized.

```yaml
assertions:
  - type: reasoning_budget
    max_reasoning_tokens: 2000
```

#### `memory_consulted`

Asserts the agent did (or did not) consult memory during the run.

```yaml
assertions:
  - type: memory_consulted
    expected: true                       # set false to assert memory was NOT touched
    tools: ["recall_memory", "search_memory", "memory_search"]   # default names
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `expected` | `bool` | `true` | `true` requires a memory tool call; `false` asserts none happened. |
| `tools` | `list[string]` | `["recall_memory", "search_memory", "memory_search"]` | Tool names treated as memory consultation. |

#### `span`

Matches spans by name and attribute. Falls back to the run-event timeline when
no OTel spans were recorded (treating each tool call as a span named after the
tool, with its entry keys as attributes).

```yaml
assertions:
  - type: span
    name_contains: "web_search"   # substring match on span / tool name
    attribute: "tool_call_id"     # optional: require this attribute key
    attribute_value: "abc123"     # optional: require this attribute value
    count: 1                      # optional: exact match count; omit for "at least one"
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name_contains` | `string` | *(none)* | Substring that must appear in the span or tool name. |
| `attribute` | `string` | *(none)* | Attribute key the span must carry. |
| `attribute_value` | `string` | *(none)* | Required value for `attribute` (only checked when `attribute` is set). |
| `count` | `int` | *(none)* | When set, the number of matching spans must equal it exactly. Otherwise at least one match is required. |

## Running on pydantic-evals

InitRunner can run the same YAML suite through
[pydantic-evals](https://ai.pydantic.dev/evals/), translating each case into a
`Dataset` of `Case` objects with evaluators built from your assertions. Pass
`--pydantic-evals` to opt in (requires the `observability` extra, which bundles
`pydantic-evals`):

```bash
uv pip install "initrunner[observability]"
initrunner test role.yaml --suite tests.yaml --pydantic-evals -v
```

The output table and exit codes are identical to the default path, so this is a
drop-in for CI. The difference is under the hood: each case runs inside an OTel
span-capture block, so `span` assertions can query a real span tree, and you can
reach the native `EvaluationReport` from Python for aggregate metrics and span
analysis:

```python
from pathlib import Path

from initrunner.agent.loader import load_and_build
from initrunner.eval.runner import load_suite, run_suite_pydantic_evals

role, agent = load_and_build(Path("role.yaml"))
suite = load_suite(Path("tests.yaml"))

result = run_suite_pydantic_evals(agent, role, suite)
print(result.suite_result.passed, "/", result.suite_result.total, "passed")

# Native pydantic-evals report for deeper analysis.
report = result.report
report.print()                       # rich table with per-evaluator scores
for case in report.cases:
    print(case.name, case.assertions)
```

`run_suite_pydantic_evals` returns a `PydanticEvalsResult` with two fields:
`suite_result` (the familiar `SuiteResult`, so `to_dict()` exports are unchanged)
and `report` (the `pydantic_evals.reporting.EvaluationReport`).

## CLI Reference

### `initrunner test`

```
initrunner test <PATH> --suite <suite.yaml> [--dry-run] [-v]
```

| Option | Short | Required | Description |
|--------|-------|----------|-------------|
| `--suite` | `-s` | yes | Path to the test suite YAML file. |
| `--dry-run` | | no | Use `TestModel` instead of the configured LLM. No API calls. |
| `--verbose` | `-v` | no | Show per-assertion pass/fail details in the output table. |
| `--concurrency` | `-j` | no | Number of concurrent workers (default `1`). |
| `--tag` | | no | Filter cases by tag. Repeatable. |
| `--pydantic-evals` | | no | Run via pydantic-evals with OTel span capture. Needs the `observability` extra. |

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
initrunner run <PATH> -p "prompt" --dry-run
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

## Async Tests

Tests for async execution use `pytest-asyncio`:

| Test File | Coverage |
|-----------|----------|
| `tests/test_flow_graph.py` | Graph-based flow execution: fan-out parallelism, fan-in join ordering, callbacks, failure isolation |
| `tests/test_executor_async.py` | `execute_run_async`, `execute_run_stream_async`, async retry logic, `prefer_async` tool building |
| `tests/test_signal_async.py` | Async signal handler, double-Ctrl-C force exit |

These tests use `@pytest.mark.asyncio` and mock PydanticAI's `agent.run()` / `agent.run_stream()` to avoid real LLM calls.

## Architecture

The eval framework lives in `initrunner/eval/`:

| Module | Purpose |
|--------|---------|
| `schema.py` | Pydantic models: `TestSuiteDefinition`, `TestCase`, assertion types |
| `assertions.py` | Pure functions: `evaluate_assertion()`, `evaluate_assertions()`, timeline helpers |
| `runner.py` | `load_suite()`, `run_suite()`, `run_suite_pydantic_evals()`, `CaseResult`, `SuiteResult` |
| `evaluators.py` | pydantic-evals `Evaluator` adapters backed by `assertions.py`; only imported on the `--pydantic-evals` path |
| `judge.py` | LLM-as-judge agent (`get_judge_agent`, `parse_judge_response`, `run_judge_sync`) |

Both runner paths share `assertions.py`, so the bespoke runner and the
pydantic-evals runner agree on pass/fail semantics. Span capture for the
pydantic-evals path uses `initrunner.observability.capture_span_tree()`, which
attaches an in-memory exporter to the active OTel provider and degrades to the
run-event timeline when no provider is configured.

The `--dry-run` flag is powered by a `model_override` parameter threaded through
the execution pipeline: the CLI creates a `TestModel`, `run_suite()` forwards it
to `executor.execute_run(model_override=...)`, and the executor passes it to
`agent.run_sync(model=model_override)`. When `model_override` is `None` (the
default), the agent uses its configured model as usual.
