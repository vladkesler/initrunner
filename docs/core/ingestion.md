# Document Ingestion

InitRunner's ingestion pipeline extracts text from source files, splits it into chunks, generates embeddings, and stores vectors in a local Zvec vector database. Once ingested, an agent can search these documents at runtime via the auto-registered `search_documents` tool.

## Quick Start

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: kb-agent
  description: Knowledge base agent
spec:
  role: |
    You are a knowledge assistant. Use search_documents to find relevant
    content before answering. Always cite your sources.
  model:
    provider: openai
    name: gpt-5-mini
  ingest:
    sources:
      - "./docs/**/*.md"
      - "./knowledge-base/**/*.txt"
    chunking:
      strategy: fixed
      chunk_size: 512
      chunk_overlap: 50
```

```bash
# Ingest documents
initrunner ingest role.yaml

# Run the agent (search_documents is auto-registered)
initrunner run role.yaml -p "What does the onboarding guide say?"
```

## Pipeline

The ingestion pipeline runs in four stages:

```
resolve sources (globs + URLs) → extract text → chunk → embed → store
```

1. **Resolve sources** — Glob patterns are expanded into file paths and URL sources are collected. The role file's parent directory is used as the base for relative glob paths.
2. **Extract text** — Each file is passed through a format-specific extractor based on its extension.
3. **Chunk text** — Extracted text is split into overlapping chunks using the configured strategy.
4. **Embed** — Chunks are converted to vector embeddings using the configured embedding model.
5. **Store** — Embeddings and text are stored in a local Zvec vector database.

## Configuration

Ingestion is configured in the `spec.ingest` section:

```yaml
spec:
  ingest:
    sources:                    # required — glob patterns and/or URLs
      - "./docs/**/*.md"
      - "./data/*.csv"
      - "https://docs.example.com/api/reference"
    watch: false                # default: false (reserved for future use)
    chunking:
      strategy: fixed           # default: "fixed"
      chunk_size: 512           # default: 512
      chunk_overlap: 50         # default: 50
    embeddings:
      provider: ""              # default: "" (derives from spec.model.provider)
      model: ""                 # default: "" (uses provider default)
      base_url: ""              # default: "" (custom endpoint URL)
      api_key_env: ""           # default: "" (env var holding API key)
    store_backend: zvec         # default: "zvec"
    store_path: null            # default: ~/.initrunner/stores/<agent-name>.zvec
```

### Ingest Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sources` | `list[str]` | *(required)* | Glob patterns for source files and/or HTTP(S) URLs. Globs are resolved relative to the role file's directory. |
| `watch` | `bool` | `false` | Reserved for future use. |
| `chunking` | `ChunkingConfig` | See below | Chunking strategy and parameters. |
| `embeddings` | `EmbeddingConfig` | See below | Embedding provider and model. |
| `store_backend` | `str` | `"zvec"` | Vector store backend. Uses Zvec, an in-process vector database. |
| `store_path` | `str \| null` | `null` | Custom path for the vector store directory. Default: `~/.initrunner/stores/<agent-name>.zvec`. |

### Chunking Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `strategy` | `"fixed" \| "paragraph"` | `"fixed"` | Chunking strategy. |
| `chunk_size` | `int` | `512` | Maximum chunk size in characters. |
| `chunk_overlap` | `int` | `50` | Number of overlapping characters between consecutive chunks. |

### Embedding Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | `str` | `""` | Embedding provider. Empty string derives from `spec.model.provider`. |
| `model` | `str` | `""` | Embedding model name. Empty string uses the provider default. |
| `base_url` | `str` | `""` | Custom endpoint URL. Triggers OpenAI-compatible mode. |
| `api_key_env` | `str` | `""` | Env var name holding the embedding API key. Works for both standard providers and custom endpoints. When empty, the default key for the resolved provider is used (e.g. `OPENAI_API_KEY` for OpenAI/Anthropic, `GOOGLE_API_KEY` for Google). |

## URL Sources

Sources prefixed with `http://` or `https://` are treated as URL sources. The pipeline fetches each URL via HTTP, converts the HTML to markdown, and processes the result through the same chunk → embed → store stages as file sources.

