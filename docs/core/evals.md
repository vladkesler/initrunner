# Agent Evals

InitRunner's eval framework lets you define test suites in YAML and run them against agent roles to verify output quality, tool usage, performance, and cost. Suites can be run manually, in CI pipelines, or as part of a development workflow.

## Quick Start

Create a test suite YAML file:

```yaml
apiVersion: initrunner/v1
kind: TestSuite
metadata:
  name: web-searcher-eval
cases:
  - name: basic-search
    prompt: "What is Docker?"
    assertions:
      - type: contains
        value: "container"
        case_insensitive: true
      - type: not_contains
        value: "error"
```

Run it:

```bash
initrunner test examples/roles/web-searcher.yaml -s eval-suite.yaml --dry-run -v
```

## Assertion Types

### `contains` / `not_contains`

Check whether the output includes (or excludes) a substring.

```yaml
assertions:
  - type: contains
    value: "Docker"
    case_insensitive: true  # default: false
  - type: not_contains
    value: "I don't know"
```

### `regex`

Match a regular expression against the output.

```yaml
assertions:
  - type: regex
    pattern: "\\b\\d{3}-\\d{4}\\b"
```

### `tool_calls`

Verify which tools the agent called during the run.

```yaml
assertions:
  - type: tool_calls
    expected: ["web_search"]
    mode: subset  # default
```

Modes:
- **`subset`** — all expected tools must appear in actual calls (extras allowed)
- **`exact`** — actual and expected must match exactly (as sets)
- **`superset`** — actual calls must be a subset of expected (no unexpected tools)

The assertion message includes F1 score (precision/recall) for diagnostics.

### `max_tokens`

Cap the total token usage for a test case.

```yaml
assertions:
  - type: max_tokens
    limit: 2000
```

### `max_latency`

Cap the wall-clock latency in milliseconds.

```yaml
assertions:
  - type: max_latency
    limit_ms: 30000
```

### `llm_judge`

Use an LLM to evaluate the output against qualitative criteria. Each criterion is evaluated independently.

```yaml
assertions:
  - type: llm_judge
    criteria:
      - "The response explains what Docker volumes are"
      - "The response includes practical usage examples"
    model: openai:gpt-4o-mini  # default
```

The judge returns pass/fail per criterion with a reason. In `--dry-run` mode, LLM judge assertions are skipped (marked as failed with a `[skipped]` message) to avoid API costs.

## Tags

Tag test cases for selective execution:

```yaml
cases:
  - name: search-test
    prompt: "Find info about Docker"
    tags: [search, docker]
    assertions:
      - type: contains
        value: "Docker"

  - name: math-test
    prompt: "What is 2+2?"
    tags: [math, fast]
    assertions:
      - type: contains
        value: "4"
```

Run only tagged cases:

```bash
initrunner test role.yaml -s suite.yaml --tag search
initrunner test role.yaml -s suite.yaml --tag search --tag math
```

Multiple `--tag` values are OR'd — a case runs if it has any of the specified tags.

## Concurrent Execution

Run test cases in parallel with `-j`:

```bash
initrunner test role.yaml -s suite.yaml -j 4
```

Each worker thread gets its own agent instance (built from the role file) to avoid shared-state issues. Result ordering is deterministic regardless of completion order.

## JSON Output

Save results to a JSON file for CI integration or historical tracking:

```bash
initrunner test role.yaml -s suite.yaml -o results.json
```

The output schema:

```json
{
  "suite_name": "my-suite",
  "timestamp": "2026-02-28T12:00:00+00:00",
  "summary": {
    "total": 3,
    "passed": 2,
    "failed": 1,
    "total_tokens": 4500,
    "total_duration_ms": 12000
  },
  "cases": [
    {
      "name": "case-1",
      "passed": true,
      "duration_ms": 3000,
      "tokens": {"input": 200, "output": 100, "total": 300},
      "tool_calls": ["web_search"],
      "assertions": [
        {"type": "contains", "passed": true, "message": "Output contains 'Docker'"}
      ],
      "output_preview": "Docker is a containerization...",
      "error": null
    }
  ]
}
```

## CLI Reference

```bash
initrunner test <role.yaml> -s <suite.yaml> [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `-s`, `--suite` | Path to test suite YAML (required) |
| `--dry-run` | Simulate with TestModel, no API calls |
| `-v`, `--verbose` | Show assertion details in output |
| `-j`, `--concurrency` | Number of concurrent workers (default: 1) |
| `-o`, `--output` | Save JSON results to file |
| `--tag` | Filter cases by tag (repeatable) |

## CI Usage

```bash
# Run evals in CI with dry-run for quick validation
initrunner test roles/agent.yaml -s evals/suite.yaml --dry-run

# Run real evals with JSON output for tracking
initrunner test roles/agent.yaml -s evals/suite.yaml -o eval-results.json -j 4

# Exit code is 1 if any test fails
echo $?
```

## Full Example

```yaml
apiVersion: initrunner/v1
kind: TestSuite
metadata:
  name: web-searcher-eval
cases:
  - name: search-query
    prompt: "Find information about Docker volumes"
    tags: [search, docker]
    assertions:
      - type: contains
        value: "volume"
        case_insensitive: true
      - type: tool_calls
        expected: ["web_search"]
        mode: subset
      - type: llm_judge
        criteria:
          - "The response explains what Docker volumes are"
          - "The response includes practical usage examples"
      - type: max_tokens
        limit: 2000
      - type: max_latency
        limit_ms: 30000

  - name: no-hallucination
    prompt: "What is the capital of Atlantis?"
    tags: [safety]
    assertions:
      - type: not_contains
        value: "the capital of Atlantis is"
        case_insensitive: true
      - type: regex
        pattern: "(?i)(fictional|myth|does not exist|no.+capital)"
```
