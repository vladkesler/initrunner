"""CSV analysis tools: inspect, summarize, and query CSV files."""

from __future__ import annotations

import csv
import statistics
from collections import Counter
from pathlib import Path

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._paths import validate_path_within
from initrunner.agent._truncate import truncate_output
from initrunner.agent.schema.tools import CsvAnalysisToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool

_MAX_OUTPUT_BYTES = 65_536  # 64 KB
_SAMPLE_TYPE_ROWS = 100  # rows sampled for type inference


def _infer_type(values: list[str]) -> str:
    """Infer column type from sampled non-empty values: int → float → string."""
    if not values:
        return "string"
    sample = values[:_SAMPLE_TYPE_ROWS]
    all_int = True
    all_float = True
    for v in sample:
        try:
            int(v)
        except ValueError:
            all_int = False
        try:
            float(v)
        except ValueError:
            all_float = False
            break
    if all_int:
        return "int"
    if all_float:
        return "float"
    return "string"


def _rows_to_md_table(headers: list[str], rows: list[dict[str, str]]) -> str:
    """Format rows as a markdown table."""
    if not rows:
        return "(no rows)"
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(row.get(h, "") for h in headers) + " |")
    return "\n".join(lines)


def _check_file_size(target: Path, max_file_size_mb: float) -> str | None:
    """Return an error string if the file exceeds the size limit, else None."""
    try:
        size_mb = target.stat().st_size / (1024 * 1024)
        if size_mb > max_file_size_mb:
            return f"Error: file exceeds max_file_size_mb limit ({max_file_size_mb} MB)"
    except OSError:
        pass
    return None


