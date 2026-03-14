# Cerbos Agent Policy Set

Policy set for InitRunner's agent-as-principal policy engine. Agents get their own Cerbos identity derived from role metadata, and Cerbos governs what tools an agent can use and which agents it can delegate to.

## Policy Set

### `agent/` -- Agent-as-Principal Policies

Policies where agents are the principals. Agent identity is constructed from `role.yaml` metadata:

- **Principal ID**: `agent:<metadata.name>`
- **Roles**: `["agent"]` + `"team:<metadata.team>"` when team is set
- **Attributes**: `team`, `author`, `tags` (as list), `version`

#### Files

| File | Description |
|------|-------------|
| `derived_roles.yaml` | `trusted_agent` (tags contain "trusted"), `same_team` (matching team attr) |
| `agent_delegation_policy.yaml` | Same-team can delegate; trusted can delegate to anyone; deny delegation to "privileged"-tagged agents |
| `agent_tool_policy.yaml` | Agents get safe tools; trusted agents get everything; deny shell/python to non-trusted |

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

### With Docker Compose

```bash
docker compose -f docker-compose.cerbos.yml up
```

### Environment Variables

```bash
INITRUNNER_CERBOS_ENABLED=true        # Enable Cerbos integration
INITRUNNER_CERBOS_HOST=127.0.0.1      # PDP host
INITRUNNER_CERBOS_PORT=3592           # PDP port
INITRUNNER_CERBOS_AGENT_CHECKS=true   # Enable agent policy enforcement
```

### Standalone Cerbos

```bash
docker run --rm -p 3592:3592 \
  -v ./examples/policies/agent:/policies \
  ghcr.io/cerbos/cerbos:latest
```

## Customization

Copy the `agent/` directory and modify the policies. Agent principals are constructed automatically from role metadata -- no user configuration needed.

See the [Agent Policy docs](../../docs/security/agent-policy.md) for the full reference.
