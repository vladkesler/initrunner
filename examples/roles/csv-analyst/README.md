# CSV Analyst

Demonstrates InitRunner's `csv_analysis` tool type, which inspects, summarizes,
and queries CSV files within a sandboxed directory — using only Python's stdlib,
with no extra dependencies.

## Setup

Run from this directory so the tool finds `sample.csv`:

```bash
cd examples/roles/csv-analyst
initrunner run csv-analyst.yaml -i
```

## Example prompts

- "What columns does sample.csv have?"
- "Summarize the unit_price column"
- "Summarize the region column"
- "Show me all rows where region is West"
- "Which product has the highest total revenue?"
- "How many rows are in the file?"
- "Give me a full summary of all columns"

## Configuration reference

The `csv_analysis` tool accepts the following options:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `root_path` | `str` | `"."` | Root directory for CSV file access. Paths cannot escape this directory. |
| `max_rows` | `int` | `1000` | Maximum rows read per tool call. Acts as a hard cap on memory usage. |
| `max_file_size_mb` | `float` | `10.0` | Files larger than this (in MB) are rejected before reading. |
| `delimiter` | `str` | `","` | CSV field delimiter. Use `"\t"` for TSV files. |

## Registered tools

- **`inspect_csv(path)`** — Show column names, inferred types, row count, and first 5 rows.
- **`summarize_csv(path, column="")`** — Statistics for a single column (numeric: min/max/mean/median/stdev; categorical: top values) or a one-liner per column when `column` is empty.
- **`query_csv(path, filter_column="", filter_value="", columns="", limit=50)`** — Filter rows and return a markdown table. Use `columns` for a subset of fields.
