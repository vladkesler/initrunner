# Agent Policy Set

Policy set for InitRunner's agent-as-principal policy engine powered by [initguard](https://github.com/initrunner/initguard). Agents get their own identity derived from role metadata, and the embedded policy engine governs what tools an agent can use and which agents it can delegate to.

## Policy Set

### `agent/` -- Agent-as-Principal Policies

Policies where agents are the principals. Agent identity is constructed from `role.yaml` metadata:

- **Principal ID**: `agent:<metadata.name>`
- **Roles**: `["agent"]` + `"team:<metadata.team>"` when team is set
- **Attributes**: `team`, `author`, `tags` (as list), `version`

#### Files

| File | Description |
|------|-------------|
| `schema.yaml` | Attribute definitions for principals and resources (lint validation) |
| `derived_roles.yaml` | `trusted_agent` (tags contain "trusted"), `same_team` (matching team attr) |
| `delegation_policy.yaml` | Same-team can delegate; trusted can delegate to anyone; deny delegation to "privileged"-tagged agents |
| `tool_policy.yaml` | Agents get safe tools; trusted agents get everything; deny shell/python to non-trusted |

#### Delegation Rules

- **Trusted agents** (tagged "trusted") can delegate to any agent
- **Same-team agents** can delegate to each other
- Delegation to **privileged-tagged** agents is denied unless the source is trusted
- MCP remote delegation uses **name-only** policy checks (no target metadata available)

#### Tool Rules

- All agents can use safe tool types (datetime, search, web_reader, http, retrieval, etc.)
- Trusted agents can use all tools including shell and python
- Non-trusted agents are denied shell and python tools

## Usage

```bash
export INITRUNNER_POLICY_DIR=./examples/policies/agent
export INITRUNNER_AGENT_CHECKS=true   # default: true when POLICY_DIR is set
initrunner run role.yaml
```

## Customization

Copy the `agent/` directory and modify the policies. Agent principals are constructed automatically from role metadata -- no user configuration needed.

See the [Agent Policy docs](../../docs/security/agent-policy.md) for the full reference.
