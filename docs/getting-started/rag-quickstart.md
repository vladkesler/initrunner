# RAG in 5 Minutes

Get a document Q&A agent running with three commands. For the full reference, see [RAG Patterns & Guide](../core/rag-guide.md) and [Ingestion](../core/ingestion.md).

> **Before you start:** `initrunner ingest` needs an embedding model. The default is OpenAI `text-embedding-3-small` -- set `OPENAI_API_KEY` to use it, or set `embeddings.provider` to switch providers (Google, Ollama, and more). No API keys? Jump to [Local RAG with Ollama](#local-rag-with-ollama).

## Prerequisites

- InitRunner installed (`pip install initrunner` or `uv tool install initrunner`)
- An API key for your provider (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.) — or [Ollama](../configuration/ollama.md) for fully local RAG
- Documents to index (Markdown, text, HTML, PDF, etc.)

## Step 1: Scaffold a RAG role

```bash
initrunner setup --template rag
```

The wizard configures your provider, API key, and generates a `role.yaml` with ingestion pre-configured for `./docs/**/*.md`.

Edit `role.yaml` to point `sources` at your actual documents:

```yaml
spec:
  ingest:
    sources:
      - "./my-docs/**/*.md"
      - "./my-docs/**/*.txt"
```

## Step 2: Ingest your documents

```bash
initrunner ingest role.yaml
```

This extracts text, splits it into chunks, generates embeddings, and stores vectors locally. A `search_documents` tool is auto-registered on your agent.

## Embedding API Key

| Provider | Default env var | Notes |
|----------|-----------------|-------|
| `openai` | `OPENAI_API_KEY` | |
| `anthropic` | `OPENAI_API_KEY` | Anthropic has no embeddings API -- falls back to OpenAI by default |
| `google` | `GOOGLE_API_KEY` | |
| `ollama` | *(none)* | Runs locally |

**Anthropic users:** set `OPENAI_API_KEY` for the default embedding model, or set `embeddings.provider: google` or `embeddings.provider: ollama` to avoid needing an OpenAI key.

## Step 3: Ask questions

```bash
# Single question
initrunner run role.yaml -p "How do I authenticate?"

# Interactive chat
initrunner run role.yaml -i
```

The agent calls `search_documents` behind the scenes to find relevant chunks from your docs.

## Local RAG with Ollama

No API key needed — use Ollama for both the LLM and embeddings:

```bash
# Install and start Ollama, then pull models
ollama pull llama3.2
ollama pull nomic-embed-text

# Setup with Ollama
initrunner setup --provider ollama
```

Edit the generated `role.yaml` to add ingestion:

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

Then ingest and run:

```bash
initrunner ingest role.yaml
initrunner run role.yaml -i
```

## Quick Alternative: `chat --ingest`

Skip the role file entirely — ingest and chat in one command:

```bash
initrunner chat --ingest "./my-docs/**/*.md"
```

This auto-detects your provider, runs ingestion, and starts a REPL with `search_documents` available. See [Chat & Quick Start](chat.md#document-qa---ingest) for details.

## What's Next

- [RAG Patterns & Guide](../core/rag-guide.md) — common patterns, source filtering, auto re-indexing
- [Ingestion Reference](../core/ingestion.md) — chunking strategies, embedding models, supported formats
- [Tutorial Step 6](tutorial.md) — RAG walkthrough in the full tutorial
