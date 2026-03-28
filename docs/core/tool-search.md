# Tool Search

When agents have many configured tools (10+), two problems emerge:

1. Tool definitions consume massive context (50 tools can use 10-20K tokens)
2. Model tool-selection accuracy degrades beyond ~30 tools

The **tool search** meta-tool solves both by hiding tools behind a keyword search. The agent sees only a small set of always-available tools plus a `search_tools` function. When it needs a specific tool, it searches by description and matching tools are revealed.

## Configuration

Add `tool_search` to your role's `spec`:

```yaml
spec:
  tool_search:
    enabled: true
    always_available: [current_time, search_documents]
    max_results: 5
    threshold: 0.0
```

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Enable tool search (all existing roles unaffected) |
| `always_available` | list[str] | `[]` | Tool function names always visible to the model |
| `max_results` | int | `5` | Maximum tools returned per search (1-20) |
| `threshold` | float | `0.0` | Minimum BM25 relevance score to include a result |

## How It Works

```
Agent starts → model sees only search_tools + always_available tools
                    ↓
Model calls search_tools("send slack notification")
                    ↓
BM25 keyword search over tool catalog (name + description + params)
                    ↓
Matching tools added to discovered set, results returned to model
                    ↓
prepare_tools callback includes discovered tools on next step
                    ↓
Model sees and calls the actual tool (e.g. send_slack_message)
```

- **BM25 keyword search** — no API calls, no embeddings, works offline
- **PydanticAI `prepare_tools` callback** — tools are genuinely hidden from context, not just marked deferred
- **Discovered tools persist** across turns — once found, a tool stays available for the session
- **Runtime tools pass through** — tools added dynamically (e.g. reflection, scheduling) are always visible

## Ephemeral Mode

Tool search is **automatically enabled** in ephemeral mode (`initrunner run` without a role file). You don't need a `role.yaml` -- the CLI wires it up for you.

### How it works

All tools from the built-in extras (`datetime`, `web_reader`, `search`, `python`, `filesystem`, `slack`, `git`, `shell`) are registered but **hidden** behind tool search. The tools from your selected `--tool-profile` are set as `always_available`, so the agent sees them on every turn. Everything else is discoverable via `search_tools()`.

| Profile | Always visible | Discoverable via search |
|---------|---------------|------------------------|
| `none` | `search_tools` only | All built-in extras |
| `minimal` | `current_time`, `parse_date`, `fetch_page` + `search_tools` | `web_search`, `run_python`, `read_file`, `shell_exec`, etc. |
| `all` | Every tool registered as always-visible | Nothing hidden (no search needed) |

### Example

```bash
initrunner run --tool-profile minimal
```

The agent sees `current_time`, `parse_date`, `fetch_page`, and `search_tools`. When the user asks "search the web for Python 3.13 release notes", the agent calls `search_tools("web search")`, discovers `web_search`, and then calls it — all in the same turn.

Tools added with `--tools` are also set as always-visible. For example, `--tool-profile minimal --tools git` makes `git_log`, `git_diff`, etc. always visible alongside the datetime and web_reader tools.

### Relationship to `--tool-profile all`

The `all` profile registers every tool as always-visible, so `search_tools` has nothing to discover. This is fine for local use, but the context overhead grows with the number of tools. For bots and resource-constrained models, `minimal` (the default) keeps context tight and relies on tool search for anything beyond the basics.

## Dashboard Configuration

Tool search can be configured visually in the [dashboard agent creation wizard](../interfaces/dashboard.md) without hand-editing YAML.

In the **Editor** step, open the **Cognition** panel (lime toggle in the toolbar). The **Tool Search** section appears when the agent has 10 or more tools configured, or when `tool_search` is already enabled in the YAML.

The panel provides:

- **Enable/disable toggle** -- writes `spec.tool_search` to the YAML. On first enable, common functions (`current_time`, `parse_date`, `think`, `search_documents`) are auto-pinned as always-available.
- **Always-visible picker** -- a checklist of all resolved function names (e.g. `current_time`, `fetch_page`, `read_file`) with their origin tool type in parentheses. One tool type can produce multiple functions (e.g. `datetime` produces `current_time` and `parse_date`). Checked functions go into `always_available`; unchecked functions are discoverable via `search_tools` at runtime.
- **Tuning** (collapsed by default) -- `max_results` slider (1-20).

The function name mapping is resolved at startup and served in the builder options response (`tool_func_map`), so the picker resolves locally with no round-trips.

**Agent detail view**: when tool search is enabled, the Config tab shows a **Tool Search** section with the status, always-visible function list, discoverable tool count, and max results. Agent cards display a cyan `search` badge.

## Best Practices

- **Enable when you have 10+ tools** — below that, the overhead isn't worth it
- **Choose `always_available` wisely** — include tools the agent needs on every turn (e.g. `current_time`, `search_documents`)
- **Use descriptive tool names and descriptions** — the search indexes tool names, descriptions, and parameter names
- **Adjust `max_results`** — increase if agents commonly need several tools at once; decrease to keep context tight
