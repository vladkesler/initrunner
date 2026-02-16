# Example Document

This is a sample document for the local-rag example. Replace it with your own content.

## About This Example

This agent demonstrates fully local RAG using Ollama:

- **LLM**: `llama3.2` runs locally via Ollama.
- **Embeddings**: `nomic-embed-text` generates vectors locally — no API keys needed.
- **Storage**: Chunks and vectors are stored in a local SQLite database.

## Getting Started

1. Place your `.md` or `.txt` files in this `docs/` directory.
2. Run `initrunner ingest local-rag.yaml` to index the documents.
3. Run `initrunner run local-rag.yaml -i` to start chatting.

All processing happens on your machine. No data is sent to external services.
