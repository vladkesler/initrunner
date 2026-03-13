# Cerbos Authorization

InitRunner integrates with [Cerbos](https://github.com/cerbos/cerbos), an
open-source policy decision point (PDP) for attribute-based access control
(ABAC). When enabled, every dashboard and API request is checked against
Cerbos policies before the route handler runs.

Cerbos authorization is **strictly opt-in**. When disabled (the default),
InitRunner behaves exactly as before: a single shared API key authenticates
all requests with no identity or role distinctions.

## Prerequisites

1. **Cerbos PDP** running as a sidecar or standalone service.
2. **Python extras** installed:

```bash
pip install initrunner[authz]
# or
uv pip install initrunner[authz]
```

This pulls in the `cerbos` Python SDK and `PyJWT`.

## Quick Start with Docker

```bash
# 1. Write a minimal policy (see Policy Authoring below)
mkdir -p policies

# 2. Start Cerbos
docker run --rm -p 3592:3592 -v ./policies:/policies ghcr.io/cerbos/cerbos:latest

# 3. Enable authorization
export INITRUNNER_CERBOS_ENABLED=true
export INITRUNNER_JWT_SECRET=my-secret-key

# 4. Start the dashboard
initrunner ui
```

On startup the dashboard verifies connectivity to the Cerbos PDP. If the
PDP is unreachable, InitRunner exits immediately with a troubleshooting
message.

## Configuration

All configuration is via environment variables. Authorization config is
**global** (app-level), never stored in role YAML files.

| Variable | Default | Description |
|----------|---------|-------------|
| `INITRUNNER_CERBOS_ENABLED` | `false` | Set to `true`, `1`, or `yes` to enable. |
| `INITRUNNER_CERBOS_HOST` | `127.0.0.1` | Cerbos PDP hostname or IP. |
| `INITRUNNER_CERBOS_PORT` | `3592` | Cerbos HTTP port. |
| `INITRUNNER_CERBOS_TLS` | `false` | Enable TLS for the HTTP connection. |
| `INITRUNNER_JWT_SECRET` | *(empty)* | Shared secret for HS256 JWT validation. |
| `INITRUNNER_JWT_ALGORITHM` | `HS256` | JWT signing algorithm. |
| `INITRUNNER_CERBOS_ANONYMOUS_ROLES` | `anonymous` | Comma-separated roles for API-key-only requests. |

## Identity Model

InitRunner supports two identity transport mechanisms within a single
`Authorization: Bearer` header:

### JWT Tokens (recommended)

When a Bearer token has three dot-separated segments (the JWT format), it is
decoded and validated as a JWT. The following claims are extracted:

| Claim | Required | Description |
|-------|----------|-------------|
| `sub` | Yes | Principal ID (unique user identifier). |
| `roles` | No | List of role strings (defaults to `["user"]`). |
| `attrs` | No | Dict of arbitrary attributes for policy conditions. |

Example JWT payload:

```json
{
  "sub": "alice",
  "roles": ["admin", "operator"],
  "attrs": {"team": "platform"}
}
```

### Plain API Key (backward compatible)

When the Bearer token is a plain API key (not a JWT), it is validated via
the existing timing-safe HMAC comparison. If authorization is enabled, the
request receives an **anonymous principal** with the roles defined by
`INITRUNNER_CERBOS_ANONYMOUS_ROLES` (default: `["anonymous"]`).

This means existing API-key-only setups continue to work. To restrict what
anonymous users can do, write Cerbos policies that limit the `anonymous`
role.

## Resource Model

InitRunner maps its API surface to Cerbos resources:

| Resource Kind | Description | Actions |
|---------------|-------------|---------|
| `agent` | Agent roles (list, view, run, edit) | `read`, `write`, `execute` |
| `memory` | Per-agent memory stores | `read`, `write`, `delete` |
| `audit` | Audit log records | `read` |
| `ingest` | Document ingestion | `read`, `execute` |
| `daemon` | Daemon processes | `execute`, `write` |
| `tool` | Tool calls within agent runs | `execute` |

The `resource_id` is typically the role ID (a hash of the role file path)
for per-agent resources, or `*` for collection-level actions like listing.

## Policy Authoring

Cerbos policies are YAML files placed in a directory mounted into the Cerbos
container. See the [Cerbos policy documentation](https://docs.cerbos.dev/cerbos/latest/policies/)
for the full reference.

### Example: Agent Access Policy

```yaml
# policies/agent_policy.yaml
apiVersion: api.cerbos.dev/v1
resourcePolicy:
  version: default
  resource: "agent"
  rules:
    # Admins can do everything
    - actions: ["read", "write", "execute"]
      roles: ["admin"]
      effect: EFFECT_ALLOW

    # Operators can read and run agents
    - actions: ["read", "execute"]
      roles: ["operator"]
      effect: EFFECT_ALLOW

    # Viewers can only read
    - actions: ["read"]
      roles: ["viewer"]
      effect: EFFECT_ALLOW

    # Anonymous users (API-key auth) get read-only
    - actions: ["read"]
      roles: ["anonymous"]
      effect: EFFECT_ALLOW
```

### Example: Audit Log Policy

```yaml
# policies/audit_policy.yaml
apiVersion: api.cerbos.dev/v1
resourcePolicy:
  version: default
  resource: "audit"
  rules:
    - actions: ["read"]
      roles: ["admin", "auditor"]
      effect: EFFECT_ALLOW
```

### Example: Memory Access Policy

```yaml
# policies/memory_policy.yaml
apiVersion: api.cerbos.dev/v1
resourcePolicy:
  version: default
  resource: "memory"
  rules:
    - actions: ["read", "write", "delete"]
      roles: ["admin"]
      effect: EFFECT_ALLOW
    - actions: ["read"]
      roles: ["operator", "viewer"]
      effect: EFFECT_ALLOW
```

### Derived Roles

Cerbos derived roles augment static roles with runtime context. For example,
grant elevated access to agents a user owns:

```yaml
# policies/derived_roles.yaml
apiVersion: api.cerbos.dev/v1
derivedRoles:
  name: initrunner_roles
  definitions:
    - name: agent_owner
      parentRoles: ["operator"]
      condition:
        match:
          expr: request.resource.attr.author == request.principal.id
```

## PlanResources (List Filtering)

For list endpoints like `GET /api/roles`, InitRunner uses the Cerbos
`PlanResources` API to determine which resources to include in the response.
This avoids checking each resource individually:

- **ALWAYS_ALLOWED**: Return all resources (no filtering).
- **ALWAYS_DENIED**: Return an empty list.
- **CONDITIONAL**: Evaluate the Cerbos condition AST against each resource's
  attributes to filter the list.

This happens transparently. No configuration is needed.

## Audit Trail

When authorization is enabled, every audit log record includes the
`principal_id` of the user who triggered the run. This enables:

- Filtering audit logs by user: `GET /api/audit?principal_id=alice`
- Tracing actions to identities in security events
- Compliance reporting

Trigger-based runs (Telegram, Discord, webhooks) also record the platform
user identity (e.g., `telegram:12345`, `discord:67890`).

## Route Authorization Matrix

Every dashboard and API endpoint is protected by a `requires()` dependency
that checks Cerbos before the handler executes:

| Endpoint | Resource | Action |
|----------|----------|--------|
| `GET /api/roles` | `agent` | `read` |
| `GET /api/roles/{role_id}` | `agent` | `read` |
| `POST /api/roles` | `agent` | `write` |
| `POST /api/roles/validate` | `agent` | `read` |
| `POST /api/roles/generate` | `agent` | `write` |
| `PUT /api/roles/{role_id}` | `agent` | `write` |
| `GET /roles/{role_id}/chat` | `agent` | `execute` |
| `GET /roles/{role_id}/chat/stream` | `agent` | `execute` |
| `GET /chat` | `agent` | `execute` |
| `GET /chat/stream` | `agent` | `execute` |
| `GET /api/audit` | `audit` | `read` |
| `POST /api/ingest/{role_id}` | `ingest` | `execute` |
| `GET /api/ingest/{role_id}/sources` | `ingest` | `read` |
| `GET /api/memories/{role_id}` | `memory` | `read` |
| `DELETE /api/memories/{role_id}` | `memory` | `delete` |
| `POST /api/daemon/{role_id}/start` | `daemon` | `execute` |
| `POST /api/daemon/{role_id}/stop` | `daemon` | `write` |

## Tool-Level Authorization

When enabled, Cerbos can authorize individual tool calls within agent runs.
This complements route-level checks (which gate access to endpoints) with
per-tool identity-based authorization (which controls what the agent can do
on behalf of a given user).

### How It Works

Agents are built once and cached, so toolsets are wired at build time.
Per-request identity is carried into tool calls via two `contextvars.ContextVar`s
(principal and authz) that are set by the dashboard/API call site before
each agent run. A `CerbosToolset` wrapper reads them at call time and checks
the Cerbos PDP.

The existing fnmatch tool permissions (`tools.permissions` in role YAML)
continue to work unchanged. When both are configured, fnmatch rules
(local, cheap) are evaluated first and short-circuit before the Cerbos PDP
call:

```
PydanticAI -> PermissionToolset (fnmatch, local) -> CerbosToolset (Cerbos PDP) -> actual tool
```

### Configuration

Tool-level Cerbos checks are **opt-in** via environment variable:

| Variable | Default | Description |
|----------|---------|-------------|
| `INITRUNNER_CERBOS_TOOL_CHECKS` | `false` | Set to `true`, `1`, or `yes` to enable tool-level Cerbos checks. |

This is separate from `INITRUNNER_CERBOS_ENABLED` (which enables
route-level checks). You must have Cerbos enabled and a `tool` resource
policy deployed before activating tool-level checks, otherwise Cerbos will
DENY all tool calls.

### Resource Model

Tool calls use the `tool` resource kind with the `execute` action:

| Field | Value | Description |
|-------|-------|-------------|
| `resource_kind` | `tool` | Fixed for all tool calls. |
| `resource_id` | callable name | e.g. `get_repo`, `run_shell`, `delegate_to_writer` |
| `action` | `execute` | Fixed for all tool calls. |

Resource attributes provide granular matching:

| Attribute | Description | Example |
|-----------|-------------|---------|
| `tool_type` | Tool type from role YAML | `shell`, `api`, `search`, `python` |
| `agent` | Agent name from role metadata | `research-assistant` |
| `callable` | Function name (same as resource_id) | `run_shell` |
| `instance` | Multi-instance key (API tools only) | `internal-api` |

### Example Policy

```yaml
# policies/tool_policy.yaml
apiVersion: api.cerbos.dev/v1
resourcePolicy:
  version: default
  resource: "tool"
  rules:
    # Admins can use all tools
    - actions: ["execute"]
      roles: ["admin"]
      effect: EFFECT_ALLOW

    # Operators can use all tools except shell and python
    - actions: ["execute"]
      roles: ["operator"]
      effect: EFFECT_ALLOW
      condition:
        match:
          expr: !(request.resource.attr.tool_type in ["shell", "python"])

    # Anonymous users (API-key auth) get safe tools only
    - actions: ["execute"]
      roles: ["anonymous"]
      effect: EFFECT_ALLOW
      condition:
        match:
          expr: request.resource.attr.tool_type in ["datetime", "search", "web_reader"]
```

See `examples/policies/tool_policy.yaml` for a complete example with
instance-level blocking.

### Exemptions

- **CLI and trigger paths**: When no principal ContextVar is set (CLI runs,
  cron/file triggers), tool-level checks are skipped. Only HTTP-originated
  runs (dashboard, API server) set a principal.
- **Reflection and scheduling toolsets**: Internal control-flow tools
  (`finish_task`, `update_plan`, `schedule_followup`) are exempt. A Cerbos
  deny on these would break the autonomous loop.

## Troubleshooting

### "Cerbos authorization is enabled but PDP is unreachable"

This error appears at startup when the health check fails.

1. Verify Cerbos is running: `docker ps | grep cerbos`
2. Check the host/port: `curl http://localhost:3592/api/health`
3. Ensure the HTTP port (default 3592) is exposed
4. If using TLS, verify certificates match

### "Cerbos requires: pip install initrunner[authz]"

The `cerbos` and `PyJWT` packages are not installed. Install them:

```bash
pip install initrunner[authz]
```

### JWT validation fails

- Verify `INITRUNNER_JWT_SECRET` matches the secret used to sign tokens
- Check the algorithm matches (`INITRUNNER_JWT_ALGORITHM`, default HS256)
- Ensure the JWT has a `sub` claim
- Check token expiration (`exp` claim)

### 403 Access Denied

- Check which roles the principal has (from the JWT `roles` claim)
- Review your Cerbos policies to ensure the role has the required action
- Use the Cerbos admin API or logs to debug policy evaluation

## Docker Compose

The repository includes a self-contained Docker Compose file that runs InitRunner alongside a Cerbos PDP:

```bash
docker compose -f docker-compose.cerbos.yml up
```

By default the compose file mounts the `examples/policies/permissive/` policy set. To switch to a different set, edit the Cerbos volume mount:

```yaml
# strict (production, external-facing)
- ./examples/policies/strict:/policies

# team (multi-team organizations)
- ./examples/policies/team:/policies
```

See `examples/policies/README.md` for a description of each curated policy set.
