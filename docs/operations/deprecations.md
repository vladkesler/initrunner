# Deprecations & Schema Versioning

InitRunner uses a centralized deprecation system to manage removed or renamed configuration fields across role, flow, and team YAML schemas. When a field is deprecated, you get a clear error message pointing to the replacement instead of a cryptic validation failure.

## spec_version

Role YAML files include a `metadata.spec_version` field that tracks which schema version the file was written against.

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: my-agent
  spec_version: 2   # current version
  description: ...
```

**Behavior:**

| spec_version | Runtime | Doctor |
|---|---|---|
| Current (2) | Loads normally | "Valid and up to date" |
| Older (1) | Loads normally | Shows informational note |
| Future (>2) | Rejected with error | Rejected with error |

When you save or generate a role through InitRunner (builder, templates, `initrunner new`), `spec_version` is automatically set to the current version.

## Current Deprecation Rules

| ID | Applies to | Field | Error |
|---|---|---|---|
| DEP001 | Role | `spec.memory.max_memories` | Removed. Use `memory.semantic.max_memories` instead. |
| DEP002 | Role | `spec.ingest.store_backend: zvec` | zvec has been removed. Use `lancedb`. |
| DEP003 | Role | `spec.memory.store_backend: zvec` | zvec has been removed. Use `lancedb`. |
| DEP004 | Flow, Team | `spec.shared_memory.store_backend: zvec` | zvec has been removed. Use `lancedb`. |
| DEP005 | Flow, Team | `spec.shared_documents.store_backend: zvec` | zvec has been removed. Use `lancedb`. |

All current rules are error-severity with automatic migration. Run `initrunner doctor --fix --role <path>` to auto-patch deprecated fields with interactive confirmation. Use `--yes` to skip prompts.

## Checking Your Role

Three commands surface schema and deprecation problems, each tuned to a different workflow:

| Command | What it catches | When to use |
|---|---|---|
| `initrunner run <PATH>` | Syntax errors, schema errors, deprecation errors -- anything that would block the run. Renders a Rich panel with field paths, line numbers, and fix hints, then exits **before any API call** | Every run -- pre-flight is automatic |
| `initrunner validate <PATH>` | Same as the run pre-flight, plus warnings and info-level recommendations. On a clean role, also shows the configuration table | Auditing a role you just edited |
| `initrunner doctor --role <PATH>` | Deprecation rules table, spec version drift, and (with `--fix`) automatic migration | Upgrading roles between InitRunner releases |

Schema errors from the run pre-flight and `validate` show per-field paths
(e.g. `spec.model.provider`) thanks to the shared `unwrap_pydantic_error`
helper that follows Pydantic's `ValidationError` through the deprecation
wrapper. Deprecation rule failures (DEP001..DEP005) appear with `field:
deprecation`.

Run `doctor --role` for the deprecation table view:

```bash
initrunner doctor --role role.yaml
```

Example output for a role with a deprecated field:

```
       Role Validation: my-agent (spec_version: 1, current: 2)
┏━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┓
┃ ID     ┃ Severity ┃ Issue                                     ┃ Status        ┃
┡━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━┩
│ DEP002 │ error    │ store_backend 'zvec' has been removed...  │ auto-fixable  │
└────────┴──────────┴───────────────────────────────────────────┴───────────────┘
```

Auto-fix with `doctor --fix`:

```
$ initrunner doctor --fix --yes --role role.yaml
  Fixed DEP002: spec.ingest.store_backend
  Bumped spec_version to 2
```

When the role is clean:

```
Role is valid and up to date.
```

When the role is valid but uses an older spec version:

```
Role is valid.
spec_version 1 is behind current 2.
```

If `--quickstart` is also provided and role validation finds errors, the smoke test is skipped and the command exits with code 1.

## Fixing Deprecated Fields

### memory.max_memories (DEP001)

**Before:**
```yaml
spec:
  memory:
    max_memories: 500
```

**After:**
```yaml
spec:
  memory:
    semantic:
      max_memories: 500
```

### store_backend: zvec (DEP002-DEP005)

**Before:**
```yaml
spec:
  ingest:
    sources: ["*.md"]
    store_backend: zvec
```

**After:**
```yaml
spec:
  ingest:
    sources: ["*.md"]
    store_backend: lancedb
```

The same fix applies to `memory.store_backend`, `shared_memory.store_backend`, and `shared_documents.store_backend` in role, flow, and team files.
