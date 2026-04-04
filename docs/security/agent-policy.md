# Agent Policy Engine

InitRunner uses [initguard](https://github.com/initrunner/initguard) as an embedded **agent-as-principal** policy engine. Agents get their own identity derived from role metadata, and the engine governs what tools an agent can use and which agents it can delegate to -- across all execution paths (CLI, flow, daemon, API, pipeline).

The engine runs in-process with no sidecar, no network round-trips, and sub-millisecond policy evaluation.

## Quick Start

```bash
# Point to your policy directory
export INITRUNNER_POLICY_DIR=./policies

# Run an agent -- policies now enforce tool and delegation rules
initrunner run my-agent.yaml "do something"
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `INITRUNNER_POLICY_DIR` | *(unset)* | Path to policy YAML directory. If unset, policy enforcement is disabled. |
| `INITRUNNER_AGENT_CHECKS` | `true` | Enable per-agent tool and delegation checks. |

When `INITRUNNER_POLICY_DIR` is set, policies **must** load successfully or the first run fails (fail-fast). There is no allow-all fallback when the operator has explicitly opted into policy enforcement.

## How Agent Principals Are Constructed

Every agent run constructs a principal from `role.yaml` metadata:

```yaml
# role.yaml
metadata:
  name: code-reviewer
  team: platform
  author: alice
  tags: [trusted, code]
  version: "1.0"
```

Produces a principal:

| Field | Value |
|-------|-------|
| **ID** | `agent:code-reviewer` |
| **Roles** | `["agent", "team:platform"]` |
| **Attributes** | `{team: "platform", author: "alice", tags: ["trusted", "code"], version: "1.0"}` |

The `team:<name>` role is only added when `metadata.team` is set. The `tags` attribute is a native list (not CSV), enabling CEL expressions like `request.principal.attr.tags.exists(t, t == "trusted")`.

## Agent Principal Scoping

The agent principal is set per-run via a ContextVar in the executor:

- **CLI/daemon**: `_enter_agent_context(role)` is called at the top of `execute_run()` / `execute_run_stream()` / `execute_run_async()` / `execute_run_stream_async()`, and reset in `finally`.
- **Flow**: Each agent's run goes through the executor, so the principal is automatically scoped.
- **Pipeline**: Inline steps go through the executor. MCP steps construct a lightweight `Metadata` from the step name.

The `PolicyEngine` instance is loaded once per process (immutable, thread-safe). Only the agent principal ContextVar changes per run.

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

### Flow Delegation

`DelegateSink` routes agent output between flow agents. The policy check uses **role metadata** (from loaded role YAML), not the flow agent key.

## Agent Tool Policy

The `PolicyToolset` wraps every toolset and checks whether the current agent principal is allowed to execute a given tool:

- **Principal**: from `get_current_agent_principal()` ContextVar
- **Resource**: `kind=tool`, `id=<tool_function_name>`, `attrs={tool_type, agent, callable, instance}`
- **Action**: `execute`

When `agent_checks` is disabled or no agent principal is set, the check is a no-op (allow-all).

Policy denials return a `Decision` with `reason` and optional `advice`, which are surfaced in the tool's permission-denied message.

## Example Policies

See `examples/policies/agent/` for a complete policy set:

### Schema (`schema.yaml`)

Defines expected attributes for principals and resources. Used for lint validation at load time.

### Derived Roles (`derived_roles.yaml`)

```yaml
- name: trusted_agent
  parentRoles: ["agent"]
  when: request.principal.attr.tags.exists(t, t == "trusted")

- name: same_team
  parentRoles: ["agent"]
  when: request.principal.attr.team != ""
  unless: request.principal.attr.team != request.resource.attr.team
```

### Delegation Policy (`delegation_policy.yaml`)

- **Trusted agents** can delegate to any agent
- **Same-team agents** can delegate to each other
- Delegation to **privileged-tagged** agents is denied (unless the source is trusted)

### Tool Policy (`tool_policy.yaml`)

- All agents can use safe tool types (datetime, search, web_reader, http, etc.)
- **Trusted agents** can use all tools including shell and python
- Non-trusted agents are **denied** shell and python tools

## Audit Integration

The `principal_id` field in audit records tracks trigger source identity (e.g., `telegram:12345`, `webhook:github`). This is independent of agent principals and is preserved across all execution paths.

Delegation policy denials in flow are logged as `policy_denied` audit events via the `DelegateSink` audit buffer.

## Docker

Mount the policy directory into your container:

```yaml
volumes:
  - ./policies:/data/policies
environment:
  - INITRUNNER_POLICY_DIR=/data/policies
```
