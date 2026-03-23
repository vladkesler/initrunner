# Role Registry

InitRunner's role registry lets you install, share, and discover roles from InitHub and OCI registries. Roles are downloaded, validated, and saved to `~/.initrunner/roles/` where they integrate automatically with the CLI.

## Quick Start

```bash
# Install from InitHub
initrunner install owner/agent-pack
initrunner install owner/agent-pack@1.2.0

# Install from an OCI registry
initrunner install oci://ghcr.io/user/my-role:latest

# Inspect a role (works with all source types)
initrunner info owner/agent-pack
initrunner info oci://ghcr.io/user/my-role:latest

# Search InitHub
initrunner search "code review"

# List / update / remove
initrunner list
initrunner update code-reviewer
initrunner update --all
initrunner uninstall code-reviewer
```

## Source Identifiers

The `install` and `info` commands accept flexible source identifiers:

| Format | Example | Description |
|--------|---------|-------------|
| `owner/name` | `alice/code-reviewer` | Installs from InitHub (latest version) |
| `owner/name@ver` | `alice/code-reviewer@1.2.0` | Installs a specific version from InitHub |
| `hub:owner/name` | `hub:alice/code-reviewer` | InitHub (backward compatibility alias) |
| `hub:owner/name@ver` | `hub:alice/code-reviewer@1.2.0` | InitHub pinned version (backward compatibility alias) |
| `oci://reg/repo:tag` | `oci://ghcr.io/user/role:latest` | Pulls an OCI bundle |
| `bare-name` | `code-reviewer` | Error with a search hint: "Did you mean to search? Try: initrunner search code-reviewer" |

Detection order: `oci://` prefix selects OCI, `hub:` prefix or `owner/name` format selects InitHub, and bare names without a `/` produce an error with a search suggestion.

## Install Flow

When you run `initrunner install`, the following happens:

1. **Parse** the source identifier into owner, name, and optional version.
2. **Resolve** the package on InitHub, selecting the requested version or latest.
3. **Download** the bundle archive from InitHub.
4. **Extract** the role YAML and any bundled assets from the archive.
5. **Validate** the file as a valid InitRunner role definition (reuses the same validation as `initrunner validate`).
6. **Check dependencies** declared in the role's `metadata.dependencies` and warn about any that are missing.
7. **Display a security summary** showing the role name, description, tools, model provider, and other features. Prompt for confirmation.
8. **Save** the role to `~/.initrunner/roles/{owner}__{name}.yaml`.
9. **Record** the installation in `~/.initrunner/roles/registry.json` with source, version, and content hash.

### Namespace Strategy

Installed roles use flat namespaced filenames to prevent collisions between different authors:

```
~/.initrunner/roles/
  jcdenton__code-reviewer.yaml
  adamjensen__code-reviewer.yaml
  registry.json
```

Two different authors can publish roles with the same `name`. The CLI displays the human-friendly name and disambiguates when collisions exist (e.g. `code-reviewer (jcdenton)` vs `code-reviewer (adamjensen)`).

## Authentication

Publishing to InitHub requires authentication. Two login methods are available:

```bash
initrunner login                    # browser-based device code flow (default)
initrunner login --token <TOKEN>    # for CI/headless environments
```

The default `login` generates a one-time device code, opens your browser to approve it, and stores the resulting token locally. Use `--token` to pass an API token directly in CI pipelines or headless servers.

Publishing requires a token with `publish` scope. Tokens created via the device code flow are granted `publish,read` scopes by default.

## CLI Commands

### `install`

Install a role from InitHub or an OCI registry.

```bash
initrunner install owner/name                         # from InitHub (latest)
initrunner install owner/name@1.0.0                   # specific version
initrunner install oci://ghcr.io/user/role:latest     # from OCI
initrunner install owner/name --force                 # overwrite existing
initrunner install owner/name --yes                   # skip confirmation
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `source` | `str` | *(required)* | Source identifier: `owner/name[@ver]`, `hub:owner/name[@ver]`, or `oci://reg/repo:tag`. |
| `--force, -f` | `bool` | `false` | Overwrite if the role is already installed. |
| `--yes, -y` | `bool` | `false` | Skip the confirmation prompt. |

Before installing, the command displays a security summary:

```
  Role:        code-reviewer
  Description: Reviews code for best practices and bugs
  Author:      jcdenton
  Tools:       filesystem
  Model:       openai/gpt-5-mini

Install this role? [y/N]:
```

### `uninstall`

Remove an installed role.

```bash
initrunner uninstall code-reviewer
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `name` | `str` | *(required)* | Role name to remove. |

Removes both the YAML file and the manifest entry.

### `search`

Search InitHub for agent packs. Results include version information, download counts, and tags.

```bash
initrunner search "code review"
initrunner search python
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `query` | `str` | *(required)* | Search query. Matches against package name, description, and tags. |

Results are displayed in a table:

```
                        InitHub Packages
┌────────────────────┬─────────────────────────────────┬─────────┬───────────┬──────────────┐
│ Package            │ Description                     │ Version │ Downloads │ Tags         │
├────────────────────┼─────────────────────────────────┼─────────┼───────────┼──────────────┤
│ alice/code-reviewer│ Reviews code for best practices │ 1.2.0   │ 1,204     │ code, review │
│ bob/python-linter  │ Lints Python files              │ 0.9.1   │ 873       │ code, python │
└────────────────────┴─────────────────────────────────┴─────────┴───────────┴──────────────┘
```

### `info`

