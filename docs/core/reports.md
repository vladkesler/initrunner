# Report Export

InitRunner can export a structured markdown report after any `run` command. Reports capture the prompt, output, token usage, timing, and status — useful for PR reviews, changelog generation, CI analysis, or any workflow where you need a persistent artifact from an agent run.

## Quick Start

```bash
# Export a report after a run
initrunner run role.yaml -p "Review this PR" --export-report

# Custom output path
initrunner run role.yaml -p "Review this PR" --export-report --report-path ./review.md

# Use a purpose-built template
initrunner run role.yaml -p "Review this PR" --export-report --report-template pr-review

# Combine with --dry-run for testing
initrunner run role.yaml -p "Hello" --dry-run --export-report
```

Reports are always written regardless of whether the run succeeds or fails. A failed run produces a report with the error details.

## CLI Options

These flags are available on the `run` command:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--export-report` | `bool` | `false` | Export a markdown report after the run. |
| `--report-path` | `Path` | `initrunner-report.md` | Output file path for the report. |
| `--report-template` | `str` | `default` | Report template to use: `default`, `pr-review`, `changelog`, `ci-fix`. |

## Templates

Four built-in templates are included. All receive the same data — they differ in layout and emphasis.

### `default`

Full report with header, prompt, output, metrics table, and iteration breakdown (if autonomous). Best for general-purpose use.

```bash
initrunner run role.yaml -p "Summarize this" --export-report
```

### `pr-review`

Compact layout with a "PR Review Report" header. The agent output is presented as the review body. Metrics are shown in a single-row table.

```bash
initrunner run role.yaml -p "Review the changes in this diff" \
  --export-report --report-template pr-review
```

### `changelog`

"Changelog Report" header with the output as changelog content. Compact metrics.

```bash
initrunner run role.yaml -p "Generate a changelog from these commits" \
  --export-report --report-template changelog
```

### `ci-fix`

"CI Fix Analysis" header with iteration details (especially useful with `--autonomous`), followed by output and metrics.

```bash
initrunner run role.yaml -p "Fix the failing CI tests" \
  -a --export-report --report-template ci-fix
```

## Report Contents

Every report includes:

| Field | Description |
|-------|-------------|
| Agent name | From `metadata.name` in the role YAML |
| Model | Provider and model name (e.g. `openai:gpt-5-mini`) |
| Run ID | Unique identifier for the run |
| Timestamp | ISO 8601 UTC timestamp |
| Status | `Success` or `Failed` |
| Mode | `dry-run` or `autonomous` (if applicable) |
| Prompt | The input prompt text |
| Output | The agent's response (or error message on failure) |
| Tokens In/Out/Total | Token usage metrics |
| Tool Calls | Number of tool invocations |
| Duration | Wall-clock time in milliseconds |

For autonomous runs (`-a`), the `default` and `ci-fix` templates also include per-iteration breakdowns showing tokens, tool calls, duration, and a preview of each iteration's output.

## Behaviour

- **Always exports**: Reports are written whether the run succeeds or fails. Failed runs include the error message.
- **Early validation**: An unknown template name is a hard error before execution — the agent never runs.
- **Export failures are warnings**: If report writing fails (e.g. permission denied), a warning is printed but the run exit code is not affected.
- **Works with all run modes**: Single-shot (`-p`), autonomous (`-a`), and interactive with initial prompt (`-p -i`). For `-p -i`, the report captures the initial prompt/response before entering interactive mode.

## Examples

### PR review with custom path

```bash
initrunner run code-reviewer.yaml \
  -p "Review the diff in review.patch" \
  -A review.patch \
  --export-report \
  --report-template pr-review \
  --report-path ./pr-review-report.md
```

### CI fix with autonomous mode

```bash
initrunner run ci-fixer.yaml \
  -p "The build is failing on test_auth. Fix it." \
  -a --max-iterations 5 \
  --export-report \
  --report-template ci-fix \
  --report-path /tmp/ci-analysis.md
```

### Dry-run report for testing

```bash
initrunner run role.yaml -p "Hello" --dry-run --export-report
cat initrunner-report.md
```

## Programmatic Usage

The report module can be used directly from Python:

```python
from initrunner.report import build_report_context, render_report, export_report

# Build context from a run result
context = build_report_context(role, result, prompt, dry_run=False)

# Render to string
markdown = render_report(context, template_name="pr-review")

# Or export directly to file
path = export_report(role, result, prompt, Path("report.md"),
                     template_name="default", dry_run=False)
```

The `services.py` layer also provides `export_run_report_sync()` for use from the API or TUI.
