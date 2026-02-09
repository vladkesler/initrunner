"""Tests for the chunker."""

from initrunner.ingestion.chunker import chunk_text


class TestFixedChunking:
    def test_basic(self):
        text = "a" * 100
        chunks = chunk_text(text, "test.txt", chunk_size=30, chunk_overlap=10)
        assert len(chunks) >= 3
        assert all(c.source == "test.txt" for c in chunks)

    def test_empty_text(self):
        chunks = chunk_text("", "test.txt", chunk_size=100, chunk_overlap=10)
        assert chunks == []

    def test_small_text(self):
        chunks = chunk_text("hello", "test.txt", chunk_size=100, chunk_overlap=10)
        assert len(chunks) == 1
        assert chunks[0].text == "hello"

    def test_overlap(self):
        text = "abcdefghij" * 10  # 100 chars
        chunks = chunk_text(text, "test.txt", chunk_size=30, chunk_overlap=10)
        # Chunks should overlap
        assert len(chunks) >= 4

    def test_index_increments(self):
        text = "word " * 200
        chunks = chunk_text(text, "test.txt", chunk_size=50, chunk_overlap=10)
        for i, chunk in enumerate(chunks):
            assert chunk.index == i


class TestParagraphChunking:
    def test_basic(self):
        text = "Para one.\n\nPara two.\n\nPara three."
        chunks = chunk_text(text, "test.txt", strategy="paragraph", chunk_size=1000)
        assert len(chunks) == 1  # all fit in one chunk

    def test_split_on_large_paragraphs(self):
        text = "\n\n".join([f"Paragraph {i} " * 20 for i in range(10)])
        chunks = chunk_text(text, "test.txt", strategy="paragraph", chunk_size=100, chunk_overlap=0)
        assert len(chunks) >= 5

    def test_source_preserved(self):
        text = "Hello\n\nWorld"
        chunks = chunk_text(text, "source.md", strategy="paragraph")
        assert all(c.source == "source.md" for c in chunks)