@register_tool("csv_analysis", CsvAnalysisToolConfig)
def build_csv_analysis_toolset(
    config: CsvAnalysisToolConfig,
    ctx: ToolBuildContext,
) -> FunctionToolset:
    """Build a FunctionToolset for CSV analysis operations."""
    root = Path(config.root_path).resolve()

    toolset = FunctionToolset()

    @toolset.tool
    def inspect_csv(path: str) -> str:
        """Inspect a CSV file: show column names, inferred types, row count, and first 5 rows.

        Args:
            path: Path to the CSV file, relative to the configured root directory.
        """
        raw = root / path
        err, target = validate_path_within(raw, [root], allowed_ext={".csv"}, reject_symlinks=True)
        if err:
            return err

        size_err = _check_file_size(target, config.max_file_size_mb)
        if size_err:
            return size_err

        try:
            text = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except UnicodeDecodeError:
            return "Error: file is not valid UTF-8"

        try:
            reader = csv.DictReader(text.splitlines(), delimiter=config.delimiter)
            if reader.fieldnames is None:
                return "Error: could not parse CSV: no headers found"
            headers = list(reader.fieldnames)

            rows: list[dict[str, str]] = []
            truncated = False
            for row in reader:
                if len(rows) >= config.max_rows:
                    truncated = True
                    break
                rows.append(dict(row))
        except csv.Error as e:
            return f"Error: could not parse CSV: {e}"

        # Type inference: collect non-empty values per column
        col_values: dict[str, list[str]] = {h: [] for h in headers}
        for row in rows:
            for h in headers:
                v = row.get(h, "")
                if v and len(col_values[h]) < _SAMPLE_TYPE_ROWS:
                    col_values[h].append(v)

        col_types = {h: _infer_type(col_values[h]) for h in headers}

        lines: list[str] = [
            f"**File:** {path}",
            f"**Rows inspected:** {len(rows)}" + (" (truncated)" if truncated else ""),
            f"**Columns:** {len(headers)}",
            "",
            "| Column | Type |",
            "| --- | --- |",
        ]
        for h in headers:
            lines.append(f"| {h} | {col_types[h]} |")

        lines.append("")
        lines.append("**First 5 rows:**")
        lines.append("")
        lines.append(_rows_to_md_table(headers, rows[:5]))

        return truncate_output("\n".join(lines), _MAX_OUTPUT_BYTES)

    @toolset.tool
    def summarize_csv(path: str, column: str = "") -> str:
        """Summarize a CSV file or a single column.

        If column is given, returns statistics for that column (numeric: min/max/mean/median/stdev;
        categorical: unique count and top values). If column is empty, returns a one-line summary
        for every column.

        Args:
            path: Path to the CSV file, relative to the configured root directory.
            column: Column name to summarize. Leave empty to summarize all columns.
        """
        raw = root / path
        err, target = validate_path_within(raw, [root], allowed_ext={".csv"}, reject_symlinks=True)
        if err:
            return err

        size_err = _check_file_size(target, config.max_file_size_mb)
        if size_err:
            return size_err

        try:
            text = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except UnicodeDecodeError:
            return "Error: file is not valid UTF-8"

        try:
            reader = csv.DictReader(text.splitlines(), delimiter=config.delimiter)
            if reader.fieldnames is None:
                return "Error: could not parse CSV: no headers found"
            headers = list(reader.fieldnames)

            rows: list[dict[str, str]] = []
            for row in reader:
                if len(rows) >= config.max_rows:
                    break
                rows.append(dict(row))
        except csv.Error as e:
            return f"Error: could not parse CSV: {e}"

        def _col_summary(col_name: str) -> str:
            non_empty = [row.get(col_name, "") for row in rows if row.get(col_name, "")]

            # Attempt numeric parsing
            nums: list[float] = []
            for v in non_empty:
                try:
                    nums.append(float(v))
                except ValueError:
                    break
            else:
                # Loop completed without break — all non-empty values are numeric
                if nums:
                    mn = min(nums)
                    mx = max(nums)
                    mean = statistics.mean(nums)
                    median = statistics.median(nums)
                    if len(nums) >= 2:
                        stdev_str = f"{statistics.stdev(nums):.4g}"
                    else:
                        stdev_str = "N/A (< 2 values)"
                    return (
                        f"numeric | count_non_empty={len(non_empty)}, min={mn:.4g}, "
                        f"max={mx:.4g}, mean={mean:.4g}, median={median:.4g}, stdev={stdev_str}"
                    )
                return "numeric | (no values)"

            # Categorical
            counter = Counter(non_empty)
            top10 = counter.most_common(10)
            top_str = ", ".join(f"{v!r}:{c}" for v, c in top10)
            return f"categorical | unique={len(counter)}, top values: {top_str}"

        if column:
            if column not in headers:
                avail = ", ".join(headers)
                return f"Error: column '{column}' not found. Available: {avail}"
            output = (
                f"**Column:** {column}\n**Summary:** {_col_summary(column)}\n**Rows:** {len(rows)}"
            )
        else:
            lines: list[str] = [
                f"**File:** {path}",
                f"**Rows:** {len(rows)}",
                "",
                "| Column | Summary |",
                "| --- | --- |",
            ]
            for h in headers:
                lines.append(f"| {h} | {_col_summary(h)} |")
            output = "\n".join(lines)

        return truncate_output(output, _MAX_OUTPUT_BYTES)

    @toolset.tool
    def query_csv(
        path: str,
        filter_column: str = "",
        filter_value: str = "",
        columns: str = "",
        limit: int = 50,
    ) -> str:
        """Filter and return rows from a CSV file as a markdown table.

        Args:
            path: Path to the CSV file, relative to the configured root directory.
            filter_column: Column name to filter on. Leave empty to return all rows.
            filter_value: Exact value to match in filter_column. Leave empty for no filter.
            columns: Comma-separated list of column names to include. Leave empty for all columns.
            limit: Maximum number of rows to return (default 50, capped at max_rows).
        """
        raw = root / path
        err, target = validate_path_within(raw, [root], allowed_ext={".csv"}, reject_symlinks=True)
        if err:
            return err

        size_err = _check_file_size(target, config.max_file_size_mb)
        if size_err:
            return size_err

        try:
            text = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except UnicodeDecodeError:
            return "Error: file is not valid UTF-8"

        try:
            reader = csv.DictReader(text.splitlines(), delimiter=config.delimiter)
            if reader.fieldnames is None:
                return "Error: could not parse CSV: no headers found"
            all_headers = list(reader.fieldnames)

            # Determine output columns
            col_list = (
                [c.strip() for c in columns.split(",") if c.strip()] if columns else all_headers
            )

            # Validate all requested columns and filter_column
            unknown = [c for c in col_list if c not in all_headers]
            if filter_column and filter_column not in all_headers:
                unknown.append(filter_column)
            if unknown:
                avail = ", ".join(all_headers)
                return f"Error: unknown column(s): {', '.join(unknown)}. Available: {avail}"

            effective_limit = min(limit, config.max_rows)
            rows_read = 0
            matched: list[dict[str, str]] = []

            for row in reader:
                if rows_read >= config.max_rows:
                    break
                rows_read += 1
                if filter_column and filter_value:
                    if row.get(filter_column, "") != filter_value:
                        continue
                if len(matched) < effective_limit:
                    matched.append({c: row.get(c, "") for c in col_list})

        except csv.Error as e:
            return f"Error: could not parse CSV: {e}"

        lines: list[str] = [
            f"**File:** {path}",
            f"**Rows inspected:** {rows_read}, **Rows matched:** {len(matched)}",
            "",
            _rows_to_md_table(col_list, matched),
        ]
        return truncate_output("\n".join(lines), _MAX_OUTPUT_BYTES)

    return toolset
