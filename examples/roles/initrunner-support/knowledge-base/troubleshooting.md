# Troubleshooting

Common errors and their solutions when working with InitRunner.


## No API key found

**Error:**
```
Error: No API key found. Run initrunner setup or set an API key environment variable.
```

**Cause:** No provider API key is configured. InitRunner checks for keys in this order: Anthropic, OpenAI, Google, Groq, Mistral, Cohere, Ollama.

**Fix:**

```bash
# Option 1: Run the setup wizard
initrunner setup

# Option 2: Export directly
export OPENAI_API_KEY="sk-..."

# Option 3: Use a .env file
echo 'OPENAI_API_KEY=sk-...' >> ~/.initrunner/.env

# Option 4: Use Ollama (no key needed)
ollama serve
```


## EmbeddingModelChangedError

**Error:**
```
EmbeddingModelChangedError: Embedding model changed from 'openai:text-embedding-3-small'
to 'google:text-embedding-004'. Use --force to wipe and re-ingest.
```

**Cause:** The vector store was created with one embedding model, and you are now using a different one. Embedding models produce vectors with different dimensions and semantics, so they cannot be mixed.

**Fix:**

```bash
initrunner ingest role.yaml --force
```

This wipes the existing store and re-ingests all documents with the new model. If you have memory data, clear it too:

```bash
initrunner memory clear role.yaml --force
```

**Prevention:** Decide on your embedding provider before ingesting large document sets. See the Provider Configuration article for embedding defaults by provider.


## DimensionMismatchError

**Error:**
```
DimensionMismatchError: Expected 1536 dimensions, got 768
```

**Cause:** The embedding model produces vectors with a different number of dimensions than what is stored. This usually happens when switching between providers (e.g. OpenAI's 1536-dim vs Google's 768-dim).

**Fix:** Same as EmbeddingModelChangedError -- re-ingest with `--force`:

```bash
initrunner ingest role.yaml --force
```


## Missing extras / import errors

**Error:**
```
ModuleNotFoundError: No module named 'anthropic'
```

**Cause:** The provider SDK is not installed. Only the OpenAI and Ollama providers are included by default.

**Fix:** Install the required extra:

```bash
pip install initrunner[anthropic]     # for Anthropic
pip install initrunner[google]        # for Google
pip install initrunner[groq]          # for Groq
pip install initrunner[mistral]       # for Mistral
pip install initrunner[all-models]    # all providers
pip install initrunner[ingest]        # PDF, DOCX, XLSX support
```


## Tools not being called

**Symptom:** The agent answers questions without calling `search_documents` or other tools.

**Possible causes and fixes:**

1. **System prompt does not instruct tool use.** Add clear instructions like "ALWAYS call search_documents before answering a question" to `spec.role`.

2. **Tool call limit too low.** Check `guardrails.max_tool_calls`. If the agent hits the limit, it stops calling tools.

3. **Temperature too high.** Higher temperatures make tool calls less reliable. Use `temperature: 0.1` for tool-heavy agents.

4. **Documents not ingested.** Run `initrunner ingest role.yaml` before running the agent. The `search_documents` tool is only registered when `spec.ingest` is configured.


## Memory not persisting

**Symptom:** The agent does not remember information from previous sessions.

**Possible causes and fixes:**

1. **Memory not configured.** Add a `memory` section to your role.yaml. See the Memory Configuration article.

2. **Not using --resume.** Session history is only loaded when you pass `--resume`:
   ```bash
   initrunner run role.yaml -i --resume
   ```

3. **Using chat without memory.** Check that `--no-memory` is not set. Chat mode has memory enabled by default.

4. **Agent not calling memory tools.** Add instructions to your system prompt telling the agent when to use `remember()`, `recall()`, etc.


## search_documents returns no results

**Symptom:** `search_documents` returns empty or irrelevant results.

**Possible causes and fixes:**

1. **Documents not ingested.** Run:
   ```bash
   initrunner ingest role.yaml
   ```

2. **Query vocabulary mismatch.** Rephrase the query. Embedding search is semantic, so "authentication" may not match "login credentials" if the embedding model does not capture the relationship.

3. **Chunk size too large.** If chunks are 1024+ characters, specific questions may get diluted. Try `chunk_size: 256` or `chunk_size: 512`.

4. **Source filter too restrictive.** If using the `source` parameter, check that the glob pattern matches your files.

5. **Wrong embedding model.** If you changed `spec.model.provider` since the last ingest, the embedding model may have changed. Re-ingest with `--force`.


## Provider resolution errors

**Error:**
```
Could not resolve provider for model 'my-model'. Either specify 'provider' explicitly,
use 'provider:model' format, or add an alias to ~/.initrunner/models.yaml
```

**Cause:** InitRunner cannot determine which provider to use for the given model name.

**Fix:** Either set `provider` explicitly in your role.yaml:

```yaml
spec:
  model:
    provider: openai
    name: gpt-5-mini
```

Or use `provider:model` format:

```yaml
spec:
  model:
    name: openai:gpt-5-mini
```

Or define an alias in `~/.initrunner/models.yaml`:

```yaml
aliases:
  my-model: openai:gpt-5-mini
```


## Ollama connectivity

**Error:**
```
Connection refused: http://localhost:11434
```

**Cause:** Ollama is not running or not reachable.

**Fix:**

```bash
# Start Ollama
ollama serve

# Verify it is running
curl http://localhost:11434/api/tags

# Pull a model if needed
ollama pull llama3.2
```

For Docker or remote Ollama, set `base_url` in your role.yaml:

```yaml
spec:
  model:
    provider: ollama
    name: llama3.2
    base_url: http://host.docker.internal:11434/v1  # Docker
```


## Anthropic users needing OPENAI_API_KEY

**Symptom:** Using Anthropic as your model provider but getting errors about missing `OPENAI_API_KEY` when using RAG or memory.

**Cause:** Anthropic does not provide an embedding API. By default, InitRunner falls back to OpenAI embeddings (`text-embedding-3-small`), which requires `OPENAI_API_KEY`.

**Fix:** Either:

1. Set `OPENAI_API_KEY` in addition to `ANTHROPIC_API_KEY`

2. Override the embedding provider to one you have keys for:
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

3. Use Ollama embeddings (no key needed):
   ```yaml
   spec:
     ingest:
       embeddings:
         provider: ollama
         model: nomic-embed-text
     memory:
       embeddings:
         provider: ollama
         model: nomic-embed-text
   ```


## Diagnosing issues with doctor

When in doubt, run the doctor command:

```bash
initrunner doctor
```

This checks all provider API keys, SDK availability, and Ollama connectivity in one table. For a full end-to-end test:

```bash
initrunner doctor --quickstart --role role.yaml
```
