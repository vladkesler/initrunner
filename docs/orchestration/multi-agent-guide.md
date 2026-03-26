# Choosing the Right Multi-Agent Pattern

InitRunner offers several ways to coordinate agents. This guide helps you pick the right one based on what you're trying to build.

## Decision Tree

Start here if you're not sure what you need.

```
Do you need multiple agents?
  |
  No --> Single agent with reasoning patterns
  |     (todo_driven, plan_execute, reflexion)
  |     See: docs/core/reasoning.md
  |
  Yes --> Is it one-shot work with multiple perspectives?
            |
            Yes --> Team
                    |       (2+ personas, sequential handoff or parallel)
                    |
                    No --> Is it long-running with triggers or events?
                            |
                            Yes --> Compose
                            |       (daemon with cron/file/webhook triggers, routed sinks)
                            |
                            No --> Does the parent agent decide at runtime?
                                    |
                                    Need parallel? --> Spawn
                                    (fire multiple sub-agents, poll/await results)
                                    |
                                    Need blocking? --> Delegate
                                    (call one sub-agent as a tool, get result inline)
```

## Quick Comparison

| | Single + Reasoning | Team | Compose | Spawn | Delegate |
|--|-------------------|------|---------|-------|----------|
| **Kind** | Agent | Team | Compose | Agent (tool) | Agent (tool) |
| **Config** | `spec.reasoning` | `spec.personas` | `spec.services` | `spec.tools` | `spec.tools` |
| **Who decides** | You + LLM | You (YAML) | You (YAML) | LLM (runtime) | LLM (runtime) |
| **Execution** | Iterative loop | Sequential/parallel | Trigger-driven | Non-blocking | Blocking |
| **Lifetime** | One run | One run | Daemon | Within parent run | Within parent run |
| **Triggers** | No | No | Yes | No | No |
| **Shared memory** | N/A | Yes | Yes | Optional | Optional |
| **Typical agents** | 1 | 2-5 | 2-20 | 1-5 | 1-3 |
| **Best for** | Planning, research, writing | Code review, analysis, ETL | Monitoring, bots | Parallel research | Conditional routing |

## When to Use Each

### Single Agent with Reasoning

One agent that plans, executes, and optionally self-critiques. No sub-agents needed.

```yaml
kind: Agent
spec:
  tools:
    - type: think
      critique: true
    - type: todo
  reasoning:
    pattern: todo_driven
    auto_plan: true
  autonomy: {}
```

```bash
initrunner run agent.yaml -a -p "Compare PostgreSQL vs MongoDB for our SaaS"
```

Use when: the task is complex but a single agent with the right tools can handle it. Most tasks start here.

### Team

Multiple personas process the same task, each with a different perspective. Output flows sequentially (persona A's output becomes persona B's input) or all run in parallel on the same prompt.

```yaml
kind: Team
spec:
  personas:
    triage:
      role: Gather cluster state and classify the issue.
    diagnostician:
      role: Analyze gathered data and identify root cause.
    advisor:
      role: Write fix commands with rollback plans.
  mode: sequential
  shared_memory:
    enabled: true
```

```bash
initrunner run team.yaml -p "Pods are CrashLoopBackOff in staging"
```

Use when: you want structured multi-perspective analysis with a fixed set of roles.

### Compose

Long-running daemon with independent services, each with their own triggers (cron, file watcher, webhook) and optional sinks that route output to other services.

```yaml
kind: Compose
spec:
  services:
    watcher:
      role: ./agents/watcher.yaml
      trigger:
        type: file_watch
        path: ./inbox
        patterns: ["*.md"]
      sink:
        type: delegate
        target: processor
    processor:
      role: ./agents/processor.yaml
```

```bash
initrunner run compose.yaml  # runs as daemon
```

Use when: you need event-driven agents that run continuously and route work between each other.

### Spawn (Tool)

A single parent agent spawns sub-agents as non-blocking background tasks. The parent polls for results or awaits completion. The LLM decides what to parallelize at runtime.

```yaml
kind: Agent
spec:
  tools:
    - type: todo
    - type: spawn
      max_concurrent: 3
      agents:
        - name: researcher
          role_file: ./agents/researcher.yaml
          description: Web research specialist
  reasoning:
    pattern: todo_driven
    auto_plan: true
  autonomy: {}
```

```bash
initrunner run lead.yaml -a -p "Compare the top 3 vector databases"
```

Use when: you need the agent to dynamically decide what to parallelize (e.g., research 3 topics concurrently).

### Delegate (Tool)

A parent agent calls sub-agents as blocking tool calls. The sub-agent runs, returns its result, and the parent continues reasoning with that result.

```yaml
kind: Agent
spec:
  tools:
    - type: delegate
      mode: inline
      agents:
        - name: sql-expert
          role_file: ./agents/sql-expert.yaml
          description: Writes and optimizes SQL queries
        - name: python-expert
          role_file: ./agents/python-expert.yaml
          description: Writes Python code
```

```bash
initrunner run coordinator.yaml -p "Analyze sales data and create a visualization"
```

Use when: the parent agent needs to dynamically choose which specialist to consult, one at a time.

## Common Combinations

### Spawn + Todo-Driven (Parallel Research)

The lead creates a todo list, spawns researchers for parallelizable items, awaits results, synthesizes.

```yaml
tools:
  - type: think
    critique: true
  - type: todo
  - type: spawn
    agents:
      - name: researcher
        role_file: ./agents/researcher.yaml
reasoning:
  pattern: todo_driven
  auto_plan: true
```

### Team + Shared Memory (Multi-Perspective Analysis)

Multiple personas share memory so later personas can reference earlier findings.

```yaml
kind: Team
spec:
  personas:
    researcher: ...
    critic: ...
    writer: ...
  mode: sequential
  shared_memory:
    enabled: true
    store_path: ./.initrunner/team_memory.db
```

### Compose + Delegate Sinks (Event-Driven with Routing)

Services trigger on events and route output to the best-fit downstream service.

```yaml
kind: Compose
spec:
  services:
    intake:
      role: ./agents/intake.yaml
      trigger:
        type: webhook
        port: 8080
      sink:
        type: delegate
        target: [researcher, responder]
        strategy: sense
    researcher: ...
    responder: ...
```

## Upgrading Between Patterns

As your needs grow, patterns compose and upgrade naturally:

- **Single agent** that needs parallel research? Add `type: spawn` to tools
- **Spawn agent** that needs a fixed review workflow? Wrap it in a Team
- **Team** that needs to run on a schedule? Move to Compose with a cron trigger
- **Compose** services that need dynamic sub-delegation? Add `type: delegate` tools to individual services
