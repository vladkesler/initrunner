# Deprecations & Schema Versioning

InitRunner uses a centralized deprecation system to manage removed or renamed configuration fields across role, flow, and team YAML schemas. When a field is deprecated, you get a clear error message pointing to the replacement instead of a cryptic validation failure.

## spec_version

Flat Agent/Team/Flow files use a top-level `spec_version: 3`. Old envelopes still use `metadata.spec_version` (currently 2) and still load. Convert them with `initrunner doctor --fix PATH` — see [Envelope migration](../getting-started/envelope-migration.md).

```yaml
name: my-agent
spec_version: 3
description: ...
prompt: ...
```

**Behavior (envelope `metadata.spec_version`):**

| spec_version | Runtime | Doctor |
|---|---|---|
| Current envelope (2) | Loads normally | "Valid and up to date" |
| Older (1) | Loads normally | Shows informational note |
| Future (>2 on an envelope) | Rejected with error | Rejected with error |

When you save or generate a role through InitRunner (builder, templates, `initrunner new`), `spec_version` is set to `3` on the flat document.

## Current Deprecation Rules

| ID | Applies to | Field | Error |
|---|---|---|---|
| DEP001 | Role | `spec.memory.max_memories` | Removed. Use `memory.semantic.max_memories` instead. |
| DEP002 | Role | `spec.ingest.store_backend: zvec` | zvec has been removed. Use `lancedb`. |
| DEP003 | Role | `spec.memory.store_backend: zvec` | zvec has been removed. Use `lancedb`. |
| DEP004 | Flow, Team | `spec.shared_memory.store_backend: zvec` | zvec has been removed. Use `lancedb`. |
| DEP005 | Flow, Team | `spec.shared_documents.store_backend: zvec` | zvec has been removed. Use `lancedb`. |

All current rules are error-severity with automatic migration. Run `initrunner doctor --fix PATH --yes` to rewrite envelopes and auto-patch deprecated fields. Use `--yes` to skip prompts.

## Unknown keys are errors

Every section of an agent file rejects keys it doesn't define, at any depth.
A misspelled setting used to validate clean and then do nothing, which is the
worst way for a config to fail: `memory: {max_sesions: 3}` looked fine and
the agent kept the default of 10. Now it stops the run:

```
[ERROR] memory.max_sesions
  Extra inputs are not permitted
  Fix: unknown field; check for typos against the schema
```

This covers the flat document and everything nested in it: model, tools
(including `permissions`, script parameters and API endpoints), triggers,
sinks, ingest, memory, autonomy, reasoning, guardrails, execution, and the
team and flow settings (`then`, `debate`, `ensemble`, `shared_memory`,
`shared_documents`, `durability`). Envelope files are checked at every level
too, from `metadata` and `spec` down to team personas and flow agents. Tool
entries in a skill's `SKILL.md` frontmatter are checked
too, and so is its `requires` block; the frontmatter's own top-level keys are still ignored, because
agentskills.io files written for other tools carry fields InitRunner doesn't
use.

Places that are free-form by design stay open: a plugin tool's options,
`headers` and `env` on MCP tools, `model.extra_headers` and
`model.extra_body`, `output.schema`, and `deps_schema`.

If a file that used to load now fails, the key it names was never doing
anything. Fix the spelling or delete the line. Nothing removes unknown keys
for you, and there is no switch to turn the check off.

## Checking Your Role

Three commands surface schema and deprecation problems, each tuned to a different workflow:

| Command | What it catches | When to use |
|---|---|---|
| `initrunner run <PATH>` | Syntax errors, schema errors, deprecation errors -- anything that would block the run. Renders a Rich panel with field paths, line numbers, and fix hints, then exits **before any API call** | Every run -- pre-flight is automatic |
| `initrunner validate <PATH>` | Same as the run pre-flight, plus warnings and info-level recommendations. On a clean role, also shows the configuration table | Auditing a role you just edited |
| `initrunner doctor --role <PATH>` | Deprecation rules table, spec version drift, and (with `--fix`) automatic migration | Upgrading roles between InitRunner releases |

Schema errors from the run pre-flight and `validate` show one issue per
field, with its path: `model.provider` in a flat file, `spec.model.provider`
in an envelope (where the shared `unwrap_pydantic_error` helper follows
Pydantic's `ValidationError` through the deprecation wrapper). Deprecation rule failures (DEP001..DEP005) appear with `field:
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
