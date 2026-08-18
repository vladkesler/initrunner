# Intent Sensing

Automatically pick the best matching role for a prompt — no role file argument required.

## Overview

When you have multiple agents and just want to describe a task, Intent Sensing routes your prompt to the right role without you having to specify one. It uses a **two-pass strategy**:

1. **Pass 1 — keyword/tag scoring**: zero API calls. Tokenizes the prompt and scores each discovered role by how well its name, description, and tags match. Selects confidently when one role pulls ahead.
2. **Pass 2 — LLM tiebreaker**: a compact single-turn call used only when the top two candidates score too close together. Skipped entirely when `--dry-run` is active.

The result is displayed in a panel before the agent runs, showing which role was selected and why.

## Quick Start

```bash
# Let initrunner pick the best role
initrunner run --sense -p "analyze this CSV and summarize trends"

# Search a specific directory
initrunner run --sense --role-dir ./roles/ -p "search the web for AI news"

# Preview selection without running (no API calls at all)
initrunner run --sense --dry-run -p "review my Python code for bugs"

# Confirm before committing
initrunner run --sense --confirm-role -p "deploy my app to production"
```

## How It Works

### Pass 1 — Keyword scoring

The prompt is tokenized (lowercased, punctuation stripped, stop words removed, split on whitespace/hyphens/underscores). Each token is matched against three fields of every discovered role:

| Field | Weight | Match type |
|-------|--------|------------|
| `name` | 2.0× | Prefix or substring |
| `description` | 1.5× | Exact token |
| `tags` | 3.0× | Exact token |

The raw score is divided by `min(prompt_token_count, 5)` so longer prompts don't automatically dominate. Roles are then ranked by this normalized score.

**Selection thresholds:**

| Constant | Value | Meaning |
|----------|-------|---------|
| Confidence threshold | 0.35 | Minimum score for Pass 1 to accept a winner |
| Gap threshold | 0.15 | Minimum score difference between 1st and 2nd place |

If both thresholds are met, the top scorer wins immediately — no API call. If either threshold is missed (ambiguous result), control passes to Pass 2.

### Pass 2 — LLM tiebreaker

Up to 15 candidates (by keyword score) are presented to the LLM in a compact single-turn prompt:

```
Task: "<your prompt>"

Choose the best agent role. Reply with ONLY the role name.

Roles:
web-searcher: Searches the web and summarizes results [tags: search, web]
code-reviewer: Reviews Python code for issues [tags: code, review, python]
...

Role:
```

The LLM replies with a single role name. That name is matched (case-insensitively) back to the candidate list to select the winner.

If the LLM call fails for any reason (network error, unrecognized response, etc.), Intent Sensing silently falls back to the Pass 1 top scorer. It never crashes the run.

### Selection outcomes

After sensing, the result panel shows one of four methods:

| Method | Meaning |
|--------|---------|
| `only role available` | Only one valid role was found — selected immediately |
| `keyword match` | Pass 1 selected confidently; shows score and gap |
| `LLM selection` | Pass 2 resolved an ambiguous set |
| `fallback — no strong match` | Pass 1 was ambiguous and Pass 2 was skipped or failed |

## Role Discovery

Intent Sensing scans every `*.yaml` / `*.yml` file (recursively, at any depth, skipping `node_modules`, `.venv`, `__pycache__`, `.git` and similar) and keeps the ones that load as agent documents. The directories are searched in this order:

1. `--role-dir PATH` (if provided): searched first, **in addition to** the directories below
2. Current working directory (`.`)
3. `./examples/roles/` — if the directory exists
4. Global roles directory (`~/.initrunner/roles/`, or `$INITRUNNER_HOME/roles/` or `$XDG_DATA_HOME/initrunner/roles/` when those variables are set)
5. Bundled starter examples shipped with the package

Roles with parse errors are skipped silently. Only successfully loaded roles enter the scoring pool.

## CLI Flags

| Flag | Description |
|------|-------------|
| `--sense` | Enable intent sensing (replaces the `role.yaml` argument) |
| `--role-dir PATH` | Extra directory searched first, in addition to the default directories |
| `--confirm-role` | Show the sensed role and ask for confirmation before running (requires a TTY) |
| `--dry-run` | Score roles with keyword matching only — no LLM calls, no agent execution |

`--sense` and a positional `role.yaml` argument are mutually exclusive. `--sense` requires `--prompt` (`-p`).

## Configuration

### LLM tiebreaker model

Set `INITRUNNER_DEFAULT_MODEL` to control which model is used for Pass 2:

```bash
export INITRUNNER_DEFAULT_MODEL="openai:gpt-4o-mini"   # default
export INITRUNNER_DEFAULT_MODEL="anthropic:claude-haiku-4-5-20251001"
export INITRUNNER_DEFAULT_MODEL="ollama:llama3.2"
```

The tiebreaker prompt is short (a handful of role descriptions plus the user prompt), so a small, fast model is appropriate and recommended.

## Optimizing Roles for Sensing

