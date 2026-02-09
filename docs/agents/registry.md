# Role Registry

InitRunner's role registry lets you install, share, and discover community roles directly from GitHub. Roles are downloaded, validated, and saved to `~/.initrunner/roles/` where they integrate automatically with the CLI and TUI.

No registry server is required — roles live on GitHub and a community index repo provides discovery. Everything is files and HTTP.

## Quick Start

```bash
# Install a role from GitHub
initrunner install user/repo

# Install a specific file from a repo
initrunner install user/repo:roles/code-reviewer.yaml

# Install pinned to a tag
initrunner install user/repo@v1.2.0

# Install by name from the community index
initrunner install code-reviewer

# List installed roles
initrunner list

# Inspect a role before installing
initrunner info user/repo:roles/summarizer.yaml

# Search the community index
initrunner search "code review"

# Update a role
initrunner update code-reviewer

# Update all installed roles
initrunner update --all

# Remove an installed role
initrunner uninstall code-reviewer
```

## Source Identifiers

The `install` and `info` commands accept flexible source identifiers:

| Format | Example | Description |
|--------|---------|-------------|
| `user/repo` | `jcdenton/ai-roles` | Downloads `role.yaml` from the repo root (main branch) |
| `user/repo:path` | `jcdenton/ai-roles:roles/reviewer.yaml` | Downloads a specific file from the repo |
| `user/repo@ref` | `jcdenton/ai-roles@v1.0` | Pins to a tag, branch, or commit SHA |
| `user/repo:path@ref` | `jcdenton/ai-roles:roles/reviewer.yaml@v1.0` | Specific file at a pinned ref |
| `bare-name` | `code-reviewer` | Looks up the name in the community index |

Detection: if the identifier contains `/`, it's treated as a GitHub reference. Otherwise, it's looked up in the community index.

## Install Flow

When you run `initrunner install`, the following happens:

1. **Parse** the source identifier into owner, repo, path, and ref.
2. **Download** the YAML file from `raw.githubusercontent.com`.
3. **Validate** the file as a valid InitRunner role definition (reuses the same validation as `initrunner validate`).
4. **Check dependencies** declared in the role's `metadata.dependencies` and warn about any that are missing.
5. **Display a security summary** showing the role name, description, tools, model provider, and other features. Prompt for confirmation.
6. **Save** the role to `~/.initrunner/roles/{owner}__{repo}__{name}.yaml`.
7. **Record** the installation in `~/.initrunner/roles/registry.json` with source URL, ref, commit SHA, and content hash.

### Namespace Strategy

Installed roles use flat namespaced filenames to prevent collisions between different authors:

```
~/.initrunner/roles/
  jcdenton__ai-roles__code-reviewer.yaml
  adamjensen__security-roles__code-reviewer.yaml
  registry.json
```

Two different authors can publish roles with the same `name`. The TUI and CLI display the human-friendly name and disambiguate when collisions exist (e.g. `code-reviewer (jcdenton)` vs `code-reviewer (adamjensen)`).

## CLI Commands

### `install`

Install a role from GitHub or the community index.

```bash
initrunner install user/repo                          # from GitHub
initrunner install user/repo:path/to/role.yaml        # specific file
initrunner install user/repo@v1.0                     # pinned ref
initrunner install code-reviewer                      # from community index
initrunner install user/repo --force                  # overwrite existing
initrunner install user/repo --yes                    # skip confirmation
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `source` | `str` | *(required)* | GitHub source (`user/repo[:path][@ref]`) or community role name. |
| `--force, -f` | `bool` | `false` | Overwrite if the role is already installed. |
| `--yes, -y` | `bool` | `false` | Skip the confirmation prompt. |

Before installing, the command displays a security summary:

```
  Role:        code-reviewer
  Description: Reviews code for best practices and bugs
  Author:      jcdenton
  Tools:       filesystem
  Model:       openai/gpt-4o-mini

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

Search the community role index.

```bash
initrunner search "code review"
initrunner search python
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `query` | `str` | *(required)* | Search query. Matches against role name, description, and tags. |

Results are displayed in a table:

```
        Community Roles
┌────────────────┬────────┬─────────────────────────────────┬──────────────┐
│ Name           │ Author │ Description                     │ Tags         │
├────────────────┼────────┼─────────────────────────────────┼──────────────┤
│ code-reviewer  │ jcd    │ Reviews code for best practices │ code, review │
│ python-linter  │ comm   │ Lints Python files              │ code, python │
└────────────────┴────────┴─────────────────────────────────┴──────────────┘
```

### `info`

Inspect a role's metadata and tools without installing.

```bash
initrunner info user/repo
initrunner info user/repo:roles/reviewer.yaml
initrunner info code-reviewer
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `source` | `str` | *(required)* | Role source to inspect (same format as `install`). |

Downloads and parses the role, then displays a summary table:

