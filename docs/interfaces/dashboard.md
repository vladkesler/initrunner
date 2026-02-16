# Web Dashboard

The InitRunner web dashboard is an optional browser-based UI alongside the
terminal-based [TUI](tui.md). The `initrunner ui` command serves both the
**FastAPI** JSON API and **server-rendered HTML pages** (HTMX + Jinja2 +
DaisyUI) on a single port (default 8420) — no separate frontend server or
build step required. It provides role management, streaming chat, ingestion
monitoring, memory browsing, daemon control, and audit log inspection.

## Installation

Install the dashboard extra to pull in FastAPI and uvicorn:

```bash
pip install initrunner[dashboard]
# or with uv:
uv pip install initrunner[dashboard]
```

This adds `fastapi>=0.115.0`, `uvicorn[standard]>=0.34.0`, and `jinja2`.

## Quick Start

```bash
initrunner ui
```

This starts the FastAPI backend and serves the dashboard at
`http://127.0.0.1:8420`, then opens a browser window automatically. Both API
and UI are served on the same port — no separate frontend process needed.

| Flag | Default | Description |
|------|---------|-------------|
| `--role-dir PATH` | `.` (cwd) | Directory to scan for role YAML files |
| `--host TEXT` | `127.0.0.1` | Host to bind to |
| `--port INT` | `8420` | Port to listen on |
| `--no-browser` | off | Don't open the browser on startup |
| `--api-key TEXT` | *(auto)* | API key for dashboard auth (see [Authentication](../security/auth.md)) |
| `--no-auth` | off | Disable authentication (NOT recommended) |

Interactive API docs are available at `http://127.0.0.1:8420/api/docs`
(Swagger UI) and `http://127.0.0.1:8420/api/openapi.json` (OpenAPI spec).

## Architecture

```
Browser ──► FastAPI / uvicorn (:8420)
                │
                ├── /static/*          → bundled CSS/JS (HTMX, DaisyUI, Tailwind, app.js)
                ├── /roles, /audit ... → Jinja2 templates (server-rendered HTML)
                ├── /api/*             → JSON API endpoints
                │
                └── asyncio.to_thread() → services.py → core
```

Key design decisions:

- **Server-rendered HTML** — all pages are rendered server-side with Jinja2
  templates. HTMX adds dynamic updates (search filters, table fragments,
  slide-out panels) without full page reloads. No React, Vue, or build step.
- **DaisyUI + Tailwind** — DaisyUI provides pre-built components (cards,
  badges, modals, tables, navbar) on top of Tailwind utility classes. Loaded
  via CDN script and pre-built CSS — no build-time compilation.
- **HTMX** — declarative AJAX via HTML attributes (`hx-get`, `hx-swap`,
  `hx-trigger`). `hx-boost="true"` on `<body>` makes all navigation SPA-like
  without writing JavaScript.
- **Progressive enhancement** — pages work without JavaScript for basic
  navigation. HTMX adds filtering, fragments, and streaming on top.
- **Sync service layer** — all core operations live in `initrunner/services.py`
  as plain synchronous functions. FastAPI routes call them via
  `asyncio.to_thread()` to avoid blocking the event loop.
- **Dark theme** — the dashboard uses DaisyUI's `data-theme="dark"` globally.

## Project Structure

### Backend routes — `initrunner/api/routes/`

```
initrunner/api/routes/
├── pages.py          # HTML pages: roles list, role detail, audit log
├── auth_ui.py        # Login page + cookie-based auth flow
├── chat_ui.py        # Chat page + SSE streaming endpoint
├── memory_ui.py      # Memory page + HTMX fragments (filter, clear)
├── ingest_ui.py      # Ingestion page (delegates to SSE API)
├── daemon_ui.py      # Daemon control page (delegates to WebSocket API)
├── roles.py          # JSON API: role discovery, detail, validation
├── audit.py          # JSON API: audit log queries
├── ingest.py         # JSON API: SSE ingestion progress
├── memory.py         # JSON API: memory CRUD + JSON export
└── daemon.py         # JSON API: trigger start/stop + WebSocket events
```

### Templates — `initrunner/_templates/`

```
initrunner/_templates/
├── base.html         # Base layout: dark theme, DaisyUI, HTMX, app.js
├── _nav.html         # Navbar with active page highlighting + mobile menu
├── _macros.html      # Reusable macros: badge(), stat_card(), empty_state(), etc.
├── auth/
│   └── login.html    # Standalone login page (no base layout)
├── roles/
│   ├── list.html     # Roles table with search filter
│   ├── _table.html   # HTMX fragment: filtered <tbody> rows
│   └── detail.html   # Role detail with tabs (Overview, System Prompt, YAML)
├── audit/
│   ├── list.html     # Audit log with filters + slide-out detail panel
│   ├── _table.html   # HTMX fragment: filtered audit table body
│   └── _detail.html  # HTMX fragment: audit detail side panel
├── chat/
│   └── page.html     # Chat interface with SSE streaming
├── memory/
│   └── page.html     # Memory list with filter, clear modal, export link
├── ingest/
│   └── page.html     # Ingestion sources + progress bar
└── daemon/
    └── page.html     # Daemon control + WebSocket event log
```

