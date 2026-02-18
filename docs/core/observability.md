# Observability (OpenTelemetry)

InitRunner supports opt-in distributed tracing via [OpenTelemetry](https://opentelemetry.io/). When enabled, agent runs, LLM requests, tool calls, ingestion pipelines, and delegation chains all emit traces that can be visualized in any OTel-compatible backend (Jaeger, Grafana Tempo, Datadog, Honeycomb, Logfire, etc.).

The SQLite audit trail remains the lightweight default. Observability adds a second, richer signal layer — both run side-by-side.

## Quick Start

See traces in under a minute — no Docker, no external services:

```bash
pip install initrunner[observability]
initrunner run examples/roles/traced-agent.yaml -p "What time is it?" --no-audit
```

JSON spans print to stderr showing the full trace hierarchy: the parent `initrunner.agent.run` span, the PydanticAI `agent run` and `chat` spans, and the `running tool (get_current_time)` tool span.

See [`examples/roles/traced-agent.yaml`](../../examples/roles/traced-agent.yaml) for the complete role definition.

### Console Output Example

With `backend: console`, each completed span is printed to stderr as a JSON object. A typical run produces output like this (timestamps and IDs shortened for readability):

```json
{
    "name": "running tool (get_current_time)",
    "context": {
        "trace_id": "0x3a1f...",
        "span_id": "0x8b2c...",
        "trace_state": "[]"
    },
    "kind": "SpanKind.INTERNAL",
    "parent_id": "0x4d1e...",
    "start_time": "2026-02-17T12:00:00.100000Z",
    "end_time": "2026-02-17T12:00:00.102000Z",
    "status": { "status_code": "OK" },
    "attributes": {}
}
```

```json
{
    "name": "chat gpt-5-mini",
    "context": {
        "trace_id": "0x3a1f...",
        "span_id": "0x4d1e..."
    },
    "kind": "SpanKind.CLIENT",
    "parent_id": "0x9f3a...",
    "attributes": {
        "gen_ai.operation.name": "chat",
        "gen_ai.request.model": "gpt-5-mini",
        "gen_ai.response.model": "gpt-5-mini-2024-07-18",
        "gen_ai.usage.input_tokens": 85,
        "gen_ai.usage.output_tokens": 24
    }
}
```

```json
{
    "name": "initrunner.agent.run",
    "context": {
        "trace_id": "0x3a1f...",
        "span_id": "0x7e5b..."
    },
    "kind": "SpanKind.INTERNAL",
    "attributes": {
        "initrunner.agent_name": "traced-agent",
        "initrunner.run_id": "a1b2c3d4",
        "initrunner.tokens_total": 109,
        "initrunner.duration_ms": 1200,
        "initrunner.success": true
    }
}
```

Spans appear in completion order (leaf spans first, root span last). All spans share the same `trace_id`, forming a single trace.

## Installation

```bash
pip install initrunner[observability]
```

This installs `opentelemetry-sdk`, `opentelemetry-exporter-otlp`, and `opentelemetry-instrumentation-logging`.

For the Logfire backend, install separately:

```bash
pip install logfire
```

## Configuration

Add an `observability` section to your role's `spec`:

```yaml
spec:
  observability:
    backend: otlp              # "otlp" | "logfire" | "console"
    endpoint: http://localhost:4317
    service_name: my-agent     # default: agent metadata.name
    trace_tool_calls: true
    trace_token_usage: true
    sample_rate: 1.0
    include_content: false     # include prompts/completions in spans
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `backend` | `otlp` \| `logfire` \| `console` | `otlp` | Exporter backend |
| `endpoint` | string | `http://localhost:4317` | OTLP gRPC endpoint (ignored for console/logfire) |
| `service_name` | string | agent name | Service name in traces |
| `trace_tool_calls` | bool | `true` | Emit spans for tool calls |
| `trace_token_usage` | bool | `true` | Emit token usage metrics |
| `sample_rate` | float (0.0–1.0) | `1.0` | Trace sampling rate |
| `include_content` | bool | `false` | Include prompt/completion text in spans |

## Quickstart with Jaeger

### Docker run

```bash
docker run -d --name jaeger \
  -p 16686:16686 \
  -p 4317:4317 \
  jaegertracing/all-in-one:latest
```

### Docker Compose

```yaml
# docker-compose.yaml
services:
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"   # Jaeger UI
      - "4317:4317"     # OTLP gRPC
```

```bash
docker compose up -d
```

### Run with OTLP

Add observability to your role:

```yaml
spec:
  observability:
    backend: otlp
    endpoint: http://localhost:4317
```

Run your agent:

```bash
initrunner run role.yaml -p "Hello, world"
```

Open Jaeger UI at `http://localhost:16686` and search for your agent's service name.

## Span Hierarchy

When observability is enabled, traces follow this hierarchy:

```
initrunner.agent.run                    ← InitRunner parent span
├── agent run                           ← PydanticAI agent span
│   ├── chat gpt-4o                     ← LLM request span
│   ├── running tool (my_tool)          ← Tool execution span
│   └── chat gpt-4o                     ← Follow-up LLM request
└── initrunner.ingest                   ← Ingestion pipeline span (if applicable)
```

### InitRunner-specific spans

| Span Name | Attributes |
|-----------|------------|
| `initrunner.agent.run` | `initrunner.run_id`, `initrunner.agent_name`, `initrunner.trigger_type`, `initrunner.tokens_total`, `initrunner.duration_ms`, `initrunner.success` |
| `initrunner.ingest` | `initrunner.agent_name`, `initrunner.ingest.files_processed`, `initrunner.ingest.chunks_created` |

### PydanticAI spans (automatic)

PydanticAI emits these spans when `instrument` is set on the Agent:

- **`agent run`** — Full agent run lifecycle
- **`chat {model}`** — Each LLM API call (`SpanKind.CLIENT`)
- **`running tool`** — Each tool execution
- **`gen_ai.client.token.usage`** — Token usage histogram metric

## Distributed Traces via Delegation

In compose orchestrations, trace context propagates automatically through delegation chains using W3C Trace Context (`traceparent`/`tracestate` headers).

```
initrunner.agent.run [service_a]
├── agent run [PydanticAI]
│   ├── chat gpt-4o
│   └── running tool (delegate)
└── initrunner.agent.run [service_b]    ← linked via traceparent
    └── agent run [PydanticAI]
        └── chat gpt-4o
```

This means you can visualize an entire multi-agent pipeline as a single distributed trace in Jaeger or your preferred backend.

## Backends

### OTLP (default)

Sends traces via gRPC to any OTLP-compatible collector. Uses `BatchSpanProcessor` for efficient batching.

### Console

Prints spans to stderr. Useful for quick debugging:

```yaml
spec:
  observability:
    backend: console
```

### Logfire

Uses [Pydantic Logfire](https://logfire.pydantic.dev/) for managed observability:

```yaml
spec:
  observability:
    backend: logfire
    service_name: my-agent
```

Logfire manages its own `TracerProvider` — InitRunner delegates to `logfire.configure()` and does not create a manual provider.

## Audit vs Observability

Both systems record agent activity, but they serve different purposes:

| | Audit Trail | Observability |
|---|---|---|
| **Purpose** | Compliance, history, debugging | Distributed tracing, performance analysis |
| **Backend** | Local SQLite (built-in) | Any OTel collector (Jaeger, Tempo, Datadog, etc.) |
| **Dependencies** | None (included) | `pip install initrunner[observability]` |
| **Default** | Enabled | Opt-in |
| **Granularity** | One record per agent run | Nested spans (run → LLM call → tool call) |
| **Multi-agent** | Independent per-run records | Distributed traces across delegation chains |
| **Query** | SQL / `initrunner audit export` | Jaeger UI, Grafana, vendor dashboards |
| **Retention** | Auto-pruned SQLite (configurable) | Managed by your OTel backend |

**Use audit** when you need a lightweight, zero-dependency log of what happened — prompts, outputs, token usage, and success/failure for every run.

**Use observability** when you need to understand *how* it happened — latency breakdowns across LLM calls and tools, distributed traces across multi-agent pipelines, and integration with your existing monitoring stack.

Both can run simultaneously. See [Audit Trail](audit.md) for audit configuration.

## Log Correlation

When observability is enabled, Python log records are automatically enriched with `trace_id` and `span_id` fields via OTel's `LoggingInstrumentor`. This allows correlating application logs with traces in backends that support log-trace correlation (Grafana Loki + Tempo, Datadog, etc.).

## Zero Overhead When Disabled

When `spec.observability` is not set:

- No OTel SDK is imported
- `trace.get_tracer("initrunner")` returns a no-op tracer
- Span context injection/extraction are no-ops
- CLI startup time is unaffected

## Troubleshooting

### Missing SDK

```
RuntimeError: OpenTelemetry observability requires: pip install initrunner[observability]
```

Install the optional dependency group: `pip install initrunner[observability]`

### No traces appearing

1. Verify the OTLP endpoint is reachable: `curl http://localhost:4317`
2. Check `sample_rate` is not `0.0`
3. Try `backend: console` to verify spans are being created
4. Ensure the collector/Jaeger is accepting gRPC on port 4317 (not HTTP on 4318)

### Duplicate spans with Logfire

If you see duplicate spans when using `backend: logfire`, ensure you're not also setting up a manual `TracerProvider` elsewhere. Logfire manages its own providers — InitRunner correctly delegates to `logfire.configure()` without creating additional providers.
