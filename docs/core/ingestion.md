# Document Ingestion

InitRunner's ingestion pipeline extracts text from source files, splits it into chunks, generates embeddings, and stores vectors in a local SQLite database. Once ingested, an agent can search these documents at runtime via the auto-registered `search_documents` tool.

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
    name: gpt-4o-mini
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
5. **Store** — Embeddings and text are stored in a SQLite database backed by `sqlite-vec`.

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
    store_backend: sqlite-vec   # default: "sqlite-vec"
    store_path: null            # default: ~/.initrunner/stores/<agent-name>.db
```

### Ingest Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sources` | `list[str]` | *(required)* | Glob patterns for source files and/or HTTP(S) URLs. Globs are resolved relative to the role file's directory. |
| `watch` | `bool` | `false` | Reserved for future use. |
| `chunking` | `ChunkingConfig` | See below | Chunking strategy and parameters. |
| `embeddings` | `EmbeddingConfig` | See below | Embedding provider and model. |
| `store_backend` | `str` | `"sqlite-vec"` | Vector store backend. Currently only `sqlite-vec` is supported. |
| `store_path` | `str \| null` | `null` | Custom path for the vector store database. Default: `~/.initrunner/stores/<agent-name>.db`. |

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
| `api_key_env` | `str` | `""` | Env var name holding the API key for custom endpoints. Empty uses provider default. |

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

If no match is found, falls back to `openai:text-embedding-3-small`.

## Vector Store

Documents are stored in a SQLite database using a configurable backend (default: `sqlite-vec`). The store is dimension-agnostic — embedding dimensions are auto-detected from the model on first ingestion and persisted in a `store_meta` table.

### Backends

| Backend | Config value | Description |
|---------|-------------|-------------|
| sqlite-vec | `sqlite-vec` | Default. Local SQLite with the `sqlite-vec` extension for vector similarity search. |

Set `store_backend` in the ingest config to select a backend. Future backends (e.g. Chroma, Pinecone) can be added as new enum members.

### Default Location

```
~/.initrunner/stores/<agent-name>.db
```

Override with `store_path` in the ingest config.

### Dimension & Model Identity Tracking

The store tracks both embedding dimensions and the embedding model identity:

- **First ingestion**: dimensions are detected from the embedding output, and the model identity string is recorded in `store_meta` under the `embedding_model` key.
- **Model identity format**: `provider:model` (e.g. `openai:text-embedding-3-small`) or `provider:model:url_hash` for custom `base_url` endpoints.
- **Model change detection**: on subsequent ingestions, the store compares the current model identity against the stored value. If they differ, an `EmbeddingModelChangedError` is raised.
- **Interactive prompt**: in the CLI, the error triggers a `typer.confirm()` prompt asking whether to wipe the store and re-ingest with the new model.
- **`--force` flag**: skips the interactive prompt — the store is automatically wiped and re-ingested with the new model.
- **Legacy stores**: stores created before model identity tracking (no `embedding_model` key in `store_meta`) record the identity on the next ingest without triggering a wipe. Dimension checks still apply.
- **Migration**: pre-existing stores created before dimension tracking was added default to 1536 (the previous hard-coded value).

### Schema

The store contains three tables:

**`store_meta`** — Key-value metadata (e.g. dimensions, embedding model):

| Column | Type | Description |
|--------|------|-------------|
| `key` | `TEXT PRIMARY KEY` | Metadata key (e.g. `"dimensions"`, `"embedding_model"`) |
| `value` | `TEXT` | Metadata value (e.g. `"1536"`, `"openai:text-embedding-3-small"`) |

**`chunks`** — Text content and metadata:

| Column | Type | Description |
|--------|------|-------------|
| `id` | `INTEGER PRIMARY KEY` | Auto-incrementing chunk ID |
| `text` | `TEXT` | Chunk text content |
| `source` | `TEXT` | Source file path |
| `chunk_index` | `INTEGER` | Position within the source file |
| `ingested_at` | `TEXT` | ISO 8601 ingestion timestamp |

**`chunks_vec`** — Virtual table for vector search:

| Column | Type | Description |
|--------|------|-------------|
| `rowid` | `INTEGER` | Matches `chunks.id` |
| `embedding` | `float[N]` | Vector embedding (dimension auto-detected from model) |

An index on `chunks(source)` enables efficient deletion by source.

### Re-indexing Behavior

When you run `initrunner ingest` again, the pipeline:

1. Resolves the same glob patterns to find current files.
2. For each source file, **deletes all existing chunks** from that source.
3. Inserts new chunks from the fresh extraction.

This means re-running ingestion is safe and idempotent — it always reflects the current state of your source files. Files that no longer match the glob patterns are purged from the store. URL sources follow a different policy: they are never auto-purged (see [URL Sources](#url-sources) above).

## The `search_documents` Tool

When `spec.ingest` is configured, a `search_documents` tool is auto-registered on the agent:

```
search_documents(query: str, top_k: int = 5) -> str
```

- Creates an embedding from the query using the same embedding model as ingestion.
- Searches the vector store for the `top_k` most similar chunks.
- Returns results formatted as:

```
[Source: ./docs/guide.md | Score: 0.872]
This is the matching chunk text...

---

[Source: ./docs/faq.md | Score: 0.845]
Another matching chunk...
```

The score is `1 - distance` (higher is more similar).

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

## Scaffold a RAG Role

```bash
initrunner init --name kb-agent --template rag
```

This generates a role.yaml with `ingest` pre-configured for `./docs/**/*.md` and `./docs/**/*.txt`.
