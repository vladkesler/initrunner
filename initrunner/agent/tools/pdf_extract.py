"""PDF extraction tool: extract text and metadata from PDF files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._paths import validate_path_within
from initrunner.agent._truncate import truncate_output
from initrunner.agent.schema.tools import PdfExtractToolConfig
from initrunner.agent.tools._registry import register_tool

if TYPE_CHECKING:
    from initrunner.agent.tools._registry import ToolBuildContext

logger = logging.getLogger(__name__)


def _parse_page_spec(spec: str, total_pages: int) -> list[int] | str:
    """Parse a page specification like ``"1-5,8,10-12"`` into 0-based indices.

    Returns a sorted list of page indices or an error string.
    """
    if not spec.strip():
        return list(range(total_pages))

    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            bounds = part.split("-", 1)
            try:
                start, end = int(bounds[0]), int(bounds[1])
            except ValueError:
                return f"Error: invalid page range: {part!r}"
            if start < 1 or end < start:
                return f"Error: invalid page range: {part!r}"
            if end > total_pages:
                return f"Error: page {end} exceeds total pages ({total_pages})"
            pages.update(range(start - 1, end))
        else:
            try:
                p = int(part)
            except ValueError:
                return f"Error: invalid page number: {part!r}"
            if p < 1 or p > total_pages:
                return f"Error: page {p} out of range (1-{total_pages})"
            pages.add(p - 1)

    return sorted(pages)


def _check_file_size(target: Path, max_file_size_mb: float) -> str | None:
    """Return an error string if the file exceeds the size limit, else None."""
    try:
        size_mb = target.stat().st_size / (1024 * 1024)
        if size_mb > max_file_size_mb:
            return f"Error: file exceeds size limit ({max_file_size_mb} MB)"
    except OSError:
        pass
    return None


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def _do_extract_text(
    target: Path,
    root: Path,
    path_display: str,
    max_pages: int,
    max_content_bytes: int,
    max_file_size_mb: float,
    page_spec: str,
) -> str:
    """Extract text from a PDF as markdown."""
    err, resolved = validate_path_within(target, [root], allowed_ext={".pdf"}, reject_symlinks=True)
    if err:
        return err

    size_err = _check_file_size(resolved, max_file_size_mb)
    if size_err:
        return size_err

    if not resolved.exists():
        return f"Error: file not found: {path_display}"

    from initrunner._compat import require_ingest

    require_ingest("pymupdf4llm")
    import pymupdf4llm  # type: ignore[import-not-found]

    try:
        import pymupdf  # type: ignore[import-not-found]

        doc = pymupdf.open(str(resolved))
    except Exception as exc:
        return f"Error: could not open PDF: {exc}"

    try:
        total = doc.page_count
        page_indices = _parse_page_spec(page_spec, total)
        if isinstance(page_indices, str):
            return page_indices

        if len(page_indices) > max_pages:
            page_indices = page_indices[:max_pages]
    finally:
        doc.close()

    try:
        text = pymupdf4llm.to_markdown(str(resolved), pages=page_indices)
    except Exception as exc:
        return f"Error: extraction failed: {exc}"

    return truncate_output(text, max_content_bytes)


def _do_extract_metadata(
    target: Path,
    root: Path,
    path_display: str,
    max_file_size_mb: float,
) -> str:
    """Extract metadata from a PDF."""
    err, resolved = validate_path_within(target, [root], allowed_ext={".pdf"}, reject_symlinks=True)
    if err:
        return err

    size_err = _check_file_size(resolved, max_file_size_mb)
    if size_err:
        return size_err

    if not resolved.exists():
        return f"Error: file not found: {path_display}"

    try:
        import pymupdf  # type: ignore[import-not-found]

        doc = pymupdf.open(str(resolved))
    except Exception as exc:
        return f"Error: could not open PDF: {exc}"

    try:
        meta = doc.metadata or {}
        page_count = doc.page_count
    finally:
        doc.close()

    lines = [
        f"**File:** {path_display}",
        f"**Pages:** {page_count}",
    ]
    for key in ("title", "author", "subject", "creator", "producer", "creationDate", "modDate"):
        val = meta.get(key, "")
        if val:
            lines.append(f"**{key}:** {val}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


@register_tool("pdf_extract", PdfExtractToolConfig)
def build_pdf_extract_toolset(
    config: PdfExtractToolConfig,
    ctx: ToolBuildContext,
) -> FunctionToolset:
    """Build a FunctionToolset for PDF text and metadata extraction."""
    root = Path(config.root_path).resolve()

    toolset = FunctionToolset()

    @toolset.tool_plain
    def extract_pdf_text(path: str, pages: str = "") -> str:
        """Extract text from a PDF file as markdown.

        Args:
            path: Path to the PDF file, relative to the configured root directory.
            pages: Page range to extract, e.g. "1-5", "3,7,10-12". Empty for all pages.
        """
        return _do_extract_text(
            root / path,
            root,
            path,
            config.max_pages,
            config.max_content_bytes,
            config.max_file_size_mb,
            pages,
        )

    @toolset.tool_plain
    def extract_pdf_metadata(path: str) -> str:
        """Extract metadata from a PDF file (title, author, page count, dates).

        Args:
            path: Path to the PDF file, relative to the configured root directory.
        """
        return _do_extract_metadata(
            root / path,
            root,
            path,
            config.max_file_size_mb,
        )

    return toolset
