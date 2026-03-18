# InitRunner Support Agent

Ask it questions about InitRunner and it searches a curated knowledge base of 6 articles covering installation, configuration, RAG, memory, providers, and publishing. Remembers your setup details and past interactions across sessions.

## Quick start

```bash
# Install
initrunner install initrunner-team/initrunner-support

# Ingest the knowledge base
initrunner ingest role.yaml

# Interactive session
initrunner run role.yaml -i

# One-shot question
initrunner run role.yaml -p "How do I install InitRunner?"

# Resume where you left off
initrunner run role.yaml -i --resume
```

## Example prompts

```
How do I install InitRunner with uv?
What chunking strategy should I use for markdown docs?
How do I configure memory with consolidation?
I'm using Anthropic -- do I need an OpenAI key for embeddings?
I get an EmbeddingModelChangedError, what do I do?
How do I publish my agent to InitHub?
```

## What's inside

- **Documentation search** -- paragraph-chunked RAG over 6 articles covering the InitRunner essentials
- **File reading** -- full article access when search snippets need more context
- **Three memory types** -- semantic (your preferences/environment), episodic (resolved issues), procedural (your workflows)
- **Session persistence** -- resume conversations with `--resume`
- **Auto-consolidation** -- extracts facts from episodic memories after each session

## Changing the model

Edit `spec.model` in `role.yaml`. If you use RAG or memory, embedding providers resolve independently. Anthropic falls back to OpenAI embeddings (`OPENAI_API_KEY` needed). See the [helpdesk README](../helpdesk/README.md) for how to override embeddings explicitly.
