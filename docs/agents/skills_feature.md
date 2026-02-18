# Skills — Reusable Tool & Prompt Bundles

Skills are self-contained bundles of tools and system prompt instructions packaged as Markdown files. They enable composition and reuse across agents — define a capability once, reference it from any role. Skills use the SKILL.md format (compatible with the [agentskills.io](https://agentskills.io) standard) with InitRunner extensions for tool configs and requirements.

## Quick Start

Create a skill:

```bash
initrunner init --template skill --name web-researcher
```

This creates `web-researcher/SKILL.md`:

```markdown
---
name: web-researcher
description: Web research tools for fetching and reading web pages.
tools:
  - type: web_reader
    timeout_seconds: 15
  - type: http
    base_url: https://httpbin.org
    allowed_methods: [GET]
---

You have web research capabilities. Use fetch_page to read web pages
and http_request for API calls. Always summarize findings concisely.
```

Reference it from a role:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: my-agent
  description: Agent with skills
spec:
  role: |
    You are a helpful research assistant.
  model:
    provider: openai
    name: gpt-5-mini
  skills:
    - web-researcher
  tools:
    - type: datetime
```

Validate and list skills:

```bash
initrunner skill validate web-researcher/
initrunner skill list
```

## SKILL.md Format

A SKILL.md file has two parts: YAML frontmatter (delimited by `---`) and a Markdown body that becomes the skill's system prompt contribution.

### Frontmatter Fields

**Standard agentskills.io fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | *(required)* | Skill identifier. Must match `^[a-z0-9][a-z0-9-]*[a-z0-9]$`. |
| `description` | `str` | *(required)* | Human-readable description of what the skill provides. |
| `license` | `str` | `""` | License identifier (e.g. `"MIT"`). |
| `compatibility` | `str` | `""` | Compatibility notes (e.g. required tool types). |
| `metadata` | `dict[str, str]` | `{}` | Arbitrary key-value metadata (author, version, tags, etc.). |
| `allowed_tools` | `str` | `""` | Tool allowlist (agentskills.io standard field). |

**InitRunner extensions:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `tools` | `list[ToolConfig]` | `[]` | Tool configurations contributed by the skill. Same format as `spec.tools` in a role. |
| `requires` | `RequiresConfig` | `{}` | External dependencies to check at load time. |

Unknown frontmatter fields are silently ignored (`extra="ignore"`) to maintain compatibility with community SKILL.md files that may include additional fields.

### Markdown Body

Everything after the closing `---` delimiter is the skill's prompt. It is injected into the agent's system prompt under a `### Skill: {name}` sub-header. Empty prompts are skipped.

### File Layouts

Skills support two file layouts:

**Directory format** — `{name}/SKILL.md`:

```
skills/
  web-researcher/
    SKILL.md
```

**Flat format** — `{name}.md`:

```
skills/
  code-tools.md
```

Both are equivalent. The directory format is preferred when a skill needs auxiliary files alongside it.

## Referencing Skills from Roles

Skills are referenced in the `spec.skills` list of a role definition. Each entry is a string that is resolved to a SKILL.md file.

```yaml
spec:
  skills:
    # Bare name — resolved via search dirs
    - web-researcher

    # Explicit .md path (relative to role file)
    - ../skills/code-tools.md

    # Explicit directory (looks for SKILL.md inside)
    - ../skills/web-researcher

    # Explicit directory with SKILL.md
    - ../skills/web-researcher/SKILL.md
```

### Full Example

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: skill-demo
  description: Demonstration of skill-based composition
  tags:
    - demo
    - skills
spec:
  role: |
    You are a versatile research assistant that can browse the web,
    read code, and tell the time. Use the appropriate skills for each task.
  model:
    provider: openai
    name: gpt-5-mini
    temperature: 0.1
    max_tokens: 4096
  skills:
    - ../skills/web-researcher
    - ../skills/code-tools.md
  tools:
    - type: datetime
  guardrails:
    max_tokens_per_run: 50000
    max_tool_calls: 20
    timeout_seconds: 300
    max_request_limit: 50
```

## Skill Resolution

How a skill reference string is resolved to a file depends on whether it is an **explicit path** or a **bare name**.

### Explicit Paths

A reference is treated as an explicit path if it contains `/` or ends with `.md`:

- If it ends with `.md`, the path is resolved relative to the role file's directory.
- If it is a directory path, InitRunner looks for `SKILL.md` inside the directory, then tries appending `.md` to the path.

### Bare Name Lookup

A bare name (e.g. `web-researcher`) is searched across multiple directories. At each directory, the directory format is checked before the flat format:

| Priority | Location | Description |
|----------|----------|-------------|
| 1 | `{role_dir}/skills/{name}/SKILL.md` | Skills directory next to the role file |
| 1 | `{role_dir}/skills/{name}.md` | Flat format next to the role file |
| 2 | `{extra_dirs}/{name}/SKILL.md` | Extra search directories (`--skill-dir` / `INITRUNNER_SKILL_DIR`) |
| 2 | `{extra_dirs}/{name}.md` | Flat format in extra directories |
| 3 | `~/.initrunner/skills/{name}/SKILL.md` | Global skills directory |
| 3 | `~/.initrunner/skills/{name}.md` | Flat format in global directory |

The `--skill-dir` CLI option takes precedence over `INITRUNNER_SKILL_DIR`. Both are checked before the global `~/.initrunner/skills/` directory.

### Deduplication

If two skill references resolve to the same file path, the duplicate is silently skipped. Deduplication is by resolved absolute path.

## Requirements

Skills can declare external dependencies that are checked at load time:

```yaml
requires:
  env:
    - OPENAI_API_KEY
    - CUSTOM_SERVICE_TOKEN
  bins:
    - python3
    - git
```

| Field | Type | Check | Description |
|-------|------|-------|-------------|
| `env` | `list[str]` | `os.environ` | Environment variables that must be set. |
| `bins` | `list[str]` | `shutil.which` | Binaries that must be on `PATH`. |

Unmet requirements are **non-fatal**: warnings are logged and shown in `skill validate` output, but the agent still builds. This allows partial functionality when not all requirements are available.

## Tool Merging

When skills contribute tools, they are merged with the role's own tools using deduplication by `tool.type`.

### Order

1. **Skill tools** are added first, in skill declaration order (the order of `spec.skills`).
2. **Role tools** are added last.

### Override Rules

| Scenario | Behavior |
|----------|----------|
| Two skills declare the same tool type | The later skill's config overrides the earlier one. A warning is logged. |
| A role declares a tool type that a skill also declares | The role's config overrides the skill's. A warning is logged. |

This means role-level tools always take precedence, giving the role author final control over tool configuration.

## System Prompt Integration

Skills contribute to the agent's system prompt in a structured format:

1. The **role prompt** (`spec.role`) comes first — this defines the agent's identity.
2. A `## Skills` section follows, with a brief introduction.
3. Each skill's Markdown body is rendered under a `### Skill: {name}` sub-header.

Skills with empty prompts are skipped.

Example of the generated system prompt structure:

```
You are a helpful research assistant.

## Skills

The following skills provide you with additional capabilities.
Follow their usage guidelines when performing relevant tasks.

### Skill: web-researcher
You have web research capabilities. Use fetch_page to read web pages
and http_request for API calls. Always summarize findings concisely.

### Skill: code-tools
You have code tools available. Use read_file/list_directory to browse
the codebase and run_python to execute Python snippets.
```

## Security

- The role's `SecurityPolicy` applies to **all** tools, including those contributed by skills. Skills cannot weaken or bypass security policies.
- Skills cannot nest — the `SkillFrontmatter` schema does not include a `skills` field, so a skill cannot reference other skills.
- Tool sandbox restrictions (blocked modules, MCP command allowlists, sensitive env prefixes) apply uniformly regardless of whether a tool came from a skill or the role itself.

See [Security](../security/security.md) for the full security policy reference.

## CLI Commands

### `skill validate <path>`

Validate a skill definition and display its metadata.

```bash
initrunner skill validate web-researcher/        # directory format
initrunner skill validate code-tools.md           # flat format
```

If the path is a directory, InitRunner looks for `SKILL.md` inside it.

Output includes: name, description, license, compatibility, metadata, tools (with summaries), requirement status (met/unmet), and a prompt preview (first 200 characters).

### `skill list [--skill-dir DIR]`

List all available skills discovered across search locations.

```bash
initrunner skill list
initrunner skill list --skill-dir ./my-skills
```

Scans these directories (in order):
1. `./skills/` (current working directory)
2. The `--skill-dir` argument (if provided)
3. `~/.initrunner/skills/` (global)

Output table includes: name, description, tools, and file path.

### `init --template skill --name <name>`

Scaffold a new skill in directory format.

```bash
initrunner init --template skill --name web-researcher
```

Creates `web-researcher/SKILL.md` with template frontmatter and prompt. Refuses to overwrite an existing directory.

### `--skill-dir` Option

The `--skill-dir` option is available on `validate`, `run`, `daemon`, and `serve` commands. It adds an extra directory to the skill search path.

```bash
initrunner run role.yaml -i --skill-dir ./shared-skills
initrunner daemon role.yaml --skill-dir /opt/skills
initrunner serve role.yaml --skill-dir ./shared-skills
```

### `INITRUNNER_SKILL_DIR` Environment Variable

Set `INITRUNNER_SKILL_DIR` to permanently add an extra skill search directory. It has lower precedence than `--skill-dir` but higher precedence than `~/.initrunner/skills/`.

```bash
export INITRUNNER_SKILL_DIR=/opt/shared-skills
initrunner run role.yaml -i
```

## Examples

See the example skills and role in the repository:

- `examples/skills/web-researcher/SKILL.md` — Directory-format skill with web tools
- `examples/skills/code-tools.md` — Flat-format skill with filesystem and Python tools
- `examples/roles/skill-demo.yaml` — Role that composes both skills