### Static assets — `initrunner/_static/`

```
initrunner/_static/
├── htmx.min.js       # HTMX core library
├── ext/
│   ├── sse.js        # HTMX SSE extension
│   └── ws.js         # HTMX WebSocket extension
├── tailwindcss.js    # Tailwind CSS (CDN script)
├── daisyui.css       # DaisyUI component library (pre-built)
├── style.css         # Custom overrides (transitions, streaming indicator, etc.)
└── app.js            # Vanilla JS helpers (chat streaming, scroll, escaping)
```

### App factory — `initrunner/api/app.py`

`create_dashboard_app()` wires everything together:

1. Creates FastAPI app with Swagger docs at `/api/docs`
2. Configures Jinja2 templates from `_templates/`
3. Mounts static files from `_static/` at `/static`
4. Applies middleware stack (body size → rate limiting → auth)
5. Registers JSON API routers and HTML page routers
6. Adds `/api/health` endpoint

### Shared service layer — `initrunner/services.py`

All routes delegate to sync functions in `services.py`. The TUI's
`ServiceBridge` (`initrunner/tui/services.py`) wraps the same functions via
`asyncio.to_thread()` for Textual's async event loop.

| Function | Used by |
|----------|---------|
| `discover_roles_sync()` | Roles, Chat, Ingest, Memory, Daemon |
| `validate_role_sync()` | Roles |
| `build_agent_sync()` | Chat |
| `execute_run_stream_sync()` | Chat |
| `query_audit_sync()` | Audit |
| `run_ingest_sync()` | Ingest |
| `list_memories_sync()` | Memory |
| `clear_memories_sync()` | Memory |
| `export_memories_sync()` | Memory |
| `start_triggers_sync()` | Daemon |

## HTML Pages

| Route | Template | Description |
|-------|----------|-------------|
| `/` | — | Redirects to `/roles` |
| `/roles` | `roles/list.html` | Role listing with search filter |
| `/roles/table` | `roles/_table.html` | HTMX fragment: filtered table body |
| `/roles/{role_id}` | `roles/detail.html` | Role detail — config cards, system prompt, YAML tabs |
| `/roles/{role_id}/chat` | `chat/page.html` | Streaming chat interface (SSE) |
| `/roles/{role_id}/chat/stream` | — | SSE streaming endpoint (GET) |
| `/roles/{role_id}/memory` | `memory/page.html` | Memory browser with filter, clear, export |
| `/roles/{role_id}/memory/table` | — | HTMX fragment: filtered memory rows |
| `/roles/{role_id}/memory/clear` | — | HTMX action: DELETE clears memories |
| `/roles/{role_id}/ingest` | `ingest/page.html` | Ingestion sources + progress UI |
| `/roles/{role_id}/daemon` | `daemon/page.html` | Trigger monitor with event log |
| `/login` | `auth/login.html` | Login form |
| `/logout` | — | Clears cookie, redirects to `/login` |
| `/audit` | `audit/list.html` | Audit log with filters and detail slide-out |
| `/audit/table` | `audit/_table.html` | HTMX fragment: filtered audit rows |
| `/audit/{run_id}` | `audit/_detail.html` | HTMX fragment: audit detail panel |

## File Attachments

The chat interface supports uploading files to send as multimodal input alongside text prompts.

- **Upload endpoint:** `POST /roles/{role_id}/chat/upload` — accepts form-data file uploads, returns a JSON list of attachment IDs
- **Staging:** uploaded files are held in memory for **5 minutes** (TTL), then pruned
- **Size limit:** 20 MB per file
- **Flow:** attachment IDs from the upload response are passed to the SSE stream endpoint with the next prompt

Supported file types: images, audio, video, and documents. See [Multimodal Input](../core/multimodal.md) for the full list.

## HTMX Patterns

### Fragment-based updates

Search filters and table sorting swap only the `<tbody>`, not the whole page:

```html
<!-- Search input triggers filtered table swap -->
<input name="q" hx-get="/roles/table" hx-target="#roles-table-body"
       hx-trigger="keyup changed delay:300ms" />

<!-- Target tbody gets replaced -->
<tbody id="roles-table-body">
  {% include "roles/_table.html" %}
</tbody>
```

