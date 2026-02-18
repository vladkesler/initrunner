# Ollama & Local Models

InitRunner supports running agents against local LLMs served by [Ollama](https://ollama.com) or any OpenAI-compatible endpoint (vLLM, LiteLLM, llama.cpp server, etc.). This requires **zero additional dependencies** — it reuses the `openai` SDK already bundled with the core install.

## Quick Start

1. Install and start Ollama:

```bash
# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh
ollama serve
```

2. Pull a model:

```bash
ollama pull llama3.2
```

3. Scaffold a role:

```bash
initrunner init --template ollama --name my-local-agent --model llama3.2
```

4. Run the agent:

```bash
initrunner run role.yaml -i
```

## How It Works

Ollama exposes an OpenAI-compatible API at `http://localhost:11434/v1`. When `provider: ollama` is set (or a `base_url` is specified), InitRunner constructs a PydanticAI `OpenAIProvider` with that endpoint instead of calling the real OpenAI API. A dummy API key (`"ollama"`) is set automatically so the SDK doesn't look for `OPENAI_API_KEY` in the environment.

## Configuration

### Minimal Ollama Role

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: local-agent
  description: Agent using local Ollama model
spec:
  role: |
    You are a helpful assistant.
  model:
    provider: ollama
    name: llama3.2          # Run: ollama pull llama3.2
```

### Model Config Reference

```yaml
spec:
  model:
    provider: ollama               # required — triggers local model setup
    name: llama3.2                 # required — model name as known to Ollama
    base_url: http://localhost:11434/v1  # default for ollama; override for remote
    temperature: 0.1               # default: 0.1
    max_tokens: 4096               # default: 4096
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | `str` | — | Set to `"ollama"` for local Ollama models |
| `name` | `str` | — | Model name (e.g. `llama3.2`, `mistral`, `codellama`) |
| `base_url` | `str \| null` | `null` | Custom endpoint URL. Defaults to `http://localhost:11434/v1` when provider is `ollama`. |
| `temperature` | `float` | `0.1` | Sampling temperature (0.0–2.0) |
| `max_tokens` | `int` | `4096` | Maximum tokens per response (1–128000) |

### Custom OpenAI-Compatible Endpoints

The `base_url` field works with any provider, not just Ollama. Use it to point at vLLM, LiteLLM, llama.cpp, or any other server that exposes an OpenAI-compatible API:

```yaml
spec:
  model:
    provider: openai
    name: my-model
    base_url: http://my-server:8000/v1
```

When `base_url` is set on a non-ollama provider, the API key is set to `"custom-provider"` to avoid environment variable lookups. If your endpoint requires authentication, set `OPENAI_API_KEY` in the environment and omit `base_url` (use the standard `openai` provider flow).

## Embeddings

Ollama also serves embeddings. When using ingestion or memory with Ollama, configure the embedding model in the `embeddings` section:

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
      model: nomic-embed-text        # Run: ollama pull nomic-embed-text
      # base_url: http://localhost:11434/v1  # default
```

### Embedding Config Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | `str` | `""` | Embedding provider. Set to `"ollama"` for local embeddings. Empty inherits from `spec.model.provider`. |
| `model` | `str` | `""` | Embedding model name. Empty uses provider default (`nomic-embed-text` for Ollama). |
| `base_url` | `str` | `""` | Custom endpoint URL. Defaults to `http://localhost:11434/v1` when provider is `ollama`. |
| `api_key_env` | `str` | `""` | Env var name holding the embedding API key. Works for both standard providers and custom endpoints. When empty, the default key for the resolved provider is used (not needed for Ollama). |

### Default Embedding Models

| Provider | Default Model |
|----------|--------------|
| `openai` | `text-embedding-3-small` |
| `ollama` | `nomic-embed-text` |
| `google` | `text-embedding-004` |
| `anthropic` | `text-embedding-3-small` (uses OpenAI) |

### Dimension & Model Identity Tracking

Embedding dimensions and model identity are auto-detected from the first batch of embeddings. If you switch embedding models (e.g. from `nomic-embed-text` to `mxbai-embed-large`), the store detects the model change and raises an `EmbeddingModelChangedError`. In the CLI, this triggers an interactive prompt asking whether to wipe the store and re-ingest. Use `--force` to skip the prompt and automatically wipe and re-ingest:

```bash
initrunner ingest role.yaml --force
```

See [Ingestion: Dimension & Model Identity Tracking](../core/ingestion.md#dimension--model-identity-tracking) for full details.

## RAG with Ollama

Full local RAG stack — no external API calls:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: local-rag
  description: Local RAG agent with Ollama
  tags:
    - rag
    - ollama
spec:
  role: |
    You are a knowledge assistant. Use search_documents to find relevant
    content before answering. Always cite your sources.
  model:
    provider: ollama
    name: llama3.2
  ingest:
    sources:
      - "./docs/**/*.md"
      - "./docs/**/*.txt"
    chunking:
      strategy: fixed
      chunk_size: 512
      chunk_overlap: 50
    embeddings:
      provider: ollama
      model: nomic-embed-text
```

```bash
ollama pull llama3.2
ollama pull nomic-embed-text
initrunner ingest role.yaml
initrunner run role.yaml -i
```

## Memory with Ollama

Long-term memory also works fully offline:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: local-memory
  description: Local agent with memory
spec:
  role: |
    You are a helpful assistant with long-term memory.
    Use remember() to save important information.
    Use recall() to search your memories.
  model:
    provider: ollama
    name: llama3.2
  memory:
    max_sessions: 10
    max_memories: 1000
    embeddings:
      provider: ollama
      model: nomic-embed-text
```

## Docker

When running InitRunner inside Docker, `localhost` won't reach the host machine. Use `host.docker.internal` instead:

```yaml
spec:
  model:
    provider: ollama
    name: llama3.2
    base_url: http://host.docker.internal:11434/v1
```

InitRunner automatically detects Docker environments (via `/.dockerenv`) and logs a warning if `base_url` contains `localhost` or `127.0.0.1`.

Alternatively, run Ollama in the same Docker network:

```yaml
# docker-compose.yml
services:
  ollama:
    image: ollama/ollama
    ports:
      - "11434:11434"
  agent:
    build: .
    environment:
      - OLLAMA_HOST=http://ollama:11434/v1
```

```yaml
spec:
  model:
    provider: ollama
    name: llama3.2
    base_url: http://ollama:11434/v1
```

## CLI

### Scaffold an Ollama Role

```bash
initrunner init --template ollama --name my-agent --model mistral
```

This generates a `role.yaml` pre-configured for `provider: ollama` with the specified model (or `llama3.2` by default). After scaffolding, InitRunner pings `http://localhost:11434/api/tags` and prints a warning if Ollama is not reachable.

### Available Templates

Any template works with `--provider ollama`:

```bash
initrunner init --template basic --provider ollama --model codellama
initrunner init --template rag --provider ollama --model llama3.2
initrunner init --template memory --provider ollama
initrunner init --template daemon --provider ollama
initrunner init --template ollama  # dedicated template with Ollama-specific comments
```

### Validate

```bash
initrunner validate role.yaml
```

The validate command shows the model string and provider status. Ollama is always marked as `available` since it uses the bundled OpenAI SDK.

## Troubleshooting

### "Ollama does not appear to be running"

Start the Ollama server:

```bash
ollama serve
```

On macOS, you can also launch the Ollama desktop app.

### Connection refused at runtime

Verify Ollama is running and accessible:

```bash
curl http://localhost:11434/api/tags
```

If using a remote Ollama instance, set `base_url` explicitly:

```yaml
spec:
  model:
    provider: ollama
    name: llama3.2
    base_url: http://remote-host:11434/v1
```

### Model not found

Pull the model before running:

```bash
ollama pull llama3.2
```

List available models:

```bash
ollama list
```

### Slow responses

Local models are limited by your hardware. Tips:

- Use smaller models (`llama3.2` 3B is faster than `llama3.1` 70B)
- Increase `timeout_seconds` in guardrails for larger models
- Use GPU acceleration (Ollama auto-detects CUDA/Metal)

### EmbeddingModelChangedError on ingestion

You switched embedding models. The CLI will prompt you to confirm wiping the store and re-ingesting. To skip the prompt, use `--force`:

```bash
initrunner ingest role.yaml --force
```

## Popular Ollama Models

| Model | Size | Good For |
|-------|------|----------|
| `llama3.2` | 3B | General purpose, fast |
| `llama3.1` | 8B/70B | Higher quality, slower |
| `mistral` | 7B | Balanced performance |
| `codellama` | 7B/13B | Code generation |
| `nomic-embed-text` | 137M | Embeddings (for RAG/memory) |
| `mxbai-embed-large` | 335M | Higher-quality embeddings |