Inspect a role's metadata and tools without installing. Works with InitHub and OCI sources.

```bash
initrunner info owner/name
initrunner info oci://ghcr.io/user/role:latest
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `source` | `str` | *(required)* | Role source to inspect (same format as `install`). |

Resolves the source and displays a summary table. InitHub sources show package metadata (versions, downloads), and OCI sources show bundle manifest info:

```
        Role: code-reviewer
┌─────────────┬────────────────────────────────────┐
│ Field       │ Value                              │
├─────────────┼────────────────────────────────────┤
│ Name        │ code-reviewer                      │
│ Description │ Reviews code for best practices    │
│ Author      │ jcdenton                           │
│ Model       │ openai/gpt-5-mini                 │
│ Tools       │ filesystem                         │
│ Triggers    │ no                                 │
│ Ingestion   │ no                                 │
│ Memory      │ no                                 │
└─────────────┴────────────────────────────────────┘
```

### `list`

Show installed roles.

```bash
initrunner list
initrunner list --installed
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--installed` | `bool` | `true` | Show installed roles. |

### `update`

Update installed roles to the latest version.

```bash
initrunner update code-reviewer     # update a specific role
initrunner update --all             # update all installed roles
initrunner update                   # same as --all
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `name` | `str \| null` | `null` | Role name to update. If omitted, updates all. |
| `--all` | `bool` | `false` | Update all installed roles. |

The update process compares the remote version against the installed version. If they match, the role is skipped.

### `login`

Authenticate with InitHub.

```bash
initrunner login                    # browser-based device code flow
initrunner login --token <TOKEN>    # direct token for CI/headless use
```

### `logout`

Remove stored InitHub credentials.

```bash
initrunner logout
```

### `whoami`

Display the currently authenticated InitHub user.

```bash
initrunner whoami
```

### `publish`

Publish a role to InitHub or push to an OCI registry.

```bash
initrunner publish role.yaml                          # publish to InitHub (default)
initrunner publish role.yaml oci://ghcr.io/user/role  # push as OCI bundle
```

When called without an OCI reference, the role is published to InitHub under the authenticated user's namespace. When an `oci://` reference is provided, the role is packaged and pushed as an OCI bundle instead.

## Metadata Extensions

The role `metadata` section supports three optional fields for registry use:

```yaml
metadata:
  name: code-reviewer
  description: Reviews code for best practices and bugs
  author: jcdenton              # role author
  version: "1.0.0"              # semantic version
  dependencies:                 # external dependencies
    - python>=3.11
    - ffmpeg
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `author` | `str` | `""` | Role author name. Displayed in `info` and security summary. |
| `version` | `str` | `""` | Semantic version string for the role. |
| `dependencies` | `list[str]` | `[]` | External dependencies. Binary names are checked via `which`, Python version constraints are compared against the running interpreter. |

All fields are optional and backwards-compatible. Existing roles without these fields continue to work.

### Dependency Checking

During installation, declared dependencies are checked:

- **Binary dependencies** (e.g. `ffmpeg`): checked with `shutil.which()`. A warning is printed if not found on PATH.
- **Python version** (e.g. `python>=3.11`): compared against the running interpreter version.

Dependency warnings do not block installation. They are advisory only.

## Local Manifest

The registry manifest at `~/.initrunner/roles/registry.json` tracks all installed roles:

```json
{
  "roles": {
    "code-reviewer": {
      "source": "jcdenton/code-reviewer",
      "version": "1.2.0",
      "local_path": "jcdenton__code-reviewer.yaml",
      "installed_at": "2026-02-10T12:00:00+00:00",
      "sha256": "abc123..."
    }
  }
}
```

| Field | Description |
|-------|-------------|
| `source` | InitHub `owner/name` identifier. |
| `version` | Installed version string. |
| `local_path` | Namespaced filename on disk. |
| `installed_at` | ISO 8601 timestamp of installation. |
| `sha256` | SHA-256 hash of the YAML content for integrity verification. |

The manifest is written atomically (write to `.tmp`, then rename) to prevent corruption.

## Using Installed Roles

Installed roles are standard YAML files and work with all existing commands:

```bash
# Run an installed role
initrunner run ~/.initrunner/roles/jcdenton__code-reviewer.yaml -p "Review this code"

# Validate an installed role
initrunner validate ~/.initrunner/roles/jcdenton__code-reviewer.yaml

# Interactive mode
initrunner run ~/.initrunner/roles/jcdenton__code-reviewer.yaml -i
```

Audit logging works normally. Runs are logged by the `agent_name` from the role's metadata.

## Error Handling

| Scenario | Message |
|----------|---------|
| Network unreachable | "Could not reach InitHub. Check your connection." |
| Role not found (404) | "Package not found: {source}. Check the owner and name." |
| Invalid YAML | "Downloaded file is not a valid InitRunner role: {details}" |
| Already installed | "Role '{name}' is already installed. Use --force to overwrite." |
| Bare name without slash | "Unknown source format. Did you mean to search? Try: initrunner search {name}" |
| Not authenticated | "Authentication required. Run: initrunner login" |
| Role not installed | "Role '{name}' is not installed." |

## Security

- Downloaded YAML is validated with the same parser used by `initrunner validate` before being saved to disk.
- A security summary (tools, model, features) is displayed and confirmation is required before installation.
- Content integrity is tracked via SHA-256 hash in the manifest.
- Downloads are restricted to InitHub and configured OCI registries. No arbitrary URLs are fetched.
- Authentication tokens are stored locally and never recorded in the manifest.
