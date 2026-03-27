# CLI Reference

## Path resolution

All commands that accept a role path also accept a **directory** or an **installed role name**. Resolution order:

1. If the path is a file, use it.
2. If the path is a directory:
   a. If `<dir>/role.yaml` exists, use it.
   b. Otherwise scan top-level `*.yaml`/`*.yml` for files with `apiVersion: initrunner/v1`.
   c. Exactly one match is used; zero or multiple matches produce an error.
3. Otherwise, look up the name in the installed role registry (exact key, owner/name, or display name).

This means `initrunner run .` works from inside an agent directory, and `initrunner run code-reviewer` works after `initrunner install alice/code-reviewer`.

## Commands

| Command | Description |
|---------|-------------|
| `initrunner run` | Run an agent (ephemeral or from role file), team, compose, or pipeline |
| `initrunner run <PATH>` | Run an agent from a role file, team, compose, or pipeline (auto-detected from YAML kind) |
| `initrunner validate <PATH>` | Validate a role definition |
| `initrunner validate <PATH> --explain` | Validate and explain what each section does in plain language |
| `initrunner new [description]` | Create a new agent via conversational builder |
| `initrunner setup` | Guided setup wizard (provider selection + test) |
| `initrunner ingest <PATH>` | Ingest documents into vector store |
| `initrunner test <PATH> -s <suite>` | Run a test suite against an agent |
| `initrunner install <source>` | Install a role from InitHub or OCI registry |
| `initrunner uninstall <name>` | Remove an installed role |
| `initrunner search <query>` | Search InitHub for agent packs |
| `initrunner info <source>` | Inspect a role's metadata without installing |
| `initrunner list` | List installed roles (with run commands) |
| `initrunner update [name]` | Update installed role(s) to latest version |
| `initrunner doctor` | Check provider configuration, API keys, and connectivity |
| `initrunner plugins` | List discovered tool plugins |
| `initrunner audit prune` | Prune old audit records |
| `initrunner audit export` | Export audit records as JSON or CSV |
| `initrunner memory clear <PATH>` | Clear agent memory store |
| `initrunner memory export <PATH>` | Export memories to JSON |
| `initrunner memory import <PATH> <file>` | Import memories from JSON |
| `initrunner memory list <PATH>` | List stored memories |
| `initrunner memory consolidate <PATH>` | Run memory consolidation manually |
| `initrunner skill new [name]` | Scaffold a new skill directory |
| `initrunner skill validate <path>` | Validate a skill definition |
| `initrunner skill list` | List available skills |
| `initrunner compose new <name>` | Scaffold a new compose project directory |
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
| `initrunner mcp list-tools <PATH>` | List tools from MCP servers in a role |
| `initrunner mcp serve <PATH>...` | Expose agents as an MCP server |
| `initrunner login` | Log in to InitHub (browser auth) or OCI registry |
| `initrunner logout` | Remove stored InitHub credentials |
| `initrunner whoami` | Show current InitHub user |
| `initrunner publish [PATH]` | Publish to InitHub (default) or OCI registry |
| `initrunner hub login` | (deprecated) Authenticate with InitHub |
| `initrunner hub logout` | (deprecated) Remove stored InitHub credentials |
| `initrunner hub whoami` | (deprecated) Show current InitHub user |
| `initrunner hub search <QUERY>` | (deprecated) Search InitHub for agent packs |
| `initrunner hub publish [PATH]` | (deprecated) Publish an agent pack to InitHub |
| `initrunner hub info <PACKAGE>` | (deprecated) Show InitHub package details |
| `initrunner --version` | Print version |

