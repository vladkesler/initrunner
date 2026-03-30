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
| `--api-key` | string | -- | Require this API key for all requests (see [Security](#security)) |
| `--roles-dir` | path | -- | Extra directories to scan for role YAML files (repeatable) |

```bash
# Custom port, scan extra directory
initrunner dashboard --port 9000 --roles-dir ~/agents

# Don't open browser
initrunner dashboard --no-open

# Expose with authentication
initrunner dashboard --expose --api-key my-secret-key
```

## Pages

### Launchpad (`/`)

Action-oriented home page with two states.

**Zero state** (no agents, composes, or teams):

Onboarding surface designed to reduce time-to-first-agent:

- **Provider status banner**: shows which AI providers are configured (env var presence + Ollama). When no providers are configured, shows an inline key entry form (provider dropdown + API key input + "Save & Verify" button) so users can configure a provider without leaving the dashboard. Links to the provider setup guide and the System page for full provider management.
- **Primary CTAs**: "Create an Agent" and "Read the Quickstart" (links to `https://www.initrunner.ai/docs/quickstart`).
- **Starter template cards**: up to 6 curated single-file Agent starters from `_starters/` (helpdesk, rag-agent, memory-assistant, telegram, discord, email). Each card shows name, description, and derived feature badges (RAG, Memory, Triggers, Web, etc.). Clicking a card navigates to `/agents/new?starter={slug}`, which auto-loads the starter YAML into the editor when a provider is detected.
- **Capability chips**: pill links to RAG, Memory, Triggers, Compose, and Teams docs/creation flows.
- **Full documentation link**: external link to the quickstart guide.

**Full state** (agents, composes, or teams exist):

- **Stats strip**: total runs, success rate, total tokens, average duration
- **Quick actions**: "New Agent", "New Compose", "New Team", and "Run Doctor" buttons
- **Failing agents**: red-bordered cards for agents with load errors
- **Top agents**: bar chart of the 5 most-used agents (by run count)
- **Recent activity**: compact timeline of last 10 runs
- **Orchestration**: section header grouping the Compositions and Teams cards (appears when either exists)

### Agents (`/agents`)

Two views, toggled in the header bar:

- **Flow view** (default, desktop): Interactive SvelteFlow canvas. Agents render as draggable nodes organized into category sections (Reactive, Intelligence, Skilled, Cognitive, Connected, Equipped, Other). Each node shows the agent name, model, description, capability glyph, and a hero icon matching its primary feature. Category labels separate the sections. Canvas supports pan, zoom, minimap, and an auto-arrange button. Node positions persist to localStorage. On mobile (< 1024px), falls back to list view automatically.
- **List view**: Sortable table with status dot, name, description, model, and capability glyph columns. Each row has a trash icon (visible on hover) to delete the agent with a name-typing confirmation dialog.

A toolbar above the canvas (or list) provides search, capability filter buttons (All, Equipped, Reactive, Intelligence, Connected, Skilled, Cognitive, Errored), a result count, and the view toggle. The **Cognitive** filter shows agents with non-default reasoning patterns (todo_driven, plan_execute, reflexion) or autonomy configuration. In flow view, filtering dims non-matching nodes instead of hiding them. Click any node/row to open the detail view.

### New Agent (`/agents/new`)

Create a new agent through four modes, presented in a 2x2 card grid:

| Mode | Description |
|------|-------------|
| **Describe** | Type a natural language description and an LLM generates the role YAML |
| **Template** | Pick from 8 preset templates (basic, rag, daemon, memory, ollama, api, telegram, discord) |
| **Blank** | Start from a minimal YAML skeleton |
| **InitHub** | Search and browse packages on hub.initrunner.ai, select one to load its YAML |

All modes include a provider/model selector so the generated (or loaded) YAML uses the user's preferred model. For InitHub, the bundle's original model config is replaced with the user's selection.

**Provider warning**: when no providers are configured (no API keys set and Ollama not running), an inline provider setup form appears at the top of the configure step. Users can select a provider, enter an API key, and save it directly. For OpenAI and Anthropic, the key is validated against the provider API before saving. Once saved, the form disappears and the configure step unlocks.

**Starter URL parameter**: navigating to `/agents/new?starter={slug}` (e.g. from a launchpad starter card) loads a starter template. When a provider is detected, it auto-loads the YAML into the editor with the detected provider/model rewritten in. When no provider is detected, it stays on the configure step with the starter intent preserved, so the user can pick a provider first.

After choosing a mode and provider/model, the page generates a role YAML and opens an editor with live validation. A **Cognition** toggle (lime-tinted, always visible) in the toolbar opens a structured side panel for configuring reasoning patterns, autonomy, think, todo, and tool search without hand-editing YAML. The panel includes a link to the [reasoning docs](https://www.initrunner.ai/docs/reasoning). It reads from and writes to the YAML text using `js-yaml` (client-side parse/dump). Edit the YAML, pick a save location from the configured role directories, and save. The new agent appears immediately in the agents list.

**Tool Search** (in Cognition panel): when an agent has 10 or more tools configured, a **Tool Search** section appears in the Cognition panel with an info banner showing the expected context savings. Enabling it writes `spec.tool_search` to the YAML with auto-pinned common functions (`current_time`, `parse_date`, etc.). A checklist shows all resolved function names (not tool type names) with their origin type, letting users pick which tools stay always-visible vs discoverable at runtime via `search_tools`. A collapsible **Tuning** section exposes `max_results` (1-20). The function name mapping is loaded from the builder options endpoint (`tool_func_map`) and resolved client-side with zero round-trips. See [Tool Search](../core/tool-search.md) for details on the underlying mechanism.

Validation issues use three severity levels: **error** (blocks save), **warning** (advisory), and **info** (recommendations such as "Think tool with critique recommended for reflexion pattern").

InitHub packages may contain sidecar files (knowledge bases, etc.) that are not loaded into the editor. Use `initrunner install owner/name` from the CLI for full package installation with all assets.

### Agent Detail (`/agents/{id}`)

Header with agent name, model badge, and status indicator. A **Delete** button opens a confirmation dialog requiring the agent name. Stats bar shows runs, success rate, tokens, and avg duration.

**Provider warning**: when the agent's provider SDK is not installed or its API key is missing, a warning banner appears below the header with an actionable message (e.g., install command or env var to set). The Run tab is disabled until the issue is resolved. Build errors during streaming runs are also caught and displayed inline in the conversation thread instead of leaving the UI stuck.

**Trigger panel**: for agents with triggers configured, an operational status panel appears between the stats bar and tabs. Each trigger shows its type, config summary, fire count, success rate (color-coded), average duration, last fired time (relative), and next check time (for cron and heartbeat triggers). Last errors are shown in a collapsed section. Stats are derived from the audit trail via `GET /api/agents/{id}/trigger-stats`. The static trigger listing in the Config tab is preserved as a fallback. Fire counts are aggregated per trigger type (v1 limitation: multiple triggers of the same type share aggregated stats).

Six tabs below the trigger panel:

| Tab | Contents |
|-----|----------|
| **Run** (default) | Prompt input with SSE streaming output. Deterministic Rings avatars (seeded from agent name) identify each turn. Token breakdown, tool call names, and duration after completion. Multi-turn message history. |
| **History** | Audit log filtered to this agent. |
| **Memory** | Memory items and conversation sessions (shown when agent has `memory` config). Filter by type, consolidate memories. |
| **Ingest** | Document management for RAG agents (shown when agent has `ingest` config). See below. |
| **Config** | Read-only nested sections: model, tools, triggers, guardrails, cognition, memory, ingestion, skills, sinks, metadata. |
| **Editor** | YAML editor with live validation and save. |

#### Ingest Tab

Available for agents with `spec.ingest` configured. Provides full document lifecycle management without leaving the UI.

**Summary strip** -- three stat cards: total documents, total chunks, last ingested timestamp.

**Actions:**
- **Re-ingest** -- runs the full ingestion pipeline (config sources + managed sources). Progress streamed via SSE with per-file status badges (new/updated/skipped/error).
- **Force Re-ingest** -- same but with `force=true` (wipes store on embedding model change).
- **Upload Files** -- multipart file upload. Files are saved to `~/.initrunner/uploads/{agent_name}/` and ingested as managed sources.
- **Add URL** -- inline URL input. The URL is fetched, extracted, chunked, embedded, and registered as a managed source.
- **Delete** -- removes a managed source from the store and manifest. Only available for managed sources (dashboard-added). Config-sourced documents (from `ingest.sources` globs) show a "from config" badge and cannot be deleted individually.

**Managed sources** persist in the store's `_meta` table as a JSON manifest. They survive re-ingestion (not purged by glob resolution) and survive store wipes (manifest is read before wipe and restored after). See [Managed Sources](../core/ingestion.md#managed-sources-dashboard) in the ingestion docs.

### Compose (`/compose`)

Card grid of all discovered compose YAML files. Each card shows the composition name, description, service count, and service name pills. Each card has a trash icon (visible on hover) to delete the composition with a name-typing confirmation dialog. A [Docs](https://www.initrunner.ai/docs/compose) link in the header opens the compose documentation. Click a card to open the detail view.

### New Compose (`/compose/new`)

Create a new multi-agent composition through a 3-step flow: **Configure -> Editor -> Success**.

**Configure** -- pick a pattern and wire agents into slots:

| Pattern | Description | Topology |
|---------|-------------|----------|
| **Pipeline** | Linear A -> B -> C pipeline | Adjustable service count (min 2) |
| **Fan-out** | Dispatch to all workers simultaneously | Adjustable service count (min 3) |
| **Route** | Route to the best specialist automatically | Adjustable service count (min 3), semantic slot names |

The **Route** pattern uses semantic specialist names from a curated pool (`researcher`, `responder`, `escalator`, `analyst`, `summarizer`, `validator`, `coordinator`, `reviewer`) instead of generic numbered slots. At 3 services: intake + researcher + responder. Additional specialists appear as the count increases. A lime `sense` badge on the pattern card distinguishes it from the other patterns.

Each slot uses an **Agent Picker** -- a searchable inline dropdown that shows all discovered agents with their name, description, model badge, and feature pills. Search filters across name, description, tags, features, and path. Slots default to "Generate placeholder" (a generic role YAML is created at seed time). When an agent is selected, the trigger shows the agent name and model; clearing it reverts to the placeholder label. Provider/model selection and shared memory toggle are available for placeholder roles.

**Routing strategy** (Route pattern only): three inline pill buttons appear below the slot picker:

| Strategy | Label | Behavior |
|----------|-------|----------|
| `all` | Broadcast | Fan-out to every target. No filtering. |
| `keyword` | Keyword | [Intent Sensing](../core/intent_sensing.md) keyword scoring. Near-zero cost. |
| `sense` | Sense (Recommended) | Keyword scoring first, LLM tiebreaker on ties. Highest accuracy. |

The Route pattern defaults to **Sense** (with a lime "Recommended" badge). When Keyword or Sense is selected, a collapsible detail section reveals scoring weights (tags 3x, name 2x, description 1.5x) and per-slot quality indicators showing whether each target agent has tags and descriptions for effective routing. The strategy is passed to the seed endpoint and written into the generated `compose.yaml` as the intake service's `sink.strategy`.

**Editor** -- review and edit the generated `compose.yaml` with live schema validation. Placeholder role YAMLs are shown in a collapsible section. Pick a save directory and project name, then save.

**Success** -- shows the saved path and CLI commands to validate and run the composition.

### Compose Detail (`/compose/{id}`)

Tabbed detail page with a stats bar and five tabs. A **Delete** button in the header opens a confirmation dialog requiring the composition name to be typed. Deleting removes only the `compose.yaml` file (referenced role files are not affected) and redirects to the compose list.

**Stats bar** (4 cards): total events, delivery rate %, service count, issue count (non-delivered events). Delivery rate is color-coded green/yellow/red.

| Tab | Contents |
|-----|----------|
| **Run** (default) | Chat interface for running prompts through the pipeline. Deterministic Rings avatars seeded from the active service name identify each turn (avatar swaps during streaming as services execute). The entry service (first with no incoming delegation edges) receives the prompt; delegation flows through the chain via real orchestrator wiring (shared memory, routing strategies, audit events). Service-level progress shown during execution ("Running step-2..."). Output mode adapts to topology: single terminal service shows output directly, fan-out shows per-service trace expanded. Collapsible pipeline trace under each response shows per-service name, duration, tokens, and output preview. Message history scoped to entry service for multi-turn conversations. |
| **Graph** | SvelteFlow canvas showing the service DAG. Services are custom nodes (240px) with capability icons (trigger, health check, circuit breaker, sink). Layout uses topological tiering by `depends_on` (falls back to `sink.targets` when no dependencies exist). Delegation edges are solid lime (animated), dependency edges are dashed muted (hidden when a delegation edge covers the same pair). Minimap, auto-arrange, and localStorage position persistence. Click a node to inspect, double-click to navigate to the linked agent. |
| **Events** | Delegation event table filtered by `compose_name`. Columns: status (color-coded dot with glow), source, target, routing (method + score from sense/keyword routing, lime for keyword matches, cyan for LLM tiebreaks), time, run ID. Six status filters: delivered, dropped, filtered, error, policy_denied, circuit_open. |
| **Config** | Collapsible per-service sections showing sink (strategy, targets, queue size, timeout, circuit breaker), trigger, restart policy, health check, depends_on, and environment count. When sink strategy is `sense` or `keyword`, an inline explanation appears below the strategy field. Shared memory/documents badges. |
| **Editor** | YAML editor with debounced schema validation, in-place save, reset, and copy. Warns when `metadata.name` changes (splits event history). |

Events are filtered by `compose_name` (stored in the `delegate_events` audit table), so two compositions with overlapping service names show the correct events for each. Tab selection persists to localStorage.

### Teams (`/teams`)

Card grid of all discovered team YAML files. Each card shows the team name, description, strategy badge (sequential/parallel), model overrides badge, persona name pills, and feature badges for shared memory and shared documents. Each card has a trash icon (visible on hover) to delete the team with a name-typing confirmation dialog. Click a card to open the detail view.

### New Team (`/teams/new`)

Create a new multi-persona team through a 3-step flow: **Configure -> Editor -> Success**.

**Configure** -- pick a strategy, define personas, and select a team-level model:

| Strategy | Description |
|----------|-------------|
| **Sequential** | Personas execute in order, each receiving the previous persona's output |
| **Parallel** | All personas execute simultaneously, outputs are combined |

Personas are configured individually through expandable cards (2-8). Each card has:
- **Role source** -- toggle between "Custom" (write a role description manually) and "From agent" (pick an existing agent via the Agent Picker). Selecting an agent copies its description into the role field, auto-renames the persona if the name is still a default, and pre-fills the model override with the agent's provider/model/endpoint. The copied fields remain fully editable. A "Seeded from `<agent-name>`" indicator shows the source while the link is active. This is a one-time copy; saved team YAML contains plain persona data with no agent reference.
- **Name** -- editable, validated against kebab-case naming rules, unique across the team
- **Role** -- textarea describing what the persona does (becomes the persona's system prompt)
- **Model override** -- optional toggle to use a different model than the team default, with full provider parity (cloud, Ollama, OpenRouter, custom endpoints with API key persistence via `/api/providers/save-key`)

For sequential teams, arrow connectors between cards show execution order, and up/down buttons allow reordering (persona order in the YAML determines execution order). Default persona names are assigned from a pool (analyst, reviewer, advisor, checker, specialist, evaluator, auditor, planner).

The team-level model selector supports the same provider options as agent creation (cloud providers, Ollama, custom presets, custom endpoints).

**Editor** -- review and edit the generated `team.yaml` with live validation. Pick a save directory and filename, then save.

**Success** -- shows the saved path and CLI command to run the team.

### Team Detail (`/teams/{id}`)

Tabbed detail page with four tabs. A **Delete** button in the header opens a confirmation dialog requiring the team name to be typed. Deleting removes the team YAML file and redirects to the teams list.

| Tab | Contents |
|-----|----------|
| **Pipeline** (default) | Strategy-aware visualization. Sequential shows a vertical chain of persona cards with handoff arrows; parallel shows a fan-out/fan-in layout. Cards display persona name, model override badge, tool count, duration, and token counts. Cards animate through states: idle, active (pulsing dot), pending, complete (checkmark), error (X). |
| **Run** | Chat interface for running prompts through the team. Deterministic Rings avatars seeded from the active persona name identify each turn. Active persona indicator matches the pipeline visualization. Collapsible persona trace shows per-persona name, duration, tokens, and output preview. |
| **Config** | Collapsible sections: model, strategy (with handoff_max_chars), guardrails, shared memory, shared documents, tools, observability. |
| **Editor** | YAML editor with live validation, in-place save, and copy. Warns when name changes (affects team ID). |

### Skills (`/skills`)

Browse all discovered skill files (both directory-form `skills/name/SKILL.md` and flat-form `skills/name.md`). Skills are inventoried by physical path -- duplicate names across scopes are all shown, not deduplicated.

- **Filter bar**: scope pills (All, Role-local, Project, Extra, User) and type pills (All, Tool-providing, Methodology). Filter state syncs to URL query params for shareability.
- **Search**: substring match against name and description.
- **Skill cards**: show name, scope badge, description, tool count or "methodology" label, and requirement status. Cards with 3+ tools get a subtle lime glow.

Click a card to open the detail view. A "New Skill" button opens the creation page.

### New Skill (`/skills/new`)

Scaffold a new skill in directory format. Form fields: name (kebab-case validated), directory (populated from skill root directories), and provider (for template defaults). On success, redirects to the new skill's detail page.

### Skill Detail (`/skills/{id}`)

Header with skill name, scope badge, requirement status dot, and a Delete button.

Two tabs:

| Tab | Contents |
|-----|----------|
| **Overview** (default) | Collapsible sections: description, tools (type + summary, hidden for methodology-only), requirements (checklist with green/red indicators), prompt (expandable preview), metadata (license, compatibility, author, version), and "Used by" (agents that reference this skill, clickable links to agent detail). |
| **Editor** | Full SKILL.md content editor (YAML frontmatter + markdown body). Validate-before-save: invalid content returns errors without writing to disk. Name change warning. |

**Delete behavior**: flat `.md` files delete directly. Directory-form skills block deletion when sibling resource files exist (shows the blocking file list). Resource-bearing skill directories must be cleaned up manually or via CLI.

**Cross-linking**: agent detail pages show resolved skill refs as clickable links to `/skills/{id}`. Skill detail pages show which agents use the skill via "Used by" section.

### Audit Log (`/audit`)

Filterable table of all agent runs with analytics.

- **Stats strip**: aggregate totals (runs, success rate, tokens, avg duration) for the current filter
- **Filters**: agent name, trigger type, date range (since/until), all/failures toggle
- **Detail drawer**: click any row to see full prompt, full output, all tool call names, trigger type, run ID, and error details
- **Export**: download filtered results as JSON or CSV

### System (`/system`)

Four sections:

| Section | Contents |
|---------|----------|
| **Providers** | Full provider management. Shows configured providers as card-surface rows (name + env var + green status dot). Includes an inline form to add new provider API keys -- select a provider, enter the key, and save. For OpenAI and Anthropic, keys are validated against the provider API. Supports standard providers, OpenRouter, and custom endpoints. Keys are written to `~/.initrunner/.env`. |
| **Default Model** | Pick the global default model for agents that don't specify one. Uses the same model selector as the agent builder (provider dropdown + searchable model list). Shows where the current default comes from: `INITRUNNER_MODEL` env var, `run.yaml`, auto-detected from API keys, or none. Save writes to `~/.initrunner/run.yaml`. Reset clears the saved model and returns to auto-detection. Preset names (e.g. OpenRouter) are normalized to canonical runtime fields. |
| **Health Check** | "Run Doctor" button that checks API key validity, SDK availability, Ollama connectivity, and Docker status. Results shown as a checklist with green/amber/red indicators. |
| **Tool Registry** | List of all registered tool types with descriptions. Useful when deciding what tools to add to an agent. |

### Command Palette

Press `Cmd+K` (or `Ctrl+K`) anywhere to open the command palette. Provides:

- Fuzzy search across all agents, compositions, and teams by name and description
- Quick navigation to any page (Launchpad, Agents, Skills, Compose, Teams, Audit, System)
- Quick actions: "New Agent", "New Skill", "New Compose", "New Team"
- Keyboard navigation with arrow keys and Enter

Results are grouped: Pages, Actions, Agents, Compositions, Teams.

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
  |      /api/agents/{id}      DELETE delete agent YAML and evict from cache
  |      /api/agents/{id}/trigger-stats GET per-trigger-type operational stats
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
  |      /api/compose/{id}/stats  GET compose event statistics
  |      /api/compose/{id}/yaml   PUT save edited compose YAML
  |      /api/compose/{id}        DELETE delete compose YAML and evict from cache
  |      /api/compose/{id}/run/stream POST streaming compose run (SSE)
  |      /api/compose-builder/options GET patterns, agents, providers
  |      /api/compose-builder/seed POST generate compose YAML
  |      /api/compose-builder/validate POST schema-only validation
  |      /api/compose-builder/save POST write compose + roles to disk
  |      /api/teams            GET   list discovered team files
  |      /api/teams/{id}      GET   team detail with personas
  |      /api/teams/{id}/yaml GET   raw team YAML
  |      /api/teams/{id}/yaml PUT   save edited team YAML
  |      /api/teams/{id}      DELETE delete team YAML and evict from cache
  |      /api/teams/{id}/run/stream POST streaming team run (SSE)
  |      /api/team-builder/options GET strategies, providers
  |      /api/team-builder/seed POST generate team YAML
  |      /api/team-builder/validate POST schema validation
  |      /api/team-builder/save POST write team YAML to disk
  |      /api/skills           GET   list discovered skills (path-based, no name dedup)
  |      /api/skills           POST  create new skill (directory format)
  |      /api/skills/refresh   POST  re-scan all skill directories
  |      /api/skills/directories GET  valid create target directories
  |      /api/skills/{id}      GET   skill detail with used_by_agents cross-refs
  |      /api/skills/{id}      DELETE delete skill (blocks if resource files exist)
  |      /api/skills/{id}/content GET raw SKILL.md content for editor
  |      /api/skills/{id}/content PUT validate-then-save skill content
  |      /api/runs             POST  execute single run
  |      /api/runs/stream      POST  streaming run (SSE)
  |      /api/audit            GET   query audit records
  |      /api/audit/stats      GET   aggregate audit statistics
  |      /api/providers        GET   detected providers
  |      /api/providers/status GET   all providers with config status
  |      /api/providers/save-key POST save API key to ~/.initrunner/.env
  |      /api/system/doctor    GET   provider health checks
  |      /api/system/tools     GET   registered tool types
  |      /api/system/default-model GET/POST/DELETE  default model config
  |      /                     static SvelteKit build
  |
  +--> Browser (opens automatically)
```

### Agent Identity

Agents are identified by a stable opaque ID derived from their file path (`sha256[:12]`). This avoids ambiguity when multiple role directories contain agents with the same `metadata.name`.

### Services Layer

The backend imports exclusively from `initrunner.services.*` and `initrunner.config`. It never imports from `initrunner.agent.*` or `initrunner.audit.*` directly. This is the same boundary the CLI uses.

### Streaming

Agent runs use SSE (Server-Sent Events). Single-agent runs use `execute_run_stream_sync` in a thread pool with an `asyncio.Queue` bridge. Compose and team runs use the graph engine directly via `asyncio.create_task` (no thread pool hop). Events:

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

The `--expose` flag binds to `0.0.0.0`, making it accessible on all network interfaces. When exposing the dashboard, use `--api-key` to require authentication.

The dashboard can execute any discovered agent with any prompt. It has the same access as `initrunner run` on the command line.

### Authentication

Pass `--api-key <value>` to enable authentication:

```bash
initrunner dashboard --api-key my-secret-key
initrunner dashboard --expose --api-key my-secret-key
```

When enabled:

- **Browser sessions**: Unauthenticated HTML requests redirect to `/login`. After entering the API key, a session cookie (`initrunner_token`, HttpOnly, SameSite=Strict) is set. All subsequent requests use this cookie.
- **API clients**: Pass the key as a Bearer token: `Authorization: Bearer <key>`.
- **Public endpoints**: Only `/api/health` and `/login` are accessible without authentication. All other routes (including `/api/docs` and `/api/openapi.json`) require a valid key.
- **Logout**: `POST /logout` clears the session cookie.

Without `--api-key`, the dashboard runs with no authentication (suitable for localhost-only use).

**Limitations**: Authentication mode supports the built-in same-origin UI and Bearer-token API clients. The cross-origin Vite dev server (`localhost:5173`) is not supported in authenticated mode. For development with auth, use the production build served by the backend.

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
    "features": ["tools", "memory", "reasoning", "autonomy"],
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

Validate YAML text against the role schema. Performs Pydantic schema validation, cross-field reasoning checks (e.g. `todo_driven` requires a `todo` tool, `reflexion` requires `reflection_rounds > 0`), and emits recommendation-level `info` issues (e.g. think tool recommended for reflexion). Issues have severity `error`, `warning`, or `info`.

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

### `GET /api/agents/{id}/ingest/documents`

List all ingested documents for an agent. Returns source path, chunk count, ingested timestamp, content hash, `is_url` flag, and `is_managed` flag (true for dashboard-added sources).

### `GET /api/agents/{id}/ingest/summary`

Aggregate ingestion stats: total documents, total chunks, store path, configured source patterns, managed source count, and last ingested timestamp.

### `POST /api/agents/{id}/ingest/run?force=false`

Trigger a full re-ingestion via SSE. Ingests all sources from `ingest.sources` config plus managed sources from the manifest. SSE events:
- `progress` -- per-file status (`new`, `updated`, `skipped`, `error`)
- `result` -- final `IngestStatsResponse`
- `error` -- error string

### `POST /api/agents/{id}/ingest/upload`

Multipart file upload. Files are saved to `~/.initrunner/uploads/{agent_name}/` and ingested as managed sources. Returns `IngestStatsResponse`.

### `POST /api/agents/{id}/ingest/add-url`

Add a URL source. The URL is fetched, chunked, embedded, and registered as a managed source.

```json
{"url": "https://docs.example.com/api-reference"}
```

### `DELETE /api/agents/{id}/ingest/documents?source=...`

Remove a single source from the store and manifest. For managed file sources, also deletes the uploaded file. Returns `{"chunks_deleted": N}`.

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
| `status` | string | Filter by status (delivered/dropped/filtered/error/policy_denied/circuit_open) |
| `since` | string | ISO 8601 start time |
| `until` | string | ISO 8601 end time |
| `limit` | int | Max events (default 200) |

### `GET /api/compose/{id}/stats`

Returns aggregate event statistics for this composition. Status buckets are dynamic (not hard-coded).

```json
{
  "total_events": 42,
  "by_status": {
    "delivered": 38,
    "filtered": 2,
    "dropped": 1,
    "policy_denied": 1
  }
}
```

### `PUT /api/compose/{id}/yaml`

Save edited compose YAML in place. Validates against the compose schema before writing; returns 422 with issue details on validation errors. Does not support rename -- writes to the existing file path only.

```json
{ "yaml_text": "apiVersion: initrunner/v1\nkind: Compose\n..." }
```

Returns `{ path, valid, issues[] }`.

### `POST /api/compose/{id}/run/stream`

Run a single prompt through the compose pipeline via SSE. Uses the real orchestrator wiring (shared memory, delegate sinks, routing strategies) in one-shot mode -- triggers and non-delegate role sinks are suppressed.

```json
{ "prompt": "Analyze this email...", "message_history": null }
```

SSE events:
- `service_start` -- service name about to execute
- `service_complete` -- per-service result (name, output preview, duration, tokens, success)
- `result` -- final `ComposeRunResponse` with `output`, `output_mode` (single/multiple/none), `steps[]`, aggregate tokens, and entry service `message_history`
- `error` -- error string

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

### `GET /api/teams`

Returns all discovered team definitions.

```json
[
  {
    "id": "b2c3d4e5f6a7",
    "name": "research-team",
    "description": "Multi-persona research pipeline",
    "strategy": "sequential",
    "persona_count": 3,
    "personas": ["researcher", "analyst", "writer"],
    "provider": "anthropic",
    "model": "claude-sonnet-4-20250514",
    "path": "/home/user/teams/research.yaml",
    "error": null
  }
]
```

### `GET /api/teams/{id}`

Returns full team detail with persona definitions and configuration.

### `GET /api/teams/{id}/yaml`

Returns raw team YAML content.

### `PUT /api/teams/{id}/yaml`

Save edited team YAML in place. Validates against the team schema before writing.

```json
{ "yaml_text": "apiVersion: initrunner/v1\nkind: Team\n..." }
```

Returns `{ path, valid, issues[] }`.

### `POST /api/teams/{id}/run/stream`

Run a prompt through the team via SSE.

```json
{ "prompt": "Research quantum computing advances" }
```

SSE events:
- `persona_start` -- persona name about to execute
- `persona_complete` -- per-persona result (name, output preview, duration, tokens, success)
- `result` -- final `TeamRunResponse` with output, steps, and aggregate tokens
- `error` -- error string

### `GET /api/team-builder/options`

Returns available strategies, provider/model options, and save directories.

### `POST /api/team-builder/seed`

Generate team YAML from a strategy and persona definitions.

```json
{
  "mode": "blank",
  "strategy": "sequential",
  "name": "my-team",
  "persona_count": 3,
  "personas": [
    {"name": "analyst", "role": "Analyze the input data", "model": null},
    {"name": "reviewer", "role": "Review the analysis for errors", "model": null},
    {
      "name": "advisor",
      "role": "Provide recommendations",
      "model": {"provider": "anthropic", "name": "claude-opus-4-6", "base_url": null, "api_key_env": null}
    }
  ],
  "provider": "anthropic",
  "model": "claude-sonnet-4-20250514"
}
```

When `personas` is provided, it takes precedence over `persona_count`. Each persona entry specifies a `name`, `role`, and optional `model` override. Custom preset providers (e.g. `"openrouter"`) are resolved to canonical form (`provider: "openai"` with injected `base_url`/`api_key_env`). When `personas` is omitted, falls back to generating default persona names from a pool.

Response includes `yaml_text`, `explanation`, `issues[]`, and `ready`.

### `POST /api/team-builder/validate`

Schema-only validation of team YAML.

### `POST /api/team-builder/save`

Write team YAML to disk. Returns `path`, `valid`, `issues[]`, `next_steps[]`, and `team_id`. Returns 409 if the file already exists and `force` is false.

### `GET /api/health`

```json
{"status": "ok", "version": "1.39.2"}
```
