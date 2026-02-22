# Tutorial: Build a Site Monitor Agent

This hands-on tutorial walks you through building a **site monitor agent** — an agent that fetches web pages, summarizes changes, saves timestamped reports, remembers findings across sessions, and runs on a schedule. By the end, you'll have used every major InitRunner feature.

Each step builds on the previous one and shows the **complete YAML** so you can copy-paste at any point.

## Prerequisites

- **Python 3.11–3.12** installed
- **InitRunner** installed — see [Installation](installation.md)
- **An API key** configured — see [Setup](setup.md)

The examples below use `openai/gpt-5-mini`. To use a different provider, swap the `model:` block — see [Provider Configuration](../configuration/providers.md) for options including Anthropic, Google, Ollama, and others.

> **Hitting API issues?** Add `--dry-run` to any `initrunner run` command to simulate with a test model. This lets you verify your YAML and follow along without making API calls.

Create a working directory for the tutorial:

```bash
mkdir site-monitor && cd site-monitor
```

## Step 1: Your First Agent — A Simple Summarizer

Every agent starts with a `role.yaml` file. Create one with the minimum required fields:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: site-monitor
  description: Monitors websites and summarizes changes
spec:
  role: |
    You are a site monitoring assistant. You help users track changes
    to web pages by fetching content, summarizing it, and reporting
    what changed. Be concise and focus on meaningful changes.
  model:
    provider: openai
    name: gpt-5-mini
    temperature: 0.1
    max_tokens: 2048
  guardrails:
    max_tokens_per_run: 10000
    max_tool_calls: 5
    timeout_seconds: 60
```

Every role file has four top-level keys:

- **`apiVersion`**: Always `initrunner/v1`
- **`kind`**: Always `Agent`
- **`metadata`**: Name (lowercase, hyphens only), description, and optional tags/author/version
- **`spec`**: The agent's behavior — system prompt (`role`), model, tools, and guardrails

Validate the file, then run it:

```bash
initrunner validate role.yaml
initrunner run role.yaml -p "What can you help me with?"
```

The agent responds based on its system prompt. Without tools, it can only answer from its training data — it can't actually fetch web pages yet.

> **Troubleshooting:** If you get an API key error, make sure your key is set in the environment (`OPENAI_API_KEY`) or configured via `initrunner setup`. If the provider SDK is missing, install it with `pip install initrunner[all-models]` or the specific extra (e.g., `pip install initrunner[anthropic]`).

## Step 2: Interactive Mode — Chatting With Your Agent

You don't need to change the YAML to try interactive mode. Run the same agent with `-i`:

```bash
initrunner run role.yaml -i
```

This starts a multi-turn REPL where you can have a conversation:

```
You: What kind of sites would be good to monitor?
Agent: Good candidates for monitoring include...
You: How often should I check a news site?
Agent: For news sites, checking every few hours...
You: quit
```

The agent keeps context within a session — it remembers what you discussed earlier in the conversation. When you exit (type `quit`, `exit`, or press Ctrl+D), the session ends and context is lost. Step 5 adds memory to persist information across sessions.

> **Troubleshooting:** To exit the REPL, type `quit`, `exit`, or press Ctrl+D. If the agent seems stuck, press Ctrl+C to cancel the current request.

## Step 3: Adding Tools — Fetching Pages and Saving Reports

Tools give your agent capabilities beyond conversation. Add three tools to fetch web pages, get timestamps, and save reports:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: site-monitor
  description: Monitors websites and summarizes changes
spec:
  role: |
    You are a site monitoring assistant. You fetch web pages, summarize
    their content, and save reports.

    When asked to monitor a page:
    1. Use current_time() to get today's date
    2. Use fetch_page() to retrieve the page content
    3. Summarize the key content and any notable elements
    4. Save a report using write_file() with a timestamped filename
       like "2026-02-16-example-com.md" (date-domain format)
    5. Include the date, URL, and summary in the report content

    Always use timestamped filenames so reports can be searched by date.
  model:
    provider: openai
    name: gpt-5-mini
    temperature: 0.1
    max_tokens: 4096
  tools:
    - type: web_reader
    - type: datetime
    - type: filesystem
      root_path: ./reports
      read_only: false
      allowed_extensions:
        - .md
  guardrails:
    max_tokens_per_run: 30000
    max_tool_calls: 15
    timeout_seconds: 120
```

