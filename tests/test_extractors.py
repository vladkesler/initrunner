"""Tests for the extractors."""

import json
from unittest.mock import patch

import pytest

from initrunner.ingestion.extractors import extract_text, extract_url


class TestExtractors:
    def test_plain_text(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello world")
        assert extract_text(f) == "Hello world"

    def test_markdown(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# Title\n\nBody text")
        assert "Title" in extract_text(f)

    def test_csv(self, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("a,b,c\n1,2,3\n")
        result = extract_text(f)
        assert "a, b, c" in result
        assert "1, 2, 3" in result

    def test_json(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text(json.dumps({"key": "value"}))
        result = extract_text(f)
        assert "key" in result
        assert "value" in result

    def test_html(self, tmp_path):
        f = tmp_path / "test.html"
        f.write_text("<html><body><h1>Title</h1><p>Content</p></body></html>")
        result = extract_text(f)
        assert "Title" in result
        assert "Content" in result

    def test_html_strips_script(self, tmp_path):
        f = tmp_path / "test.html"
        f.write_text("<html><body><script>alert(1)</script><p>Safe</p></body></html>")
        result = extract_text(f)
        assert "alert" not in result
        assert "Safe" in result

    def test_unsupported_format(self, tmp_path):
        f = tmp_path / "test.xyz"
        f.write_text("data")
        with pytest.raises(ValueError, match="Unsupported file type"):
            extract_text(f)

    def test_pdf_requires_extra(self, tmp_path):
        f = tmp_path / "test.pdf"
        f.write_text("fake pdf")
        with pytest.raises(RuntimeError, match="pip install initrunner"):
            extract_text(f)

    def test_docx_requires_extra(self, tmp_path):
        f = tmp_path / "test.docx"
        f.write_text("fake docx")
        with pytest.raises(RuntimeError, match="pip install initrunner"):
            extract_text(f)

    def test_xlsx_requires_extra(self, tmp_path):
        f = tmp_path / "test.xlsx"
        f.write_text("fake xlsx")
        with pytest.raises(RuntimeError, match="pip install initrunner"):
            extract_text(f)


class TestExtractUrl:
    def test_extract_url_delegates_to_html_util(self):
        with patch(
            "initrunner._html.fetch_url_as_markdown",
            return_value="# Fetched Page\n\nContent here",
        ) as mock_fetch:
            result = extract_url("https://example.com/page")

        assert result == "# Fetched Page\n\nContent here"
        mock_fetch.assert_called_once_with(
            "https://example.com/page", timeout=15, max_bytes=512_000
        )

    def test_extract_url_custom_params(self):
        with patch(
            "initrunner._html.fetch_url_as_markdown",
            return_value="content",
        ) as mock_fetch:
            extract_url("https://example.com", timeout=30, max_bytes=1000)

        mock_fetch.assert_called_once_with("https://example.com", timeout=30, max_bytes=1000)

    def test_extract_url_propagates_errors(self):
        with patch(
            "initrunner._html.fetch_url_as_markdown",
            side_effect=ConnectionError("timeout"),
        ):
            with pytest.raises(ConnectionError):
                extract_url("https://down.example.com")