```
        Role: code-reviewer
┌─────────────┬────────────────────────────────────┐
│ Field       │ Value                              │
├─────────────┼────────────────────────────────────┤
│ Name        │ code-reviewer                      │
│ Description │ Reviews code for best practices    │
│ Author      │ jcdenton                           │
│ Model       │ openai/gpt-4o-mini                 │
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

The update process compares the remote commit SHA against the stored SHA. If unchanged, the role is skipped. If the role was installed with a tag ref (e.g. `@v1.0`), update warns that tags are immutable and suggests reinstalling with a different ref.

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

All fields are optional and backwards-compatible — existing roles without these fields continue to work.

### Dependency Checking

During installation, declared dependencies are checked:

- **Binary dependencies** (e.g. `ffmpeg`): checked with `shutil.which()`. A warning is printed if not found on PATH.
- **Python version** (e.g. `python>=3.11`): compared against the running interpreter version.

Dependency warnings do not block installation — they are advisory only.

## Local Manifest

The registry manifest at `~/.initrunner/roles/registry.json` tracks all installed roles:

```json
{
  "roles": {
    "code-reviewer": {
      "source_url": "https://raw.githubusercontent.com/jcdenton/ai-roles/main/roles/code-reviewer.yaml",
      "repo": "jcdenton/ai-roles",
      "path": "roles/code-reviewer.yaml",
      "ref": "main",
      "commit_sha": "a1b2c3d4e5f6...",
      "local_path": "jcdenton__ai-roles__code-reviewer.yaml",
      "installed_at": "2026-02-10T12:00:00+00:00",
      "sha256": "abc123..."
    }
  }
}
```

| Field | Description |
|-------|-------------|
| `source_url` | Full download URL used during installation. |
| `repo` | GitHub `owner/repo` string. |
| `path` | File path within the repository. |
| `ref` | Branch, tag, or commit SHA the role was installed from. |
| `commit_sha` | Git commit SHA at the time of installation (for update comparison). |
| `local_path` | Namespaced filename on disk. |
| `installed_at` | ISO 8601 timestamp of installation. |
| `sha256` | SHA-256 hash of the YAML content for integrity verification. |

The manifest is written atomically (write to `.tmp`, then rename) to prevent corruption.

## Community Index

The community index is a GitHub repository containing an `index.yaml` file that maps bare role names to their GitHub sources:

```yaml
roles:
  - name: code-reviewer
    description: Reviews code for best practices and bugs
    author: jcdenton
    source: jcdenton/ai-roles:roles/code-reviewer.yaml
    tags: [code, review]
  - name: summarizer
    description: Summarizes documents and articles
    author: community
    source: community/ai-roles:summarizer.yaml
    tags: [text, summary]
```

The `search` command fetches this index and filters locally. The `install` command uses it to resolve bare names (e.g. `initrunner install code-reviewer`).

If the community index is unavailable, commands that depend on it print a helpful message suggesting direct installation with `user/repo` syntax.

## TUI Integration

Installed roles appear automatically in the TUI dashboard (`initrunner ui`). The roles screen scans `~/.initrunner/roles/` alongside other directories and handles namespaced filenames:

- Names are displayed without the `owner__repo__` prefix.
- When two installed roles have the same name from different authors, the display disambiguates them: `code-reviewer (jcdenton)` vs `code-reviewer (adamjensen)`.

No additional configuration is needed — installed roles are discovered on startup.

## Using Installed Roles

Installed roles are standard YAML files and work with all existing commands:

```bash
# Run an installed role
initrunner run ~/.initrunner/roles/jcdenton__ai-roles__code-reviewer.yaml -p "Review this code"

# Validate an installed role
initrunner validate ~/.initrunner/roles/jcdenton__ai-roles__code-reviewer.yaml

# Interactive mode
initrunner run ~/.initrunner/roles/jcdenton__ai-roles__code-reviewer.yaml -i
```

Audit logging works normally — runs are logged by the `agent_name` from the role's metadata.

## GitHub Authentication

By default, the registry uses unauthenticated GitHub API requests, which are subject to rate limits (60 requests/hour). For higher limits or to access private repositories, set the `GITHUB_TOKEN` environment variable:

```bash
export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
initrunner install user/private-repo
```

The token is sent as a Bearer token in the `Authorization` header for all GitHub API and raw content requests.

## Error Handling

| Scenario | Message |
|----------|---------|
| Network unreachable | "Could not reach GitHub. Check your connection." |
| Role not found (404) | "Role not found at {url}. Check the path and try again." |
| Invalid YAML | "Downloaded file is not a valid InitRunner role: {details}" |
| Already installed | "Role '{name}' is already installed. Use --force to overwrite." |
| Community index down | "Community index unavailable. Install directly: initrunner install user/repo" |
| Rate limited | "GitHub API rate limit reached. Set GITHUB_TOKEN env var for higher limits." |
| Role not installed | "Role '{name}' is not installed." |

## Security

- Downloaded YAML is validated with the same parser used by `initrunner validate` before being saved to disk.
- A security summary (tools, model, features) is displayed and confirmation is required before installation.
- Content integrity is tracked via SHA-256 hash in the manifest.
- Downloads are restricted to `raw.githubusercontent.com` — no arbitrary URLs.
- The `GITHUB_TOKEN` environment variable is supported for authenticated requests but never stored in the manifest.