Three tools are now available to the agent:

- **`web_reader`**: Provides `fetch_page(url)` — fetches a URL and returns its content as markdown
- **`datetime`**: Provides `current_time()` and `parse_date()` — for timestamps
- **`filesystem`**: Provides `read_file()`, `list_directory()`, and `write_file()` — file operations scoped to `./reports`

Notice `read_only: false` on the filesystem tool — this enables `write_file()`. The `root_path` and `allowed_extensions` sandbox the agent to only write `.md` files inside `./reports/`.

Validate and run:

```bash
initrunner validate role.yaml
initrunner run role.yaml -p "Monitor https://example.com and save a report"
```

Then check the output:

```bash
ls reports/
```

You should see a file like `2026-02-16-example-com.md` containing a dated summary of the page.

> **Troubleshooting:** If you get "permission denied" on write, check that `read_only: false` is set (the default is `true`). If URL fetching fails, check your network connection. The `web_reader` tool respects `allowed_domains` and `blocked_domains` if you need to restrict access — see [Tool Reference](../agents/tools.md).

## Step 4: Autonomous Mode — Monitoring Multiple Sites

Autonomous mode lets the agent execute multi-step tasks in a loop — plan, act, observe, repeat — without you prompting each step.

> **Cost and safety note:** Autonomous mode runs multiple LLM calls in a loop. The `max_iterations` guardrail caps the number of iterations. Start low (5) and increase as needed. You can also set `autonomous_token_budget` to cap total token usage. See [Autonomous Execution](../orchestration/autonomy.md) for details.

Add `max_iterations: 5` to guardrails to limit the agentic loop:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: site-monitor
  description: Monitors websites and summarizes changes
spec:
  role: |
    You are a site monitoring assistant. You fetch web pages, summarize
    their content, and save reports.

    When asked to monitor a page:
    1. Use current_time() to get today's date
    2. Use fetch_page() to retrieve the page content
    3. Summarize the key content and any notable elements
    4. Save a report using write_file() with a timestamped filename
       like "2026-02-16-example-com.md" (date-domain format)
    5. Include the date, URL, and summary in the report content

    When monitoring multiple pages, compare findings across sites
    and note similarities and differences. Save individual reports
    for each site, then write a consolidated comparison report.

    Always use timestamped filenames so reports can be searched by date.
  model:
    provider: openai
    name: gpt-5-mini
    temperature: 0.1
    max_tokens: 4096
  tools:
    - type: web_reader
    - type: datetime
    - type: filesystem
      root_path: ./reports
      read_only: false
      allowed_extensions:
        - .md
  guardrails:
    max_tokens_per_run: 50000
    max_tool_calls: 20
    timeout_seconds: 300
    max_iterations: 5
```

Validate, then run in autonomous mode with `-a`:

```bash
initrunner validate role.yaml
initrunner run role.yaml -a -p "Monitor these 3 sites and write a comparison report: https://example.com, https://example.org, https://example.net"
```

The agent autonomously fetches each URL, writes individual reports, then produces a consolidated comparison — all in one run. You'll see it iterate through plan-execute-reflect cycles until it finishes or hits `max_iterations`.

> **Troubleshooting:** If the agent loops without finishing, lower `max_iterations` or add `autonomous_token_budget: 30000` to guardrails for a hard token cap. If token usage is too high, use a smaller model or reduce `max_tokens`.

## Step 5: Memory — Tracking Changes Over Time

Memory lets your agent persist information across sessions. Add a `memory:` block:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: site-monitor
  description: Monitors websites and summarizes changes
spec:
  role: |
    You are a site monitoring assistant. You fetch web pages, summarize
    their content, and save reports.

    When asked to monitor a page:
    1. Use current_time() to get today's date
    2. Use fetch_page() to retrieve the page content
    3. Summarize the key content and any notable elements
    4. Save a report using write_file() with a timestamped filename
       like "2026-02-16-example-com.md" (date-domain format)
    5. Include the date, URL, and summary in the report content

    When monitoring multiple pages, compare findings across sites
    and note similarities and differences. Save individual reports
    for each site, then write a consolidated comparison report.

    Always use timestamped filenames so reports can be searched by date.

    Memory guidelines:
    - After each monitoring run, use remember() to store key findings
      with category "monitoring" (e.g., "example.com homepage featured
      a new product launch on 2026-02-16")
    - Before reporting, use recall() to check what you found last time
      and highlight what changed
    - Use list_memories() when asked for a summary of past observations
  model:
    provider: openai
    name: gpt-5-mini
    temperature: 0.1
    max_tokens: 4096
  tools:
    - type: web_reader
    - type: datetime
    - type: filesystem
      root_path: ./reports
      read_only: false
      allowed_extensions:
        - .md
  memory:
    max_sessions: 10
    max_memories: 1000
    max_resume_messages: 20
  guardrails:
    max_tokens_per_run: 50000
    max_tool_calls: 20
    timeout_seconds: 300
    max_iterations: 5
```