```yaml
sources:
  - "./docs/**/*.md"
  - "https://docs.example.com/api/reference"
  - "https://blog.example.com/announcements"
```

### Incremental hashing

URL sources use the SHA-256 hash of the **extracted markdown** (not the raw HTML) to determine whether content has changed. If the hash matches the stored value, the URL is skipped. This avoids re-embedding unchanged content even when the raw HTML differs (e.g. due to dynamic ads or timestamps).

### Per-domain rate limiting

The pipeline enforces a 1-second delay between consecutive requests to the same domain to avoid overwhelming remote servers.

### Error handling

Failed URL fetches are logged as errors but do not crash the pipeline. The remaining sources (both files and URLs) continue processing normally.

### Purge behavior

URL sources are **never auto-purged**. Removing a URL from the `sources` list stops it from being re-ingested, but previously stored content persists in the document store. To remove stored URL content, clear the store with `initrunner memory clear` or delete the store database.

## Chunking Strategies

### Fixed (`strategy: fixed`)

Splits text into fixed-size character windows with overlap. Simple and predictable.

- Starts at position 0, takes `chunk_size` characters.
- The next chunk starts at `chunk_size - chunk_overlap`.
- Empty chunks (after stripping whitespace) are skipped.

Best for: uniform document types, code files, logs.

### Paragraph (`strategy: paragraph`)

Splits on double newlines (`\n\n`) first, then merges small paragraphs until `chunk_size` is reached. Preserves natural document structure.

- Paragraphs are split on `\n\n` boundaries.
- Small paragraphs are merged until adding the next one would exceed `chunk_size`.
- When a chunk is emitted, the last `chunk_overlap` characters are carried over to the next chunk.

Best for: prose documents, markdown, articles, documentation.

### Choosing a Strategy and Parameters

**Fixed vs Paragraph**: Use `fixed` when documents lack clear paragraph boundaries (code, logs, CSV data). Use `paragraph` when documents have natural structure (markdown, articles, prose) — it produces more coherent chunks because it avoids splitting mid-sentence.

**`chunk_size`**: Smaller chunks (256–512) give more precise retrieval — each result closely matches the query. Larger chunks (512–1024) include more surrounding context per result, which helps when answers span multiple sentences. Rules of thumb:
- **Q&A over documentation**: 256–512 characters
- **Summarization or dense technical content**: 512–1024 characters

**`chunk_overlap`**: Overlap prevents key information from being split across chunk boundaries. Set it to roughly 10% of `chunk_size` (e.g. 50 for chunk_size 512, 100 for chunk_size 1024). Too little overlap risks losing context at boundaries; too much wastes storage on duplicate content.

### Recommended Settings by Document Type

| Document Type | Strategy | chunk_size | chunk_overlap | Why |
|--------------|----------|-----------|--------------|-----|
| Markdown docs | `paragraph` | 512 | 50 | Natural paragraph boundaries; precise retrieval |
| API reference | `paragraph` | 256 | 25 | Short entries; one chunk per endpoint/method |
| Long-form articles | `paragraph` | 1024 | 100 | Preserves context around multi-sentence answers |
| Source code | `fixed` | 512 | 50 | No paragraph structure; fixed windows work well |
| Log files | `fixed` | 256 | 0 | Each line is independent; no overlap needed |
| CSV / tabular data | `fixed` | 1024 | 0 | Keep rows together; overlap would split rows |
| PDFs (mixed layout) | `fixed` | 512 | 50 | Paragraph detection unreliable after PDF extraction |
| Mixed knowledge base | `paragraph` | 512 | 50 | Good default for heterogeneous content |

These are starting points — adjust based on your retrieval quality. Smaller chunks improve precision (each result closely matches the query); larger chunks provide more context per result.

## Supported File Formats

### Core Formats (always available)

| Extension | Extractor |
|-----------|-----------|
| `.txt` | Plain text (UTF-8) |
| `.md` | Plain text (UTF-8) |
| `.rst` | Plain text (UTF-8) |
| `.csv` | CSV rows joined with commas and newlines |
| `.json` | Pretty-printed JSON (2-space indent) |
| `.html`, `.htm` | HTML → Markdown conversion (scripts/styles removed) |

