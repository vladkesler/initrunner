# Deep Researcher

Multi-agent research team that produces structured reports with citations.

## How it works

Three personas run sequentially, sharing memory:

1. **Planner** -- breaks your question into 3-5 targeted search queries
2. **Researcher** -- executes searches, reads sources, stores verified facts in shared memory
3. **Synthesizer** -- recalls facts from memory, produces a structured report

Each persona's output is handed off to the next. Shared memory means the synthesizer can recall facts the researcher stored, even beyond the handoff text limit.

## Prerequisites

```bash
uv pip install "initrunner[search]"
```

## Usage

```bash
# One-shot research
initrunner run deep-researcher -p "Compare vector databases for RAG applications"

# More examples
initrunner run deep-researcher --task "State of WebAssembly in 2026"
initrunner run deep-researcher -p "What are the tradeoffs of microservices vs monoliths?"
```

## What to expect

A structured report with:

- **Executive Summary** -- 3-4 sentence answer
- **Key Findings** -- cited bullet points
- **Analysis** -- synthesis across sources with comparisons
- **Limitations** -- gaps in available data
- **Sources** -- numbered list with URLs

## Memory across runs

Shared memory persists. The synthesizer saves meta-insights about what research approaches work best, so subsequent runs improve over time. Use `--resume` to continue building on previous research.
