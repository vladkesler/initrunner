# Cerbos Policy Sets

Curated policy sets for InitRunner authorization. Each directory is a self-contained set of Cerbos policies that can be mounted directly into the Cerbos PDP container.

## Policy Sets

### `strict/` -- Production, External-Facing

Locked-down policies for production environments exposed to external users.

- **Admin**: full access to all resources and tools
- **Operator**: read all agents; execute only own agents (via `agent_owner` derived role); read-only ingest and memory; no daemon control
- **Viewer/Anonymous**: denied
- **Tools**: admin gets all tools; operator gets datetime, search, web_reader, filesystem; explicit DENY on shell, python, script for non-admin

### `permissive/` -- Development, Internal/Trusted

Relaxed policies for development or internal environments where users are trusted.

- **Admin**: full access
- **Operator**: read, write, execute agents; read/write memory; all tools except shell/python
- **Viewer**: read and execute agents; safe tools
- **Anonymous**: read and execute agents; safe tools
- **Audit**: readable by admin, auditor, operator, and viewer

### `team/` -- Multi-Team Organizations

Team-aware policies using derived roles for cross-team isolation.

- **Admin**: full access everywhere
- **team_admin**: admin + matching team, gets write on team agents
- **agent_owner**: read, write, execute own agents
- **team_member**: read and execute team agents; read team memory/ingest
- **Operator**: read all agents
- **Tools**: team members get operator-tier access (all except shell/python)

## Usage

### With Docker Compose

```bash
docker compose -f docker-compose.cerbos.yml up
```

The compose file mounts `permissive/` by default. Edit the Cerbos volume to switch:

```yaml
volumes:
  - ./examples/policies/strict:/policies
```

### Standalone Cerbos

```bash
docker run --rm -p 3592:3592 \
  -v ./examples/policies/strict:/policies \
  ghcr.io/cerbos/cerbos:latest
```

## Customization

Copy a policy set directory and modify it. Each set contains:

| File | Description |
|------|-------------|
| `derived_roles.yaml` | Derived roles (agent_owner, team_member, team_admin) |
| `agent_policy.yaml` | Agent read/write/execute access |
| `audit_policy.yaml` | Audit log read access |
| `daemon_policy.yaml` | Daemon start/stop access |
| `ingest_policy.yaml` | Ingestion pipeline access |
| `memory_policy.yaml` | Memory store access |
| `tool_policy.yaml` | Per-tool execution access |

See the [Cerbos Authorization docs](../../docs/security/cerbos.md) for the full configuration reference.
