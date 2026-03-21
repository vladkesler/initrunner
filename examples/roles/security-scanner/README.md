# Security Scanner

Runs static analysis scanners, verifies each finding by tracing data flow through your source code, and reports only the vulnerabilities it is confident about. Learns your false positives so they stay suppressed.

## Quick start

```bash
# Install
initrunner install vladkesler/security-scanner

# Install scanners (optional -- skills degrade gracefully)
pip install bandit       # Python SAST

# Set your API key
export OPENAI_API_KEY="your-api-key"

# Scan the current repository
initrunner run role.yaml -p "Scan this repository for security issues"
```

## Prerequisites

1. **bandit** (for Python scanning) -- `pip install bandit`. If missing, the agent skips Python SAST and moves on.
2. **node/npm** (for JavaScript) -- `npm audit` checks dependency vulnerabilities. If missing, the agent skips JS scanning.
3. **rg** (ripgrep, for secret detection) -- Pre-installed on most dev machines. Used for pattern-based secret scanning.

All scanner skills are optional. The agent detects which tools are available and activates only the relevant skills.

## Example session

```
> initrunner run role.yaml -p "Scan this repository for security issues"

[detecting languages] Found pyproject.toml, package.json

> activate_skill("python-sast")
> activate_skill("javascript-sast")
> activate_skill("secret-detection")

> shell: bandit -r src/ -f json -ll --exclude .venv,tests
[2 findings]

> read_file("src/db/queries.py", lines="42-55")
[traces f-string SQL query, confirms user input from request.args]

> recall("src/db/queries.py SQL injection")
[no prior false positive -- this is new]

{
  "findings": [
    {
      "file": "src/db/queries.py",
      "line": 45,
      "severity": "critical",
      "category": "sql-injection",
      "description": "SQL query built with f-string using request.args['user_id']",
      "evidence": "query = f\"SELECT * FROM users WHERE id = {request.args['user_id']}\"",
      "recommendation": "Use parameterized query: cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))",
      "confidence": "high"
    }
  ],
  "summary": {
    "total": 1,
    "critical": 1,
    "high": 0,
    "medium": 0,
    "low": 0,
    "suppressed": 1
  },
  "scan_metadata": {
    "languages_detected": ["python", "javascript"],
    "skills_activated": ["python-sast", "javascript-sast", "secret-detection"],
    "timestamp": "2026-03-19T02:00:00Z"
  }
}
```

## Example prompts

```
Scan this repository for security issues
Scan only the src/api/ directory
Check for hardcoded secrets in this project
Run a Python-only security scan
What changed since the last scan? Scan only modified files.
```

## Daemon mode

```bash
initrunner run role.yaml --daemon
```

Runs the cron trigger at 2am UTC daily. The agent detects languages, activates scanner skills, triages findings, and outputs the structured report. Memory persists between runs -- false positives stay suppressed.

## What's inside

- **Auto-discovered skills** -- Python SAST, JavaScript SAST, secret detection, and container scanning. The agent detects your project's languages and activates only the relevant scanners.
- **Structured JSON output** -- Every scan returns a typed report with findings, severity counts, and scan metadata. Pipe it to jq, store it, or feed it to another agent.
- **Memory-powered false positive suppression** -- Tell the agent a finding is a false positive and it remembers. Future scans skip known non-issues automatically.
- **Confidence-based triage** -- Each finding is verified by reading source context and tracing data flow. LOW confidence findings (theoretical, best-practice-only) are dropped entirely.
- **Changed-files mode** -- Use git_diff to scan only modified files since the last commit or branch point.

## Adding your own scanner skill

Create a directory under `skills/` with a `SKILL.md` file:

```
skills/
  go-security/
    SKILL.md
```

```yaml
---
name: go-security
description: Go security scanning with gosec and govulncheck.
requires:
  bins: [gosec]
---

## When to activate
Use when go.mod is present in the repository.

## Scanner command
gosec -fmt json ./...

## Verification steps
...
```

The agent auto-discovers it on the next run.

## Customization

### Cron schedule

```yaml
triggers:
  - type: cron
    schedule: "0 2 * * *"    # nightly at 2am
    timezone: UTC             # change to your timezone
```

### Allowed shell commands

Add scanner binaries to the allow list:

```yaml
tools:
  - type: shell
    allowed_commands: [bandit, semgrep, npm, rg, find, cat, head, wc, gosec]
```

### Memory limits

```yaml
memory:
  semantic:
    max_memories: 500    # false positives, accepted risks
  episodic:
    max_episodes: 200    # past scan outcomes
  procedural:
    max_procedures: 100  # learned skip rules
```

## Changing the model

Edit `spec.model` in `role.yaml`. Memory uses embeddings that inherit from the model provider -- Anthropic falls back to OpenAI embeddings (`OPENAI_API_KEY` needed).

```yaml
spec:
  model:
    provider: anthropic
    name: claude-sonnet-4-5-20250929
  memory:
    embeddings:
      provider: google
      model: text-embedding-004
```
