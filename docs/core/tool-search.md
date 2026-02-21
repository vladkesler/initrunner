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

## Best Practices

- **Enable when you have 10+ tools** — below that, the overhead isn't worth it
- **Choose `always_available` wisely** — include tools the agent needs on every turn (e.g. `current_time`, `search_documents`)
- **Use descriptive tool names and descriptions** — the search indexes tool names, descriptions, and parameter names
- **Adjust `max_results`** — increase if agents commonly need several tools at once; decrease to keep context tight
