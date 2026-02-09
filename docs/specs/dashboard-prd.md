# InitRunner Dashboard — Product Requirements Document

## Overview

Web-based dashboard replacing the Textual TUI (~3000 LOC, 7 screens). The dashboard is an optional visual layer on top of the existing CLI. Built with **Next.js App Router + Tailwind + shadcn/ui** frontend and **FastAPI** backend.

**Port:** `8420` (default)
**Launch:** `initrunner ui` starts FastAPI + serves static Next.js export

---

## Architecture

```
Browser ──► FastAPI (uvicorn :8420)
              ├── /api/*        → JSON/WebSocket/SSE endpoints
              └── /*            → Next.js static export (HTML/JS/CSS)
```

- Backend reuses sync core functions directly (same as ServiceBridge pattern)
- Frontend communicates via REST, WebSocket (chat, daemon), and SSE (ingestion)
- In-memory session state for active chat sessions with timeout cleanup

---

## API Endpoints

### Roles

| Method | Path | Description | Request | Response |
|--------|------|-------------|---------|----------|
| GET | `/api/roles` | List discovered roles | `?dirs=path1,path2` | `RoleListResponse` |
| GET | `/api/roles/{role_id}` | Get role detail | — | `RoleDetailResponse` |
| POST | `/api/roles/validate` | Validate a role file | `{path: string}` | `ValidationResponse` |
| PUT | `/api/roles/{role_id}` | Update role YAML fields | `{field: string, value: any}` | `ValidationResponse` |

### Chat

| Method | Path | Description | Notes |
|--------|------|-------------|-------|
| WS | `/api/chat/{role_id}` | Bidirectional chat | Client sends `{prompt}`, server streams `{type: "token"|"done"|"error", data}` |

**WebSocket protocol:**
- Client → Server: `{"type": "message", "prompt": "...", "session_id": "..."}`
- Server → Client: `{"type": "token", "data": "chunk"}` (streaming)
- Server → Client: `{"type": "done", "data": {"output": "...", "tokens_in": N, "tokens_out": N, "duration_ms": N}}`
- Server → Client: `{"type": "error", "data": {"message": "..."}}`

### Audit

| Method | Path | Description | Request | Response |
|--------|------|-------------|---------|----------|
| GET | `/api/audit` | Query audit records | `?agent_name=&since=&until=&limit=100` | `AuditListResponse` |
| GET | `/api/audit/{record_id}` | Get audit record detail | — | `AuditRecord` |

### Ingestion

| Method | Path | Description | Notes |
|--------|------|-------------|-------|
| POST | `/api/ingest/{role_id}` | Run ingestion | SSE stream of progress events |
| GET | `/api/ingest/{role_id}/sources` | List source files | — |

**SSE protocol:**
- `event: progress` / `data: {"file": "name.pdf", "status": "new|updated|skipped|error", "current": N, "total": N}`
- `event: done` / `data: {"new": N, "updated": N, "skipped": N, "errored": N, "total_chunks": N}`
- `event: error` / `data: {"message": "..."}`

### Memory

| Method | Path | Description | Request | Response |
|--------|------|-------------|---------|----------|
| GET | `/api/memories/{role_id}` | List memories | `?category=&limit=100` | `MemoryListResponse` |
| DELETE | `/api/memories/{role_id}` | Clear memories | — | `{status: "ok"}` |
| GET | `/api/memories/{role_id}/export` | Export memories as JSON | — | `application/json` download |

### Daemon

| Method | Path | Description | Notes |
|--------|------|-------------|-------|
| WS | `/api/daemon/{role_id}` | Trigger event stream | Server pushes `{type: "event"|"started"|"stopped", data}` |
| POST | `/api/daemon/{role_id}/start` | Start triggers | — |
| POST | `/api/daemon/{role_id}/stop` | Stop triggers | — |

---

## Response Models

