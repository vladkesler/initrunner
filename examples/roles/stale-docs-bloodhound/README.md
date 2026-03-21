# Stale Docs Bloodhound

Watches source code for changes, searches documentation for stale references using ripgrep and RAG, and files GitHub issues when documentation is confidently out of date.

## Quick start

```bash
# Install
initrunner install vladkesler/stale-docs-bloodhound

# Ingest your documentation for semantic search
initrunner ingest role.yaml

# Set your GitHub token (repo scope required)
export GITHUB_TOKEN=ghp_...

# Start watching for code changes
initrunner run role.yaml --daemon
```

## Prerequisites

- **GITHUB_TOKEN** -- personal access token with `repo` scope. The agent uses it to search existing issues, create new ones, and add comments.
- **ripgrep** (`rg`) -- used for exact identifier matching across documentation files. Install via your package manager (`apt install ripgrep`, `brew install ripgrep`, etc.).
- **Git repository** -- the agent must run from inside a git repo that has documentation files (markdown, rst, or plain text).

## How it works

The agent follows a 7-step pipeline for every code change:

1. **Read the diff** -- extracts changed identifiers (function names, CLI flags, config keys, defaults, error messages)
2. **Skip noise** -- ignores whitespace-only, comment-only, test, and generated file changes
3. **Exact search with rg** -- runs ripgrep over doc directories for each identifier
4. **Semantic fallback with RAG** -- uses `search_documents` to catch paraphrased references that rg misses
5. **Verify each hit** -- reads the full doc context and compares against the new code
6. **Classify severity** -- breaking, incorrect, incomplete, or cosmetic
7. **Deduplicate and file** -- checks for existing `stale-docs` issues, then creates or comments

## Example session

A function `parse_config` is renamed to `load_config` in `src/config.py`:

```
[file_watch trigger] Source file changed: src/config.py

> git_diff(path="src/config.py")
-def parse_config(path: str, strict: bool = True) -> Config:
+def load_config(path: str, strict: bool = False) -> Config:

> shell: rg -n --glob '*.md' 'parse_config' docs/ README.md
docs/configuration.md:42:Call `parse_config("settings.yaml")` to load your config.
docs/api-reference.md:118:### parse_config(path, strict=True)

> read_file("docs/configuration.md", lines="38-48")
[confirms doc references old function name and old default]

> list_issues(owner="acme", repo="myapp", labels="stale-docs")
[no matching open issues]

> create_issue(owner="acme", repo="myapp",
    title="Stale docs: configuration.md references parse_config",
    body="## Stale documentation found\n\n**Source change**: `src/config.py` -- "
         "`parse_config` renamed to `load_config`, `strict` default changed "
         "from `True` to `False`\n\n**Affected docs**:\n"
         "- `docs/configuration.md:42` -- references `parse_config`\n"
         "- `docs/api-reference.md:118` -- shows old signature with `strict=True`\n\n"
         "**Severity**: incorrect\n\n"
         "**Suggested fix**: Replace `parse_config` with `load_config` and "
         "update the `strict` default to `False` in both files.",
    labels="stale-docs")
Created issue #47
```

## Example prompts

```
Check docs for staleness against the last 5 commits
Analyze docs/api.md against current source
What documentation is stale in this repo?
Check if the README is up to date with the latest changes
Review the diff in abc1234..def5678 for doc staleness
```

## Daemon mode

In daemon mode (`initrunner run role.yaml --daemon`), the file-watch trigger monitors `./src` and `./lib` for changes to source files. When a file is saved, the agent waits 5 seconds (debounce), then runs the full analysis pipeline autonomously.

The agent caps at 5 issue actions per trigger event to avoid flooding your issue tracker.

## Customization

**Watched paths** -- edit `triggers[0].paths` to match your project layout:

```yaml
triggers:
  - type: file_watch
    paths:
      - ./src
      - ./lib
      - ./cmd
```

**File extensions** -- edit `triggers[0].extensions` to add or remove file types.

**Documentation sources** -- edit `ingest.sources` to match where your docs live:

```yaml
ingest:
  sources:
    - "./documentation/**/*.md"
    - "./wiki/**/*.md"
    - "./*.md"
```

Re-ingest after changing sources: `initrunner ingest role.yaml --force`

**GitHub repo override** -- by default the agent parses the repo from `git remote get-url origin`. Set `GITHUB_REPO=owner/repo` to override.

## What's inside

- **Dual search strategy** -- ripgrep for exact identifier matching, RAG for semantic fallback
- **Git-native** -- reads diffs and history directly, works with any branch or ref
- **Smart dedup** -- searches existing `stale-docs` issues before filing, adds comments to open issues
- **Severity classification** -- breaking, incorrect, incomplete, cosmetic
- **Three memory types** -- semantic (code-to-doc mappings), episodic (past findings), procedural (learned skip rules)
- **Rate-limited filing** -- max 5 issue actions per trigger, high-confidence only
- **Read-only on source** -- never modifies code or docs, only files issues

## Changing the model

Edit `spec.model` in `role.yaml`. RAG and memory use embeddings that resolve independently from the chat model. Anthropic falls back to OpenAI embeddings (`OPENAI_API_KEY` needed). To override embeddings explicitly:

```yaml
spec:
  ingest:
    embeddings:
      provider: openai
      model: text-embedding-3-small
  memory:
    embeddings:
      provider: openai
      model: text-embedding-3-small
```

After changing embedding providers, re-ingest with `--force`: `initrunner ingest role.yaml --force`
