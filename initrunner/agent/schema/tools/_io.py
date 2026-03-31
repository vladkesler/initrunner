"""IO tool configurations: filesystem, PDF, CSV."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from initrunner.agent.schema.tools._base import ToolConfigBase


class FileSystemToolConfig(ToolConfigBase):
    type: Literal["filesystem"] = "filesystem"
    root_path: str = "."
    allowed_extensions: list[str] = []
    read_only: bool = True

    def summary(self) -> str:
        return f"filesystem: {self.root_path} (ro={self.read_only})"


class PdfExtractToolConfig(ToolConfigBase):
    type: Literal["pdf_extract"] = "pdf_extract"
    root_path: str = "."
    max_pages: int = Field(default=100, ge=1)
    max_content_bytes: int = 512_000
    max_file_size_mb: float = 50.0

    def summary(self) -> str:
        return f"pdf_extract: {self.root_path}"


class CsvAnalysisToolConfig(ToolConfigBase):
    type: Literal["csv_analysis"] = "csv_analysis"
    root_path: str = "."
    max_rows: int = 1000
    max_file_size_mb: float = 10.0
    delimiter: str = ","

    def summary(self) -> str:
        return f"csv_analysis: {self.root_path}"