Fragment templates (prefixed with `_`) return bare HTML rows — no `<html>` or
`<head>` wrapper.

### SPA-like navigation

`hx-boost="true"` on `<body>` intercepts all `<a>` clicks and replaces only
the `<body>` content, preserving CSS/JS state and providing instant-feeling
navigation without full page reloads.

### Slide-out panels

The audit detail view uses a side panel: clicking a row swaps the panel content
via `hx-get="/audit/{run_id}"` targeting `#audit-detail`.

### Reusable macros

`_macros.html` provides DaisyUI component wrappers:

| Macro | Description |
|-------|-------------|
| `badge(text, variant)` | Colored badge (info, warning, success, etc.) |
| `stat_card(title, value, desc)` | Stat display card |
| `empty_state(message, icon)` | Empty state placeholder |
| `feature_badges(features)` | Feature badges for roles (tools, triggers, etc.) |
| `success_badge(is_success)` | Success/error badge |

## Streaming Strategy

The dashboard uses three streaming protocols depending on the feature:

### Chat — SSE (Server-Sent Events)

The chat page uses `EventSource` to stream tokens from the agent:

1. Client submits prompt via form → `app.js:initChatStream()` opens
   `EventSource` to `/roles/{role_id}/chat/stream?prompt=...`
2. Server creates/reuses a `ChatSession`, runs `execute_run_stream_sync()` in a
   thread executor, and pushes tokens to an `asyncio.Queue`
3. Tokens stream as `data: <chunk>\n\n` (default SSE "message" event)
4. On completion, sends `event: close\ndata: {"total_tokens": N, "duration_ms": M, "success": true}\n\n`
5. Client appends tokens to the assistant bubble, shows stats on close

Session management: in-memory `SessionStore` (max 1000 sessions, 1-hour TTL,
LRU eviction). Message history trimmed to 40 messages per session.

### Ingestion — SSE via `fetch()`

Ingestion requires a POST request, so `EventSource` (GET-only) can't be used.
The ingest page uses `fetch()` with `ReadableStream` and manually parses the
SSE format:

1. Client POSTs to `/api/ingest/{role_id}` with JavaScript
2. Server runs `run_ingest_sync()` in a thread, pushes progress to a queue
3. Events: `event: progress` (per-file status), `event: done` (summary),
   `event: error`
4. Client updates a `<progress>` bar and displays alerts on completion

### Daemon — WebSocket

The daemon page uses a raw WebSocket connection for bidirectional control:

1. Client connects to `WebSocket /api/daemon/{role_id}`
2. Server authenticates, starts triggers, streams events
3. Messages: `{"type": "started"}`, `{"type": "event", "data": {...}}`,
   `{"type": "stopped"}`, `{"type": "error", "data": {...}}`
4. Client appends events to `#event-log` with auto-scroll
5. Disconnecting the WebSocket stops the triggers

## Authentication

See [Authentication](../security/auth.md) for full details. Summary of the dashboard flow:

### Auth sources (priority order)

1. **Bearer token** — `Authorization: Bearer <token>` header
2. **Query param** — `?api_key=<token>` (sets HttpOnly cookie, then redirects)
3. **Cookie** — `initrunner_token` (HttpOnly, SameSite=strict)

### Login flow

1. Unauthenticated HTML request → redirect to `/login?next=/original/path`
2. User submits API key → `POST /login` validates with `hmac.compare_digest()`
3. On success: sets `initrunner_token` cookie, redirects to `next`
4. On failure: re-renders login page with error (401)

### Auto-cookie setup

When the browser opens on startup, the URL includes `?api_key=<key>`. The auth
middleware validates it, sets the cookie, and redirects — subsequent requests
use the cookie transparently.

### API key resolution

The `initrunner ui` command resolves the API key in this order:

1. Explicit `--api-key` flag
2. `INITRUNNER_DASHBOARD_API_KEY` env var
3. Persisted key from `~/.initrunner/dashboard.key`
4. Auto-generate + persist (localhost only, stored with `0600` permissions)

Non-localhost binding requires an explicit key or `--no-auth`.

### WebSocket auth

WebSocket endpoints authenticate via `?api_key=` query param or `Authorization`
header. The connection is closed with code 1008 (Policy Violation) before
acceptance if auth fails.

## Security Middleware

The middleware stack is applied in reverse registration order (body size →
rate limiting → auth):

| Middleware | Scope | Details |
|------------|-------|---------|
| Authentication | All paths except `/api/health`, `/login`, `/logout`, `/static/*` | Timing-safe `hmac.compare_digest()` comparison |
| Rate limiting | `/api/*` except `/api/health` | Token bucket: 120 req/min, 20 burst |
| Body size limit | All paths except `/api/health` | 2 MB max on POST/PUT/PATCH |