### Optional Formats (`pip install initrunner[ingest]`)

| Extension | Extractor | Library |
|-----------|-----------|---------|
| `.pdf` | PDF → Markdown | `pymupdf4llm` |
| `.docx` | Paragraphs joined with double newlines | `python-docx` |
| `.xlsx` | Sheets as CSV with sheet title headers | `openpyxl` |

Attempting to ingest an optional format without the extra installed raises a helpful error message directing the user to install `initrunner[ingest]`.

Unsupported file types raise a `ValueError` and are skipped during ingestion (the pipeline continues with remaining files).

## Embedding Models

The embedding provider is determined by this priority:

1. `ingest.embeddings.model` — If set, used directly (e.g. `"openai:text-embedding-3-large"`).
2. `ingest.embeddings.provider` — Used to look up the default model for that provider.
3. `spec.model.provider` — Falls back to the agent's model provider.

### Provider Defaults

| Provider | Default Embedding Model |
|----------|------------------------|
| `openai` | `openai:text-embedding-3-small` |
| `anthropic` | `openai:text-embedding-3-small` (Anthropic has no embeddings API) |
| `google` | `google:text-embedding-004` |
| `ollama` | `ollama:nomic-embed-text` |

If no match is found, falls back to `openai:text-embedding-3-small`.

## Vector Store

Documents are stored in a local Zvec vector database using a configurable backend (default: `zvec`). The store is dimension-agnostic — embedding dimensions are auto-detected from the model on first ingestion and persisted in the `_meta` collection.

### Backends

| Backend | Config value | Description |
|---------|-------------|-------------|
| Zvec | `zvec` | Default. In-process vector database built on Alibaba's Proxima engine. Uses HNSW indexing with cosine similarity. |

Set `store_backend` in the ingest config to select a backend.

### Default Location

```
~/.initrunner/stores/<agent-name>.zvec
```

Override with `store_path` in the ingest config.

### Dimension & Model Identity Tracking

The store tracks both embedding dimensions and the embedding model identity:

- **First ingestion**: dimensions are detected from the embedding output, and the model identity string is recorded in the `_meta` collection under the `embedding_model` key.
- **Model identity format**: `provider:model` (e.g. `openai:text-embedding-3-small`) or `provider:model:url_hash` for custom `base_url` endpoints.
- **Model change detection**: on subsequent ingestions, the store compares the current model identity against the stored value. If they differ, an `EmbeddingModelChangedError` is raised.
- **Interactive prompt**: in the CLI, the error triggers a `typer.confirm()` prompt asking whether to wipe the store and re-ingest with the new model.
- **`--force` flag**: skips the interactive prompt — the store is automatically wiped and re-ingested with the new model.
- **Legacy stores**: stores created before model identity tracking (no `embedding_model` key in `_meta`) record the identity on the next ingest without triggering a wipe. Dimension checks still apply.

### Collections

The store directory contains three zvec collections:

**`_meta`** — Key-value metadata (e.g. dimensions, embedding model):

| Field | Type | Description |
|-------|------|-------------|
| Doc ID | string | Metadata key (e.g. `"dimensions"`, `"embedding_model"`) |
| `value` | STRING | Metadata value |

**`chunks`** — Text content and vector embeddings:

| Field | Type | Description |
|-------|------|-------------|
| Doc ID | string | Auto-incrementing chunk ID |
| `text` | STRING | Chunk text content |
| `source` | STRING (indexed) | Source file path |
| `chunk_index` | INT32 | Position within the source file |
| `ingested_at` | STRING | ISO 8601 ingestion timestamp |
| `embedding` | VECTOR_FP32 | Vector embedding (dimension auto-detected from model) |

**`file_metadata`** — Incremental ingestion tracking:

| Field | Type | Description |
|-------|------|-------------|
| Doc ID | string | SHA-256 hash of the source path |
| `source` | STRING | Original source file path |
| `content_hash` | STRING | SHA-256 hash of file content |
| `last_modified` | DOUBLE | File modification time |
| `ingested_at` | STRING | ISO 8601 ingestion timestamp |
| `chunk_count` | INT32 | Number of chunks from this source |

