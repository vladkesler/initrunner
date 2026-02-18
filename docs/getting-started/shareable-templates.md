# Shareable Templates — One Command, Copy-Paste Output

For a hands-on walkthrough, see [Templates Tutorial](template-tutorial.md).

These three templates are designed for a specific workflow: **run one command, get output you paste directly into Slack or a GitHub PR**. The formatted output *is* the product — no extra steps, no post-processing.

All templates are read-only (they never modify your repo), use the project default model (`openai/gpt-5-mini`), and work out of the box with no configuration beyond an API key.

## Quick Start

```bash
# PR review → paste into GitHub PR comment
initrunner run examples/roles/pr-reviewer.yaml -p "Review changes vs main"

# Changelog → paste into Slack channel
initrunner run examples/roles/changelog-slack.yaml -p "Changelog since v1.2.0"

# CI failure explanation → paste into PR comment or issue
initrunner run examples/roles/ci-explainer.yaml -p "Explain the failure in /tmp/build.log"
```

---

## PR Reviewer

**File:** [`examples/roles/pr-reviewer.yaml`](../../examples/roles/pr-reviewer.yaml)

Reviews the diff between your current branch and `main`, then produces a GitHub-flavored Markdown review ready to paste into a PR comment.

### Usage

```bash
# Review current branch against main
initrunner run examples/roles/pr-reviewer.yaml -p "Review changes vs main"

# Review a specific range
initrunner run examples/roles/pr-reviewer.yaml -p "Review changes in main...feature-branch"

# Focus on specific concerns
initrunner run examples/roles/pr-reviewer.yaml -p "Review changes vs main, focusing on security"
```

### Tools Used

| Tool | Mode | Purpose |
|------|------|---------|
| `git` | read-only | `git_changed_files`, `git_diff`, `git_log` to inspect the branch diff |
| `filesystem` | read-only | `read_file` for surrounding code context |

### Output Format

The output is GitHub-flavored Markdown with severity-tagged findings:

```markdown
## Review: ✅ Approve

**Summary**: Clean implementation of the caching layer with good test coverage.

### Findings

🟡 **Major**
- **`src/cache.py:42`** — Cache key doesn't account for query parameters.
  > Consider hashing the full URL including query string:
  > `key = hashlib.sha256(url.encode()).hexdigest()`

🔵 **Minor**
- **`src/cache.py:15`** — `TTL` constant is defined but not documented.

### What's Good
- Thread-safe implementation using `threading.Lock`
- Comprehensive test coverage for edge cases

---
_Files reviewed: 3 | Findings: 0 critical, 1 major, 1 minor, 0 nit_
```

**Verdict emojis:** `✅` Approve, `⚠️` Request Changes, `💬` Needs Discussion. Empty severity sections are omitted.

### Configuration

| Setting | Value |
|---------|-------|
| Temperature | `0.1` |
| Max tool calls | `30` |
| Timeout | `300s` |

---

## Changelog for Slack

**File:** [`examples/roles/changelog-slack.yaml`](../../examples/roles/changelog-slack.yaml)

Generates a changelog from git history formatted in Slack `mrkdwn` — ready to paste into a Slack channel.

### Usage

```bash
# Changelog since a tag
initrunner run examples/roles/changelog-slack.yaml -p "Changelog since v1.2.0"

# Last N commits
initrunner run examples/roles/changelog-slack.yaml -p "Changelog for the last 20 commits"

# Between two tags
initrunner run examples/roles/changelog-slack.yaml -p "What changed between v1.1.0 and v1.2.0?"
```

### Tools Used

| Tool | Mode | Purpose |
|------|------|---------|
| `git` | read-only | `git_diff` with ref ranges for file-change stats |
| `shell` | `allowed_commands: [git]` | `git log <range>` for range-based history (the built-in `git_log` tool has no `ref` parameter) |
| `datetime` | — | `get_current_time` for the date header |

> **Why shell?** The built-in `git_log(max_count, format)` function accepts no `ref` argument, so range-based changelogs like "since v1.2.0" require `git log v1.2.0..HEAD` via the shell tool. The shell is restricted to `git` commands only.

### Output Format

The output uses Slack `mrkdwn` syntax (not Markdown — Slack has its own formatting):

```
*Release Notes — 2026-02-18*
_v1.2.0 → HEAD (14 commits by 3 contributors)_

*Features*
• Add caching layer for API responses (`abc1234`)
• Support WebSocket connections in gateway (`def5678`)

*Fixes*
• Fix race condition in session cleanup (`111aaa`)

*Breaking Changes*
• ⚠️ Remove deprecated v1 API endpoints (`222bbb`)

*Maintenance*
• Update dependencies to latest versions (`333ccc`)

*Contributors*: @alice, @bob, @carol
*Stats*: 14 commits · 8 files changed · +240 / −85 lines
```

