# Dashboard -- Web UI for Agent Management

The dashboard provides a local web interface for managing agents, running prompts, browsing audit trails, inspecting system health, and viewing provider status. It ships as part of the `initrunner` package and launches with a single command.

## Quick Start

```bash
pip install "initrunner[dashboard]"   # or: uv add "initrunner[dashboard]"
initrunner dashboard                  # opens http://localhost:8100
```

The browser opens automatically. Use `--no-open` to skip.

## CLI Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--port` | int | `8100` | Port to listen on |
| `--no-open` | flag | off | Don't open the browser automatically |
| `--expose` | flag | off | Bind to `0.0.0.0` instead of `127.0.0.1` (see [Security](#security)) |
| `--roles-dir` | path | -- | Extra directories to scan for role YAML files (repeatable) |

```bash
# Custom port, scan extra directory
initrunner dashboard --port 9000 --roles-dir ~/agents

# Don't open browser
initrunner dashboard --no-open
```

## Pages

### Launchpad (`/`)

Action-oriented home page. When agents exist, shows:

- **Stats strip**: total runs, success rate, total tokens, average duration
- **Quick actions**: "New Agent" and "Run Doctor" buttons
- **Failing agents**: red-bordered cards for agents with load errors
- **Top agents**: bar chart of the 5 most-used agents (by run count)
- **Recent activity**: compact timeline of last 10 runs

When no agents exist, shows a welcome screen with onboarding CTAs.

When compose files exist, a **Compositions** card appears showing the first 3 compose projects with links to `/compose`.

### Agents (`/agents`)

Card grid of all discovered roles. Each card shows the agent name, model/provider, enabled features, and description. Click a card to open the detail view.

### New Agent (`/agents/new`)

Create a new agent through four modes, presented in a 2x2 card grid:

| Mode | Description |
|------|-------------|
| **Describe** | Type a natural language description and an LLM generates the role YAML |
| **Template** | Pick from 8 preset templates (basic, rag, daemon, memory, ollama, api, telegram, discord) |
| **Blank** | Start from a minimal YAML skeleton |
| **InitHub** | Search and browse packages on hub.initrunner.ai, select one to load its YAML |

All modes include a provider/model selector so the generated (or loaded) YAML uses the user's preferred model. For InitHub, the bundle's original model config is replaced with the user's selection.

After choosing a mode and provider/model, the page generates a role YAML and opens an editor with live validation. Edit the YAML, pick a save location from the configured role directories, and save. The new agent appears immediately in the agents list.

InitHub packages may contain sidecar files (knowledge bases, etc.) that are not loaded into the editor. Use `initrunner install owner/name` from the CLI for full package installation with all assets.

### Agent Detail (`/agents/{id}`)

Split-panel layout with configuration on the left and the run panel on the right.

| Panel | Contents |
|-------|----------|
| **Config** (340px sidebar) | Model details, tools with summaries, triggers, guardrails, memory, ingestion, skills, sinks, reasoning, autonomy, metadata, and a collapsible YAML viewer. Sections are collapsible and only render when the agent has data for them. |
| **Run** (primary, flex-1) | Prompt input with streaming output. Token breakdown (in/out), tool call names, and duration shown after completion. |

On narrow screens (< 1024px) the config panel collapses into a disclosure above the run panel.

Streaming output uses Server-Sent Events. Tokens appear in real time as the model generates them.

### Compose (`/compose`)

Card grid of all discovered compose YAML files. Each card shows the composition name, description, service count, and service name pills. Click a card to open the detail view.

### New Compose (`/compose/new`)

Create a new multi-agent composition through a 3-step flow: **Configure -> Editor -> Success**.

**Configure** -- pick a pattern and wire agents into slots:

| Pattern | Description | Topology |
|---------|-------------|----------|
| **Pipeline** | Linear A -> B -> C chain | Adjustable service count (min 2) |
| **Fan-out** | One dispatcher fans to multiple workers | Adjustable service count (min 3) |
| **Route** | Intake routes to specialists via LLM intent sensing | Fixed 4 services (intake, researcher, responder, escalator) |

Each slot can be filled with an existing agent from the dashboard's discovered roles, or left as a placeholder (a generic role is generated). Provider/model selection and shared memory toggle are available for placeholder roles.

**Editor** -- review and edit the generated `compose.yaml` with live schema validation. Placeholder role YAMLs are shown in a collapsible section. Pick a save directory and project name, then save.

**Success** -- shows the saved path and CLI commands to validate and run the composition.

### Compose Detail (`/compose/{id}`)

Split-panel layout with topology on the left and delegation events on the right.

| Panel | Contents |
|-------|----------|
| **Topology** (340px sidebar) | Service cards showing name, role path (linked to agent detail when matched), sink summary, depends_on, restart policy. Shared memory/documents badges. Collapsible YAML viewer. |
| **Events** (flex-1) | Table of delegation routing events filtered by `compose_name`. Columns: status (color-coded dot), source, target, time, run ID. Filter controls for source, target, and status. |

Events are filtered by `compose_name` (stored in the `delegate_events` audit table), so two compositions with overlapping service names show the correct events for each.

### Audit Log (`/audit`)

Filterable table of all agent runs with analytics.

- **Stats strip**: aggregate totals (runs, success rate, tokens, avg duration) for the current filter
- **Filters**: agent name, trigger type, date range (since/until), all/failures toggle
- **Detail drawer**: click any row to see full prompt, full output, all tool call names, trigger type, run ID, and error details
- **Export**: download filtered results as JSON or CSV

### System (`/system`)

Three sections:

| Section | Contents |
|---------|----------|
| **Providers** | Table of detected providers with their default models |
| **Health Check** | "Run Doctor" button that checks API key validity, SDK availability, Ollama connectivity, and Docker status. Results shown as a checklist with green/amber/red indicators. |
| **Tool Registry** | List of all registered tool types with descriptions. Useful when deciding what tools to add to an agent. |

### Command Palette

Press `Cmd+K` (or `Ctrl+K`) anywhere to open the command palette. Provides:

- Fuzzy search across all agents by name, tags, and description
- Quick navigation to any page
- Quick actions (e.g. "New Agent")
- Keyboard navigation with arrow keys and Enter

## Architecture

The dashboard is a FastAPI backend serving a SvelteKit frontend.

```
initrunner dashboard
  |
  +--> FastAPI (localhost:8100)
  |      /api/health           GET   health check
  |      /api/agents           GET   list discovered roles
  |      /api/agents/{id}      GET   single role summary
  |      /api/agents/{id}/detail GET full role config (model, tools, triggers, guardrails, etc.)
  |      /api/agents/{id}/yaml GET   raw YAML file
  |      /api/builder/templates GET   templates, providers, options
  |      /api/builder/seed     POST  generate YAML from template/description/blank
  |      /api/builder/validate POST  validate YAML text
  |      /api/builder/save     POST  save YAML to disk
  |      /api/builder/hub-search GET search InitHub packages
  |      /api/builder/hub-featured GET popular InitHub packages (5-min cache)
  |      /api/builder/hub-seed POST  load YAML from hub bundle
  |      /api/compose          GET   list discovered compose files
  |      /api/compose/{id}     GET   compose detail with service graph
  |      /api/compose/{id}/yaml GET  raw compose YAML
  |      /api/compose/{id}/events GET delegation events
  |      /api/compose-builder/options GET patterns, agents, providers
  |      /api/compose-builder/seed POST generate compose YAML
  |      /api/compose-builder/validate POST schema-only validation
  |      /api/compose-builder/save POST write compose + roles to disk
  |      /api/runs             POST  execute single run
  |      /api/runs/stream      POST  streaming run (SSE)
  |      /api/audit            GET   query audit records
  |      /api/audit/stats      GET   aggregate audit statistics
  |      /api/providers        GET   detected providers
  |      /api/system/doctor    GET   provider health checks
  |      /api/system/tools     GET   registered tool types
  |      /                     static SvelteKit build
  |
  +--> Browser (opens automatically)
```

### Agent Identity

Agents are identified by a stable opaque ID derived from their file path (`sha256[:12]`). This avoids ambiguity when multiple role directories contain agents with the same `metadata.name`.

### Services Layer

The backend imports exclusively from `initrunner.services.*` and `initrunner.config`. It never imports from `initrunner.agent.*` or `initrunner.audit.*` directly. This is the same boundary the CLI uses.

### Streaming

Agent runs use SSE (Server-Sent Events). The backend runs `execute_run_stream_sync` in a thread pool and forwards tokens to the browser via an `asyncio.Queue` bridge. Events:

| Event type | Payload |
|------------|---------|
| `token` | String chunk of model output |
| `result` | Full `RunResponse` with token counts, tool calls, duration |
| `error` | Error message string |

## Desktop App

Open the dashboard in a native window instead of the browser. Uses the OS WebView (WebKitGTK on Linux, WebView2 on Windows, WKWebView on macOS).

### Install

```bash
pip install "initrunner[desktop]"   # or: uv add "initrunner[desktop]"
```

### Usage

```bash
initrunner desktop                  # opens native window on port 8100
initrunner desktop --port 9000      # custom port
```

If a dashboard is already running on the port (e.g. from `initrunner dashboard --no-open`), the desktop window connects to it. Otherwise, an embedded backend starts and shuts down when the window closes.

### System Requirements

- **macOS**: No extra packages. WKWebView ships with the OS.
- **Windows**: No extra packages. WebView2 ships with Edge (Windows 10+).
- **Linux**: Requires system GTK/WebKit packages. Most GNOME desktops already have them. If missing, the command prints the exact install command for your distro (apt/dnf/pacman). For example on Ubuntu/Debian:
  ```bash
  sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1
  ```
  The desktop command automatically bridges system-installed PyGObject into isolated venvs (uv, virtualenv). This works when the venv Python matches the distro Python ABI. If you use a uv-managed Python that differs from the distro version (e.g. distro ships 3.12 but venv uses 3.13), install PyGObject into the venv manually: `uv pip install PyGObject pycairo` (requires `libgirepository-2.0-dev`).

## Development

For frontend hot-reload during development, run the backend and frontend separately:

```bash
# Terminal 1: backend API
initrunner dashboard --no-open

# Terminal 2: frontend dev server with hot reload
cd dashboard/
pnpm install
pnpm dev          # http://localhost:5173, proxies /api/* to :8100
```

### Frontend Stack

- SvelteKit 2 with adapter-static (SPA mode)
- shadcn-svelte components (Bits UI primitives)
- Tailwind CSS v4 with custom design tokens
- Svelte 5 runes for state management

### Building

```bash
cd dashboard/
pnpm build        # outputs to ../initrunner/dashboard/_static/
```

The built static files are served by the FastAPI backend in production. During development they are served by Vite's dev server.

### Design System

See [Design System](design-system.md) for the full reference (colors, typography, radius rules, component patterns, animation). Key points:

- **Theme**: "Electric Charcoal" -- dark-only, warm charcoal surfaces, electric lime accent
- **Typography**: Space Grotesk (display/body), IBM Plex Mono (data/code)
- **Radius rule**: Sharp (0px) for containers, pill for interactive elements
- **Tokens**: All defined in `dashboard/src/app.css`

## Security

By default, the dashboard binds to `127.0.0.1` (localhost only). It is not accessible from other machines.

The `--expose` flag binds to `0.0.0.0`, making it accessible on all network interfaces. **No authentication is provided.** Only use `--expose` on trusted networks. Authentication support is planned for a future release.

The dashboard can execute any discovered agent with any prompt. It has the same access as `initrunner run` on the command line.

## API Reference

All endpoints return JSON. Errors return `{"detail": "message"}`.

### `GET /api/agents`

Returns a list of all discovered agents.

```json
[
  {
    "id": "a1b2c3d4e5f6",
    "name": "code-reviewer",
    "description": "Reviews code for bugs",
    "tags": ["code"],
    "provider": "openai",
    "model": "gpt-4o",
    "features": ["tools", "memory"],
    "path": "/home/user/agents/reviewer.yaml",
    "error": null
  }
]
```

### `GET /api/agents/{id}`

Returns a single agent by its opaque ID.

### `GET /api/builder/templates`

Returns available templates, provider/model options, auto-detected defaults, and configured role directories.

```json
{
  "templates": [{"name": "basic", "description": "Simple assistant"}, ...],
  "providers": [{"provider": "openai", "models": [{"name": "gpt-5-mini", "description": "Fast, affordable"}, ...]}, ...],
  "detected_provider": "anthropic",
  "detected_model": "claude-sonnet-4-5-20250929",
  "role_dirs": ["/home/user/agents"]
}
```

### `POST /api/builder/seed`

Generate role YAML from a template, natural language description, or blank skeleton.

```json
{"mode": "template", "template": "rag", "provider": "openai", "model": "gpt-4o"}
```

Response includes `yaml_text`, `explanation`, `issues[]`, and `ready` (true when no validation errors).

### `POST /api/builder/validate`

Validate YAML text against the role schema.

```json
{"yaml_text": "apiVersion: initrunner/v1\n..."}
```

### `GET /api/builder/hub-search`

Search InitHub for agent packages. Query parameters:

| Param | Type | Description |
|-------|------|-------------|
| `q` | string | Search query (min 2 characters) |
| `tag` | string | Filter by tag (repeatable) |

```json
{
  "items": [
    {
      "owner": "alice",
      "name": "code-reviewer",
      "description": "Reviews pull requests for bugs",
      "tags": ["code", "review"],
      "downloads": 42,
      "latest_version": "1.0.0"
    }
  ]
}
```

Returns 502 if InitHub is unreachable.

### `GET /api/builder/hub-featured`

Fetch popular packages from InitHub. No parameters. Returns the same `HubSearchResponse` shape as hub-search. Results are cached server-side with a 5-minute TTL. On error, returns stale cache or empty list (never 502).

### `POST /api/builder/hub-seed`

Load a role YAML from an InitHub package and rewrite the model block with the user's provider/model.

```json
{
  "ref": "alice/code-reviewer@1.0.0",
  "provider": "anthropic",
  "model": "claude-sonnet-4-20250514"
}
```

Response is the same `SeedResponse` as `/api/builder/seed`. The explanation notes any sidecar files not loaded.

### `POST /api/builder/save`

Save YAML to disk within a configured role directory.

```json
{"yaml_text": "...", "directory": "/home/user/agents", "filename": "reviewer.yaml", "force": false}
```

Returns `path`, `valid`, `issues[]`, `next_steps[]`, and `agent_id`. Returns 409 if the file exists and `force` is false. Returns 400 if the directory is outside configured role dirs.

### `GET /api/agents/{id}/yaml`

Returns the raw YAML file content.

```json
{"yaml": "apiVersion: initrunner/v1\n...", "path": "/home/user/agents/reviewer.yaml"}
```

### `POST /api/runs`

Execute an agent run. Request body:

```json
{"agent_id": "a1b2c3d4e5f6", "prompt": "Review the latest commit"}
```

Response:

```json
{
  "run_id": "run-abc123",
  "output": "The code looks good...",
  "tokens_in": 150,
  "tokens_out": 200,
  "total_tokens": 350,
  "tool_calls": 2,
  "tool_call_names": ["git_log", "read_file"],
  "duration_ms": 3400,
  "success": true,
  "error": null
}
```

### `POST /api/runs/stream`

Same request body as `/api/runs`. Returns an SSE stream (`text/event-stream`).

### `GET /api/audit`

Query audit records. Query parameters:

| Param | Type | Description |
|-------|------|-------------|
| `agent_name` | string | Filter by agent name |
| `run_id` | string | Filter by run ID |
| `trigger_type` | string | Filter by trigger type |
| `since` | string | ISO 8601 start time |
| `until` | string | ISO 8601 end time |
| `limit` | int | Max records (default 50, max 500) |

### `GET /api/audit/stats`

Aggregate statistics over audit records. Query parameters: `agent_name`, `since`, `until`.

```json
{
  "total_runs": 1234,
  "success_rate": 97.5,
  "total_tokens": 5678900,
  "avg_duration_ms": 2100,
  "top_agents": [
    {"name": "code-reviewer", "count": 350, "avg_duration_ms": 1800}
  ]
}
```

### `GET /api/providers`

Returns detected providers.

```json
[{"provider": "openai", "model": "gpt-4o"}]
```

### `GET /api/system/doctor`

Runs provider health checks. Returns status for each provider, Ollama, and Docker.

```json
{
  "checks": [
    {"name": "openai", "status": "ok", "message": "Ready"},
    {"name": "ollama", "status": "fail", "message": "Not running"},
    {"name": "docker", "status": "ok", "message": "Available"}
  ]
}
```

### `GET /api/system/tools`

Returns all registered tool types.

```json
[
  {"name": "filesystem", "description": "Read and write files within a root directory."},
  {"name": "http", "description": "Make HTTP requests to external APIs."}
]
```

### `GET /api/compose`

Returns all discovered compose definitions.

```json
[
  {
    "id": "f1e2d3c4b5a6",
    "name": "support-desk",
    "description": "Intake routes to specialists via intent sensing.",
    "service_count": 4,
    "service_names": ["intake", "researcher", "responder", "escalator"],
    "path": "/home/user/support-desk/compose.yaml",
    "error": null
  }
]
```

### `GET /api/compose/{id}`

Returns full compose detail with service topology and agent cross-references.

### `GET /api/compose/{id}/yaml`

Returns raw compose YAML content.

### `GET /api/compose/{id}/events`

Query delegation routing events for this compose. Filters by `compose_name` in the audit DB.

| Param | Type | Description |
|-------|------|-------------|
| `source` | string | Filter by source service |
| `target` | string | Filter by target service |
| `status` | string | Filter by status (delivered/dropped/filtered/error) |
| `since` | string | ISO 8601 start time |
| `until` | string | ISO 8601 end time |
| `limit` | int | Max events (default 200) |

### `GET /api/compose-builder/options`

Returns available patterns, discovered agents (for slot assignment), provider/model options, and save directories.

### `POST /api/compose-builder/seed`

Generate compose YAML from a pattern and slot assignments.

```json
{
  "pattern": "pipeline",
  "name": "my-pipeline",
  "services": [
    {"slot": "step-1", "agent_id": "a1b2c3d4e5f6"},
    {"slot": "step-2", "agent_id": null}
  ],
  "service_count": 2,
  "shared_memory": false,
  "provider": "openai"
}
```

Response includes `compose_yaml`, `role_yamls` (placeholder roles only), `issues[]`, and `ready`.

### `POST /api/compose-builder/validate`

Schema-only validation of compose YAML. Does not check that role files exist on disk.

### `POST /api/compose-builder/save`

Write compose YAML and placeholder roles to disk. Performs full validation (compose schema + role file existence).

Returns `path`, `valid`, `issues[]`, `next_steps[]`, and `compose_id`. Returns 409 if the project directory already exists.

### `GET /api/health`

```json
{"status": "ok", "version": "1.39.2"}
```
