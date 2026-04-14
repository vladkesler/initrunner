# Doctor

The `doctor` command checks your InitRunner environment -- API keys, provider SDKs, and service connectivity -- in a single command. With `--role` or `--flow`, it validates tools, skills, memory stores, triggers, and MCP servers before you run anything. With `--quickstart`, it runs a real agent prompt to verify the entire stack end-to-end.

## Quick Start

```bash
# Check provider configuration
initrunner doctor

# Full end-to-end smoke test (makes a real API call)
initrunner doctor --quickstart

# Test a specific role file (static checks)
initrunner doctor --role role.yaml

# Active checks: connect to MCP servers, import custom tools, open memory DBs
initrunner doctor --role role.yaml --deep

# Validate a flow and all its agent roles
initrunner doctor --flow flow.yaml

# Auto-fix: install missing SDKs, missing role extras, bump spec_version
initrunner doctor --fix --role role.yaml

# Non-interactive (CI) -- auto-confirm all fix prompts
initrunner doctor --fix --yes --role role.yaml
```

## CLI Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--quickstart` | `bool` | `false` | Run a smoke prompt to verify end-to-end connectivity. |
| `--role` | `Path` | -- | Role file to test. Used for `.env` loading and as the agent for `--quickstart`. |
| `--flow` | `Path` | -- | Flow YAML file to validate. Checks flow topology and runs diagnostics on all referenced roles. |
| `--deep` | `bool` | `false` | Run active checks (MCP connectivity, tool imports, DB open). Requires `--role` or `--flow`. |
| `--skill-dir` | `Path` | -- | Extra skill search directory. Requires `--role` or `--flow`. |
| `--fix` | `bool` | `false` | Interactively repair detected issues (missing SDKs, extras, stale spec_version). |
| `--yes` / `-y` | `bool` | `false` | Auto-confirm all fix prompts. Required with `--fix` in non-interactive (piped) mode. |

### Flag interactions

- `--flow` is mutually exclusive with `--role`, `--quickstart`, and `--fix`.
- `--deep` and `--skill-dir` require `--role` or `--flow`.

## Config Scan

The config scan runs automatically on every `doctor` invocation. It checks:

| Check | What it verifies |
|-------|------------------|
| **API Key** | Whether the provider's environment variable is set (e.g. `OPENAI_API_KEY`) |
| **SDK** | Whether the provider's Python SDK is importable (only checked when key is set) |
| **Ollama** | Whether the Ollama server is reachable at `localhost:11434` |

Example output:

```
               Provider Status
┏━━━━━━━━━━━┳━━━━━━━━━┳━━━━━┳━━━━━━━━━━━━━━━━┓
┃ Provider  ┃ API Key ┃ SDK ┃ Status         ┃
┡━━━━━━━━━━━╇━━━━━━━━━╇━━━━━╇━━━━━━━━━━━━━━━━┩
│ openai    │ Set     │ OK  │ Ready          │
│ anthropic │ Missing │ —   │ Not configured │
│ google    │ Missing │ —   │ Not configured │
│ groq      │ Missing │ —   │ Not configured │
│ mistral   │ Missing │ —   │ Not configured │
│ cohere    │ Missing │ —   │ Not configured │
│ ollama    │ —       │ —   │ Ready          │
└───────────┴─────────┴─────┴────────────────┘
```

The scan loads `.env` files before checking, so keys defined in `.env` files (project-local or `~/.initrunner/.env`) are detected. If `--role` is provided, the `.env` in the role's directory is loaded first.

## Embedding Providers

After the provider table, `doctor` shows an **Embedding Providers** section that checks whether the API keys needed for embeddings (RAG and memory) are configured. This is separate from the LLM provider table because embedding keys can differ from LLM keys.

| Check | What it verifies |
|-------|------------------|
| **Embedding Key Env** | The environment variable name used for embedding API keys for each provider |
| **Status** | Whether the embedding key is set (`Set`), missing (`Missing`), or not needed (`No key needed` for Ollama) |

Example output:

```
               Embedding Providers
┏━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┓
┃ Provider  ┃ Embedding Key Env ┃ Status        ┃
┡━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━┩
│ openai    │ OPENAI_API_KEY    │ Set           │
│ anthropic │ OPENAI_API_KEY    │ Set           │
│ google    │ GOOGLE_API_KEY    │ Missing       │
│ ollama    │ —                 │ No key needed │
└───────────┴───────────────────┴───────────────┘
Note: Anthropic uses OpenAI embeddings (OPENAI_API_KEY) for RAG/memory.
```

> **Important:** Anthropic does not offer an embeddings API. If your agent uses `provider: anthropic` with RAG or memory, you need `OPENAI_API_KEY` set for embeddings — even though `ANTHROPIC_API_KEY` handles the LLM. The doctor output makes this explicit.

## Role Validation