Pass 1 scoring relies entirely on the top-level `name`, `description`, and `tags` you write. Well-tagged roles are selected faster and more reliably.

**Use specific, task-oriented tags.** Tags carry the highest weight (3×):

```yaml
name: web-searcher
description: Searches the web and summarizes results into concise reports
tags: [search, web, research, summarize, browse]
```

**Use domain keywords in `description`.** Description tokens score at 1.5×. One clear sentence beats a vague paragraph:

```yaml
# Good
description: Analyzes CSV and Excel files, computes statistics, and plots charts

# Weaker
description: A helpful data agent that can do many things with files
```

**Match your `name` to the primary verb.** Name tokens score at 2× with prefix matching, so `code-reviewer` will match prompts containing "review", "code", "check":

```yaml
# Matches: "review my code", "code review", "check code quality"
name: code-reviewer

# Matches: "deploy app", "deployment", "release"
name: deployment-agent
```

**Avoid overlapping tags across roles.** If two roles both have `tags: [python]`, Pass 1 scores them equally for Python tasks and the LLM tiebreaker is invoked. Reserve broad tags for the role most suited to handle them.

## Examples

### Multiple specialist roles

```
roles/
  web-searcher.yaml   tags: [search, web, research, news, browse]
  code-reviewer.yaml  tags: [code, review, lint, python, quality]
  csv-analyst.yaml    tags: [csv, excel, data, statistics, chart]
  sql-agent.yaml      tags: [sql, database, query, postgres, mysql]
```

```bash
initrunner run --sense -p "find the latest Python 3.14 release notes"
# → web-searcher (keyword: "find", "latest", tags: search, web)

initrunner run --sense -p "review my pull request for style issues"
# → code-reviewer (keyword: "review", tags: code, review)

initrunner run --sense -p "plot monthly sales from sales.csv"
# → csv-analyst (keyword: "plot", "csv", tags: csv, chart)
```

### Dry-run exploration

Use `--dry-run` to see how roles score without running anything:

```bash
initrunner run --sense --dry-run -p "send a slack message about the deployment"
```

The panel shows the selected role, its score, and the gap to the runner-up — useful for debugging tag coverage.

### Confirm before executing

```bash
initrunner run --sense --confirm-role -p "delete old log files"
```

The panel is displayed, then:

```
Use this role? [Y/n]:
```

Answering `n` exits cleanly (exit code 0) without running the agent.

## Troubleshooting

### Wrong role selected

Check which role won and why using `--dry-run`:

```bash
initrunner run --sense --dry-run -p "your prompt"
```

The panel shows the method (`keyword match` or `LLM selection`), score, and gap. If Pass 1 is scoring unexpectedly:

- Add more specific tags to the intended role
- Remove overlapping tags from other roles
- Make the description more specific to the task domain

### "No valid role files found"

Intent Sensing searched all default directories and found nothing loadable. Fix options:

- Point at a specific directory: `--role-dir ./my-roles/`
- Create a role: `initrunner new --blank`
- Check that existing role files parse correctly: `initrunner validate role.yaml`

### LLM tiebreaker fails

When Pass 2 fails, Intent Sensing falls back to the Pass 1 top scorer (method shown as `fallback`). Common causes:

- No API key set for the default model — set `OPENAI_API_KEY` or change `INITRUNNER_DEFAULT_MODEL`
- The LLM response didn't match any candidate name — rare, but retry usually fixes it
- Network issue — check connectivity

To avoid Pass 2 entirely, use `--dry-run` (skips LLM) or improve tag coverage so Pass 1 is always decisive.

### Prompt has no meaningful keywords

If every word in the prompt is a stop word (e.g. "do it"), Intent Sensing raises an error before searching. Use a prompt with at least one content word.

## Flow Integration

Intent Sensing can also auto-route messages between agents in a [flow pipeline](../orchestration/flow.md). Set `strategy: keyword` or `strategy: sense` on a multi-target delegate sink:

```yaml
triager:
  use: roles/triager.yaml
  then:
    to: [researcher, responder, escalator]
    strategy: sense
```

The same two-pass scoring (keyword + optional LLM tiebreak) runs on each message, using the target agents' role metadata (name, description, tags) as candidates. See [Flow -- Routing Strategy](../orchestration/flow.md#routing-strategy) for full details.

### Dashboard Configuration

The [dashboard flow builder](../interfaces/dashboard.md) surfaces routing strategy as a first-class option when creating a new flow with the **Route** pattern. Three inline pill buttons (Broadcast / Keyword / Sense) let you choose the strategy visually, with Sense recommended by default. A collapsible detail section shows scoring weights and per-slot quality indicators based on whether the assigned agents have tags and descriptions.

The Route pattern supports variable agent counts (3-10) with semantic specialist names (`researcher`, `responder`, `escalator`, `analyst`, etc.) that contribute to the 2x name-match weight in scoring. After creation, the flow detail Events tab shows a **Routing** column with the method and score for each delegation event.