Commits are categorized by conventional-commit prefix (`feat`, `fix`, `docs`, `refactor`, `perf`, `chore`, `breaking`). Commits without a prefix are categorized by content. Empty categories are omitted.

### Configuration

| Setting | Value |
|---------|-------|
| Temperature | `0.1` |
| Max tool calls | `15` |
| Timeout | `120s` |

---

## CI Failure Explainer

**File:** [`examples/roles/ci-explainer.yaml`](../../examples/roles/ci-explainer.yaml)

Reads a CI/CD log file, identifies the root failure (not cascading noise), and produces a GitHub-flavored Markdown explanation ready to paste into a PR comment or issue.

### Usage

```bash
# Explain a local log file
initrunner run examples/roles/ci-explainer.yaml -p "Explain the failure in /tmp/build.log"

# Point to a log in the repo
initrunner run examples/roles/ci-explainer.yaml -p "What went wrong in ./ci-output/test-results.log?"

# Multiple logs
initrunner run examples/roles/ci-explainer.yaml -p "Analyze the build failure in /tmp/build.log and /tmp/test.log"
```

### Tools Used

| Tool | Mode | Purpose |
|------|------|---------|
| `filesystem` | read-only, root `/` | `read_file` on log files (anywhere on disk) and source files in the repo |
| `git` | read-only | `git_log`, `git_blame` for context on when failing code was introduced |

> **Why root `/`?** CI logs are typically written to `/tmp` or other locations outside the repo. The filesystem root is set to `/` so logs at any path are accessible. An extension allowlist (`.log`, `.txt`, `.json`, `.xml`, `.yaml`, `.yml`, `.py`, `.js`, `.ts`, `.go`, `.rs`, `.java`, `.rb`, `.sh`) restricts what file types can be read.

### Output Format

```markdown
## CI Failure: Test Failure

**TL;DR**: The `test_user_auth` test fails because the mock database
fixture returns `None` instead of a `User` object after the schema migration.

### What Failed
```
FAILED tests/test_auth.py::test_user_auth - AttributeError: 'NoneType'
object has no attribute 'email'
  File "src/auth.py", line 42, in authenticate
    return user.email
```

### Why It Failed
The `conftest.py` fixture `mock_db` was not updated after the `users` table
schema change in commit `abc1234`. The fixture still returns the old column
set, which causes `get_user_by_id()` to return `None`.

### How to Fix
1. Update `tests/conftest.py` — add the new `email_verified` column:
   ```python
   mock_users = [{"id": 1, "email": "test@x.com", "email_verified": True}]
   ```
2. Run the failing test to confirm:
   ```bash
   pytest tests/test_auth.py::test_user_auth -v
   ```
3. Commit and push.

---
_Stage: test | File: `tests/conftest.py:18` | Since: `abc1234`_
```

**Failure categories:** Build Error, Test Failure, Lint Error, Dependency Issue, Timeout, Infrastructure, Permission Error. The footer fields (Stage, File, Since) are included only when determinable from the logs.

### Configuration

| Setting | Value |
|---------|-------|
| Temperature | `0.0` (precision for log analysis) |
| Max tool calls | `20` |
| Timeout | `180s` |

---

## Tips

**Pipe output to clipboard** for instant pasting:

```bash
# macOS
initrunner run examples/roles/pr-reviewer.yaml -p "Review changes vs main" 2>/dev/null | pbcopy

# Linux (X11)
initrunner run examples/roles/pr-reviewer.yaml -p "Review changes vs main" 2>/dev/null | xclip -selection clipboard

# Linux (Wayland)
initrunner run examples/roles/pr-reviewer.yaml -p "Review changes vs main" 2>/dev/null | wl-copy
```

**Use shell aliases** for frequent workflows:

```bash
alias pr-review='initrunner run examples/roles/pr-reviewer.yaml -p'
alias changelog='initrunner run examples/roles/changelog-slack.yaml -p'
alias ci-explain='initrunner run examples/roles/ci-explainer.yaml -p'

# Then:
pr-review "Review changes vs main"
changelog "Changelog since v1.0.0"
ci-explain "Explain /tmp/build.log"
```

**Customize the model** — these templates work with any provider. Override the model block in your own copy:

```yaml
model:
  provider: anthropic
  name: claude-sonnet-4-20250514
  temperature: 0.1
  max_tokens: 4096
```

See [Provider Configuration](../configuration/providers.md) for all supported providers.
