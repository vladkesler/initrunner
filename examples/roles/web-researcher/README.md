# Web Researcher

Autonomous web research agent with a headless browser. Navigates websites, extracts structured data, takes screenshots as evidence, fills search forms, and compiles research reports from multiple sources. Remembers site structures and extraction patterns across sessions.

## Quick start

```bash
# Install
initrunner install vladkesler/web-researcher

# Install the browser runtime
npm i -g agent-browser && agent-browser install

# Interactive session (with memory)
initrunner run web-researcher -i

# One-shot research
initrunner run web-researcher -p "Compare pricing for the top 3 project management tools"
```

Requires:
- `agent-browser` installed globally (`npm i -g agent-browser && agent-browser install`)
- `OPENAI_API_KEY` (or configure another provider)

## Example prompts

```
Compare pricing for the top 3 project management tools
Go to news.ycombinator.com and summarize the top 5 stories
Find the latest release notes for Python on python.org
Search for "best mechanical keyboards 2026" and summarize the top results
Go to github.com/trending and tell me what's popular today
Extract the product specs from this page: https://example.com/product
Take a screenshot of https://example.com and describe the layout
Fill out the search form on https://docs.python.org and find info about asyncio
```

## Example session

```
$ initrunner run web-researcher -i

You: Compare pricing for the top 3 project management tools

> think: I'll check pricing pages for Asana, Monday.com, and Jira.
> Plan: visit each pricing page, extract plan names and prices,
> build a comparison table.

> open_url("https://asana.com/pricing")
Navigated to: https://asana.com/pricing
Title: Asana Pricing - Plans for Every Team

> snapshot()
@e1: [tab] Personal    @e2: [tab] Starter    @e3: [tab] Advanced
@e4: [button] Get started  ...

> get_text()
Personal - Free - Up to 10 users...
Starter - $10.99/user/mo - Unlimited users...
Advanced - $24.99/user/mo - Portfolios, goals...

> screenshot(full_page=false)
Saved: /tmp/initrunner_browser_.../screenshot.png

> think: Got Asana pricing. Moving to Monday.com.

> open_url("https://monday.com/pricing")
...

> open_url("https://www.atlassian.com/software/jira/pricing")
...

> python: Build comparison table from extracted data

## Project Management Tool Pricing Comparison

| Feature        | Asana             | Monday.com        | Jira              |
|----------------|-------------------|-------------------|-------------------|
| Free tier      | Up to 10 users    | Up to 2 users     | Up to 10 users    |
| Starter plan   | $10.99/user/mo    | $9/seat/mo        | $7.75/user/mo     |
| Mid tier       | $24.99/user/mo    | $12/seat/mo       | $15.25/user/mo    |
| Enterprise     | Custom            | Custom             | Custom            |

Sources:
- https://asana.com/pricing (screenshot: screenshot_1.png)
- https://monday.com/pricing (screenshot: screenshot_2.png)
- https://www.atlassian.com/software/jira/pricing (screenshot: screenshot_3.png)

> close_browser()
```

## Customization

### Browser timeout

The MCP server has a 60-second timeout per tool call. Increase for slow sites:

```yaml
tools:
  - type: mcp
    transport: stdio
    command: initrunner-browser-mcp
    timeout_seconds: 120
```

### Troubleshooting: Chrome sandbox error

On Linux containers, VMs, or CI environments Chrome may fail with "No usable sandbox". Fix with:

```bash
export AGENT_BROWSER_ARGS="--no-sandbox"
initrunner run web-researcher -i
```

Or install system dependencies (requires sudo):

```bash
agent-browser install --with-deps
```

### Headed mode (visible browser)

By default the browser runs headless. To see it, set the env var before running:

```bash
export AGENT_BROWSER_HEADED=true
initrunner run web-researcher -i
```

### Token budget

```yaml
guardrails:
  max_tokens_per_run: 60000    # per research session
  max_tool_calls: 50           # increase for deep multi-page research
  timeout_seconds: 600         # 10 minutes for long research tasks
```

### Memory sizing

```yaml
memory:
  semantic:
    max_memories: 500    # site structures, extraction patterns
  episodic:
    max_episodes: 300    # research session records
  procedural:
    max_procedures: 100  # navigation workflows
```

## Changing the model

Edit `spec.model` in `role.yaml`:

```yaml
spec:
  model:
    provider: anthropic
    name: claude-sonnet-4-5-20250929
    temperature: 0.1
```
