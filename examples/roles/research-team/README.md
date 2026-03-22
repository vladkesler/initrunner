# Research Team

Research lead that delegates to specialist sub-agents in parallel. Spawns web-searcher agents for concurrent research, collects findings, and synthesizes a final report.

Showcases two reasoning primitives working together:
- **Todo** (todo_driven pattern) -- structured research plan with priorities and dependencies
- **Spawn** -- non-blocking parallel agent execution for concurrent research

## Quick start

```bash
# Install
initrunner install vladkesler/research-team

# Run a comparison
initrunner run research-team -a -p "Compare the top 3 vector databases for production RAG"

# Research a topic
initrunner run research-team -a -p "Research the current state of WebAssembly adoption in 2026"

# Analyze trade-offs
initrunner run research-team -a -p "Analyze the pros and cons of edge computing vs cloud-only"
```

## How it works

```
                    +-----------------+
                    |  Research Lead  |
                    |  (todo_driven)  |
                    +--------+--------+
                             |
                    creates todo list
                             |
              +--------------+--------------+
              |              |              |
        spawn_agent    spawn_agent    spawn_agent
              |              |              |
     +--------+--+  +--------+--+  +--------+--+
     | searcher  |  | searcher  |  | searcher  |
     | (topic A) |  | (topic B) |  | (topic C) |
     +-----------+  +-----------+  +-----------+
              |              |              |
              +--------------+--------------+
                             |
                      await_tasks
                             |
                    +--------+--------+
                    |   summarizer    |
                    +-----------------+
                             |
                      final report
```

1. The lead agent creates a todo list with one item per research question
2. For parallelizable questions, it spawns `web-searcher` agents (up to 3 concurrent)
3. Each searcher independently searches the web and returns structured findings
4. The lead awaits results, then optionally spawns a `summarizer` for cross-cutting synthesis
5. Final report combines all findings with confidence levels

## Architecture

- **`role.yaml`** -- Lead agent with think, todo, spawn, datetime tools
- **`agents/web-searcher.yaml`** -- Sub-agent with search + web_reader tools
- **`agents/summarizer.yaml`** -- Sub-agent with think tool for synthesis

## Example prompts

```
Compare the top 3 vector databases for production RAG
Research the current state of WebAssembly adoption in 2026
Analyze the pros and cons of edge computing vs cloud-only architectures
What are the leading approaches to LLM evaluation in production?
Compare Kubernetes operators vs Helm charts for application deployment
```

## Customization

Add more specialist agents in `agents/`:

```yaml
# In role.yaml spec.tools, add to the spawn agents list:
- name: code-analyst
  role_file: ./agents/code-analyst.yaml
  description: Reads and analyzes code repositories
```

Increase parallelism:

```yaml
- type: spawn
  max_concurrent: 5    # up from 3
  timeout_seconds: 180  # more time per agent
```

## Changing the model

Edit `spec.model` in all YAML files (role.yaml + agents/*.yaml):

```yaml
model:
  provider: anthropic
  name: claude-sonnet-4-20250514
```
