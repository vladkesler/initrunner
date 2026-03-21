"""Tests for the pdf_extract tool: config, page parsing, extraction, and registration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from initrunner.agent.schema.tools import PdfExtractToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, get_tool_types
from initrunner.agent.tools.pdf_extract import (
    _parse_page_spec,
    build_pdf_extract_toolset,
)


def _make_ctx():
    from initrunner.agent.schema.role import RoleDefinition

    role = RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test"},
            "spec": {
                "role": "test",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
            },
        }
    )
    return ToolBuildContext(role=role)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestPdfExtractConfig:
    def test_defaults(self):
        config = PdfExtractToolConfig()
        assert config.type == "pdf_extract"
        assert config.root_path == "."
        assert config.max_pages == 100
        assert config.max_content_bytes == 512_000
        assert config.max_file_size_mb == 50.0

    def test_summary(self):
        config = PdfExtractToolConfig(root_path="/docs")
        assert config.summary() == "pdf_extract: /docs"

    def test_custom_values(self):
        config = PdfExtractToolConfig(root_path="/data", max_pages=10, max_content_bytes=100_000)
        assert config.max_pages == 10
        assert config.max_content_bytes == 100_000

    def test_round_trip(self):
        config = PdfExtractToolConfig(root_path="/tmp")
        data = config.model_dump()
        restored = PdfExtractToolConfig.model_validate(data)
        assert restored.root_path == "/tmp"

    def test_from_dict(self):
        config = PdfExtractToolConfig.model_validate({"type": "pdf_extract"})
        assert config.type == "pdf_extract"

    def test_in_agent_spec(self):
        from initrunner.agent.schema.role import parse_tool_list

        tools = parse_tool_list([{"type": "pdf_extract", "root_path": "/data"}])
        assert len(tools) == 1
        assert isinstance(tools[0], PdfExtractToolConfig)
        assert tools[0].root_path == "/data"

    def test_max_pages_ge_1(self):
        with pytest.raises(ValueError):
            PdfExtractToolConfig(max_pages=0)


# ---------------------------------------------------------------------------
# Page spec parsing
# ---------------------------------------------------------------------------


class TestParsePageSpec:
    def test_empty_returns_all(self):
        assert _parse_page_spec("", 5) == [0, 1, 2, 3, 4]

    def test_single_page(self):
        assert _parse_page_spec("3", 10) == [2]

    def test_range(self):
        assert _parse_page_spec("2-4", 10) == [1, 2, 3]

    def test_mixed(self):
        assert _parse_page_spec("1,3,5-7", 10) == [0, 2, 4, 5, 6]

    def test_dedup(self):
        assert _parse_page_spec("1,1,2-3", 5) == [0, 1, 2]

    def test_out_of_range(self):
        result = _parse_page_spec("11", 5)
        assert isinstance(result, str)
        assert "out of range" in result

    def test_range_exceeds(self):
        result = _parse_page_spec("1-20", 5)
        assert isinstance(result, str)
        assert "exceeds total pages" in result

    def test_invalid_format(self):
        result = _parse_page_spec("abc", 5)
        assert isinstance(result, str)
        assert "Error:" in result

    def test_invalid_range(self):
        result = _parse_page_spec("5-2", 10)
        assert isinstance(result, str)
        assert "invalid page range" in result

    def test_zero_page(self):
        result = _parse_page_spec("0", 5)
        assert isinstance(result, str)
        assert "out of range" in result


# ---------------------------------------------------------------------------
# Tool functions (mocked pymupdf/pymupdf4llm)
# ---------------------------------------------------------------------------


class TestExtractPdfText:
    def test_happy_path(self, tmp_path: Path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        mock_doc = MagicMock()
        mock_doc.page_count = 3
        mock_doc.close = MagicMock()

        with (
            patch("initrunner.agent.tools.pdf_extract.validate_path_within") as mock_validate,
            patch("initrunner._compat.require_ingest"),
            patch.dict("sys.modules", {"pymupdf4llm": MagicMock(), "pymupdf": MagicMock()}),
        ):
            import sys

            mock_pymupdf = sys.modules["pymupdf"]
            mock_pymupdf.open.return_value = mock_doc

            mock_pymupdf4llm = sys.modules["pymupdf4llm"]
            mock_pymupdf4llm.to_markdown.return_value = "# Hello\n\nSome text."

            mock_validate.return_value = (None, pdf_file)

            config = PdfExtractToolConfig(root_path=str(tmp_path))
            toolset = build_pdf_extract_toolset(config, _make_ctx())
            fn = toolset.tools["extract_pdf_text"].function
            result = fn(path="test.pdf")

            assert "Hello" in result
            mock_pymupdf4llm.to_markdown.assert_called_once()

    def test_path_outside_root(self, tmp_path: Path):
        config = PdfExtractToolConfig(root_path=str(tmp_path))
        toolset = build_pdf_extract_toolset(config, _make_ctx())
        fn = toolset.tools["extract_pdf_text"].function
        result = fn(path="../../../etc/passwd.pdf")
        assert "Error:" in result

    def test_non_pdf_extension(self, tmp_path: Path):
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("not a pdf")

        config = PdfExtractToolConfig(root_path=str(tmp_path))
        toolset = build_pdf_extract_toolset(config, _make_ctx())
        fn = toolset.tools["extract_pdf_text"].function
        result = fn(path="test.txt")
        assert "Error:" in result

    def test_file_too_large(self, tmp_path: Path):
        pdf_file = tmp_path / "big.pdf"
        pdf_file.write_bytes(b"%PDF" + b"\x00" * (2 * 1024 * 1024))

        config = PdfExtractToolConfig(root_path=str(tmp_path), max_file_size_mb=0.001)
        toolset = build_pdf_extract_toolset(config, _make_ctx())
        fn = toolset.tools["extract_pdf_text"].function
        result = fn(path="big.pdf")
        assert "exceeds size limit" in result

    def test_file_not_found(self, tmp_path: Path):
        config = PdfExtractToolConfig(root_path=str(tmp_path))
        toolset = build_pdf_extract_toolset(config, _make_ctx())
        fn = toolset.tools["extract_pdf_text"].function
        result = fn(path="nonexistent.pdf")
        assert "Error:" in result

    def test_truncation(self, tmp_path: Path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        mock_doc = MagicMock()
        mock_doc.page_count = 1
        mock_doc.close = MagicMock()

        with (
            patch("initrunner.agent.tools.pdf_extract.validate_path_within") as mock_validate,
            patch("initrunner._compat.require_ingest"),
            patch.dict("sys.modules", {"pymupdf4llm": MagicMock(), "pymupdf": MagicMock()}),
        ):
            import sys

            mock_pymupdf = sys.modules["pymupdf"]
            mock_pymupdf.open.return_value = mock_doc

            mock_pymupdf4llm = sys.modules["pymupdf4llm"]
            mock_pymupdf4llm.to_markdown.return_value = "x" * 1000

            mock_validate.return_value = (None, pdf_file)

            config = PdfExtractToolConfig(root_path=str(tmp_path), max_content_bytes=100)
            toolset = build_pdf_extract_toolset(config, _make_ctx())
            fn = toolset.tools["extract_pdf_text"].function
            result = fn(path="test.pdf")
            assert len(result) <= 100
            assert "[truncated]" in result


class TestExtractPdfMetadata:
    def test_happy_path(self, tmp_path: Path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        mock_doc = MagicMock()
        mock_doc.page_count = 5
        mock_doc.metadata = {
            "title": "Test Document",
            "author": "Test Author",
            "subject": "",
            "creator": "TestApp",
        }
        mock_doc.close = MagicMock()

        with (
            patch("initrunner.agent.tools.pdf_extract.validate_path_within") as mock_validate,
            patch.dict("sys.modules", {"pymupdf": MagicMock()}),
        ):
            import sys

            mock_pymupdf = sys.modules["pymupdf"]
            mock_pymupdf.open.return_value = mock_doc

            mock_validate.return_value = (None, pdf_file)

            config = PdfExtractToolConfig(root_path=str(tmp_path))
            toolset = build_pdf_extract_toolset(config, _make_ctx())
            fn = toolset.tools["extract_pdf_metadata"].function
            result = fn(path="test.pdf")

            assert "Test Document" in result
            assert "Test Author" in result
            assert "Pages:** 5" in result


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestPdfExtractRegistration:
    def test_registered_in_tool_types(self):
        types = get_tool_types()
        assert "pdf_extract" in types
        assert types["pdf_extract"] is PdfExtractToolConfig

    def test_builds_both_tools(self, tmp_path: Path):
        config = PdfExtractToolConfig(root_path=str(tmp_path))
        toolset = build_pdf_extract_toolset(config, _make_ctx())
        assert "extract_pdf_text" in toolset.tools
        assert "extract_pdf_metadata" in toolset.tools
