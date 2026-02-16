# CLI Reference

## Commands

| Command | Description |
|---------|-------------|
| `initrunner run <role.yaml>` | Run an agent (single-shot or interactive) |
| `initrunner validate <role.yaml>` | Validate a role definition |
| `initrunner init` | Scaffold a template role, tool module, or skill |
| `initrunner setup` | Guided setup wizard (provider selection + test) |
| `initrunner ingest <role.yaml>` | Ingest documents into vector store |
| `initrunner daemon <role.yaml>` | Run in trigger-driven daemon mode |
| `initrunner serve <role.yaml>` | Serve agent as an OpenAI-compatible API |
| `initrunner test <role.yaml> -s <suite>` | Run a test suite against an agent |
| `initrunner pipeline <pipeline.yaml>` | Run a pipeline of agents |
| `initrunner tui` | Launch TUI dashboard |
| `initrunner ui` | Launch web dashboard (requires `[dashboard]` extra) |
| `initrunner install <source>` | Install a role from GitHub or community index |
| `initrunner uninstall <name>` | Remove an installed role |
| `initrunner search <query>` | Search the community role index |
| `initrunner info <source>` | Inspect a role's metadata without installing |
| `initrunner list` | List installed roles |
| `initrunner update [name]` | Update installed role(s) to latest version |
| `initrunner plugins` | List discovered tool plugins |
| `initrunner audit prune` | Prune old audit records |
| `initrunner audit export` | Export audit records as JSON or CSV |
| `initrunner memory clear <role.yaml>` | Clear agent memory store |
| `initrunner memory export <role.yaml>` | Export memories to JSON |
| `initrunner skill validate <path>` | Validate a skill definition |
| `initrunner skill list` | List available skills |
| `initrunner compose up <compose.yaml>` | Run compose orchestration (foreground) |
| `initrunner compose validate <compose.yaml>` | Validate a compose definition |
| `initrunner compose install <compose.yaml>` | Install systemd user unit |
| `initrunner compose uninstall <name>` | Remove systemd unit |
| `initrunner compose start <name>` | Start systemd service |
| `initrunner compose stop <name>` | Stop systemd service |
| `initrunner compose restart <name>` | Restart systemd service |
| `initrunner compose status <name>` | Show systemd service status |
| `initrunner compose logs <name>` | Show journald logs |
| `initrunner compose events` | Query delegate routing events |
| `initrunner --version` | Print version |

## Run options

| Flag | Description |
|------|-------------|
| `-p, --prompt TEXT` | Single prompt to send |
| `-i, --interactive` | Interactive REPL mode |
| `-a, --autonomous` | Autonomous agentic loop mode (requires `-p`) |
| `--max-iterations N` | Override max iterations for autonomous mode |
| `--resume` | Resume the previous REPL session (requires `memory:` config) |
| `--dry-run` | Simulate with TestModel (no API calls) |
| `--audit-db PATH` | Custom audit database path |
| `--no-audit` | Disable audit logging |
| `--skill-dir PATH` | Extra skill search directory |
| `-A, --attach PATH_OR_URL` | Attach file or URL (repeatable). Supports images, audio, video, and documents. Requires `-p`. See [Multimodal Input](../core/multimodal.md). |

Token budgets (`max_tokens_per_run`, `autonomous_token_budget`, etc.) are set in `spec.guardrails` in the role YAML. See [Guardrails](../configuration/guardrails.md).

Combine flags: `initrunner run role.yaml -p "Hello!" -i` sends a prompt then continues interactively.

## Ingest options

| Flag | Description |
|------|-------------|
| `--force` | Force re-ingestion of all files. Also wipes the store when the embedding model has changed. |

## Init options

| Flag | Description |
|------|-------------|
| `--name TEXT` | Agent name (default: `my-agent`) |
| `--template TEXT` | Template: `basic`, `rag`, `daemon`, `memory`, `ollama`, `tool`, `api`, `skill` (default: `basic`) |
| `--provider TEXT` | Model provider (default: `openai`) |
| `--model TEXT` | Model name (e.g. `gpt-4o`, `claude-sonnet-4-5-20250929`). Uses provider default if omitted. |
| `--output PATH` | Output file path (default: `role.yaml`) |

## Setup options

| Flag | Description |
|------|-------------|
| `--provider TEXT` | Provider (skip interactive selection) |
| `--name TEXT` | Agent name (default: `my-agent`) |
| `--template TEXT` | Template: `chatbot`, `rag`, `memory`, `daemon` |
| `--model TEXT` | Model name. Uses provider default if omitted. |
| `--skip-test` | Skip connectivity test |
| `--output PATH` | Role output path (default: `role.yaml`) |
| `-y, --accept-risks` | Accept security disclaimer without prompting |
| `--interfaces TEXT` | Install interfaces: `tui`, `dashboard`, `both`, `skip` |

## Create options

| Flag | Description |
|------|-------------|
| `--provider TEXT` | Model provider for generation (auto-detected if omitted) |
| `--output PATH` | Output file path (default: `role.yaml`) |
| `--name TEXT` | Agent name (auto-derived if omitted) |
| `--model TEXT` | Model name for the generated role |
| `--no-confirm` | Skip the YAML preview |

## Serve options

| Flag | Description |
|------|-------------|
| `--host TEXT` | Host to bind to (default: `127.0.0.1`) |
| `--port INT` | Port to listen on (default: `8000`) |
| `--api-key TEXT` | API key for Bearer token authentication |
| `--audit-db PATH` | Custom audit database path |
| `--no-audit` | Disable audit logging |
| `--cors-origin TEXT` | Allowed CORS origin (repeatable). Merged with `security.server.cors_origins` from role YAML. |
| `--skill-dir PATH` | Extra skill search directory |

See [server.md](../interfaces/server.md) for endpoint details, streaming, multi-turn conversations, and usage examples.

## Compose events options

| Flag | Description |
|------|-------------|
| `--source TEXT` | Filter by source service |
| `--target TEXT` | Filter by target service |
| `--status TEXT` | Filter by status (`delivered`, `dropped`, `filtered`, `error`) |
| `--run-id TEXT` | Filter by source run ID |
| `--since TEXT` | Start timestamp (ISO 8601) |
| `--until TEXT` | End timestamp (ISO 8601) |
| `--limit INT` | Max events to show (default: `100`) |
| `--audit-db PATH` | Path to audit database |
