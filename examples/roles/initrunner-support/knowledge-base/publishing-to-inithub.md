# Publishing to InitHub

InitHub (hub.initrunner.ai) is the default registry for sharing InitRunner agents. You can publish agents for others to install with a single command.


## Overview

InitHub lets you:
- Publish agent bundles with metadata, README, and knowledge base files
- Search and discover published agents
- Install agents with `initrunner install`
- Track versions and update installed agents


## Authentication

Log in to InitHub before publishing:

```bash
initrunner login
```

This starts a device code flow: it displays a code and opens your browser. Confirm the code in the browser to authenticate. Your token is saved locally.

For CI/headless environments, pass a token directly:

```bash
initrunner login --token YOUR_TOKEN
```

Other auth commands:

```bash
initrunner logout    # remove stored credentials
initrunner whoami    # check current auth status
```


## Publishing an agent

From inside your agent directory:

```bash
initrunner publish . --readme README.md
```

With optional metadata:

```bash
initrunner publish . \
  --readme README.md \
  --category support \
  --category example \
  --repo-url https://github.com/org/repo
```

The publish command:
1. Validates the role definition
2. Creates a `.tar.gz` bundle
3. Uploads the bundle with metadata to InitHub
4. Returns the install command


## What gets bundled

The bundle automatically includes:
1. **Role file** (role.yaml) -- always included
2. **Resolved skills** -- from `spec.skills` entries
3. **Schema-referenced files** -- output schemas, ingest source files, Docker bind mounts
4. **Explicit includes** -- from `metadata.bundle.include`

To include extra files (like a README or knowledge base), add them to `metadata.bundle.include`:

```yaml
metadata:
  name: my-agent
  version: "1.0.0"
  bundle:
    include:
      - README.md
      - knowledge-base/**/*.md
      - data/schema.json
```

Ingest source files matching glob patterns in `spec.ingest.sources` are included automatically.


## Metadata fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Agent name (lowercase, alphanumeric, hyphens) |
| `description` | No | Short description of the agent |
| `version` | No | Semantic version (e.g. "1.0.0"). Defaults to "0.0.0" if omitted |
| `author` | No | Author name or team |
| `tags` | No | List of tags for discoverability |

Set the version in `metadata.version` -- it appears in the bundle manifest and on the InitHub listing. If omitted, the version defaults to "0.0.0".


## Publish flags

| Flag | Description |
|------|-------------|
| `--readme FILE` | README file to display on InitHub |
| `--category CAT` | Category tag (can repeat for multiple categories) |
| `--repo-url URL` | Link to the source repository |


## Installing published agents

```bash
# Install from InitHub
initrunner install owner/agent-name

# Install a specific version
initrunner install owner/agent-name@1.0.0

# Skip confirmation
initrunner install owner/agent-name --yes

# Force reinstall
initrunner install owner/agent-name --force
```


## Searching InitHub

```bash
# Search by keyword
initrunner search "support agent"

# Search by tag
initrunner search --tag rag --tag memory
```

Results show: package name, version, description, download count, and tags.


## Inspecting a package

```bash
initrunner info owner/agent-name
```

Shows: name, description, author, latest version, download count, tags, version history, and repository URL.


## Managing installed agents

```bash
# List installed agents
initrunner list --installed

# Update a specific agent
initrunner update agent-name

# Update all installed agents
initrunner update --all

# Uninstall
initrunner uninstall agent-name
```

Installed agents are stored in `~/.initrunner/roles/`.


## OCI registry alternative

For private registries or self-hosted distribution, publish to any OCI-compatible registry:

```bash
# Log in to an OCI registry
initrunner login ghcr.io

# Publish to OCI
initrunner publish . oci://ghcr.io/org/my-agent --tag 1.0.0

# Install from OCI
initrunner install oci://ghcr.io/org/my-agent:1.0.0
```


## Example: full publish workflow

```bash
# 1. Set metadata in role.yaml
# metadata:
#   name: my-support-agent
#   version: "1.0.0"
#   author: Your Name
#   tags: [support, rag]
#   bundle:
#     include: [README.md]

# 2. Validate
initrunner validate role.yaml

# 3. Log in
initrunner login

# 4. Publish
initrunner publish . --readme README.md --category support

# 5. Verify
initrunner search my-support-agent
initrunner info your-name/my-support-agent
```
