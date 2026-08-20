# Memory Footprint

A plain InitRunner agent process settles between 110 and 180 MB of RSS,
depending on which extras are installed. If you are used to compiled agents (a
Rust agent built on rig fits in a few MB), that looks alarming, so this page
shows exactly where the memory goes, what InitRunner does to keep it down, and
how to run many agents without paying that price per agent.

Cloud bills are RSS x time x replicas, and the third factor is the one you
control most cheaply: **one process serving fifty agents costs about as much as
one process serving one.**

## Where the memory goes

Reproduce any of these numbers with `python scripts/measure_rss.py`, which runs
each scenario in a fresh interpreter and reads `VmRSS`. Measured on CPython
3.12 / Linux x86-64, median of three runs. Absolute numbers shift a few MB
between platforms and dependency versions; the proportions do not.

| Layer | RSS | Modules | Notes |
|---|---|---|---|
| Bare CPython interpreter | 11 MB | 58 | |
| + Pydantic | +13 MB | 168 | pydantic-core is a compiled Rust extension |
| + PydanticAI | +34 MB | 727 | the agent framework itself |
| + Provider SDK | +18 MB | 1512 | OpenAI; only the SDK for your configured model loads |
| + InitRunner | +7 MB | 1632 | schema, executor, CLI, and all built-in tools |
| **Import total, plain agent** | **~83 MB** | | |
| + MCP client stack (`mcp` extra) | +28 MB | 2517 | flat cost, whether or not a role uses MCP |
| + LanceDB (`vector` extra) | +77 MB | 1937 | only when a store is actually opened |

Runtime allocations (the event loop, TLS buffers, message history, glibc
allocator overhead) add a few tens of MB on top of the import total. Serving
`hello-world.yaml` from the published images, measured with `docker stats`:

| Image | On disk | RSS serving one agent |
|---|---|---|
| `:slim` (core + dashboard) | 308 MB | 127 MB |
| `:latest` (every extra) | 1.07 GB | 165 MB |

The short version: almost all of it is the Python AI stack, not InitRunner.
InitRunner's own code is a rounding error, and there is no realistic way to get
a CPython process with a provider SDK and PydanticAI anywhere near a static
binary's footprint. CPython builds class and function objects for every library
it imports; a compiled binary links only the code paths it uses.

## What you are not paying for

- **The MCP client stack is an extra.** Importing `pydantic_ai` imports its MCP
  capability, which imports `fastmcp` -- eagerly, whether or not any role uses
  MCP. Installing without the `mcp` extra is the only way to avoid it, and it
  is worth 28 MB on every process. `initrunner[recommended]`, `[all]` and the
  `:latest` image include it; a plain `pip install initrunner` and the `:slim`
  image do not. A role that needs it fails at load with the install command.
- **LanceDB loads when a store is opened**, not at startup, so a role without
  `ingest` or vector memory never pays the +77 MB even with the extra
  installed. Leaving the extra out saves ~300 MB of disk as well.
- **Provider SDKs load when PydanticAI instantiates your configured model.**
  Running against Anthropic never imports the OpenAI SDK, and vice versa.
- **CLI subcommands import their dependencies on invocation**, which is why
  `initrunner --help` stays fast and small.

## Run many agents in one process, not one process per agent

The ~83 MB import cost is per *process*, not per *agent*. Every agent added to
an existing process costs only its own config, message history, and buffers:

| Agents in one process | RSS (core) | RSS (with `mcp`) |
|---|---|---|
| 1 | 112 MB | 137 MB |
| 5 | 115 MB | 140 MB |
| 50 | 151 MB | 176 MB |

That is under 1 MB per additional agent, which is the number that matters here:
the slope, not the intercept. These rows measure the imports, the built agents
and the assembled ASGI app, so a live `initrunner run ... --serve` reads a few
MB higher once uvicorn and its event loop are up. Measured on a core install,
one agent served this way is 119 MB and three are 127 MB; the container figures
in the table above (127 MB for `:slim`) are the same thing seen from the
outside. Compare rows within one table rather than across them.

The arithmetic for a fleet:

```
total RSS  =  processes x shared stack
            + optional dependencies each process actually loads
            + per-agent history and buffers
```

Fifty agents as fifty processes is 5.5 to 8 GB. The same fifty packed into one
process is about 150 MB: a 40x difference in memory-hours, on the same
hardware, for the same work. (Idle and warm; add headroom for however many
requests you expect to be in flight at once.)

Ways to pack:

- **Groups**: `initrunner run desk.yaml --serve` hosts every member of a
  [group](../orchestration/groups.md) in one process, each addressable as its
  own OpenAI model ID. This is the cheapest way to run agents that have nothing
  to do with each other. `--daemon` does the same for their triggers. A
  directory of agent files is a group too, so `initrunner run agents/ --serve`
  needs no manifest at all.
- **Flows**: `initrunner flow up flow.yaml` runs every agent in the flow inside
  one process on a shared event loop. A five-agent flow is one ~200 MB process,
  not five.
- **API server**: `initrunner run agent.yaml --serve` keeps one warm process
  answering many requests, instead of paying import cost (memory and startup
  latency) per invocation.
- **Daemon mode**: `initrunner run agent.yaml --daemon` hosts all of a role's
  triggers in one long-lived process.

Spawning a fresh `initrunner run` per task is the expensive pattern: each
invocation pays the full import cost in both RSS and startup time. A Kubernetes
CronJob that runs `initrunner run` every minute pays it 1,440 times a day;
pointing the same CronJob at a warm `--serve` process with `curl` pays it once.
See [Docker](../getting-started/docker.md#sizing-the-container).

## How to measure

- **A container**: `docker stats --no-stream` while the agent is serving.
- **Kubernetes**: `kubectl top pod`.
- **A managed service**: `initrunner service status <name>` prints the daemon's
  RSS next to its PID, read from `/proc` once the process identity is verified.
- **Any process**: `grep VmRSS /proc/<pid>/status`.
- **This project's own numbers**: `python scripts/measure_rss.py`, which
  regenerates the tables above.

## Container tips

- **`MALLOC_ARENA_MAX=2` is already set** in the Docker images, in the systemd
  units `initrunner flow install` writes, and in the processes
  `initrunner service start` spawns. InitRunner bridges sync and async
  execution with worker threads, and glibc creates per-thread memory arenas
  that can inflate RSS well beyond live heap in threaded Python processes.
  Capping arenas is a standard mitigation with negligible performance cost at
  this thread count. Override with `-e MALLOC_ARENA_MAX=...` if you have
  measured something better for your workload.
- **Size limits from measurement, not the sum of parts.** Container memory
  limits count RSS. Run your actual role once, check `docker stats`, and set
  the limit with ~30% headroom. A plain agent or a group of them fits
  comfortably in 256 MB; give a role that opens a vector store 512 MB, because
  the store pushes the same agent to 212 MB before it has done any work.
