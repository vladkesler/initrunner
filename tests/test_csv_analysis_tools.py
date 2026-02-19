"""Tests for the CSV analysis tool: schema, toolset builder, and tool functions."""

from __future__ import annotations

import csv
from pathlib import Path

from initrunner.agent.schema.role import AgentSpec
from initrunner.agent.schema.tools import CsvAnalysisToolConfig
from initrunner.agent.tools._registry import ToolBuildContext
from initrunner.agent.tools.csv_analysis import (
    _infer_type,
    _rows_to_md_table,
    build_csv_analysis_toolset,
)


def _make_ctx():
    """Build a minimal ToolBuildContext for tests."""
    from initrunner.agent.schema.role import RoleDefinition

    role = RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test"},
            "spec": {
                "role": "test",
                "model": {"provider": "openai", "name": "gpt-4o-mini"},
            },
        }
    )
    return ToolBuildContext(role=role)


def _write_csv(
    path: Path,
    rows: list[dict],
    delimiter: str = ",",
) -> None:
    """Write a CSV file at the given path."""
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    headers = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Schema / config tests
# ---------------------------------------------------------------------------


class TestCsvConfig:
    def test_defaults(self):
        config = CsvAnalysisToolConfig()
        assert config.type == "csv_analysis"
        assert config.root_path == "."
        assert config.max_rows == 1000
        assert config.max_file_size_mb == 10.0
        assert config.delimiter == ","

    def test_summary(self):
        config = CsvAnalysisToolConfig(root_path="/data/csv")
        assert config.summary() == "csv_analysis: /data/csv"

    def test_summary_default(self):
        config = CsvAnalysisToolConfig()
        assert config.summary() == "csv_analysis: ."

    def test_custom_values(self):
        config = CsvAnalysisToolConfig(
            root_path="./data",
            max_rows=500,
            max_file_size_mb=5.0,
            delimiter="\t",
        )
        assert config.max_rows == 500
        assert config.delimiter == "\t"

    def test_in_agent_spec(self):
        spec_data = {
            "role": "Test agent",
            "model": {"provider": "openai", "name": "gpt-4o-mini"},
            "tools": [{"type": "csv_analysis"}],
        }
        spec = AgentSpec.model_validate(spec_data)
        assert len(spec.tools) == 1
        assert isinstance(spec.tools[0], CsvAnalysisToolConfig)

    def test_in_agent_spec_with_options(self):
        spec_data = {
            "role": "Test agent",
            "model": {"provider": "openai", "name": "gpt-4o-mini"},
            "tools": [
                {
                    "type": "csv_analysis",
                    "root_path": "./reports",
                    "max_rows": 200,
                    "delimiter": "\t",
                }
            ],
        }
        spec = AgentSpec.model_validate(spec_data)
        tool = spec.tools[0]
        assert isinstance(tool, CsvAnalysisToolConfig)
        assert tool.root_path == "./reports"
        assert tool.max_rows == 200
        assert tool.delimiter == "\t"


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestInferType:
    def test_integer_values(self):
        assert _infer_type(["1", "2", "3", "42"]) == "int"

    def test_float_values(self):
        assert _infer_type(["1.5", "2.3", "3.14"]) == "float"

    def test_mixed_int_float(self):
        # "1" can be int but "1.5" cannot — result is float
        assert _infer_type(["1", "1.5", "2"]) == "float"

    def test_string_values(self):
        assert _infer_type(["apple", "banana", "cherry"]) == "string"

    def test_empty_list(self):
        assert _infer_type([]) == "string"

    def test_mixed_with_string(self):
        assert _infer_type(["1", "2", "not-a-number"]) == "string"


class TestRowsToMdTable:
    def test_basic_table(self):
        headers = ["name", "age"]
        rows = [{"name": "Alice", "age": "30"}, {"name": "Bob", "age": "25"}]
        result = _rows_to_md_table(headers, rows)
        assert "| name | age |" in result
        assert "| --- | --- |" in result
        assert "| Alice | 30 |" in result
        assert "| Bob | 25 |" in result

    def test_empty_rows(self):
        assert _rows_to_md_table(["a", "b"], []) == "(no rows)"


# ---------------------------------------------------------------------------
# Toolset builder tests
# ---------------------------------------------------------------------------


class TestCsvToolset:
    def test_builds_toolset(self, tmp_path):
        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        assert "inspect_csv" in toolset.tools
        assert "summarize_csv" in toolset.tools
        assert "query_csv" in toolset.tools


# ---------------------------------------------------------------------------
# inspect_csv tests
# ---------------------------------------------------------------------------