The `memory:` block enables two things:

- **Short-term session persistence**: Conversation history is saved, so you can resume sessions with `--resume`
- **Long-term semantic memory**: Three tools are auto-registered — `remember(content, category)`, `recall(query)`, and `list_memories()` — for storing and searching facts across sessions

Try it in interactive mode:

```bash
initrunner validate role.yaml
initrunner run role.yaml -i
```

```
You: Monitor https://example.com and save a report
Agent: [fetches page, saves report, remembers findings]
You: quit
```

Start a new session and ask about previous findings:

```bash
initrunner run role.yaml -i
```

```
You: What did you find last time you checked example.com?
Agent: Based on my memories, when I last checked example.com on...
```

Or resume the previous session directly with `--resume`:

```bash
initrunner run role.yaml -i --resume
```

This restores the conversation history so the agent has full context from where you left off — not just semantic memories, but the actual messages.

For more details on short-term vs long-term memory, see [Memory System](../core/memory.md).

> **Troubleshooting:** If memories aren't persisting, make sure the `memory:` block is present in your YAML. The `--resume` flag requires `memory:` to be configured — without it, there's nothing to resume from.

## Step 6: Knowledge Base — Searching Past Reports

By now your `./reports/` directory has several timestamped markdown files from the previous steps. You can turn these into a searchable knowledge base with the `ingest:` block.

If you don't have enough reports yet, create a few samples:

```bash
mkdir -p reports
cat > reports/2026-02-14-example-com.md << 'EOF'
# Site Report: example.com
**Date:** 2026-02-14
**URL:** https://example.com

## Summary
The Example Domain page displays a simple informational page with a heading
"Example Domain" and a short paragraph explaining this domain is for use in
illustrative examples. Contains a link to IANA for more information.
EOF

cat > reports/2026-02-15-example-com.md << 'EOF'
# Site Report: example.com
**Date:** 2026-02-15
**URL:** https://example.com

## Summary
No changes detected from previous check. The page still shows the standard
"Example Domain" content with the IANA reference link.
EOF
```

Add the `ingest:` block to your role:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: site-monitor
  description: Monitors websites and summarizes changes
