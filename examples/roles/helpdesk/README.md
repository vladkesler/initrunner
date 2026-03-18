# Helpdesk Knowledge Base Agent

A generic internal helpdesk agent powered by RAG and long-term memory. Populate `knowledge-base/` with your own documents and run it as a command, REPL, or OpenAI-compatible API server.

This agent demonstrates how to combine multi-format ingestion, all three memory types, and security hardening in a single role definition optimized for API server mode.

## Features

- **Multi-format ingestion** -- indexes `.md`, `.txt`, `.pdf`, `.html`, and `.docx` files from `knowledge-base/`
- **Semantic search** -- `search_documents` finds relevant content across all ingested files
- **File reading** -- `read_file` loads full `.md` and `.txt` documents when snippets are insufficient
- **Three memory types** -- semantic, episodic, and procedural memory with session persistence
- **Consolidation** -- automatically extracts facts from episodic memories after each session
- **Security hardening** -- prompt injection blocking, PII audit redaction, rate limiting, output length controls
- **API server ready** -- serve as an OpenAI-compatible endpoint with auth and CORS controls

## Quick start

### Install from InitHub

```bash
initrunner install initrunner-team/helpdesk
initrunner run helpdesk -i
```

### Run from source

```bash
cd examples/roles/helpdesk

# Ingest the knowledge base
initrunner ingest role.yaml

# Single question
initrunner run role.yaml -p "What is the PTO policy?"

# Interactive session
initrunner run role.yaml -i

# Resume a previous session
initrunner run role.yaml -i --resume
```

## Populating the knowledge base

Place your documents in `knowledge-base/`. Supported formats:

| Format | Extension | Requirements |
|--------|-----------|-------------|
| Markdown | `.md` | None |
| Plain text | `.txt` | None |
| PDF | `.pdf` | `pip install initrunner[ingest]` |
| HTML | `.html` | `pip install initrunner[ingest]` |
| Word | `.docx` | `pip install initrunner[ingest]` |

After adding or updating files, re-run ingestion:

```bash
initrunner ingest role.yaml
```

### Tips for good documents

- **Use headings** -- they help the chunker create coherent chunks.
- **Keep sections focused** -- one topic per section makes search results more relevant.
- **FAQ format works well** -- question/answer pairs chunk cleanly and match user queries naturally.
- **Self-contained chunks** -- avoid references like "see above" that break when split.

### Chunking strategy

This agent uses `fixed` chunking (512 tokens, 50 overlap) as the safe default for mixed-format knowledge bases. PDF text extraction can produce irregular paragraph boundaries that confuse the `paragraph` chunker.

If your knowledge base is **markdown-only**, you can switch to `paragraph` chunking for better results:

```yaml
  ingest:
    chunking:
      strategy: paragraph
      chunk_size: 512
      chunk_overlap: 50
```

### Why the filesystem tool only allows .md and .txt

The `read_file` tool reads files as UTF-8 text. PDF and DOCX files would produce garbled output. Those formats are still fully searchable via `search_documents` after ingestion -- `read_file` is only needed when a search snippet lacks context and the original is a text-based format.

## Serving as an API

Start the OpenAI-compatible API server:

```bash
initrunner serve role.yaml --api-key my-secret-key --host 0.0.0.0 --port 8000
```

### curl example

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer my-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "helpdesk",
    "messages": [{"role": "user", "content": "How do I reset my password?"}]
  }'
```

### OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="my-secret-key",
)

response = client.chat.completions.create(
    model="helpdesk",
    messages=[{"role": "user", "content": "How do I reset my password?"}],
)
print(response.choices[0].message.content)
```

### CORS

By default, `cors_origins` is empty (no cross-origin requests allowed). To allow a frontend to call the API:

```bash
initrunner serve role.yaml --api-key my-secret-key --cors-origin "https://app.example.com"
```

## Security

| Feature | Description |
|---------|-------------|
| Prompt injection blocking | Blocks inputs matching common injection patterns (e.g. "ignore previous instructions", "reveal system prompt") |
| Output filtering | Strips output matching sensitive patterns (e.g. `password: ...`) |
| PII redaction | Redacts emails, SSNs, phone numbers, and API keys **from audit logs** (does not alter model responses) |
| Input length limit | Rejects prompts over 10,000 characters |
| Output length limit | Truncates responses over 20,000 characters |
| Rate limiting | 30 requests/minute with burst size of 5 |
| Request body limit | 512 KB max request body |
| Conversation cap | 500 max concurrent conversations |