class TestInspectCsv:
    def test_happy_path(self, tmp_path):
        rows = [
            {"id": "1", "name": "Alice", "score": "95.5"},
            {"id": "2", "name": "Bob", "score": "87.0"},
            {"id": "3", "name": "Carol", "score": "92.3"},
        ]
        _write_csv(tmp_path / "data.csv", rows)

        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["inspect_csv"].function

        result = fn(path="data.csv")
        assert "data.csv" in result
        assert "id" in result
        assert "name" in result
        assert "score" in result
        assert "Rows inspected: 3" in result or "**Rows inspected:** 3" in result

    def test_type_inference(self, tmp_path):
        rows = [
            {"int_col": "1", "float_col": "1.5", "str_col": "hello"},
            {"int_col": "2", "float_col": "2.5", "str_col": "world"},
        ]
        _write_csv(tmp_path / "types.csv", rows)

        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["inspect_csv"].function

        result = fn(path="types.csv")
        assert "int" in result
        assert "float" in result
        assert "string" in result

    def test_first_five_rows_shown(self, tmp_path):
        rows = [{"n": str(i)} for i in range(10)]
        _write_csv(tmp_path / "data.csv", rows)

        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["inspect_csv"].function

        result = fn(path="data.csv")
        assert "First 5 rows" in result

    def test_truncated_flag(self, tmp_path):
        rows = [{"n": str(i)} for i in range(20)]
        _write_csv(tmp_path / "data.csv", rows)

        config = CsvAnalysisToolConfig(root_path=str(tmp_path), max_rows=5)
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["inspect_csv"].function

        result = fn(path="data.csv")
        assert "truncated" in result

    def test_not_truncated_when_within_max_rows(self, tmp_path):
        rows = [{"n": str(i)} for i in range(5)]
        _write_csv(tmp_path / "data.csv", rows)

        config = CsvAnalysisToolConfig(root_path=str(tmp_path), max_rows=10)
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["inspect_csv"].function

        result = fn(path="data.csv")
        assert "truncated" not in result

    def test_empty_file(self, tmp_path):
        (tmp_path / "empty.csv").write_text("", encoding="utf-8")
        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["inspect_csv"].function

        result = fn(path="empty.csv")
        assert result.startswith("Error:")

    def test_non_utf8_file(self, tmp_path):
        (tmp_path / "bad.csv").write_bytes(b"\xff\xfe bad bytes")
        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["inspect_csv"].function

        result = fn(path="bad.csv")
        assert "Error: file is not valid UTF-8" == result

    def test_file_too_large(self, tmp_path, monkeypatch):
        rows = [{"x": "1"}]
        _write_csv(tmp_path / "big.csv", rows)

        # Patch stat to report a large file size
        real_stat = Path.stat

        def fake_stat(self, **kwargs):
            s = real_stat(self, **kwargs)
            # Return a stat_result-like object with inflated st_size
            import os

            return os.stat_result(
                (
                    s.st_mode,
                    s.st_ino,
                    s.st_dev,
                    s.st_nlink,
                    s.st_uid,
                    s.st_gid,
                    200 * 1024 * 1024,
                    s.st_atime,
                    s.st_mtime,
                    s.st_ctime,
                )
            )

        monkeypatch.setattr(Path, "stat", fake_stat)

        config = CsvAnalysisToolConfig(root_path=str(tmp_path), max_file_size_mb=10.0)
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["inspect_csv"].function

        result = fn(path="big.csv")
        assert "Error: file exceeds max_file_size_mb limit" in result

    def test_path_outside_root(self, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        rows = [{"x": "1"}]
        _write_csv(other / "secret.csv", rows)

        config = CsvAnalysisToolConfig(root_path=str(tmp_path / "safe"))
        (tmp_path / "safe").mkdir()
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["inspect_csv"].function

        result = fn(path="../other/secret.csv")
        assert result.startswith("Error:")

    def test_file_not_found(self, tmp_path):
        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["inspect_csv"].function

        result = fn(path="nonexistent.csv")
        assert result.startswith("Error:")

    def test_non_csv_extension_rejected(self, tmp_path):
        (tmp_path / "data.txt").write_text("a,b\n1,2\n", encoding="utf-8")
        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["inspect_csv"].function

        result = fn(path="data.txt")
        assert result.startswith("Error:")


# ---------------------------------------------------------------------------
# summarize_csv tests
# ---------------------------------------------------------------------------


class TestSummarizeCsv:
    def _make_sales_csv(self, tmp_path: Path) -> None:
        rows = [
            {"product": "A", "price": "10.0", "region": "North"},
            {"product": "B", "price": "20.0", "region": "South"},
            {"product": "A", "price": "15.0", "region": "North"},
            {"product": "C", "price": "30.0", "region": "East"},
            {"product": "B", "price": "20.0", "region": "South"},
        ]
        _write_csv(tmp_path / "sales.csv", rows)

    def test_numeric_column(self, tmp_path):
        self._make_sales_csv(tmp_path)
        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["summarize_csv"].function

        result = fn(path="sales.csv", column="price")
        assert "min=" in result
        assert "max=" in result
        assert "mean=" in result
        assert "median=" in result
        assert "stdev=" in result

    def test_categorical_column(self, tmp_path):
        self._make_sales_csv(tmp_path)
        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["summarize_csv"].function

        result = fn(path="sales.csv", column="region")
        assert "categorical" in result
        assert "unique=" in result
        assert "top values" in result

    def test_stdev_guard_single_value(self, tmp_path):
        rows = [{"x": "42"}]
        _write_csv(tmp_path / "single.csv", rows)

        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["summarize_csv"].function

        result = fn(path="single.csv", column="x")
        assert "N/A (< 2 values)" in result

    def test_full_summary_no_column(self, tmp_path):
        self._make_sales_csv(tmp_path)
        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["summarize_csv"].function

        result = fn(path="sales.csv", column="")
        # All columns should appear in the table
        assert "product" in result
        assert "price" in result
        assert "region" in result

    def test_unknown_column_error(self, tmp_path):
        self._make_sales_csv(tmp_path)
        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["summarize_csv"].function

        result = fn(path="sales.csv", column="nonexistent")
        assert "Error: column 'nonexistent' not found" in result
        assert "Available:" in result

    def test_path_outside_root(self, tmp_path):
        config = CsvAnalysisToolConfig(root_path=str(tmp_path / "safe"))
        (tmp_path / "safe").mkdir()
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["summarize_csv"].function

        result = fn(path="../escape.csv")
        assert result.startswith("Error:")


# ---------------------------------------------------------------------------
# query_csv tests
# ---------------------------------------------------------------------------


class TestQueryCsv:
    def _make_data_csv(self, tmp_path: Path) -> None:
        rows = [
            {"id": "1", "name": "Alice", "dept": "Eng", "salary": "90000"},
            {"id": "2", "name": "Bob", "dept": "HR", "salary": "70000"},
            {"id": "3", "name": "Carol", "dept": "Eng", "salary": "95000"},
            {"id": "4", "name": "Dave", "dept": "HR", "salary": "72000"},
            {"id": "5", "name": "Eve", "dept": "Eng", "salary": "88000"},
        ]
        _write_csv(tmp_path / "staff.csv", rows)

    def test_filter_match(self, tmp_path):
        self._make_data_csv(tmp_path)
        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["query_csv"].function

        result = fn(path="staff.csv", filter_column="dept", filter_value="Eng")
        assert "Alice" in result
        assert "Carol" in result
        assert "Eve" in result
        assert "Bob" not in result
        assert "Dave" not in result

    def test_filter_no_match(self, tmp_path):
        self._make_data_csv(tmp_path)
        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["query_csv"].function

        result = fn(path="staff.csv", filter_column="dept", filter_value="Finance")
        assert "Rows matched: 0" in result or "**Rows matched:** 0" in result

    def test_no_filter_returns_all(self, tmp_path):
        self._make_data_csv(tmp_path)
        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["query_csv"].function

        result = fn(path="staff.csv")
        assert "Alice" in result
        assert "Eve" in result

    def test_column_subset(self, tmp_path):
        self._make_data_csv(tmp_path)
        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["query_csv"].function

        result = fn(path="staff.csv", columns="name,dept")
        assert "name" in result
        assert "dept" in result
        # salary and id should not appear in column headers
        lines = result.split("\n")
        header_line = next((line for line in lines if "name" in line and "|" in line), "")
        assert "salary" not in header_line
        assert "id" not in header_line

    def test_unknown_filter_column_error(self, tmp_path):
        self._make_data_csv(tmp_path)
        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["query_csv"].function

        result = fn(path="staff.csv", filter_column="nonexistent", filter_value="x")
        assert "Error: unknown column(s):" in result
        assert "Available:" in result

    def test_unknown_columns_param_error(self, tmp_path):
        self._make_data_csv(tmp_path)
        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["query_csv"].function

        result = fn(path="staff.csv", columns="name,ghost_column")
        assert "Error: unknown column(s):" in result

    def test_limit_capping(self, tmp_path):
        rows = [{"n": str(i)} for i in range(100)]
        _write_csv(tmp_path / "data.csv", rows)

        config = CsvAnalysisToolConfig(root_path=str(tmp_path), max_rows=20)
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["query_csv"].function

        # limit=200 should be capped at max_rows=20
        result = fn(path="data.csv", limit=200)
        # Should not have more than 20 data rows (plus header and separator)
        table_lines = [line for line in result.split("\n") if line.startswith("|")]
        # header + separator = 2, so at most max_rows + 2 table lines
        assert len(table_lines) <= 22

    def test_path_outside_root(self, tmp_path):
        config = CsvAnalysisToolConfig(root_path=str(tmp_path / "safe"))
        (tmp_path / "safe").mkdir()
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["query_csv"].function

        result = fn(path="../escape.csv")
        assert result.startswith("Error:")

    def test_rows_inspected_reported(self, tmp_path):
        self._make_data_csv(tmp_path)
        config = CsvAnalysisToolConfig(root_path=str(tmp_path))
        toolset = build_csv_analysis_toolset(config, _make_ctx())
        fn = toolset.tools["query_csv"].function

        result = fn(path="staff.csv")
        assert "Rows inspected:" in result
        assert "Rows matched:" in result
