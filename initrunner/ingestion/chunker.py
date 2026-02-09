"""Text chunking strategies."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    source: str
    index: int


def chunk_text(
    text: str,
    source: str,
    *,
    strategy: str = "fixed",
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> list[Chunk]:
    """Split text into chunks using the specified strategy."""
    if strategy == "paragraph":
        return _chunk_paragraph(text, source, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return _chunk_fixed(text, source, chunk_size=chunk_size, chunk_overlap=chunk_overlap)


def _chunk_fixed(
    text: str,
    source: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[Chunk]:
    """Fixed-size character chunking with overlap."""
    chunks: list[Chunk] = []
    start = 0
    idx = 0
    while start < len(text):
        end = start + chunk_size
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append(Chunk(text=chunk_text, source=source, index=idx))
            idx += 1
        start = end - chunk_overlap if end < len(text) else end
    return chunks


def _chunk_paragraph(
    text: str,
    source: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[Chunk]:
    """Paragraph-aware chunking: splits on double newlines, then merges small paragraphs."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[Chunk] = []
    current = ""
    idx = 0

    for para in paragraphs:
        if current and len(current) + len(para) + 2 > chunk_size:
            chunks.append(Chunk(text=current.strip(), source=source, index=idx))
            idx += 1
            # Keep overlap from the end of current
            if chunk_overlap > 0 and len(current) > chunk_overlap:
                current = current[-chunk_overlap:] + "\n\n" + para
            else:
                current = para
        else:
            current = f"{current}\n\n{para}" if current else para

    if current.strip():
        chunks.append(Chunk(text=current.strip(), source=source, index=idx))

    return chunks
