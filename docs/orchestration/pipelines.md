# Pipelines — Declarative Agent DAGs

Pipelines define a directed acyclic graph (DAG) of agent steps. Each step runs an agent with a prompt, and steps can depend on each other to form sequential or parallel workflows. Data flows between steps via variable interpolation.

Pipelines use a separate YAML format (`kind: Pipeline`) distinct from role definitions (`kind: Agent`).

## Quick Example

```yaml
apiVersion: initrunner/v1
kind: Pipeline
metadata:
  name: research-pipeline
  description: "Research and summarize a topic"
spec:
  steps:
    - name: research
      role_file: ./roles/researcher.yaml
      prompt: "Research {{topic}}"
      output_format: json
    - name: summarize
      role_file: ./roles/summarizer.yaml
      prompt: "Summarize this research: {{steps.research.output}}"
      depends_on: [research]
  error_strategy: fail-fast
  max_parallel: 4
```

```bash
initrunner pipeline research-pipeline.yaml --var topic="quantum computing"
```

## Pipeline Definition

A pipeline YAML has four top-level fields:

```yaml
apiVersion: initrunner/v1       # required
kind: Pipeline                   # required — must be "Pipeline"
metadata:
  name: my-pipeline              # required
  description: "What it does"    # optional
spec:
  steps: [...]                   # required — at least one step
  error_strategy: fail-fast      # default: "fail-fast"
  max_parallel: 4                # default: 4
```

### Spec Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `steps` | `list[PipelineStep]` | *(required)* | The pipeline steps. Must contain at least one step. |
| `error_strategy` | `"fail-fast" \| "continue"` | `"fail-fast"` | How to handle step failures. `fail-fast` skips remaining steps after any failure. `continue` runs all steps regardless. |
| `max_parallel` | `int` | `4` | Maximum number of steps to run concurrently within a tier. |

## Steps

Each step defines an agent to run with a prompt. Steps can be inline (local role file) or MCP (remote agent service).

```yaml
steps:
  - name: research              # required — unique step name
    role_file: ./roles/r.yaml   # required for inline mode
    prompt: "Research {{topic}}" # required — supports variable interpolation
    depends_on: [prior_step]    # default: [] — steps this depends on
    output_format: json         # default: "text" — or "json"
    timeout_seconds: 300        # default: 300
    retry_count: 0              # default: 0
    condition: "{{enabled}}"    # default: null — skip if falsy
```

### Step Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | *(required)* | Unique step identifier. Referenced by other steps in `depends_on`. |
| `role_file` | `str \| null` | `null` | Path to the agent's role YAML file. **Required** for inline steps. Resolved relative to the pipeline file's directory. |
| `url` | `str \| null` | `null` | Base URL of a remote agent's `initrunner serve` endpoint. **Required** for MCP steps. |
| `mode` | `"inline" \| "mcp"` | `"inline"` | Execution mode. Steps can mix modes within a pipeline. |
| `prompt` | `str` | *(required)* | Prompt template sent to the agent. Supports `{{variable}}` and `{{steps.NAME.output}}` interpolation. |
| `depends_on` | `list[str]` | `[]` | Step names that must complete before this step runs. |
| `output_format` | `"text" \| "json"` | `"text"` | Expected output format. When `json`, enables dot-access in downstream interpolation. |
| `timeout_seconds` | `int` | `300` | Timeout in seconds for this step. |
| `retry_count` | `int` | `0` | Number of retries on failure (reserved for future use). |
| `condition` | `str \| null` | `null` | Condition expression. Step is skipped if this evaluates to falsy. Supports variable interpolation. |
| `headers_env` | `dict[str, str]` | `{}` | Header-to-env-var mapping for MCP steps. See [Delegation](delegation.md) for details. |

## Variable Interpolation

Prompts and conditions support `{{...}}` variable interpolation. There are three types of references:

### User Variables

Passed via `--var` on the command line:

```bash
initrunner pipeline p.yaml --var topic="AI safety" --var language=fr
```

```yaml
prompt: "Research {{topic}}"        # becomes "Research AI safety"
prompt: "Translate to {{language}}" # becomes "Translate to fr"
```

### Step Output References

Reference the output of a completed step:

```yaml
- name: research
  prompt: "Research {{topic}}"
- name: summarize
  depends_on: [research]
  prompt: "Summarize: {{steps.research.output}}"
```

`{{steps.research.output}}` is replaced with the full text output of the `research` step.

### JSON Key Access

When a step has `output_format: json`, its output is parsed as JSON, enabling dot-access to specific keys:

```yaml
- name: research
  prompt: "Research {{topic}}. Return JSON with 'summary' and 'sources' keys."
  output_format: json
- name: translate
  depends_on: [research]
  prompt: "Translate this summary: {{steps.research.output.summary}}"
```

If the `research` step returns `{"summary": "AI is...", "sources": ["url1", "url2"]}`, then `{{steps.research.output.summary}}` resolves to `AI is...`.

