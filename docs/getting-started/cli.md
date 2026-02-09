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
| `--resume` | Resume the previous REPL session (requires `memory:` config) |
| `--dry-run` | Simulate with TestModel (no API calls) |
| `--audit-db PATH` | Custom audit database path |
| `--no-audit` | Disable audit logging |

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
| `--output PATH` | Output file path (default: `role.yaml`) |

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
