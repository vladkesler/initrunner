# Agent Policy Engine (Cerbos)

InitRunner uses [Cerbos](https://cerbos.dev) as an **agent-as-principal** policy engine. Agents get their own Cerbos identity derived from role metadata, and Cerbos governs what tools an agent can use and which agents it can delegate to -- across all execution paths (CLI, compose, daemon, API, pipeline).

## Quick Start

```bash
# Start Cerbos PDP with agent policies
docker compose -f docker-compose.cerbos.yml up -d

# Enable agent policy checks
export INITRUNNER_CERBOS_ENABLED=true
export INITRUNNER_CERBOS_AGENT_CHECKS=true

# Run an agent -- Cerbos now enforces tool and delegation policies
initrunner run my-agent.yaml "do something"
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `INITRUNNER_CERBOS_ENABLED` | `false` | Enable Cerbos integration |
| `INITRUNNER_CERBOS_HOST` | `127.0.0.1` | PDP hostname |
| `INITRUNNER_CERBOS_PORT` | `3592` | PDP HTTP port |
| `INITRUNNER_CERBOS_TLS` | `false` | Use HTTPS for PDP connection |
| `INITRUNNER_CERBOS_AGENT_CHECKS` | `false` | Enable agent-level policy enforcement |

Both `INITRUNNER_CERBOS_ENABLED` and `INITRUNNER_CERBOS_AGENT_CHECKS` must be `true` for policy checks to activate.

## How Agent Principals Are Constructed

Every agent run constructs a Cerbos principal from `role.yaml` metadata:

```yaml
# role.yaml
metadata:
  name: code-reviewer
  team: platform
  author: alice
  tags: [trusted, code]
  version: "1.0"
```

Produces a Cerbos principal:

| Field | Value |
|-------|-------|
| **ID** | `agent:code-reviewer` |
| **Roles** | `["agent", "team:platform"]` |
| **Attributes** | `{team: "platform", author: "alice", tags: ["trusted", "code"], version: "1.0"}` |

The `team:<name>` role is only added when `metadata.team` is set. The `tags` attribute is a native list (not CSV), which allows Cerbos CEL expressions like `request.principal.attr.tags.exists(t, t == "trusted")`.

## Agent Principal Scoping

The agent principal is set per-run via a ContextVar in the executor:

- **CLI/daemon**: `_enter_agent_context(role)` is called at the top of `execute_run()` / `execute_run_stream()` / `execute_run_async()` / `execute_run_stream_async()`, and reset in `finally`.
- **Compose**: Each service's agent run goes through the executor, so the principal is automatically scoped.
- **Pipeline**: Inline steps go through the executor. MCP steps construct a lightweight `Metadata` from the step name.

The `CerbosAuthz` instance is cached once per process (the PDP connection is stable). Only the agent principal ContextVar changes per run.

## Delegation Policy

Delegation policy checks happen at two levels:

### Inline Delegation (full metadata)

When an agent delegates to another agent via `InlineInvoker`, the target role is loaded first. The policy check uses full metadata from both source and target:

- **Source principal**: constructed from the delegating agent's `role.metadata`
- **Resource**: `kind=agent`, `id=<target_name>`, `attrs={team, author, tags}`
- **Action**: `delegate`

### MCP Remote Delegation (name-only)

When an agent delegates to a remote agent via `McpInvoker`, only the target agent's name is known (no role YAML to load). The policy check uses:

- **Source principal**: constructed from the delegating agent's `role.metadata`
- **Resource**: `kind=agent`, `id=<target_name>`, `attrs={}` (empty)
- **Action**: `delegate`

This is an explicit limitation: remote delegation policy can only match on the target name, not on team/tags/author.

### Compose Delegation

`DelegateSink` routes agent output between compose services. The policy check uses **role metadata** (from loaded role YAML), not the compose service key. This matters when compose service keys differ from role names (e.g., compose service `code-reviewer` vs role name `reviewer`).

## Agent Tool Policy

The `CerbosToolset` wraps every toolset and checks whether the current agent principal is allowed to execute a given tool:

- **Principal**: from `get_current_agent_principal()` ContextVar
- **Resource**: `kind=tool`, `id=<tool_function_name>`, `attrs={tool_type, agent, callable, instance}`
- **Action**: `execute`

When `agent_checks_enabled` is `false` or no agent principal is set, the check is a no-op (allow-all).

## Example Policies

See `examples/policies/agent/` for a complete policy set:

### Derived Roles (`derived_roles.yaml`)

```yaml
- name: trusted_agent
  parentRoles: ["agent"]
  condition:
    match:
      expr: request.principal.attr.tags.exists(t, t == "trusted")

- name: same_team
  parentRoles: ["agent"]
  condition:
    match:
      all:
        of:
          - expr: request.principal.attr.team != ""
          - expr: request.principal.attr.team == request.resource.attr.team
```

### Delegation Policy (`agent_delegation_policy.yaml`)

- **Trusted agents** can delegate to any agent
- **Same-team agents** can delegate to each other
- Delegation to **privileged-tagged** agents is denied (unless the source is trusted)

### Tool Policy (`agent_tool_policy.yaml`)

- All agents can use safe tool types (datetime, search, web_reader, http, etc.)
- **Trusted agents** can use all tools including shell and python
- Non-trusted agents are **denied** shell and python tools

## PDP Health Check

When Cerbos is enabled, the executor performs a one-time health check on first run. If the PDP is unreachable:

- A warning is logged
- Agent policy checks are disabled (allow-all fallback)
- The process is **not** crashed (CLI/daemon should not abort at import time)

## Audit Integration

The `principal_id` field in audit records tracks trigger source identity (e.g., `telegram:12345`, `webhook:github`). This is independent of Cerbos agent principals and is preserved across all execution paths.

Delegation policy denials in compose are logged as `policy_denied` audit events via the `DelegateSink` audit buffer.

## Docker Compose

```bash
docker compose -f docker-compose.cerbos.yml up
```

The compose file:
- Mounts `examples/policies/agent/` into the Cerbos PDP
- Sets `INITRUNNER_CERBOS_ENABLED=true` and `INITRUNNER_CERBOS_AGENT_CHECKS=true`
- Waits for Cerbos health check before starting InitRunner