```python
class RoleSummary:
    id: str           # base64url of path
    path: str
    name: str
    description: str
    model: str         # "provider:name"
    features: list[str]  # ["tools", "triggers", "ingest", "memory"]
    valid: bool
    error: str | None

class RoleDetail(RoleSummary):
    system_prompt: str
    model_config: ModelConfig
    guardrails: Guardrails
    tools: list[ToolSummary]
    triggers: list[TriggerSummary]
    sinks: list[SinkSummary]
    ingest: IngestConfig | None
    memory: MemoryConfig | None
    security: SecuritySummary
    yaml_content: str

class AuditRecord:
    id: str
    agent_name: str
    run_id: str
    prompt: str
    output: str
    success: bool
    error: str | None
    tokens_in: int
    tokens_out: int
    duration_ms: int
    timestamp: str

class MemoryItem:
    id: str
    content: str
    category: str
    created_at: str
    metadata: dict
```

---

## Pages

### `/roles` — Role List (Home)

**Mapped from:** TUI `RolesScreen`

- DataTable: Status indicator (green/red dot), Name, Description, Model, Features (tag chips)
- Search/filter bar (client-side filtering)
- "New Role" button → template picker dialog (basic, rag, daemon, memory, ollama)
- Click row → navigates to `/roles/[id]`
- Auto-refresh on mount

### `/roles/[id]` — Role Detail

**Mapped from:** TUI `RoleDetailScreen`

- Header: name, model, description, tags
- Card grid layout:
  - **Model** card: provider, name, temperature, max_tokens, base_url
  - **Guardrails** card: max_tokens_per_run, timeout, max_tool_calls, max_requests
  - **Tools** card: list with type badges
  - **Triggers** card: list with type badges
  - **Ingest** card: sources, chunking config, store backend
  - **Memory** card: store_backend, max_sessions, max_memories
- Action buttons: Chat, Ingest, Daemon, Memory, Validate
- YAML viewer toggle (syntax-highlighted)
- Inline editing via form dialogs

### `/roles/[id]/chat` — Streaming Chat

**Mapped from:** TUI `RunScreen`

- Chat message bubbles (user/assistant)
- WebSocket streaming with token-by-token rendering
- TextArea input with Shift+Enter for newlines, Enter to send
- Session management: New Session / Resume Session buttons
- Header: role name, token counter, connection status indicator
- Copy response button on each message
- Auto-scroll to bottom on new messages

### `/audit` — Audit Log

**Mapped from:** TUI `AuditScreen`

- DataTable: timestamp, agent name, run_id, success/fail, duration, tokens
- Filters: agent name dropdown, date range picker
- Click row → slide-over detail panel
- Detail panel: full prompt, full output (markdown rendered), metadata
- Copy output button

### `/roles/[id]/ingest` — Ingestion

**Mapped from:** TUI `IngestScreen`

- Source file list with status indicators
- "Run Ingestion" button, "Force Re-ingest" button
- SSE-driven progress bar with per-file status updates
- Stats summary on completion (new, updated, skipped, errors)
- Error details expandable

### `/roles/[id]/memory` — Memory Browser

**Mapped from:** TUI `MemoryScreen`

- DataTable: ID, Content (preview), Category, Created timestamp
- Category filter dropdown
- Clear button with confirmation dialog
- Export button → JSON file download
- Search/filter bar

### `/roles/[id]/daemon` — Trigger Monitor

**Mapped from:** TUI `DaemonScreen`

- Start/Stop toggle button with status indicator
- Trigger cards: type, config summary, last fired timestamp, fire count
- Live event log (WebSocket): auto-scrolling log with timestamps
- Clear log button

---

## Navigation

- Sidebar: Roles (home), Audit
- Breadcrumb navigation within role pages
- Role sub-navigation: Detail | Chat | Ingest | Memory | Daemon

---

## Tech Stack

**Frontend:** Next.js 15 App Router, React 19, Tailwind CSS 4, shadcn/ui, TypeScript
**Backend:** FastAPI, uvicorn
**Build:** `next build` static export, served by FastAPI at `/`
**Dev mode:** `next dev` (port 3000) + `uvicorn` (port 8420) with proxy