Middleware factories live in `initrunner/middleware.py` and are shared with the
OpenAI-compatible server (`initrunner serve`).

## JSON API Reference

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Returns `{"status": "ok"}` |

### Roles — `/api/roles`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/roles` | List discovered roles. Query: `dirs` (comma-separated directories). |
| `GET` | `/api/roles/{role_id}` | Full role detail (model, guardrails, tools, triggers, ingest, memory, YAML). |
| `POST` | `/api/roles/validate` | Validate a role file. Body: `{"path": "..."}`. Returns `{valid, error, role}`. |

### Audit — `/api/audit`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/audit` | Query audit records. Queries: `agent_name`, `since` (ISO), `until` (ISO), `limit` (1–1000, default 100). |

### Ingestion — `/api/ingest`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/ingest/{role_id}/sources` | List files that would be ingested. |
| `POST` | `/api/ingest/{role_id}` | Run ingestion with SSE progress. Query: `force` (default `false`). |

The `POST` endpoint returns a `text/event-stream` response with three event
types:

| Event | Data | Description |
|-------|------|-------------|
| `progress` | `{"file", "status", "current", "total"}` | Per-file progress update. |
| `done` | `{"new", "updated", "skipped", "errored", "total_chunks"}` | Ingestion complete. |
| `error` | `{"message": "..."}` | Pipeline failure. |

### Memory — `/api/memories`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/memories/{role_id}` | List memories. Queries: `category`, `limit` (1–1000, default 100). |
| `DELETE` | `/api/memories/{role_id}` | Clear all memories. Returns `{"status": "ok"}`. |
| `GET` | `/api/memories/{role_id}/export` | Download memories as a JSON file. |

### Daemon — `/api/daemon`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/daemon/{role_id}/start` | Start triggers. Returns `{"status": "started"}` or `{"status": "already_running"}`. |
| `POST` | `/api/daemon/{role_id}/stop` | Stop triggers. Returns `{"status": "stopped"}` or `{"status": "not_running"}`. |
| `WS` | `/api/daemon/{role_id}` | Live event stream from running triggers. |

**Server → client** messages on the daemon WebSocket:

| Type | Payload | Description |
|------|---------|-------------|
| `started` | — | Triggers are running. |
| `event` | `{"trigger", "prompt", "timestamp"}` | A trigger fired. |
| `error` | `{"message": "..."}` | Error (role not found, no triggers configured). |
| `stopped` | — | Triggers stopped (on disconnect). |

## Extending the Dashboard

### Adding a new HTML page

1. Create a template in `initrunner/_templates/<section>/page.html` extending
   `base.html`:

   ```html
   {% extends "base.html" %}
   {% block title %}My Page — InitRunner{% endblock %}
   {% block content %}
     <h2 class="text-2xl font-bold mb-4">My Page</h2>
     <!-- DaisyUI components here -->
   {% endblock %}
   ```

2. Create a route file in `initrunner/api/routes/my_page.py`:

   ```python
   from fastapi import APIRouter, Request
   from fastapi.responses import HTMLResponse

   router = APIRouter(tags=["my-page"])

   @router.get("/my-page", response_class=HTMLResponse)
   async def my_page(request: Request):
       return request.app.state.templates.TemplateResponse(
           request, "my_section/page.html", {"active_page": "my-page"}
       )
   ```

3. Register the router in `initrunner/api/app.py`:

   ```python
   from initrunner.api.routes.my_page import router as my_page_router
   app.include_router(my_page_router)
   ```

4. Add a nav link in `_nav.html` if needed.

### Adding an HTMX fragment

For dynamic partial updates (filtering, search, etc.):

1. Create a fragment template prefixed with `_` (e.g., `_table.html`) that
   returns only the HTML snippet to be swapped.
2. Add a route that returns the fragment.
3. Use `hx-get`, `hx-target`, and `hx-trigger` on the triggering element.

### Adding custom JavaScript

Add functions to `initrunner/_static/app.js`. The file is loaded on every page
via `base.html`. Keep it minimal — prefer HTMX attributes over custom JS.

### Using macros

Import macros in templates:

```html
{% from "_macros.html" import badge, stat_card, feature_badges %}
{{ badge("active", "success") }}
{{ stat_card("Total Runs", "42", "last 24h") }}
```

## Role IDs

Each role file is identified by a URL-safe ID: `base64url(sha256(abs_path)[:12])`.
The same absolute path always produces the same ID. The `RoleRegistry` caches
discovery results for 30 seconds to avoid redundant directory scans across
list → detail → chat navigation.