spec:
  role: |
    You are a site monitoring assistant. You fetch web pages, summarize
    their content, and save reports.

    When asked to monitor a page:
    1. Use current_time() to get today's date
    2. Use fetch_page() to retrieve the page content
    3. Summarize the key content and any notable elements
    4. Save a report using write_file() with a timestamped filename
       like "2026-02-16-example-com.md" (date-domain format)
    5. Include the date, URL, and summary in the report content

    When monitoring multiple pages, compare findings across sites
    and note similarities and differences. Save individual reports
    for each site, then write a consolidated comparison report.

    Always use timestamped filenames so reports can be searched by date.

    Memory guidelines:
    - After each monitoring run, use remember() to store key findings
      with category "monitoring" (e.g., "example.com homepage featured
      a new product launch on 2026-02-16")
    - Before reporting, use recall() to check what you found last time
      and highlight what changed
    - Use list_memories() when asked for a summary of past observations

    Knowledge base guidelines:
    - When asked about past monitoring results, ALWAYS call
      search_documents() first to find relevant reports
    - Cite the report date and URL when referencing past findings
    - Use read_file() to view a full report when the search snippet
      isn't enough context
  model:
    provider: openai
    name: gpt-5-mini
    temperature: 0.1
    max_tokens: 4096
  tools:
    - type: web_reader
    - type: datetime
    - type: filesystem
      root_path: ./reports
      read_only: false
      allowed_extensions:
        - .md
  ingest:
    sources:
      - ./reports/**/*.md
    chunking:
      strategy: fixed
      chunk_size: 512
      chunk_overlap: 50
  memory:
    max_sessions: 10
    max_memories: 1000
    max_resume_messages: 20
  guardrails:
    max_tokens_per_run: 50000
    max_tool_calls: 20
    timeout_seconds: 300
    max_iterations: 5
```

Validate, then index the reports:

```bash
initrunner validate role.yaml
initrunner ingest role.yaml
```

The ingestion pipeline reads all `.md` files matching the glob pattern, chunks them, generates embeddings, and stores them in a local Zvec vector database. This auto-registers a `search_documents(query)` tool for the agent.

Now query your report history:

```bash
initrunner run role.yaml -p "When did I last check example.com? What did the page contain?"
```

The agent searches the indexed reports and answers with specific dates and content from your timestamped files.

When you add new reports (from monitoring runs), re-run `initrunner ingest role.yaml` to update the index. For more on RAG patterns, see [Ingestion Pipeline](../core/ingestion.md) and [RAG Guide](../core/rag-guide.md).

> **Troubleshooting:** If search returns nothing, make sure you ran `initrunner ingest role.yaml` after creating the reports. If results seem off, check that your report files have substantive content for the embeddings to index.

## Step 7: Scheduled Monitoring — Triggers and Daemon Mode

Triggers let your agent run automatically on a schedule. Add a `triggers:` block with a cron schedule and a `sinks:` block to log results:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: site-monitor
  description: Monitors websites and summarizes changes
spec:
  role: |
    You are a site monitoring assistant. You fetch web pages, summarize
    their content, and save reports.

    When asked to monitor a page:
    1. Use current_time() to get today's date
    2. Use fetch_page() to retrieve the page content
    3. Summarize the key content and any notable elements
    4. Save a report using write_file() with a timestamped filename
       like "2026-02-16-example-com.md" (date-domain format)
    5. Include the date, URL, and summary in the report content

    When monitoring multiple pages, compare findings across sites
    and note similarities and differences. Save individual reports
    for each site, then write a consolidated comparison report.

    Always use timestamped filenames so reports can be searched by date.

    Memory guidelines:
    - After each monitoring run, use remember() to store key findings
      with category "monitoring" (e.g., "example.com homepage featured
      a new product launch on 2026-02-16")
    - Before reporting, use recall() to check what you found last time
      and highlight what changed
    - Use list_memories() when asked for a summary of past observations

    Knowledge base guidelines:
    - When asked about past monitoring results, ALWAYS call
      search_documents() first to find relevant reports
    - Cite the report date and URL when referencing past findings
    - Use read_file() to view a full report when the search snippet
      isn't enough context
  model:
    provider: openai
    name: gpt-5-mini
    temperature: 0.1
    max_tokens: 4096
  tools:
    - type: web_reader
    - type: datetime
    - type: filesystem
      root_path: ./reports
      read_only: false
      allowed_extensions:
        - .md
  ingest:
    sources:
      - ./reports/**/*.md
    chunking:
      strategy: fixed
      chunk_size: 512
      chunk_overlap: 50
  memory:
    max_sessions: 10
    max_memories: 1000
    max_resume_messages: 20
  triggers:
    - type: cron
      schedule: "* * * * *"
      prompt: "Monitor https://example.com and save a report. Compare with previous findings."
  sinks:
    - type: file
      path: ./logs/monitor.jsonl
      format: json
  guardrails:
    max_tokens_per_run: 50000
    max_tool_calls: 20
    timeout_seconds: 300
    max_iterations: 5
```

The trigger fires every minute (for demo purposes) and sends the configured `prompt` to the agent. The file sink logs every run result as JSON to `./logs/monitor.jsonl`.

Validate and start the daemon:

```bash
initrunner validate role.yaml
initrunner daemon role.yaml
```

Wait about a minute and you should see the trigger fire. The agent fetches the page, saves a report, and the result is logged to the sink file. Check the output:

```bash
cat logs/monitor.jsonl
```

Stop the daemon with Ctrl+C.

For production use, change the schedule to something practical:

```yaml
  triggers:
    - type: cron
      schedule: "0 * * * *"     # every hour
      prompt: "Monitor https://example.com and save a report."
```

Or daily at 9am:

```yaml
  triggers:
    - type: cron
      schedule: "0 9 * * *"    # daily at 9:00 UTC
      prompt: "Monitor https://example.com and save a report."
      timezone: US/Eastern     # optional: set timezone
```

For more on triggers and daemon mode, see [Triggers](../core/triggers.md) and [Sinks](../orchestration/sinks.md).

> **Troubleshooting:** If the trigger never fires, double-check the cron syntax — `* * * * *` means every minute. If the daemon exits immediately, run `initrunner validate role.yaml` to check for YAML errors.

## The Complete Agent

Here's the full `role.yaml` with every feature assembled:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: site-monitor
  description: Monitors websites and summarizes changes
spec:
  role: |
    You are a site monitoring assistant. You fetch web pages, summarize
    their content, and save reports.

    When asked to monitor a page:
    1. Use current_time() to get today's date
    2. Use fetch_page() to retrieve the page content
    3. Summarize the key content and any notable elements
    4. Save a report using write_file() with a timestamped filename
       like "2026-02-16-example-com.md" (date-domain format)
    5. Include the date, URL, and summary in the report content

    When monitoring multiple pages, compare findings across sites
    and note similarities and differences. Save individual reports
    for each site, then write a consolidated comparison report.

    Always use timestamped filenames so reports can be searched by date.

    Memory guidelines:
    - After each monitoring run, use remember() to store key findings
      with category "monitoring" (e.g., "example.com homepage featured
      a new product launch on 2026-02-16")
    - Before reporting, use recall() to check what you found last time
      and highlight what changed
    - Use list_memories() when asked for a summary of past observations

    Knowledge base guidelines:
    - When asked about past monitoring results, ALWAYS call
      search_documents() first to find relevant reports
    - Cite the report date and URL when referencing past findings
    - Use read_file() to view a full report when the search snippet
      isn't enough context
  model:
    provider: openai
    name: gpt-5-mini
    temperature: 0.1
    max_tokens: 4096
  tools:                            # Step 3: agent capabilities
    - type: web_reader              # fetch_page(url)
    - type: datetime                # current_time(), parse_date()
    - type: filesystem              # read_file(), write_file(), list_directory()
      root_path: ./reports
      read_only: false
      allowed_extensions:
        - .md
  ingest:                           # Step 6: searchable knowledge base
    sources:
      - ./reports/**/*.md
    chunking:
      strategy: fixed
      chunk_size: 512
      chunk_overlap: 50
  memory:                           # Step 5: persistent memory
    max_sessions: 10
    max_memories: 1000
    max_resume_messages: 20
  triggers:                         # Step 7: scheduled execution
    - type: cron
      schedule: "0 * * * *"
      prompt: "Monitor https://example.com and save a report. Compare with previous findings."
  sinks:                            # Step 7: result logging
    - type: file
      path: ./logs/monitor.jsonl
      format: json
  guardrails:                       # Safety limits
    max_tokens_per_run: 50000
    max_tool_calls: 20
    timeout_seconds: 300
    max_iterations: 5
```

## What's Next

Now that you've built a complete agent, explore more of what InitRunner can do:

- **Pre-built templates**: Run three dev workflow agents (PR review, changelog, CI explainer) in 10 minutes — see [Templates Tutorial](template-tutorial.md)
- **More tools**: [git](../agents/tools.md), [shell](../agents/tools.md), [sql](../agents/tools.md), [http](../agents/tools.md), [slack](../agents/tools.md), [MCP servers](../agents/tools.md), and [custom tools](../agents/tool_creation.md)
- **Multi-agent delegation**: Have agents call other agents — see [Delegation](../orchestration/delegation.md)
- **Compose pipelines**: Orchestrate multiple agents with `compose.yaml` — see [Agent Composer](../orchestration/agent_composer.md)
- **Web dashboard**: Monitor agents in your browser with `initrunner ui` — see [Dashboard](../interfaces/dashboard.md)
- **Terminal UI**: Full-featured TUI with `initrunner tui` — see [TUI](../interfaces/tui.md)
- **API server**: Expose agents as OpenAI-compatible endpoints with `initrunner serve` — see [API Server](../interfaces/server.md)
- **Role generation**: Scaffold new agents with `initrunner init` or generate them from descriptions with `initrunner create` — see [Role Generation](../agents/role_generation.md)
- **CLI reference**: Full command reference — see [CLI](cli.md)