### Re-indexing Behavior

When you run `initrunner ingest` again, the pipeline:

1. Resolves the same glob patterns to find current files.
2. For each source file, **deletes all existing chunks** from that source.
3. Inserts new chunks from the fresh extraction.

This means re-running ingestion is safe and idempotent — it always reflects the current state of your source files. Files that no longer match the glob patterns are purged from the store. URL sources follow a different policy: they are never auto-purged (see [URL Sources](#url-sources) above).

## The `search_documents` Tool

When `spec.ingest` is configured, a `search_documents` tool is auto-registered on the agent:

```
search_documents(query: str, top_k: int = 5, source: str | None = None) -> str
```

- **`query`** — The search query. An embedding is created using the same model as ingestion.
- **`top_k`** — Number of results to return (default: 5).
- **`source`** — Optional source filter. Pass an exact path (e.g. `"./docs/guide.md"`) or a glob pattern (e.g. `"*.md"`) to restrict results to matching sources.

Results are formatted as:

```
[Source: ./docs/guide.md | Score: 0.872]
This is the matching chunk text...

---

[Source: ./docs/faq.md | Score: 0.845]
Another matching chunk...
```

The score is `1 - distance` (higher is more similar).

Example with source filtering:

```python
# Search only markdown files
search_documents("installation steps", source="*.md")

# Search a specific file
search_documents("error handling", source="./docs/api-reference.md")
```

If no documents have been ingested, the tool returns a message directing the user to run `initrunner ingest`.

## CLI

```bash
# Ingest documents
initrunner ingest role.yaml

# Force re-ingestion (also wipes store on model change)
initrunner ingest role.yaml --force
```

| Flag | Description |
|------|-------------|
| `--force` | Force re-ingestion of all files. Also wipes the store when the embedding model has changed. |

The command displays the agent name, a spinner during processing, and the total number of chunks stored on completion.

## Troubleshooting

### No results from `search_documents`

- **Documents not ingested** — Run `initrunner ingest role.yaml` before querying. The tool returns "No documents have been ingested yet" if the store database doesn't exist.
- **Query mismatch** — Semantic search works best when the query uses similar vocabulary to the documents. Try rephrasing with terms that appear in your source files.

### `EmbeddingModelChangedError`

Raised when the embedding model in your role.yaml differs from the one used to create the store. The existing embeddings are incompatible with the new model.

**Fix:** Re-run with `--force` to wipe the store and re-ingest:
```bash
initrunner ingest role.yaml --force
```

### `DimensionMismatchError`

The embedding model produces vectors with a different dimension than what the store expects. This typically happens when switching between embedding models.

**Fix:** Same as above — use `--force` to wipe and re-ingest.

### Optional format errors (PDF, DOCX, XLSX)

If you see an error like `"Install initrunner[ingest] for PDF support"`, install the extra:
```bash
pip install initrunner[ingest]
# or with uv:
uv pip install initrunner[ingest]
```

### API key not set

Embedding providers require credentials. InitRunner validates embedding keys at startup and raises a clear error if they're missing. The error message names the required env var, explains that embedding keys may differ from LLM keys, and points to the `api_key_env` override.

- **OpenAI**: Set `OPENAI_API_KEY` in your environment.
- **Anthropic**: Anthropic has no embeddings API — set `OPENAI_API_KEY` (used for OpenAI embeddings by default). Run `initrunner doctor` to see embedding key status.
- **Google**: Set `GOOGLE_API_KEY` or configure Application Default Credentials.
- **Custom endpoint**: Set the env var specified in `embeddings.api_key_env`.
- **Ollama**: No API key needed — runs locally.

You can override which env var is used for the embedding key by setting `embeddings.api_key_env` in your `ingest` or `memory` config.

### `zvec` not available

The vector store backend requires the `zvec` package. Install it:
```bash
pip install zvec
# or with uv:
uv pip install zvec
```

## Scaffold a RAG Role

```bash
initrunner init --name kb-agent --template rag
```

This generates a role.yaml with `ingest` pre-configured for `./docs/**/*.md` and `./docs/**/*.txt`.