**Note**: `require_https` is off by default for local development. Enable it for production -- see the Production hardening section.

## Example prompts

```
What is the PTO policy?
How do I reset my password?
What are the travel expense limits?
How do I set up the VPN?
What equipment do remote employees receive?
What should I expect on my first day?
Who do I contact for payroll questions?
```

## What this demonstrates

### RAG (Retrieval-Augmented Generation)

- Multi-format ingestion (5 file types) with `fixed` chunking for cross-format reliability
- `search_documents` tool auto-registered from the ingest config
- `filesystem` tool (read-only, `.md`/`.txt` only) for viewing full source documents
- Source citation in responses

### Memory

- All three memory types enabled: semantic (1000), episodic (500), procedural (100)
- `consolidation.interval: after_session` for automatic fact extraction
- Session persistence with `--resume` for multi-turn helpdesk conversations

### Security

- Input pattern blocking (6 prompt injection patterns)
- Output pattern filtering with `strip` action
- PII redaction in audit logs
- Length limits on both input and output
- Rate limiting and request body size controls

### API Server

- OpenAI-compatible `/v1/chat/completions` endpoint
- API key authentication via `--api-key`
- CORS controls (locked down by default)
- Conversation and rate limits for multi-tenant use

## Configuration

| Field | Value | Why |
|-------|-------|-----|
| Model | `openai:gpt-5-mini` | Good balance of quality and cost |
| Temperature | `0.1` | Factual, consistent answers |
| Chunking | `fixed` / 512 / 50 | Safe default for mixed formats |
| Max tokens/run | 30,000 | Room for search + memory + multi-turn |
| Max tool calls | 15 | Search + memory + file reads |
| Timeout | 120s | Reasonable for helpdesk queries |
| Rate limit | 30 req/min, burst 5 | Prevents abuse in API mode |

## Changing the model provider

Changing `spec.model` alone is not enough if you use RAG or memory. Both `ingest.embeddings` and `memory.embeddings` resolve their embedding provider independently. By default, they inherit from `spec.model.provider`, but some providers (notably Anthropic) fall back to OpenAI embeddings, which requires `OPENAI_API_KEY`.

### Default embedding resolution

| Agent provider | Default embedding provider | Requires |
|---------------|---------------------------|----------|
| `openai` | `openai:text-embedding-3-small` | `OPENAI_API_KEY` |
| `anthropic` | `openai:text-embedding-3-small` | `OPENAI_API_KEY` |
| `google` | `google:text-embedding-004` | `GOOGLE_API_KEY` |
| `ollama` | `ollama:nomic-embed-text` | Ollama running locally |

### Example: Anthropic with Google embeddings

```yaml
spec:
  model:
    provider: anthropic
    name: claude-sonnet-4-5-20250929
  ingest:
    sources:
      - "./knowledge-base/**/*.md"
      - "./knowledge-base/**/*.txt"
      - "./knowledge-base/**/*.pdf"
      - "./knowledge-base/**/*.html"
      - "./knowledge-base/**/*.docx"
    chunking:
      strategy: fixed
      chunk_size: 512
      chunk_overlap: 50
    embeddings:
      provider: google
      model: text-embedding-004
  memory:
    embeddings:
      provider: google
      model: text-embedding-004
```

After changing embedding providers, re-ingest with `--force`:

```bash
initrunner ingest role.yaml --force
```

## Production hardening

Before deploying to production:

- [ ] Enable HTTPS: set `security.server.require_https: true` in `role.yaml`
- [ ] Set a strong API key: `initrunner serve role.yaml --api-key <strong-key>`
- [ ] Add CORS origins: `--cors-origin "https://your-app.example.com"`
- [ ] Review rate limits: adjust `requests_per_minute` and `burst_size` for your expected load
- [ ] Consider `secure-api-gateway.yaml` for stricter lockdown (tool sandboxing, resource limits, network restrictions)

## Publishing

```bash
initrunner publish . --readme README.md --category helpdesk --category example
```