> **PATH** can be a role YAML file (`role.yaml`, `pdf-agent.yaml`), a pipeline file, a compose file, a team file, or a directory containing one. See [Path resolution](#path-resolution).

## No-subcommand behavior

Running `initrunner` with no subcommand in a TTY shows an action menu:

```
  1. Dashboard (web UI)
  2. Quick chat (REPL)
  3. Create an agent

What would you like to do? [1/2/3] (1):
```

- **Dashboard** launches the web UI at `http://localhost:8100` (only shown when dashboard extras are installed).
- **Quick chat** starts an ephemeral REPL using the provider from `~/.initrunner/run.yaml`.
- **Create an agent** enters the interactive agent builder (`initrunner new`).

The default is Dashboard when available, otherwise Quick chat. If no provider is configured, a "Setup Required" panel is shown instead.

In non-TTY contexts (piped input), the help text is printed.

## Run options

Synopsis: `initrunner run [PATH] [OPTIONS]`

The path argument is optional when `--sense` is used. The `run` command auto-detects the YAML kind (Agent, Team, Compose, Pipeline) and dispatches accordingly.

| Flag | Description |
|------|-------------|
| `-p, --prompt TEXT` | Single prompt to send |
| `-i, --interactive` | Interactive REPL mode |
| `-a, --autonomous` | Autonomous agentic loop mode (requires `-p`) |
| `--max-iterations N` | Override max iterations for autonomous mode |
| `--resume` | Resume the previous REPL session (requires `memory:` config) |
| `--dry-run` | Simulate with TestModel (no API calls) |
| `--daemon` | Run in trigger-driven daemon mode |
| `--serve` | Serve agent as an OpenAI-compatible API |
| `--bot TEXT` | Launch as a bot (`telegram` or `discord`) |
| `--var TEXT` | Variable in `key=value` format (repeatable). Used with Pipeline kind. |
| `--host TEXT` | Host to bind to (default: `127.0.0.1`). Used with `--serve`. |
| `--port INT` | Port to listen on (default: `8000`). Used with `--serve`. |
| `--api-key TEXT` | API key for Bearer token authentication. Used with `--serve`. |
| `--cors-origin TEXT` | Allowed CORS origin (repeatable). Used with `--serve`. |
| `--allowed-users TEXT` | Restrict bot to these usernames (repeatable). Used with `--bot`. |
| `--allowed-user-ids TEXT` | Restrict bot to these user IDs (repeatable). Used with `--bot`. |
| `--audit-db PATH` | Custom audit database path |
| `--no-audit` | Disable audit logging |
| `--skill-dir PATH` | Extra skill search directory |
| `-A, --attach PATH_OR_URL` | Attach file or URL (repeatable). Supports images, audio, video, and documents. Requires `-p`. See [Multimodal Input](../core/multimodal.md). |
| `--report PATH` | Export a markdown report to PATH after the run. See [Report Export](../core/reports.md). |
| `--report-template TEXT` | Report template: `default`, `pr-review`, `changelog`, `ci-fix`. Requires `--report`. |
| `--sense` | Sense the best role for the given prompt (replaces the path argument). |
| `--role-dir PATH` | Directory to search for roles when using `--sense`. |
| `-f, --format TEXT` | Output format: `auto` (default), `json`, `text`, `rich`. See [Output Formats](#output-formats). |
| `--no-stream` | **Deprecated.** Use `--format rich`. Hidden from `--help`. |
| `--confirm-role` | Prompt to confirm the auto-selected role before running (requires a TTY). |
| `--provider TEXT` | Model provider (overrides auto-detection or role config) |
| `--model TEXT` | Model alias or provider:model (overrides auto-detection or role config). Env: `INITRUNNER_MODEL`. See [Model Aliases](../configuration/model-aliases.md). |
| `--tool-profile TEXT` | Tool profile: `none`, `minimal` (default for ephemeral), `all` |
| `--tools TEXT` | Extra tool types to enable (repeatable) |
| `--memory / --no-memory` | Enable or disable persistent memory (default: enabled for ephemeral) |
| `--ingest PATH` | Paths or globs to ingest for document Q&A (repeatable) |
| `--list-tools` | List available extra tool types and exit |

### Intent Sensing examples

```bash
# Let initrunner pick the best role for your task
initrunner run --sense -p "analyze this CSV and summarize"

# Search a specific directory for roles
initrunner run --sense --role-dir ./roles/ -p "search the web for AI news"

# Review the sensed role before running
initrunner run --sense --confirm-role -p "review my code for bugs"

# Dry-run: discover + score roles without any LLM calls
initrunner run --sense --dry-run -p "task description"
```

Intent Sensing uses a two-pass strategy:
1. **Keyword/tag scoring** — zero API calls. Selects confidently when one role clearly matches.
2. **LLM tiebreaker** — compact call used only when the top two candidates are too close. Skipped when `--dry-run` is set.

Set `INITRUNNER_DEFAULT_MODEL` to override the model used for the LLM tiebreaker (default: `openai:gpt-4o-mini`).

See [Intent Sensing](../core/intent_sensing.md) for the full algorithm reference, role tagging guide, and troubleshooting.

Token budgets (`max_tokens_per_run`, `autonomous_token_budget`, etc.) are set in `spec.guardrails` in the role YAML. See [Guardrails](../configuration/guardrails.md).

Combine flags: `initrunner run role.yaml -p "Hello!" -i` sends a prompt then continues interactively.

## Output Formats

The `--format` flag controls how `initrunner run` presents output. The default (`auto`) adapts based on whether stdout is a terminal:

| Format | Behavior |
|--------|----------|
| `auto` | **TTY:** stream tokens live. **Non-TTY (piped):** plain text to stdout, stats to stderr. |
| `json` | JSON envelope to stdout with `output`, `success`, `error`, token counts, and timing. |
| `text` | Plain text to stdout (agent output only), stats to stderr. |
| `rich` | Buffered Rich panel with Markdown rendering (the old `--no-stream` behavior). |

In `auto` (streaming), `rich`, and autonomous modes, tool call completions are shown as dimmed status lines so you can distinguish tool issues from model issues:

```
  tool search_web: ok (1523ms)
  tool search_web: error - Error: search timed out after 15s (15023ms)
```

`--format json` and `--format text` are only supported for single-shot runs (`-p` without `-i` or `-a`).

```bash
# Pipe agent output to jq
initrunner run role.yaml -p "list 3 facts" --format json | jq .output

# Clean output for scripts
initrunner run role.yaml -p "summarize this" --format text > summary.txt

# Force Rich panel on a TTY
initrunner run role.yaml -p "hello" --format rich
```

## Post-command suggestions

After a successful `run`, `validate`, or `ingest`, the CLI prints 2-3
contextual next-step commands you can copy-paste. Suggestions adapt to the
role's configuration (e.g. ingest and memory commands only appear when those
sections are defined).

Suggestions are suppressed when stdout is not a TTY (piped output) and when
using `--format json` or `--format text`, so machine-readable output stays
clean.

## Error hints

Most CLI error messages include a `Hint:` line with the likely fix -- for
example, the correct command to run, a missing YAML section to add, or a
doc page to check. These appear automatically after `Error:` output.

## Ingest options

| Flag | Description |
|------|-------------|
| `--force` | Force re-ingestion of all files. Also wipes the store when the embedding model has changed. |

## New options

Synopsis: `initrunner new [DESCRIPTION] [OPTIONS]`

Create a new agent role via conversational builder. Seed modes are mutually exclusive.

| Flag | Description |
|------|-------------|
| `DESCRIPTION` | Natural language description (generates via LLM) |
| `--from SOURCE` | Source: local file path, bundled example name, or `hub:ref` |
| `--template TEXT` | Start from a named template (use `--list-templates` to see options) |
| `--list-templates` | Show available templates and exit |
| `--blank` | Start from a minimal blank template |
| `--provider TEXT` | Model provider (auto-detected if omitted) |
| `--model TEXT` | Model name (uses provider default if omitted) |
| `--output PATH` | Output file path (default: `role.yaml`) |
| `--force` | Overwrite existing file without prompting |
| `--no-refine` | Skip the interactive refinement loop |

Without any seed, starts an interactive conversation where the LLM asks what to build.

### Examples

```bash
# Generate from description with interactive refinement
initrunner new "a code review bot that reads git diffs"

# Start from a template, skip refinement
initrunner new --template rag --no-refine

# Load from an example
initrunner new --from hello-world

# Blank template with specific provider
initrunner new --blank --provider anthropic

# Fully interactive (no seed)
initrunner new
```

## Setup options

| Flag | Description |
|------|-------------|
| `--provider TEXT` | Provider (skip interactive selection) |
| `--name TEXT` | Agent name (default: `my-agent`) |
| `--model TEXT` | Model name. Uses provider default if omitted. |
| `--skip-test` | Skip connectivity test |
| `--output PATH` | Role output path (default: `role.yaml`) |
| `-y, --accept-risks` | Accept security disclaimer without prompting |

## Serve options

The `--serve` flag on `initrunner run` starts an OpenAI-compatible API server. Server-specific flags (`--host`, `--port`, `--api-key`, `--cors-origin`) are listed in the [Run options](#run-options) table above.

See [server.md](../interfaces/server.md) for endpoint details, streaming, multi-turn conversations, and usage examples.

## MCP serve options

Synopsis: `initrunner mcp serve PATHS... [OPTIONS]`

| Flag | Description |
|------|-------------|
| `--transport, -t TEXT` | Transport: `stdio`, `sse`, `streamable-http` (default: `stdio`) |
| `--host TEXT` | Host to bind to (default: `127.0.0.1`, sse/http only) |
| `--port INT` | Port to listen on (default: `8080`, sse/http only) |
| `--server-name TEXT` | MCP server name (default: `initrunner`) |
| `--pass-through` | Also expose agent MCP tools directly |
| `--audit-db PATH` | Custom audit database path |
| `--no-audit` | Disable audit logging |
| `--skill-dir PATH` | Extra skill search directory |

See [MCP Gateway](../interfaces/mcp-gateway.md) for transport details, client configuration, pass-through mode, and usage examples.

## Compose new options

Scaffold a compose project directory with `compose.yaml` and stub role files.

```bash
initrunner compose new my-pipeline                          # default: 3-service pipeline
initrunner compose new desk --pattern route --shared-memory # support-desk style routing
initrunner compose new spread --pattern fan-out --services 5
```

| Flag | Description |
|------|-------------|
| `--pattern TEXT` | Compose pattern: `pipeline` (default), `fan-out`, `route` |
| `--services INT` | Number of services (default: `3`). Pipeline min 2, fan-out min 3, route is fixed |
| `--shared-memory` | Enable shared memory store across all services |
| `--provider TEXT` | Model provider for generated roles (auto-detected if omitted) |
| `--model TEXT` | Model name for generated roles |
| `--output PATH` | Parent directory for the project (default: `.`) |
| `--force`, `-f` | Overwrite existing directory |
| `--list-patterns` | Show available patterns and exit |

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

## Doctor options

| Flag | Description |
|------|-------------|
| `--quickstart` | Run a smoke prompt to verify end-to-end connectivity |
| `--role PATH` | Agent directory or role file to test (loads its `.env` and uses it for `--quickstart`) |

See [Doctor](../operations/doctor.md) for details.

## Hub options

Synopsis: `initrunner hub <command> [OPTIONS]`

Manage agent packs on [InitHub](https://hub.initrunner.ai).

### `hub login`

```bash
initrunner hub login              # opens browser for device code authorization
initrunner hub login --token TEXT  # pass a token directly (CI/headless environments)
```

| Flag | Description |
|------|-------------|
| `--token TEXT` | API token with `publish` scope. Skips browser-based device code flow. Use in CI or headless environments. |

Without `--token`, the CLI generates a one-time device code, opens the browser to approve it, and polls until authorization completes. The resulting token is stored locally for future commands.

### `hub publish`

```bash
initrunner hub publish                                # publish from current directory
initrunner hub publish ./my-agent/                    # publish from a path
initrunner hub publish role.yaml --readme README.md   # attach a README
```

| Flag | Description |
|------|-------------|
| `PATH` | Role file or directory to publish (default: `.`) |
| `--readme PATH` | README file to include with the package |
| `--repo-url TEXT` | Repository URL for the package listing |
| `--category TEXT` | Category slug (repeatable) |

Requires authentication (`hub login`) with a token that has `publish` scope.

### `hub search`

```bash
initrunner hub search "code review"
initrunner hub search python --tag automation
```

| Flag | Description |
|------|-------------|
| `QUERY` | Search query (matches name, description, tags) |
| `--tag TEXT` | Filter by tag (repeatable) |

### `hub info`

```bash
initrunner hub info owner/package-name
```

| Flag | Description |
|------|-------------|
| `PACKAGE` | Package identifier (`owner/name`) |

## Environment variables

| Variable | Effect |
|----------|--------|
| `INITRUNNER_AUDIT_DB` | Default audit database path (overridden by `--audit-db`) |
| `INITRUNNER_SKILL_DIR` | Extra skill search directory (CLI `--skill-dir` takes precedence, but env dir is also searched) |
