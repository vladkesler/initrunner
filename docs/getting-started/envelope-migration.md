# Envelope migration

InitRunner's public YAML is flat. `apiVersion`, `kind`, `metadata`, and `spec` are no longer written for Agent, Team, or Flow documents.

Old envelopes still **load**. Convert them with:

```bash
initrunner doctor --fix PATH [--yes] [--no-backup] [--force]
```

`PATH` may be a file or a directory. The rewriter refuses to change a file when it cannot keep execution semantics (for example a Flow whose `metadata.name` is not kebab-case). It writes `PATH.bak` unless you pass `--no-backup`.

## Before

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: web-searcher
spec:
  role: Search the web and cite sources.
  model:
    provider: openai
    name: gpt-5-mini
  tools:
    - type: search
```

## After

```yaml
name: web-searcher
model: openai:gpt-5-mini
prompt: Search the web and cite sources.
tools:
  - search
```

Composed documents use `agents`, `run`, `then`, and `after` (startup order). `personas` is not a public word.

`kind: Service` and `kind: TestSuite` are unchanged.

Filenames stay (`role.yaml`, `flow.yaml`). Nothing is renamed.
