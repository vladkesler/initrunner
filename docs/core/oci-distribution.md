# OCI Distribution & Role Bundles

InitRunner supports publishing and installing role bundles via any OCI-compliant container registry (Docker Hub, GHCR, ECR, etc.). This gives you a distribution story comparable to Docker images, with bundled skills, schemas, and data files.

## Quick Start

```bash
# Log in to a registry
initrunner login ghcr.io

# Publish a role
initrunner publish role.yaml oci://ghcr.io/org/my-agent --tag 1.0.0

# Install from a registry
initrunner install oci://ghcr.io/org/my-agent:1.0.0

# Pull (alias for install with OCI)
initrunner pull ghcr.io/org/my-agent:latest

# Inspect without installing
initrunner info oci://ghcr.io/org/my-agent:1.0.0
```

## Bundle Format

A role bundle is a `.tar.gz` archive containing:

```
manifest.json          # bundle metadata
role.yaml              # the role definition
skills/                # referenced SKILL.md files (if any)
  web-researcher/
    SKILL.md
data/                  # schemas, samples, etc. (if any)
  schema.json
```

### What Gets Bundled

File selection is **deterministic and explicit** -- no implicit directory scanning:

1. **The role file** (`role.yaml`) -- always included
2. **Resolved skills** -- each `spec.skills` entry resolved to its SKILL.md file
3. **Schema-referenced data files**:
   - `spec.output.schema_file` (if set)
   - `spec.ingest.sources` glob patterns
   - `spec.security.docker.bind_mounts[].source`
4. **Explicit `bundle.include`** -- a metadata field for extra files:

```yaml
metadata:
  name: my-agent
  bundle:
    include:
      - data/examples/*.csv
      - prompts/
```

## OCI Reference Format

OCI references use the `oci://` prefix to distinguish them from GitHub sources:

| Pattern | Type | Example |
|---------|------|---------|
| `oci://registry/repo:tag` | OCI | `oci://ghcr.io/org/my-agent:1.0` |
| `owner/repo` | GitHub | `user/repo@v1.0` |
| `bare-name` | Community index | `pr-reviewer` |

The `oci://` prefix is required and unambiguous -- existing GitHub sources (including dotted names like `my-user.name/my-repo.name`) work unchanged.

## Authentication

Credentials are resolved in this order:

1. **Environment variables**: `INITRUNNER_OCI_USERNAME` + `INITRUNNER_OCI_PASSWORD`
2. **InitRunner auth file**: `~/.initrunner/oci-auth.json` (created by `initrunner login`)
3. **Docker config**: `~/.docker/config.json` (base64 `auth` field only)

### `initrunner login`

```bash
initrunner login ghcr.io
# Username: myuser
# Password: ********
# Login succeeded for ghcr.io
```

Credentials are stored in `~/.initrunner/oci-auth.json` with file mode `0600`.

### Docker Credential Helpers

Docker credential helpers (`credsStore`, `credHelpers`) are **not supported**. If your Docker config uses credential helpers, use `initrunner login` or environment variables instead. A warning is emitted when credential helpers are detected.

## Install Identity

Installed roles are tracked with qualified IDs to prevent name collisions:

- **GitHub**: `github:owner/repo/role-name`
- **OCI**: `oci:registry/repository/role-name`

You can uninstall and manage roles using either the display name or qualified ID:

```bash
initrunner uninstall my-agent                              # by display name
initrunner uninstall "oci:ghcr.io/org/my-agent/my-agent"   # by qualified ID
```

The `initrunner list` command shows the source type for each installed role.

## Updating OCI Roles

```bash
initrunner update my-agent    # checks registry for new digest
initrunner update --all       # update all installed roles
```

For OCI sources, `update` performs a HEAD request to check if the manifest digest has changed, then re-pulls if needed.

## Commands Reference

| Command | Description |
|---------|-------------|
| `initrunner publish <role.yaml> <oci-ref> [--tag TAG]` | Bundle and push a role to an OCI registry |
| `initrunner pull <oci-ref> [--force] [--yes]` | Pull and install a role from an OCI registry |
| `initrunner install oci://... [--force] [--yes]` | Install from OCI (same as pull) |
| `initrunner login <registry>` | Store credentials for a registry |
| `initrunner info oci://...` | Inspect bundle metadata without installing |
| `initrunner list` | List installed roles with source type |
| `initrunner update <name>` | Update an installed role (GitHub or OCI) |

## OCI Media Types

- Config: `application/vnd.initrunner.config.v1+json`
- Layer: `application/vnd.initrunner.role.v1.tar+gzip`
- Manifest: `application/vnd.oci.image.manifest.v1+json`

## File Layout

OCI bundles are extracted to `~/.initrunner/roles/oci__<registry>__<repo>__<name>/`:

```
~/.initrunner/roles/
  oci__ghcr.io__org__my-agent/     # OCI bundle (directory)
    manifest.json
    role.yaml
    skills/
    data/
  user__repo__other-agent.yaml     # GitHub install (single file)
```

## Security

- All archive paths are validated to prevent path traversal attacks
- SHA-256 integrity checks are performed on every file during extraction
- Credentials are stored with restrictive file permissions (0600)
- Bundle contents are deterministic -- only explicitly referenced files are included
