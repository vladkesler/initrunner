# Memory Footprint

A plain InitRunner agent process settles at roughly 150 to 220 MB of RSS. If
you are used to compiled agents (a Rust agent built on rig fits in a few MB),
that looks alarming, so this page shows exactly where the memory goes, what
InitRunner does to keep it down, and how to run many agents without paying
that price per agent.

## Where the memory goes

Measured with CPython 3.12 on Linux x86-64 by importing each layer and reading
`VmRSS`. Absolute numbers shift a few MB between platforms and dependency
versions; the proportions do not.

| Layer | RSS | Notes |
|---|---|---|
| Bare CPython interpreter | 9 MB | |
| Pydantic | +14 MB | pydantic-core is a compiled Rust extension |
| Provider SDK | +16 to +36 MB | anthropic is ~16 MB, openai is ~36 MB; only the SDK for your configured model loads |
| PydanticAI | +43 MB | includes the MCP client stack, imported eagerly upstream |
| InitRunner itself | +7 MB | schema, executor, CLI, and all built-in tools |
| **Import total, plain agent** | **~110 MB** | |
| LanceDB | +102 MB | only when the role configures ingestion or vector memory |

Runtime allocations (the event loop, TLS buffers, message history, glibc
allocator overhead) add a few tens of MB on top of the import total, which is
how a plain agent lands in the 150 to 220 MB range and a RAG-enabled one
closer to 280 MB.

The short version: almost all of it is the Python AI stack, not InitRunner.
InitRunner's own code is a rounding error, and there is no realistic way to
get a CPython process with a provider SDK and PydanticAI anywhere near a
static binary's footprint. CPython builds class and function objects for every
library it imports; a compiled binary links only the code paths it uses.

## What loads lazily

InitRunner defers the expensive imports it controls, so you only pay for what
a role actually uses:

- **LanceDB** loads when a store is opened, not at startup. A role without
  `ingest` or vector memory never pays the +102 MB.
- **Provider SDKs** load when PydanticAI instantiates your configured model.
  Running against Anthropic never imports the OpenAI SDK, and vice versa.
- **CLI subcommands** import their dependencies on invocation, which is why
  `initrunner --help` stays fast and small.

## Run many agents in one process, not one process per agent

The ~110 MB import cost is per *process*, not per *agent*. Every agent added
to an existing process costs only its own config, message history, and
buffers. Measured on one machine, serving a group of five agents:

| Agents in the process | RSS |
|---|---|
| 1 | ~142 MB |
| 5 | ~145 MB |

That is about 1 MB per additional agent, against ~710 MB for the same five
agents as five separate processes. If you are running a fleet, this is the
number that matters for capacity planning:

- **Groups**: `initrunner run desk.yaml --serve` hosts every member of a
  [group](../orchestration/groups.md) in one process, each addressable as its
  own OpenAI model ID. This is the cheapest way to run agents that have
  nothing to do with each other. `--daemon` does the same for their triggers.
- **Flows**: `initrunner flow up flow.yaml` runs every agent in the flow
  inside one process on a shared event loop. A five-agent flow is one
  ~200 MB process, not five.
- **API server**: `initrunner run agent.yaml --serve` keeps one warm process
  answering many requests, instead of paying import cost (memory and startup
  latency) per invocation.
- **Daemon mode**: `initrunner run agent.yaml --daemon` hosts all of a role's
  triggers in one long-lived process.

Spawning a fresh `initrunner run` per task is the expensive pattern: each
invocation pays the full import cost in both RSS and startup time. Prefer a
long-lived mode whenever tasks recur.

## Container tips

- **Set `MALLOC_ARENA_MAX=2`.** InitRunner bridges sync and async execution
  with worker threads, and glibc creates per-thread memory arenas that can
  inflate RSS well beyond live heap in threaded Python processes. Capping
  arenas is a standard mitigation with negligible performance cost at this
  thread count.
- **Size limits from measurement, not the sum of parts.** Container memory
  limits count RSS. Run your actual role once, check
  `docker stats` (or `VmRSS` in `/proc/<pid>/status`), and set the limit with
  ~30% headroom. A plain agent fits comfortably in a 256 MB limit; give a
  RAG-enabled role 512 MB.
