# RAG Setup (Document Ingestion and Search)

RAG (Retrieval-Augmented Generation) lets your agent search a knowledge base of documents before answering questions. InitRunner handles the full pipeline: extract text, chunk it, generate embeddings, and store vectors.


## Quick start

Add an `ingest` section to your role.yaml:

```yaml
spec:
  ingest:
    sources:
      - ./docs/**/*.md
      - ./knowledge-base/**/*.txt
    chunking:
      strategy: paragraph
      chunk_size: 512
      chunk_overlap: 50
```

Then ingest and run:

```bash
# Build the vector store
initrunner ingest role.yaml

# Ask a question (agent will call search_documents automatically)
initrunner run role.yaml -p "How do I authenticate?"
```


## The ingestion pipeline

The pipeline runs in five stages:

1. **Resolve sources** -- expand glob patterns and URLs
2. **Extract text** -- format-specific extraction (Markdown, HTML, PDF, etc.)
3. **Chunk text** -- split into overlapping segments
4. **Embed** -- generate vector embeddings
5. **Store** -- persist to LanceDB


## Ingestion configuration reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sources` | `list[str]` | *(required)* | Glob patterns and/or URLs |
| `chunking.strategy` | `"fixed"` or `"paragraph"` | `"fixed"` | Chunking strategy |
| `chunking.chunk_size` | `int` | `512` | Maximum chunk size in characters |
| `chunking.chunk_overlap` | `int` | `50` | Overlap between adjacent chunks |
| `store_backend` | `str` | `"lancedb"` | Vector store backend |
| `store_path` | `str` or `null` | `null` | Custom store location |
| `embeddings.provider` | `str` | *(from model)* | Embedding provider override |
| `embeddings.model` | `str` | *(provider default)* | Embedding model override |


## Chunking strategies

### Fixed chunking

Splits text at a fixed character count with overlap. Works for any format:

```yaml
chunking:
  strategy: fixed
  chunk_size: 512
  chunk_overlap: 50
```

### Paragraph chunking

Splits on double newlines (blank lines), then merges small paragraphs up to `chunk_size`. Preserves natural document structure. Best for Markdown and prose:

```yaml
chunking:
  strategy: paragraph
  chunk_size: 512
  chunk_overlap: 50
```

### Recommended settings by document type

| Document type | Strategy | chunk_size | overlap | Why |
|---------------|----------|-----------|---------|-----|
| Markdown docs | `paragraph` | 512 | 50 | Natural section boundaries |
| API reference | `paragraph` | 256 | 25 | Short, independent entries |
| Long articles | `paragraph` | 1024 | 100 | Multi-sentence context |
| Source code | `fixed` | 512 | 50 | No paragraph structure |
| Log files | `fixed` | 256 | 0 | Independent lines |
| CSV/tabular | `fixed` | 1024 | 0 | Keep rows together |


## Supported file formats

**Always available** (no extras needed):
- `.txt`, `.md`, `.rst` -- plain text
- `.csv`, `.json` -- structured data
- `.html`, `.htm` -- converted to Markdown

**Requires `initrunner[ingest]` extra:**
- `.pdf` -- via pymupdf4llm
- `.docx` -- via python-docx
- `.xlsx` -- via openpyxl


## The search_documents tool

When `spec.ingest` is configured, InitRunner automatically registers a `search_documents` tool:

```
search_documents(query: str, top_k: int = 5, source: str | None = None) -> str
```

- `query` -- natural language search query
- `top_k` -- number of results to return (default: 5)
- `source` -- optional glob filter on source path (e.g. `"*billing*"`)

Results include the source file path, similarity score (0-1, higher is better), and the matching text chunk.


## Incremental re-indexing

InitRunner tracks file content hashes. On subsequent `initrunner ingest` runs, only new or modified files are re-processed. Unchanged files are skipped.

To force a full re-index (required after changing the embedding model):

```bash
initrunner ingest role.yaml --force
```


## URL sources

You can include URLs directly in your sources list:

```yaml
spec:
  ingest:
    sources:
      - ./docs/**/*.md
      - https://example.com/api-reference.html
```

URLs are fetched, converted to Markdown, and chunked like local files.


## Chat with inline ingestion

For quick experiments, use the `--ingest` flag with `chat`:

```bash
initrunner run --ingest ./docs/
```

This ingests the specified path and enables `search_documents` in an ephemeral chat session, without needing a role.yaml.


## RAG vs Memory

| Aspect | Ingestion (RAG) | Memory |
|--------|-----------------|--------|
| Purpose | Search external documents | Remember learned information |
| Data source | Files on disk, URLs | Agent observations |
| Who writes | You (via `ingest`) | Agent (via `remember()`) |
| Who reads | Agent (via `search_documents`) | Agent (via `recall()`) |
| Best for | Knowledge base Q&A | Personalization, context |
| Persistence | Rebuilt on ingest | Accumulates across sessions |

You can use both in the same agent. RAG provides the knowledge base; memory provides personalization and session continuity.