When `--role` is provided, `doctor` runs schema and deprecation checks on the role file before the quickstart smoke test. This catches common issues like removed fields, invalid YAML, and schema errors.

> The same YAML schema checks also run automatically as a pre-flight before every `initrunner run`, `flow up`, and `flow install` -- see [Pre-flight YAML validation](../getting-started/cli.md#pre-flight-yaml-validation). `doctor` is the right tool when you want the deprecation rule table and spec-version drift report; the run pre-flight is the right tool when you just want to know whether your edited role will start.

```bash
initrunner doctor --role role.yaml
```

The validation checks:

| Check | What it verifies |
|-------|------------------|
| **YAML parse** | Whether the file is valid YAML |
| **Deprecation rules** | Whether the role uses removed or renamed fields (see [Deprecations](deprecations.md)) |
| **Schema validation** | Whether the role validates against the current RoleDefinition schema |
| **spec_version** | Whether the role's spec_version is current, stale, or unsupported |

If any error-severity issues are found, the command exits with code 1. When combined with `--quickstart`, role errors block the smoke test from running.

Example output with deprecation errors:

```
       Role Validation: my-agent (spec_version: 1, current: 2)
┏━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ ID     ┃ Severity ┃ Issue                                     ┃ Status     ┃
┡━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ DEP002 │ error    │ store_backend 'zvec' has been removed...  │ manual fix │
└────────┴──────────┴───────────────────────────────────────────┴────────────┘
```

## Security Posture Check

When `--role` is provided and the role parses successfully, doctor checks the security posture:

- **External triggers without security config**: Agents with webhook, telegram, or discord triggers but no `security.preset` (or custom security policy) trigger a warning. Internal triggers (cron, file_watch, heartbeat) do not.
- **Development preset with external triggers**: Warns that rate limits and content filtering are relaxed.
- **initguard status**: Notes whether `INITRUNNER_POLICY_DIR` is configured for agent-level policy enforcement.

```
Role is valid and up to date.
  Warning: Security policy is at defaults. Consider adding security: {preset: public}
  for agents with external triggers.
```

Fix: add a security preset to your role YAML:

```yaml
security:
  preset: public
```

See [Security Presets](../security/security.md#security-presets) for preset details and override syntax.

## Role Diagnostics

When `--role` is provided and the role parses successfully, doctor runs extended diagnostics on the role's runtime dependencies. These checks catch problems that schema validation alone cannot detect.

### Static checks (default)

These run automatically with `--role` and have no side effects:

| Category | What it checks |
|----------|----------------|
| **Skills** | Resolves each skill reference (role-local, `INITRUNNER_SKILL_DIR`, `~/.initrunner/skills`). Reports unmet environment variable and binary requirements. |
| **Custom tools** | Runs `importlib.util.find_spec()` to verify the module is locatable. Validates imports against sandbox policy via AST analysis. Adds `role_dir` to `sys.path` to match runtime behavior. |
| **Memory store** | Resolves the store path and checks the parent directory exists and is writable. A missing store is reported as info (runtime creates it on first use). |
| **Triggers** | Validates cron expressions (via `croniter`), checks timezone validity, verifies file_watch/heartbeat paths exist (CWD-relative, matching runtime), checks Telegram/Discord token env vars are set. |
| **MCP servers** | Listed as "skipped" in static mode (connection requires spawning processes). |

### Active checks (`--deep`)

With `--deep`, doctor additionally performs checks that spawn processes, open connections, or execute code:

| Category | What it checks |
|----------|----------------|
| **MCP servers** | Connects to each MCP server via `fastmcp.Client`, lists available tools, measures latency. Reports healthy (<3s), degraded (3-5s), or unhealthy (timeout/error). Servers with `defer: true` are skipped. |
| **Custom tools** | Full `importlib.import_module()` plus function discovery. Verifies `function` exists if specified, or that auto-discovery finds public callables. |
| **Memory store** | Opens the LanceDB database via the store factory and closes immediately. Confirms the DB is not corrupt. |

Example output:

```
                            Role Diagnostics
┏━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Category    ┃ Component                     ┃ Status ┃ Details            ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ mcp         │ mcp: stdio initrunner-brows.. │ ok     │ 565ms, 12 tools    │
│ skill       │ ./skills/structured-extract.. │ ok     │ /path/to/SKILL.md  │
│ memory      │ ~/.initrunner/memory/agent..  │ ok     │ accessible         │
│ trigger     │ heartbeat                     │ warn   │ Checklist file ... │
└─────────────┴───────────────────────────────┴────────┴────────────────────┘
```

## Flow Validation

With `--flow`, doctor validates a flow definition and all its referenced agent roles:

```bash
initrunner doctor --flow flow.yaml
initrunner doctor --flow flow.yaml --deep
```

**What it checks:**

1. **Flow structure**: Parses the flow YAML, validates agent references, checks for dependency and delegation cycles (via `validate_yaml_file()`).
2. **Role file existence**: Verifies each agent's role file exists relative to the flow file directory.
3. **Recursive role validation**: Runs schema and deprecation checks on each referenced role.
4. **Per-agent diagnostics**: Runs the same Role Diagnostics checks (skills, tools, memory, triggers, MCP) on each agent's role.

Example output:

```
Flow structure is valid.

Agent: content-watcher
                            Role Diagnostics
┏━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Category ┃ Component  ┃ Status ┃ Details                              ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ trigger  │ file_watch │ warn   │ Watch path does not exist: ./drafts/ │
└──────────┴────────────┴────────┴──────────────────────────────────────┘

Agent: researcher
  (no issues)
```

## Quickstart Smoke Test

With `--quickstart`, the doctor runs a real agent prompt after the config scan:

```bash
initrunner doctor --quickstart
```

**What it does:**

1. Detects the available provider (or uses the one from `--role`)
2. Builds a minimal agent (or loads the role file if `--role` is given)
3. Sends a single prompt: "Say hello in one sentence."
4. Reports success or failure with response preview, token count, and duration

**On success:**

```
╭───────────────────────────── Quickstart Result ──────────────────────────────╮
│ Smoke test passed!                                                           │
│                                                                              │
│ Response: Hello!                                                             │
│ Tokens: 97 | Duration: 2229ms                                                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

**On failure**, the error is displayed and the command exits with code 1:

```
╭───────────────────────────── Quickstart Result ──────────────────────────────╮
│ Smoke test failed: Model API error: 401 Unauthorized                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### Testing a specific role

Use `--role` to test a specific role file. This loads the role's `.env`, builds the role's agent (with its model, tools, and system prompt), and runs the smoke prompt against it.

```bash
initrunner doctor --quickstart --role examples/roles/code-reviewer.yaml
```

This is useful for verifying that a role's provider, model, and SDK configuration work before deploying it.

## Auto-Fix (`--fix`)

With `--fix`, doctor offers to repair the issues it finds. Each fix is prompted interactively (or auto-confirmed with `--yes`).

### What `--fix` repairs

| Issue | Fix | Requires `--role`? |
|-------|-----|--------------------|
| Provider SDK missing (key is set) | `install_extra()` installs the pip extra | No |
| Missing API key | Prompts to enter and persist to `~/.initrunner/.env` | Interactive only (skipped with `--yes`) |
| Role tools/triggers need uninstalled extras | Installs the matching extras (e.g. `initrunner[search]`) | Yes |
| `spec_version` behind current | Bumps and writes the YAML file | Yes |

### What `--fix` does NOT repair

- **Deprecated fields** (e.g. `store_backend: zvec`): these remain diagnostic-only until explicit migration rules exist.
- **Schema errors**: structural issues in the role YAML require manual editing.

### Targeted API key repair

When `--fix` runs interactively (no `--yes`):

- With `--role`: derives the target provider from `spec.model.provider` and prompts for that key only.
- Without `--role`: if exactly one provider needs a key, targets it automatically. If multiple need keys, asks you to choose.

With `--yes`, API key repair is skipped (keys require interactive secret input).

### Example

```bash
$ initrunner doctor --fix --yes --role role.yaml

# Output:
# Installed initrunner[anthropic]
# ...
# ╭──── Fixed ────╮
# │  Installed initrunner[anthropic]  │
# │  Bumped spec_version to 2         │
# ╰──────────────╯
```

## Dashboard API

The dashboard exposes per-agent doctor diagnostics via the agents API:

```
GET /api/agents/{agent_id}/doctor?deep=false
```

Returns an `AgentDoctorResponse` with `role_checks` -- a flat list of check results in the same format as the system doctor endpoint. The `agent_id` is the RoleCache's opaque hex ID (same IDs used by all other agent endpoints).

## Use Cases

- **First-time setup**: Run `initrunner doctor` after `initrunner setup` to verify everything is configured.
- **Pre-deploy validation**: `initrunner doctor --role role.yaml --deep` catches MCP connectivity issues, missing tool modules, and corrupt memory stores before you deploy.
- **Flow pre-flight**: `initrunner doctor --flow flow.yaml` validates topology, cycles, and all referenced roles in one command.
- **CI/CD validation**: Add `initrunner doctor --fix --yes --role role.yaml` to your CI pipeline to auto-install missing extras.
- **Debugging**: When a role fails at runtime, `doctor --role role.yaml` quickly shows whether the issue is a missing skill, unavailable trigger, or unreachable MCP server.
- **Multi-provider environments**: See at a glance which providers are configured and ready.

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Config scan passed (without `--quickstart`), or smoke test passed |
| `1` | Smoke test failed, error-level role/flow issues found, flag interaction errors, or `--fix` without `--yes` in non-interactive mode |
