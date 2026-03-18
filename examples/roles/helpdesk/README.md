# Helpdesk Knowledge Base Agent

Drop your company docs into `knowledge-base/` and get an AI helpdesk that answers employee questions using your actual documentation. Supports markdown, plain text, PDF, HTML, and Word files. Remembers user preferences and past interactions across sessions.

## Quick start

```bash
# Install
initrunner install vladkesler/helpdesk

# Add your documents
cp your-docs/* knowledge-base/

# Ingest the knowledge base
initrunner ingest role.yaml

# Interactive session
initrunner run role.yaml -i

# Serve as an OpenAI-compatible API
initrunner serve role.yaml --api-key my-secret-key
```

Ingestion extras for PDF/DOCX: `pip install initrunner[ingest]`

## Example prompts

```
What is the PTO policy?
How do I reset my password?
What are the travel expense limits?
How do I set up the VPN?
What equipment do remote employees receive?
Who do I contact for payroll questions?
```

## What's inside

- **Multi-format ingestion** -- indexes `.md`, `.txt`, `.pdf`, `.html`, `.docx` from `knowledge-base/`
- **Semantic search** -- `search_documents` finds relevant content across all ingested files
- **File reading** -- `read_file` loads full `.md`/`.txt` documents when snippets need more context
- **Three memory types** -- semantic, episodic, procedural with session persistence and auto-consolidation
- **Security hardening** -- prompt injection blocking, PII redaction in audit logs, rate limiting, output filtering
- **API server ready** -- OpenAI-compatible `/v1/chat/completions` with auth and CORS controls

## API usage

```bash
# Start the server
initrunner serve role.yaml --api-key my-secret-key --host 0.0.0.0 --port 8000

# Query it
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer my-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "helpdesk", "messages": [{"role": "user", "content": "How do I reset my password?"}]}'
```

Works with the OpenAI Python SDK -- just point `base_url` at your server.

## Changing the model

Edit `spec.model` in `role.yaml`. If you use RAG or memory, embedding providers resolve independently. Anthropic falls back to OpenAI embeddings (`OPENAI_API_KEY` needed).

To override embeddings explicitly, add `embeddings` blocks to both `ingest` and `memory`:

```yaml
spec:
  model:
    provider: anthropic
    name: claude-sonnet-4-5-20250929
  ingest:
    embeddings:
      provider: google
      model: text-embedding-004
  memory:
    embeddings:
      provider: google
      model: text-embedding-004
```

After changing embedding providers, re-ingest with `--force`: `initrunner ingest role.yaml --force`