If JSON parsing fails (the output isn't valid JSON), the raw string is used as a fallback and dot-access returns the original `{{...}}` placeholder unreplaced.

### Unresolved Variables

Variables that cannot be resolved are left as-is in the prompt. This lets the LLM see what was expected and potentially handle it.

## Conditions

Steps can be conditionally skipped using the `condition` field. The condition is evaluated after variable interpolation.

```yaml
- name: translate
  depends_on: [summarize]
  prompt: "Translate to {{language}}: {{steps.summarize.output}}"
  condition: "{{translate_enabled}}"
```

```bash
# translate step runs:
initrunner pipeline p.yaml --var translate_enabled=true --var language=fr

# translate step is skipped:
initrunner pipeline p.yaml --var translate_enabled=false
```

### Truthiness

| Value | Result |
|-------|--------|
| `true`, `True`, `TRUE` | truthy |
| `1` | truthy |
| `yes`, `Yes`, `YES` | truthy |
| any non-empty string | truthy |
| `false`, `False`, `FALSE` | falsy |
| `0` | falsy |
| `no`, `No`, `NO` | falsy |
| `""` (empty string) | falsy |

Skipped steps are marked in the output table and do not count as failures.

## Structured Output

The `output_format` field controls how step output is handled:

**`text` (default)** — Output is treated as a plain string. `{{steps.NAME.output}}` returns the full text.

**`json`** — PydanticAI's `output_type=dict` is used for structured output enforcement via tool-calling. After execution:
1. The output is serialized as JSON and parsed with `json.loads()`
2. If parsing succeeds, `{{steps.NAME.output.key}}` extracts the `key` from the parsed dict
3. If parsing fails, a warning is logged and the raw string is used as fallback

```yaml
- name: analyze
  prompt: "Analyze this data and return JSON with 'score' and 'recommendation' keys."
  output_format: json
- name: act
  depends_on: [analyze]
  prompt: "The score is {{steps.analyze.output.score}}. Recommendation: {{steps.analyze.output.recommendation}}"
```

## Execution Model

### Topological Sort

Steps are sorted into tiers based on their dependency graph:

```yaml
steps:
  - name: a                    # Tier 0 (no deps)
  - name: b                    # Tier 0 (no deps)
  - name: c
    depends_on: [a]            # Tier 1 (depends on a)
  - name: d
    depends_on: [a, b]         # Tier 1 (depends on a and b)
  - name: e
    depends_on: [c, d]         # Tier 2 (depends on c and d)
```

Execution order: `{a, b}` (parallel) -> `{c, d}` (parallel) -> `{e}`.

### Parallel Execution

Steps within the same tier run concurrently using a `ThreadPoolExecutor`. The `max_parallel` setting limits the number of concurrent workers per tier.

Threading is appropriate because inline agents are I/O-bound (API calls to OpenAI/Claude/Ollama). For CPU-heavy local inference, use MCP mode with separate processes.

### Error Strategy

**`fail-fast` (default)** — When any step fails, remaining tiers are skipped. Steps already running in the current tier complete, but subsequent tiers are marked as skipped.

**`continue`** — All steps run regardless of failures. The pipeline result reports `success: false` if any step failed, but all steps get a chance to execute.

### Mixed Modes

Steps can mix inline and MCP modes within a single pipeline. This lets you run some agents locally and call others remotely:

```yaml
steps:
  - name: local-research
    role_file: ./roles/researcher.yaml
    prompt: "Research {{topic}}"
  - name: remote-translate
    url: http://translator:8000
    mode: mcp
    prompt: "Translate: {{steps.local-research.output}}"
    depends_on: [local-research]
    headers_env:
      Authorization: TRANSLATOR_TOKEN
```

## CLI

### Run a Pipeline

```bash
initrunner pipeline <pipeline.yaml> [options]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `pipeline_file` | `Path` | *(required)* | Path to the pipeline YAML file. |
| `--var` | `str` | *(repeatable)* | Variable in `key=value` format. Can be specified multiple times. |
| `--dry-run` | `bool` | `false` | Validate and display step graph without executing. |
| `--audit-db` | `Path` | `~/.initrunner/audit.db` | Path to audit database. |
| `--no-audit` | `bool` | `false` | Disable audit logging. |

### Examples

```bash
# Basic run with variables
initrunner pipeline pipeline.yaml --var topic="AI safety" --var language=fr

# Dry run — validate and show step graph
initrunner pipeline pipeline.yaml --var topic="testing" --dry-run

# Disable audit logging
initrunner pipeline pipeline.yaml --var topic="testing" --no-audit

# Custom audit database
initrunner pipeline pipeline.yaml --var topic="testing" --audit-db ./pipeline-audit.db
```

### Dry Run Output

The `--dry-run` flag validates the pipeline and displays the step graph without executing:

```
      Pipeline: research-pipeline
+----------+--------+-----------------------+------------+-----------+--------+
| Step     | Mode   | Source                | Depends On | Condition | Output |
+----------+--------+-----------------------+------------+-----------+--------+
| research | inline | ./roles/researcher.yaml| (none)    | (always)  | json   |
| summarize| inline | ./roles/summarizer.yaml| research  | (always)  | text   |
+----------+--------+-----------------------+------------+-----------+--------+

Variables:
  topic = AI safety

Strategy: fail-fast
Max parallel: 4

Pipeline definition is valid.
```

### Execution Output

After execution, a results table is displayed:

```
     Pipeline: research-pipeline (a1b2c3d4e5f6)
+-----------+------+----------+--------------------------+
| Step      | Status| Duration | Output (preview)        |
+-----------+------+----------+--------------------------+
| research  | PASS | 2340ms   | {"summary": "Quantum ... |
| summarize | PASS | 1890ms   | Quantum computing has... |
+-----------+------+----------+--------------------------+

Total: 4230ms Pipeline succeeded
```

Failed or skipped steps are clearly marked:

```
| research  | PASS | 2340ms   | {"summary": "...         |
| summarize | FAIL | 150ms    | (API rate limit exceeded) |
| translate | SKIP | 0ms      | (Skipped due to fail-...) |
```

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Pipeline succeeded (all steps passed or were skipped) |
| `1` | Pipeline failed (one or more steps failed) or validation error |

## DAG Validation

The pipeline schema validates the dependency graph at parse time:

- **Unique step names** — No two steps can have the same name
- **Valid dependency references** — All names in `depends_on` must match an existing step
- **Cycle detection** — Circular dependencies are rejected (detected via Kahn's algorithm)
- **Mode constraints** — Inline steps require `role_file`; MCP steps require `url`

```yaml
# This is rejected at parse time:
steps:
  - name: a
    role_file: a.yaml
    prompt: "..."
    depends_on: [b]    # cycle: a -> b -> a
  - name: b
    role_file: b.yaml
    prompt: "..."
    depends_on: [a]
```

```
Error: Validation failed: Pipeline contains a dependency cycle
```

## Audit Integration

Pipeline steps executed in inline mode are logged to the audit trail with `trigger_type: "pipeline"`. Each step creates its own audit record, making it possible to trace the full execution:

```bash
# Export audit records for pipeline runs
initrunner audit export --trigger-type pipeline
```

In MCP mode, each remote agent has its own local audit database.

## Examples

### Research and Summarize

```yaml
apiVersion: initrunner/v1
kind: Pipeline
metadata:
  name: research-summarize
spec:
  steps:
    - name: research
      role_file: ./roles/researcher.yaml
      prompt: "Research {{topic}} in depth. Return JSON with 'findings' and 'sources' keys."
      output_format: json
    - name: summarize
      role_file: ./roles/summarizer.yaml
      prompt: |
        Summarize these research findings:
        {{steps.research.output.findings}}

        Sources: {{steps.research.output.sources}}
      depends_on: [research]
```

```bash
initrunner pipeline research-summarize.yaml --var topic="fusion energy"
```

### Parallel Analysis with Merge

```yaml
apiVersion: initrunner/v1
kind: Pipeline
metadata:
  name: parallel-analysis
spec:
  steps:
    - name: sentiment
      role_file: ./roles/sentiment-analyzer.yaml
      prompt: "Analyze sentiment of: {{text}}"
    - name: entities
      role_file: ./roles/entity-extractor.yaml
      prompt: "Extract entities from: {{text}}"
    - name: merge
      role_file: ./roles/report-writer.yaml
      prompt: |
        Create a report combining:
        Sentiment: {{steps.sentiment.output}}
        Entities: {{steps.entities.output}}
      depends_on: [sentiment, entities]
  max_parallel: 2
```

`sentiment` and `entities` run in parallel, then `merge` runs after both complete.

### Conditional Translation

```yaml
apiVersion: initrunner/v1
kind: Pipeline
metadata:
  name: translate-pipeline
spec:
  steps:
    - name: draft
      role_file: ./roles/writer.yaml
      prompt: "Write a blog post about {{topic}}"
    - name: translate
      role_file: ./roles/translator.yaml
      prompt: "Translate to {{language}}: {{steps.draft.output}}"
      depends_on: [draft]
      condition: "{{do_translate}}"
  error_strategy: continue
```

```bash
# With translation:
initrunner pipeline translate.yaml --var topic="AI" --var language=fr --var do_translate=true

# Without translation (translate step is skipped):
initrunner pipeline translate.yaml --var topic="AI" --var do_translate=false
```

### Mixed Local and Remote

```yaml
apiVersion: initrunner/v1
kind: Pipeline
metadata:
  name: hybrid-pipeline
spec:
  steps:
    - name: research
      role_file: ./roles/researcher.yaml
      prompt: "Research {{topic}}"
    - name: translate
      url: http://translator-service:8000
      mode: mcp
      prompt: "Translate to {{language}}: {{steps.research.output}}"
      depends_on: [research]
      headers_env:
        Authorization: TRANSLATOR_API_KEY
```
