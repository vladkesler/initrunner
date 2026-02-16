# RAG Patterns & Guide

This guide covers practical patterns for using InitRunner's retrieval-augmented generation (RAG) capabilities. For full configuration reference, see [Ingestion](ingestion.md) and [Memory](memory.md).

## RAG vs Memory — When to Use Which

InitRunner has two systems for giving agents access to information beyond their training data:

| Aspect | Ingestion (RAG) | Memory |
|---|---|---|
| **Purpose** | Search external documents | Remember learned information |
| **Data source** | Files on disk, URLs | Agent's own observations |
| **Who writes** | You (via `initrunner ingest`) | Agent (via `remember()` tool) |
| **Who reads** | Agent (via `search_documents()`) | Agent (via `recall()`) |
| **Best for** | Knowledge base Q&A, doc search | Personalization, context carry-over |
| **Persistence** | Rebuilt on each `ingest` run | Accumulates across sessions |

You can use both together — ingestion for your docs, memory for user preferences:

```yaml
spec:
  ingest:
    sources:
      - "./docs/**/*.md"
  memory:
    max_memories: 500
```

## End-to-End Walkthrough

### 1. Create a role with ingestion

Create `role.yaml`:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: docs-agent
  description: Documentation Q&A agent
spec:
  role: |
    You are a documentation assistant. ALWAYS call search_documents
    before answering questions. Cite your sources.
  model:
    provider: openai
    name: gpt-4o-mini
  ingest:
    sources:
      - "./docs/**/*.md"
    chunking:
      strategy: paragraph
      chunk_size: 512
      chunk_overlap: 50
```

### 2. Add some documents

Create a `docs/` directory with markdown files:

```
docs/
├── getting-started.md
├── api-reference.md
└── faq.md
```

### 3. Ingest documents

```bash
$ initrunner ingest role.yaml
Ingesting documents for docs-agent...
✓ Stored 47 chunks from 3 files
```

### 4. Run the agent

```bash
$ initrunner run role.yaml -p "How do I authenticate?"
```

The agent calls `search_documents("authenticate")` behind the scenes, retrieves matching chunks from your docs, and uses them to answer.

### 5. Interactive session

```bash
$ initrunner run role.yaml -i
docs-agent> How do I get an API key?

I found the answer in your documentation. Per the Getting Started guide
(./docs/getting-started.md), you can generate an API key by navigating to
Settings > API Keys in your dashboard...

docs-agent> What rate limits apply?

According to the API Reference (./docs/api-reference.md), the default rate
limit is 100 requests per minute per API key...
```

## Common Patterns

### Basic knowledge base

Single format, paragraph chunking for natural document boundaries:

```yaml
ingest:
  sources:
    - "./knowledge-base/**/*.md"
  chunking:
    strategy: paragraph
    chunk_size: 512
    chunk_overlap: 50
```

### Multi-format knowledge base

Mix HTML, Markdown, and PDF sources. Install `initrunner[ingest]` for PDF support:

```yaml
ingest:
  sources:
    - "./docs/**/*.md"
    - "./docs/**/*.html"
    - "./docs/**/*.pdf"
  chunking:
    strategy: fixed
    chunk_size: 1024
    chunk_overlap: 100
```

### URL-based ingestion

Ingest content from remote URLs alongside local files:

```yaml
ingest:
  sources:
    - "./local-docs/**/*.md"
    - "https://docs.example.com/api/reference"
    - "https://docs.example.com/changelog"
```

URL content is hashed — re-running `ingest` skips unchanged pages.

### Auto re-indexing with file watch trigger

Use a `file_watch` trigger to re-ingest when source files change:

```yaml
spec:
  ingest:
    sources:
      - "./knowledge-base/**/*.md"
  triggers:
    - type: file_watch
      paths:
        - ./knowledge-base
      extensions:
        - .md
      prompt_template: "Knowledge base updated: {path}. Re-index."
      debounce_seconds: 1.0
```

### Using `source` filter to scope searches

When your knowledge base spans multiple topics, use the `source` parameter to narrow results:

```yaml
spec:
  role: |
    You are a support agent. When the user asks about billing, search
    only billing docs: search_documents(query, source="*billing*").
    For technical issues, search: search_documents(query, source="*troubleshooting*").
  ingest:
    sources:
      - "./kb/billing/**/*.md"
      - "./kb/troubleshooting/**/*.md"
      - "./kb/general/**/*.md"
```

### Fully local RAG with Ollama

No external API keys needed — use Ollama for both the LLM and embeddings:

```yaml
spec:
  model:
    provider: ollama
    name: llama3.2
  ingest:
    sources:
      - "./docs/**/*.md"
    embeddings:
      provider: ollama
      model: nomic-embed-text
```

See the [Ollama configuration guide](../../docs/configuration/ollama.md) for setup instructions.

## Next Steps

- [Ingestion reference](ingestion.md) — full configuration options, chunking strategies, embedding models
- [Memory reference](memory.md) — session persistence and long-term semantic memory
- [Tool creation guide](../agents/tool_creation.md) — build custom tools alongside RAG
