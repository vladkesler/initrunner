# TUI Dashboard

InitRunner includes a k9s-style terminal UI for browsing roles, running agents, monitoring daemons, and inspecting audit/memory data — all from a single keyboard-driven interface.

The TUI is built with [Textual](https://textual.textualize.io/) (by the same team behind Rich) and available as an optional extra (`pip install initrunner[tui]`).

## Quick Start

```bash
# Launch the TUI dashboard
initrunner tui

# Scan a specific directory for roles
initrunner tui --role-dir ./my-roles
```

## CLI Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--role-dir` | `Path` | — | Directory to scan for role YAML files. If not specified, scans cwd, `examples/roles/`, and `~/.initrunner/roles/`. |

## Navigation Model

The TUI follows a k9s-style navigation model: a home screen with keyboard shortcuts to push deeper screens onto a stack.

- **Screen stack**: Press a key to push a new screen. Press `Escape` to pop back.
- **Header**: Shows `InitRunner` title and breadcrumb (e.g. `Roles > support-agent > Run`).
- **Footer**: Context-sensitive key hints for the current screen.

### Global Key Bindings

These work on every screen:

| Key | Action |
|-----|--------|
| `?` | Open help screen (keyboard shortcut reference) |
| `a` | Open audit log |
| `q` | Quit application |
| `Escape` | Go back / close modal |

## Screens

### Roles Screen (Home)

The home screen. On launch, it scans for `apiVersion: initrunner/v1` YAML files in:

1. The `--role-dir` directory (if specified)
2. Current working directory
3. `examples/roles/` (relative to cwd)
4. `~/.initrunner/roles/` (if it exists)

Discovered roles are displayed in a table:

| Column | Description |
|--------|-------------|
| Status | `●` green = valid, `●` red = invalid |
| Name | Role `metadata.name` |
| Description | Role `metadata.description` |
| Model | `provider:model` string |
| Tools | Number of configured tools |
| Triggers | Number of configured triggers |
| Ingest | `yes` if `ingest:` is configured |
| Memory | `yes` if `memory:` is configured |

**Key bindings:**

| Key | Action |
|-----|--------|
| `Enter` | Open role detail screen |
| `Ctrl+R` | Fast run — bypass detail, open chat directly |
| `n` | Scaffold new role from template |
| `/` | Toggle filter bar — filter roles by name |
| `r` | Refresh role list |

#### New Role Modal

Pressing `n` opens a template picker where you can choose a name and template (`basic`, `rag`, `daemon`, `memory`, `ollama`). The role is written to the current directory.

#### YAML Viewer Modal

Pressing `e` opens a read-only modal showing the full YAML content of the selected role.

### Role Detail Screen

Pressing `Enter` on a role in the Roles Screen opens this configuration overview. It shows all configured sections (Model, System Prompt, Tools, Triggers, Sinks, Ingest, Memory, Guardrails, Security) as styled cards, with unconfigured sections summarized at the bottom.

**Key bindings:**

| Key | Action |
|-----|--------|
| `Enter` | Edit section — opens a picker of all configured sections |
| `r` | Run interactive chat |
| `v` | Validate role (shows result notification) |
| `i` | Open ingestion screen (requires `ingest:` config) |
| `d` | Open daemon screen (requires `triggers:` config) |
| `m` | Open memory screen (requires `memory:` config) |
| `e` | View role YAML in read-only modal |
| `Escape` | Go back to roles list |

#### Editing Sections

Pressing `Enter` opens a section picker listing all editable sections. The available sections are:

- **Model** — provider, name, temperature, max tokens, base URL
- **System Prompt** — opens a multi-line text editor (TextArea)
- **Guardrails** — max tokens per run, timeout, max tool calls, max request limit
- **Tools** — per-tool fields vary by type (filesystem, http, mcp, custom, delegate)
- **Triggers** — per-trigger fields vary by type (cron, file_watch, webhook)
- **Sinks** — per-sink fields vary by type (webhook, file, custom)
- **Ingest** — sources, chunking strategy/size/overlap, store backend
- **Memory** — max sessions, max memories, max resume messages, store backend

Tools, Triggers, and Sinks are list sections — if the role has a single item, the field editor opens directly. If there are multiple items, a sub-picker shows each item's summary before opening the editor for the selected item.

All field editors validate types before saving (e.g. integers, floats, booleans). Invalid values show an error notification and prevent the save. Changes are written to the YAML file and the role is reloaded/revalidated automatically.

### Run Screen (Streaming Chat)

Interactive chat with an agent. The layout has three sections:

```
┌─ Agent: support-agent | openai:gpt-4o-mini | tokens: 1.2k in / 890 out ─┐
│                                                                           │
│  you                                                                      │
│  What files are in the knowledge base?                                    │
│                                                                           │
│  agent                                                                    │
│  Based on searching the documents, I found...                             │
│  - guide.md (customer onboarding)                                         │
│  - faq.md (frequently asked questions)                                    │
│                                                                           │
├───────────────────────────────────────────────────────────────────────────┤
│ > Type your message...                                                    │
└───────────────────────────────────────────────────────────────────────────┘
```

- **Status bar**: Agent name, model, cumulative token counts.
- **Chat area**: Scrollable message history. User messages have a blue border; agent messages have a green border and are rendered as Markdown.
- **Input area**: Multi-line `TextArea` (supports pasting code snippets). Grows from 3 to 8 lines as you type.

**Key bindings:**

| Key | Action |
|-----|--------|
| `Ctrl+Enter` | Send message |
| `Ctrl+D` | Exit chat (back to roles) |
| `Ctrl+R` | Resume previous session (requires `memory:` config) |
| `Escape` | Exit chat (back to roles) |

#### Streaming

Agent responses stream in real time. The TUI uses `agent.run_stream_sync()` in a worker thread. Tokens are batched (flushed every 10 tokens or 50 ms) to reduce Markdown re-parsing overhead — a typical 4000-token response triggers ~80 renders instead of 4000. If streaming fails (e.g., the model doesn't support it), the TUI falls back to a non-streamed call with a "Thinking..." indicator.

#### Chat Message Limit

To keep the UI responsive during long sessions, the chat view automatically removes the oldest messages when the count exceeds 200 (keeping the most recent 150). This pruning is invisible to the agent's conversation history — it only affects the displayed widgets.

#### Session Persistence

If the role has a `memory:` config, each exchange is saved to the memory store automatically (same behavior as `initrunner run -i`). Use `Ctrl+R` to resume the most recent session, loading up to `max_resume_messages` messages.

### Audit Screen

Browse the audit trail from `~/.initrunner/audit.db`.

| Column | Description |
|--------|-------------|
| Timestamp | ISO 8601 (truncated to seconds) |
| Agent | Agent name |
| Run ID | First 8 characters |
| Model | Model name |
| Tokens | `in/out` token counts |
| Duration | Run duration in ms |
| Status | `OK` (green) or `FAIL` (red) |

**Key bindings:**

| Key | Action |
|-----|--------|
| `Enter` | View full audit record detail |
| `/` | Toggle filter bar — filter by agent name |
| `r` | Refresh records |
| `Escape` | Go back |

#### Detail Modal

Pressing `Enter` on a record opens a modal showing:

- Run metadata (run ID, agent, timestamp, model, provider, token counts, tool calls, duration, status)
- Error message (if any)
- Trigger type and metadata (if trigger-initiated)
- User prompt (plain text)
- Agent output (rendered as Markdown)

### Ingest Screen

Manage document ingestion for a role. Shows matched source files and supports running the ingestion pipeline.

| Column | Description |
|--------|-------------|
| File | Relative file path |
| Status | Ingestion status |
| Chunks | Number of chunks (after ingestion) |

**Key bindings:**

| Key | Action |
|-----|--------|
| `i` | Run ingestion |
| `f` | Force re-ingest (ignores content hash) |
| `r` | Refresh sources |
| `Escape` | Go back |

A progress bar appears during ingestion, showing the current file being processed. On completion, a summary displays counts of new, updated, skipped, and errored files.

### Memory Screen

Browse and manage agent memories. Uses tabbed navigation:

- **Memories tab**: Table of stored memories (ID, content preview, category, timestamp).
- **Sessions tab**: Session management info.

**Key bindings:**

| Key | Action |
|-----|--------|
| `x` | Clear memory (opens type-to-confirm modal) |
| `e` | Export memories to JSON (`<agent-name>-memories.json` in cwd) |
| `/` | Toggle search bar — filter by category |
| `r` | Refresh |
| `Escape` | Go back |

#### Clear Confirmation

Pressing `x` opens a modal that requires typing "delete" to confirm. This prevents accidental data loss — memory deletion is irreversible.

### Daemon Screen

Start and stop a trigger-driven daemon, monitoring events in real time.

**Layout:**

- **Status bar**: Agent name and running/stopped state.
- **Trigger table**: Type, config summary, last fired timestamp, fire count.
- **Event log**: Live `RichLog` showing trigger events and agent responses with timestamps.

**Key bindings:**

| Key | Action |
|-----|--------|
| `s` | Start / stop daemon |
| `c` | Clear event log |
| `f` | Toggle follow mode (auto-scroll on/off) |
| `Escape` | Stop daemon and go back |

When a trigger fires, the daemon:

1. Logs the trigger event (type, prompt preview)
2. Executes the agent with the trigger's prompt
3. Logs the result (OK with duration, or FAIL with error)

The daemon is automatically stopped when leaving the screen.

### Help Screen

Static reference of all keyboard shortcuts, organized by screen. Accessible from any screen via `?`.

## Architecture

### Sync/Async Bridge

InitRunner's core is synchronous (CLI uses `run_sync`). Textual's event loop is async. The `ServiceBridge` class in `services.py` bridges this gap:

```python
class ServiceBridge:
    @staticmethod
    async def discover_roles(dirs: list[Path]) -> list[DiscoveredRole]:
        return await asyncio.to_thread(services.discover_roles_sync, dirs)

    @staticmethod
    async def run_agent(agent, role, prompt, **kwargs):
        return await asyncio.to_thread(services.execute_run_sync, agent, role, prompt, **kwargs)

    @staticmethod
    def run_agent_streamed(agent, role, prompt, *, on_token=None, **kwargs):
        """Sync streaming — call from a worker thread."""
        with agent.run_stream_sync(prompt, **kwargs) as stream:
            for chunk in stream.stream_text(delta=True):
                if on_token:
                    on_token(chunk)
        ...
```

Key design decisions:

- **Short-lived DB connections**: Each worker call creates its own database connection (SQLite connections aren't thread-safe across threads).
- **`asyncio.to_thread()`**: Wraps every sync operation so Textual's event loop never blocks.
- **`app.call_from_thread()`**: Used by streaming and daemon callbacks to safely update the UI from worker threads.

### File Structure

```
initrunner/tui/
├── __init__.py            # run_tui() entry point
├── app.py                 # InitRunnerApp (main Textual App)
├── app.tcss               # Textual CSS styles
├── services.py            # ServiceBridge — async wrappers around sync core
├── screens/
│   ├── __init__.py
│   ├── base.py            # BaseScreen, RoleScreen, DataTableScreen ABCs
│   ├── roles.py           # RolesScreen (home) + YamlViewerModal + TemplatePickerModal
│   ├── detail.py          # RoleDetailScreen + SectionPickerModal + FieldEditModal + TextEditModal
│   ├── run.py             # RunScreen — streaming chat
│   ├── audit.py           # AuditScreen + AuditDetailModal
│   ├── daemon.py          # DaemonScreen — monitor triggers
│   ├── memory.py          # MemoryScreen + ConfirmClearModal
│   ├── ingest.py          # IngestScreen — sources & ingestion
│   └── help.py            # HelpScreen — key reference
└── widgets/
    ├── __init__.py
    ├── chat_input.py       # ChatInput — multi-line input with Ctrl+Enter submit
    └── chat_view.py       # ChatView, ChatMessage, StreamingMessage
```

### Streaming Chat Flow

The streaming chat in `RunScreen` works as follows:

1. User types a message and presses `Ctrl+Enter`.
2. The message is added to the chat view as a user message.
3. A `StreamingMessage` widget is created in the chat view.
4. A worker thread calls `ServiceBridge.run_agent_streamed()`.
5. Inside the worker, `agent.run_stream_sync()` iterates token deltas.
6. Each token calls `on_token()`, which uses `app.call_from_thread()` to append the token to the `StreamingMessage` widget.
7. The `StreamingMessage` widget batches tokens (every 10 tokens or 50 ms) and reactively updates its Markdown content.
8. On completion, token counts are updated in the status bar.

If streaming fails (exception during `run_stream_sync()`), the screen falls back to `ServiceBridge.run_agent()` with a "Thinking..." indicator.

## Dependencies

The TUI uses the `textual` package (>= 7.5.0), installed via the `tui` optional extra (`pip install initrunner[tui]`).
