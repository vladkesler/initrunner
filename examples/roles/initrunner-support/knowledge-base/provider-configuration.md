# Provider Configuration

InitRunner supports multiple LLM providers. Each provider requires its own API key (except Ollama, which runs locally).


## Standard providers

| Provider | Env var | Extra package | Example model |
|----------|---------|---------------|---------------|
| `openai` | `OPENAI_API_KEY` | *(included)* | `gpt-5-mini` |
| `anthropic` | `ANTHROPIC_API_KEY` | `initrunner[anthropic]` | `claude-sonnet-4-5-20250929` |
| `google` | `GOOGLE_API_KEY` | `initrunner[google]` | `gemini-2.0-flash` |
| `groq` | `GROQ_API_KEY` | `initrunner[groq]` | `llama-3.3-70b-versatile` |
| `mistral` | `MISTRAL_API_KEY` | `initrunner[mistral]` | `mistral-large-latest` |
| `cohere` | `CO_API_KEY` | `initrunner[all-models]` | `command-r-plus` |
| `bedrock` | `AWS_ACCESS_KEY_ID` | `initrunner[all-models]` | `us.anthropic.claude-sonnet-4-20250514-v1:0` |
| `xai` | `XAI_API_KEY` | `initrunner[all-models]` | `grok-3` |
| `ollama` | *(none)* | *(included)* | `llama3.2` |


## Provider YAML snippets

### OpenAI

```yaml
spec:
  model:
    provider: openai
    name: gpt-5-mini
```

### Anthropic

```yaml
spec:
  model:
    provider: anthropic
    name: claude-sonnet-4-5-20250929
```

Requires: `pip install initrunner[anthropic]`

### Google

```yaml
spec:
  model:
    provider: google
    name: gemini-2.0-flash
```

Requires: `pip install initrunner[google]`

### Ollama (fully local, no API key)

```yaml
spec:
  model:
    provider: ollama
    name: llama3.2
```

Ollama must be running locally. Start it with `ollama serve`. Pull a model with `ollama pull llama3.2`.

For remote Ollama or Docker, set `base_url`:

```yaml
spec:
  model:
    provider: ollama
    name: llama3.2
    base_url: http://192.168.1.50:11434/v1
```

### Custom endpoint (e.g. OpenRouter)

```yaml
spec:
  model:
    provider: openai
    name: anthropic/claude-sonnet-4
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
```


## Model config reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | `str` | *(empty)* | Provider name |
| `name` | `str` | *(required)* | Model identifier or alias |
| `base_url` | `str` | `null` | Custom endpoint URL |
| `api_key_env` | `str` | `null` | Env var name for API key |
| `temperature` | `float` | `0.1` | Sampling temperature (0.0-2.0) |
| `max_tokens` | `int` | `4096` | Max tokens per response (1-128000) |


## Model aliases

Create `~/.initrunner/models.yaml` to define short aliases:

```yaml
aliases:
  fast: openai:gpt-4o-mini
  smart: anthropic:claude-sonnet-4-5-20250929
  local: ollama:llama3.2
  cheap: groq:llama-3.3-70b-versatile
```

Use aliases anywhere:

```bash
initrunner run role.yaml -p "hello" --model fast
export INITRUNNER_MODEL=smart
```

Or in role.yaml (omit `provider` so the alias is resolved):

```yaml
spec:
  model:
    name: fast
```

Model resolution precedence:
1. `--model` CLI flag or `INITRUNNER_MODEL` env var
2. Role YAML `spec.model` (with alias resolution)
3. `chat.yaml` defaults (ephemeral chat only)
4. Auto-detection (ephemeral chat only)


## Embedding provider defaults

Embeddings are used by both RAG (ingestion) and memory. By default, the embedding provider is derived from `spec.model.provider`. This is critical to understand because some providers do not offer their own embedding API.

| Agent provider | Default embedding | Requires |
|---------------|-------------------|----------|
| `openai` | `openai:text-embedding-3-small` | `OPENAI_API_KEY` |
| `anthropic` | `openai:text-embedding-3-small` | `OPENAI_API_KEY` |
| `google` | `google:text-embedding-004` | `GOOGLE_API_KEY` |
| `ollama` | `ollama:nomic-embed-text` | Ollama running locally |
| All others | `openai:text-embedding-3-small` | `OPENAI_API_KEY` |

**Important:** If you use Anthropic as your model provider, you still need `OPENAI_API_KEY` for embeddings (RAG and memory) unless you override the embedding config.

### Overriding embedding provider

Override embeddings in both `ingest` and `memory` sections:

```yaml
spec:
  model:
    provider: anthropic
    name: claude-sonnet-4-5-20250929
  ingest:
    sources: ["./docs/**/*.md"]
    embeddings:
      provider: google
      model: text-embedding-004
  memory:
    embeddings:
      provider: google
      model: text-embedding-004
```

### Custom embedding endpoint

```yaml
spec:
  ingest:
    embeddings:
      provider: openai
      model: my-embedding-model
      base_url: https://my-service.example.com/v1
      api_key_env: MY_EMBEDDING_API_KEY
```


## Ollama setup

Ollama provides a fully local experience with no API keys:

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Start the server
ollama serve

# Pull models
ollama pull llama3.2           # chat model
ollama pull nomic-embed-text   # embedding model

# Scaffold an Ollama role
initrunner new --template ollama
```

For RAG and memory with Ollama, explicitly set the embedding provider:

```yaml
spec:
  model:
    provider: ollama
    name: llama3.2
  ingest:
    sources: ["./docs/**/*.md"]
    embeddings:
      provider: ollama
      model: nomic-embed-text
  memory:
    embeddings:
      provider: ollama
      model: nomic-embed-text
```

Popular Ollama models:

| Model | Size | Good for |
|-------|------|----------|
| `llama3.2` | 3B | General purpose, fast |
| `llama3.1` | 8B/70B | Higher quality |
| `mistral` | 7B | Balanced |
| `codellama` | 7B/13B | Code generation |
| `nomic-embed-text` | 137M | Embeddings |
| `mxbai-embed-large` | 335M | Higher quality embeddings |
