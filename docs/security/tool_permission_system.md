# Tool Permissions

Declarative allow/deny rules that control tool calls based on argument patterns. Add a `permissions` block to any built-in tool config to restrict what arguments the agent can pass.

## Pattern syntax

Each rule is a string in the format:

```
arg_name=glob_pattern
```

- **`arg_name`** — matches the tool function's parameter name (e.g. `command`, `path`, `url`)
- **`glob_pattern`** — standard `fnmatch` glob (`*`, `?`, `[seq]`, `[!seq]`)

A **bare pattern** (no `=`) matches against all string argument values.

## Evaluation order

1. **Deny rules** are checked first. If any deny pattern matches, the call is **blocked**.
2. **Allow rules** are checked next. If any allow pattern matches, the call is **permitted**.
3. If no rule matches, the **default** policy applies (`allow` or `deny`).

Deny always wins when the same pattern appears in both lists.

## Examples

### Shell — allowlist of safe commands

```yaml
tools:
  - type: shell
    working_dir: .
    permissions:
      default: deny
      allow:
        - "command=ls *"
        - "command=cat *"
        - "command=grep *"
        - "command=python *.py"
      deny:
        - "command=rm *"
```

### Filesystem — block sensitive files

```yaml
tools:
  - type: filesystem
    root_path: .
    permissions:
      default: allow
      deny:
        - "path=*.env"
        - "path=*credentials*"
        - "path=*.pem"
```

### HTTP — block internal URLs

```yaml
tools:
  - type: http
    base_url: https://api.example.com
    permissions:
      deny:
        - "url=*internal*"
        - "url=*admin*"
```

## Security notes

- **Denied responses are sanitized** — the error message includes the matched rule pattern but never echoes raw argument values. This prevents leaking secrets (tokens, passwords) through denial messages.
- Permissions are enforced as a `PermissionToolset` wrapper around the tool's native toolset, so they work with any built-in tool type without modifying tool implementation code.
- **Plugin tools** (`PluginToolConfig`) do not currently support `permissions` because the plugin parser strips all non-`type` keys into a generic `config` dict. This is a known limitation.

## Defaults

When no `permissions` block is present (the default), the tool operates without any permission filtering — existing behavior is fully preserved.

When `permissions` is present but has empty `allow`/`deny` lists, only the `default` policy applies.
