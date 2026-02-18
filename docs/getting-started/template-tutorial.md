# Tutorial: Dev Workflow Agents in 10 Minutes

Three pre-built templates that slot into your dev workflow: **changelog for Slack**, **PR reviewer**, and **CI failure explainer**. Each produces copy-paste-ready output — run one command, grab the result.

This tutorial walks through all three with hands-on exercises. No YAML editing required.

> For the full configuration reference, see [Shareable Templates](shareable-templates.md). To learn InitRunner concepts step-by-step, see the [Site Monitor Tutorial](tutorial.md).

## Prerequisites

- **Python 3.11+** installed
- **InitRunner** installed — see [Installation](installation.md)
- **An API key** configured — see [Setup](setup.md)
- **A git repository** with some commit history (your own project works)

The templates use `openai/gpt-5-mini` by default. To use a different provider, see [Make Them Yours](#make-them-yours) below.

> **No API key?** Add `--dry-run` to any `initrunner run` command to simulate with a test model. You can follow the entire tutorial without making API calls.

---

## 1. Changelog for Slack

This one needs zero setup — just point it at your existing git history.

### Run it

```bash
initrunner run examples/roles/changelog-slack.yaml -p "Changelog for the last 5 commits"
```

### Expected output

The agent reads your git log, categorizes commits by conventional-commit prefix, and produces Slack `mrkdwn`:

```
*Release Notes — 2026-02-18*
_Last 5 commits by 2 contributors_

*Features*
• Add audio-assistant example role (`e0e7031`)

*Maintenance*
• Update all docs, tests, and examples to gpt-5-mini default (`7afefd5`)
• Add CHANGELOG 1.0.0 section and update README version (`1bbdb49`)

*Contributors*: @alice, @bob
*Stats*: 5 commits · 12 files changed · +180 / −45 lines
```

Paste that directly into a Slack channel — it renders correctly because it uses Slack's `mrkdwn` syntax (`*bold*`, `_italic_`, `•` bullets) instead of Markdown.

### Try variations

```bash
# Tag-based range
initrunner run examples/roles/changelog-slack.yaml -p "Changelog since v1.0.0"

# More commits
initrunner run examples/roles/changelog-slack.yaml -p "Last 20 commits"
```

> **Under the hood:** The built-in `git_log` tool has no `ref` parameter, so range-based queries like "since v1.0.0" need `git log v1.0.0..HEAD` via the shell. That's why this template includes a `shell` tool restricted to `allowed_commands: [git]` — it can run git commands but nothing else.

<details>
<summary>Full YAML: changelog-slack.yaml</summary>

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: changelog-slack
  description: Generates a changelog formatted in Slack mrkdwn, ready to paste into a channel
  tags:
    - example
    - shareable
    - git
    - developer-tools
  author: initrunner
  version: "1.0.0"
spec:
  role: |
    You are a release-notes writer. Your output is Slack mrkdwn that the user
    will paste directly into a Slack channel, so formatting matters.

    Workflow:
    1. Determine the commit range from the user's prompt.
       - If the prompt includes a tag or range (e.g. "since v1.2.0"), run:
         shell_execute command="git log v1.2.0..HEAD --pretty=format:\"%h %an %s\""
         (adjust the range to match the user's request).
       - Otherwise, fall back to the built-in git_log with an appropriate max_count.
    2. Use git_diff with the same ref range and look at the --stat style output
       (ref="v1.2.0..HEAD" or similar) to collect file-change stats.
    3. Use get_current_time for the date header.
    4. Categorize each commit by its conventional-commit prefix:
       - feat      → *Features*
       - fix       → *Fixes*
       - BREAKING  → *Breaking Changes*
       - docs      → *Documentation*
       - refactor  → *Refactoring*
       - perf      → *Performance*
       - chore, ci, build, test → *Maintenance*
       If a commit has no prefix, categorize by reading the message content.
    5. Format the output as Slack mrkdwn (see template below).

    Output template (omit empty categories):

    *Release Notes — YYYY-MM-DD*
    _v1.2.0 → HEAD (N commits by N contributors)_

    *Features*
    • Brief description (`abc1234`)
    • Brief description (`def5678`)

    *Fixes*
    • Brief description (`111aaa`)

    *Breaking Changes*
    • ⚠️ Description (`222bbb`)

    *Maintenance*
    • Description (`333ccc`)

    *Contributors*: @alice, @bob, @carol
    *Stats*: N commits · N files changed · +NNN / −NNN lines

    Slack formatting rules:
    - *bold* for headings and emphasis
    - _italic_ for subheadings
    - • (bullet) for list items
    - `backticks` for commit hashes and code
    - No Markdown headings (#), no triple backticks — these don't render in Slack

    Do NOT pad output with disclaimers or preamble — the mrkdwn IS the deliverable.
  model:
    provider: openai
    name: gpt-5-mini
    temperature: 0.1
    max_tokens: 4096
  tools:
    - type: git
      repo_path: .
      read_only: true
    - type: shell
      allowed_commands:
        - git
      require_confirmation: false
      timeout_seconds: 30
    - type: datetime
  guardrails:
    max_tokens_per_run: 30000
    max_tool_calls: 15
    timeout_seconds: 120
    max_request_limit: 20
```

</details>

---

## 2. PR Reviewer

This template reviews the diff between your current branch and `main`. We'll create a branch with a deliberately buggy file so you can see it in action.

### Setup

Create a branch with a Python file containing three planted issues:

```bash
git checkout -b demo-review
```

Create a file called `app.py`:

```python
import os
import json  # unused

def get_user(db, user_id):
    query = f"SELECT * FROM users WHERE id = {user_id}"
    result = db.execute(query)
    return result.fetchone()

def process_order(order):
    total = order["items"][0]["price"] * order["items"][0]["qty"]
    return {"total": total, "status": "processed"}
```

```bash
git add app.py && git commit -m "feat: add user lookup and order processing"
```

The file has three issues: an unused `json` import, a SQL injection vulnerability in `get_user`, and a missing null check in `process_order` (crashes if `items` is empty).

### Run it

```bash
initrunner run examples/roles/pr-reviewer.yaml -p "Review changes vs main"
```

### Expected output

The agent diffs your branch against `main` and produces a severity-tagged review:

```markdown
## Review: ⚠️ Request Changes

**Summary**: New user lookup has a SQL injection vulnerability; order processing
lacks input validation.

### Findings

🔴 **Critical**
- **`app.py:6`** — SQL injection via string interpolation in query.
  > Use parameterized queries:
  > `db.execute("SELECT * FROM users WHERE id = ?", (user_id,))`

🟡 **Major**
- **`app.py:10`** — `order["items"][0]` will raise `IndexError` if items is empty.
  > Add a guard: `if not order.get("items"): return {"total": 0, "status": "empty"}`

⚪ **Nit**
- **`app.py:2`** — `json` is imported but never used.

### What's Good
- Clear function signatures with descriptive parameter names

---
_Files reviewed: 1 | Findings: 1 critical, 1 major, 0 minor, 1 nit_
```

> **Under the hood:** The agent uses `git_changed_files ref="main...HEAD"` to find modified files, then `git_diff ref="main...HEAD"` to read the actual changes. Both the `git` and `filesystem` tools are set to `read_only: true` — the reviewer can never modify your code.

### Cleanup

```bash
git checkout main && git branch -D demo-review
```

<details>
<summary>Full YAML: pr-reviewer.yaml</summary>

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: pr-reviewer
  description: Reviews PR changes and produces GitHub-flavored Markdown ready to paste into a PR comment
  tags:
    - example
    - shareable
    - engineering
    - review
  author: initrunner
  version: "1.0.0"
spec:
  role: |
    You are a senior engineer performing a pull-request review. Your output is
    GitHub-flavored Markdown that the user will paste directly into a PR comment,
    so formatting matters.

    Workflow:
    1. Use git_changed_files with ref="main...HEAD" to list what changed.
    2. Use git_diff with ref="main...HEAD" per file (use the path argument to
       narrow results if the full diff is truncated).
    3. Use read_file on changed files when you need surrounding context.
    4. Use git_log to read recent commit messages for intent.
    5. Produce the formatted review below.

    Output format (omit any severity section that has no findings):

    ## Review: [verdict emoji] [Approve | Request Changes | Needs Discussion]

    **Summary**: One-sentence overall assessment.

    ### Findings

    🔴 **Critical**
    - **`path/to/file.py:42`** — Description of issue.
      > Suggested fix or code snippet

    🟡 **Major**
    - ...

    🔵 **Minor**
    - ...

    ⚪ **Nit**
    - ...

    ### What's Good
    - Positive callout 1
    - Positive callout 2

    ---
    _Files reviewed: N | Findings: N critical, N major, N minor, N nit_

    Verdict emojis: ✅ Approve, ⚠️ Request Changes, 💬 Needs Discussion.

    Guidelines:
    - Focus on correctness, security, readability, and maintainability.
    - Reference exact file paths and line numbers when possible.
    - Suggest concrete fixes — include code snippets in fenced blocks.
    - Be constructive; explain the "why" behind each finding.
    - Do NOT pad output with disclaimers or preamble — the Markdown IS the deliverable.
  model:
    provider: openai
    name: gpt-5-mini
    temperature: 0.1
    max_tokens: 4096
  tools:
    - type: git
      repo_path: .
      read_only: true
    - type: filesystem
      root_path: .
      read_only: true
  guardrails:
    max_tokens_per_run: 50000
    max_tool_calls: 30
    timeout_seconds: 300
    max_request_limit: 50
```

</details>

---

## 3. CI Failure Explainer

This template reads a CI/CD log file, finds the root failure, and explains how to fix it. We'll create a realistic build log to test with.

### Setup

Create a sample build log:

```bash
cat > /tmp/build.log << 'EOF'
[2026-02-18T10:00:01Z] Step 1/6: Checkout repository
[2026-02-18T10:00:01Z] ✓ Checked out abc1234
[2026-02-18T10:00:02Z] Step 2/6: Set up Python 3.11
[2026-02-18T10:00:05Z] ✓ Python 3.11.8 installed
[2026-02-18T10:00:06Z] Step 3/6: Install dependencies
[2026-02-18T10:00:07Z] Collecting numpy==1.99.0
[2026-02-18T10:00:08Z] ERROR: Could not find a version that satisfies the requirement numpy==1.99.0
[2026-02-18T10:00:08Z] ERROR: No matching distribution found for numpy==1.99.0
[2026-02-18T10:00:09Z] Step 4/6: Run tests
[2026-02-18T10:00:09Z] Skipped (dependency install failed)
[2026-02-18T10:00:09Z] Step 5/6: Build package
[2026-02-18T10:00:09Z] Skipped (dependency install failed)
[2026-02-18T10:00:09Z] Step 6/6: Upload artifacts
[2026-02-18T10:00:09Z] Skipped (dependency install failed)
EOF
```

### Run it

```bash
initrunner run examples/roles/ci-explainer.yaml -p "Explain the failure in /tmp/build.log"
```

### Expected output

The agent reads the log, identifies the root cause (not the cascading "Skipped" steps), and produces a structured explanation:

```markdown
## CI Failure: Dependency Issue

**TL;DR**: The build fails because `numpy==1.99.0` doesn't exist — pip
can't find a matching version.

### What Failed
```
ERROR: Could not find a version that satisfies the requirement numpy==1.99.0
ERROR: No matching distribution found for numpy==1.99.0
```

### Why It Failed
The `requirements.txt` (or `pyproject.toml`) pins `numpy==1.99.0`, which
has never been published. The latest stable version is 2.2.x. This is
likely a typo — `1.99.0` doesn't exist in the numpy release history.

### How to Fix
1. Update the numpy version pin to a valid release:
   ```
   numpy>=2.0,<3.0
   ```
2. Re-run the pipeline.

---
_Stage: install | File: `requirements.txt`_
```

> **Under the hood:** The `filesystem` tool uses `root_path: /` so it can read logs anywhere on disk (e.g. `/tmp`). An `allowed_extensions` allowlist restricts it to log, config, and source files — it can't read arbitrary binary files. The `temperature: 0.0` setting ensures precise, deterministic analysis.

### Cleanup

```bash
rm /tmp/build.log
```

<details>
<summary>Full YAML: ci-explainer.yaml</summary>

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: ci-explainer
  description: Reads a CI/CD log file and produces a GitHub-flavored Markdown failure explanation ready to paste into a PR comment or issue
  tags:
    - example
    - shareable
    - devops
    - ci
  author: initrunner
  version: "1.0.0"
spec:
  role: |
    You are a CI/CD failure analyst. Your output is GitHub-flavored Markdown that
    the user will paste directly into a PR comment or issue, so formatting matters.

    Workflow:
    1. Use read_file to read the log file referenced in the user's prompt.
    2. Scan the log bottom-up — errors and failures cluster at the end.
    3. Identify the decisive failure: the first root error, not cascading noise.
    4. Optionally use read_file on implicated source files and git_log or
       git_blame for context on when/why the failing code was introduced.
    5. Classify the failure into one of these categories:
       Build Error, Test Failure, Lint Error, Dependency Issue, Timeout,
       Infrastructure, Permission Error.
    6. Produce the formatted explanation below.

    Output format:

    ## CI Failure: [Category]

    **TL;DR**: One-sentence plain-English summary of what went wrong.

    ### What Failed
    ```
    Exact error message or failing command, extracted from the logs
    ```

    ### Why It Failed
    Plain-English root cause analysis. Reference specific lines and files.

    ### How to Fix
    1. Step-by-step actionable instructions
    2. Include exact commands or code changes
    3. That someone can follow right now

    ---
    _Stage: build/test/lint/deploy | File: `path/file.py:42` | Since: `abc1234`_

    Guidelines:
    - Extract the exact error — do not paraphrase log output in the "What Failed" block.
    - Distinguish root cause from cascading failures.
    - Provide concrete, copy-pasteable fix commands or code changes.
    - Keep the explanation accessible to someone unfamiliar with the codebase.
    - The footer line fields (Stage, File, Since) are optional — include only what
      you can determine from the logs and git history.
    - Do NOT pad output with disclaimers or preamble — the Markdown IS the deliverable.
  model:
    provider: openai
    name: gpt-5-mini
    temperature: 0.0
    max_tokens: 4096
  tools:
    - type: filesystem
      root_path: /
      read_only: true
      allowed_extensions:
        - .log
        - .txt
        - .json
        - .xml
        - .yaml
        - .yml
        - .py
        - .js
        - .ts
        - .go
        - .rs
        - .java
        - .rb
        - .sh
    - type: git
      repo_path: .
      read_only: true
  guardrails:
    max_tokens_per_run: 40000
    max_tool_calls: 20
    timeout_seconds: 180
    max_request_limit: 25
```

</details>

---

## Make Them Yours

All three templates share the same customization surface. Copy one and edit:

```bash
cp examples/roles/pr-reviewer.yaml my-reviewer.yaml
```

**Swap the model** — any supported provider works:

```yaml
model:
  provider: anthropic
  name: claude-sonnet-4-20250514
  temperature: 0.1
  max_tokens: 4096
```

See [Provider Configuration](../configuration/providers.md) for all options including Google, Ollama, and others.

**Tune guardrails** for your repo size:

```yaml
guardrails:
  max_tool_calls: 50      # increase for large PRs with many files
  timeout_seconds: 600    # increase for slow models or big repos
```

**Edit the system prompt** — `spec.role` is free-text. Quick tweaks:

- Focus on security: add "Focus exclusively on security vulnerabilities. Ignore style and formatting issues."
- Match your stack: add "This is a Django project using PostgreSQL. Flag Django-specific anti-patterns."
- Change output language: add "Write all output in Japanese."

Then run your copy:

```bash
initrunner run my-reviewer.yaml -p "Review changes vs main"
```

---

## Tips

**Pipe output to clipboard** for instant pasting:

```bash
# macOS
initrunner run examples/roles/changelog-slack.yaml -p "Last 10 commits" 2>/dev/null | pbcopy

# Linux (X11)
initrunner run examples/roles/changelog-slack.yaml -p "Last 10 commits" 2>/dev/null | xclip -selection clipboard

# Linux (Wayland)
initrunner run examples/roles/changelog-slack.yaml -p "Last 10 commits" 2>/dev/null | wl-copy
```

The `2>/dev/null` strips stderr (progress messages) so only the agent's output reaches the clipboard.

**Shell aliases** for frequent use:

```bash
alias pr-review='initrunner run examples/roles/pr-reviewer.yaml -p'
alias changelog='initrunner run examples/roles/changelog-slack.yaml -p'
alias ci-explain='initrunner run examples/roles/ci-explainer.yaml -p'

# Then:
pr-review "Review changes vs main"
changelog "Changelog since v1.0.0"
ci-explain "Explain /tmp/build.log"
```

**Dry-run for testing** — validate your YAML and prompt without API calls:

```bash
initrunner run my-reviewer.yaml -p "Review changes vs main" --dry-run
```

---

## What's Next

- [Shareable Templates Reference](shareable-templates.md) — full configuration details and output format specs for all three templates
- [Site Monitor Tutorial](tutorial.md) — build an agent from scratch across 7 steps (tools, memory, RAG, triggers)
- [Creating Tools](../agents/tool_creation.md) — add custom tools to any agent
- [Provider Configuration](../configuration/providers.md) — use Anthropic, Google, Ollama, or other providers
- [Compose Orchestration](../orchestration/delegation.md) — chain multiple agents together
