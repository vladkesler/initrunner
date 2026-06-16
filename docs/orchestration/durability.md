# Durable, resumable flows

A long multi-agent flow can be interrupted: the process is killed, the host
reboots, a downstream agent errors out. Without durability you re-run the whole
flow from the entry agent, paying for every sub-agent again. With durability,
InitRunner records each completed sub-agent into an append-only, HMAC-signed
checkpoint journal keyed by `flow_run_id`. On resume, completed sub-agents are
replayed from the journal and execution continues at the first one that did not
finish.

The journal is the audit store itself. There is no extra service, broker, or
worker to deploy. The same signed ledger that records agent runs doubles as the
durable execution log, which keeps the whole thing local-first and tamper
evident.

## Enabling durability

Add a `durability` block to the flow `spec`:

```yaml
apiVersion: initrunner/v1
kind: Flow
metadata:
  name: durable-pipeline
spec:
  durability:
    enabled: true
  agents:
    researcher:
      role: ./researcher.yaml
      sink:
        target: writer
    writer:
      role: ./writer.yaml
```

`enabled: true` is all you need. It selects the `journal` backend, the only
working durability backend: the audit-backed checkpoint journal. The other
fields have sensible defaults:

| Field | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Turn the checkpoint journal on. |
| `backend` | `none` | `none` (off) or `journal` (audit-backed). `enabled: true` implies `journal`. |
| `retry_policy` | `exponential` | Reserved for retry tuning: `exponential`, `linear`, or `none`. |
| `max_retries` | `3` | Reserved for retry tuning. |
| `retry_delay_seconds` | `1` | Reserved for retry tuning. |

Durability is off by default, so single-shot agent runs and the REPL are
completely unaffected. Only flows that opt in pay the (small) cost of writing a
checkpoint row per completed sub-agent.

## Running and resuming

Run the flow as usual with `initrunner flow up`. A durable run records its
`flow_run_id` in the audit store as it executes; you can find it with
`initrunner flow events` or in the audit log.

If a run is interrupted, resume it by its `flow_run_id`:

```bash
initrunner flow resume flow.yaml a1b2c3d4e5f6
```

On resume:

- Sub-agents that completed successfully are **replayed** from the journal.
  Their recorded output flows downstream without calling the model again.
- The first sub-agent that **failed** or was **paused for approval** is re-run,
  along with everything after it.

A clean, fully successful run prunes its own checkpoints when it finishes, so
the journal only retains rows for runs that still need resuming.

Resume requires audit logging (the journal lives in the audit store).
Resuming a flow that does not enable durability is an error.

## What gets recorded

Each checkpoint stores, per `(flow_run_id, service_name)`:

- the serialized `DelegationEnvelope` (prompt, trace, source service, topology
  index),
- the serialized `RunResult` (output, token counts, tool-call names, status,
  any pending approvals),
- the agent message history, serialized with PydanticAI's
  `ModelMessagesTypeAdapter` so message parts round-trip cleanly,
- a `record_hash` / `prev_hash` pair forming an HMAC chain, signed with the same
  key as the main audit log.

Checkpoint writes never raise: a failed checkpoint write degrades durability for
that run but never crashes the flow, matching the `audit.log()` contract.

## Determinism and idempotency

Resume assumes sub-agents are reasonably deterministic and that their tools are
idempotent or side-effect aware. A completed sub-agent is *not* re-run on
resume, so any external side effects it produced are not repeated; conversely, a
re-run sub-agent will repeat its side effects. Design tools that mutate external
state to be safe under at-least-once execution.

**Not supported with `loop_back`.** A durable flow cannot use a `loop_back`
(critic/refine) sink. Durable checkpoints are keyed only by `(flow_run_id,
service_name)`, so a loop target would replay its first iteration's stored output
every round instead of re-running, silently defeating the loop. The combination
is rejected at flow validation; disable durability or remove the `loop_back` sink.

## Daemon flows

A trigger-driven flow daemon (`initrunner flow up`) with durability enabled
journals every triggered run and prunes the journal only when a run completes
cleanly: not timed out, with every sub-agent reporting success. A run that is
interrupted by a crash, or that finishes with a failed (or approval-paused)
sub-agent, leaves its checkpoints behind so `initrunner flow resume <id>` can
replay the completed sub-agents and re-run the one that did not finish.

## See also

- [Delegation](delegation.md)
- [Sinks](sinks.md)
- [Audit chain](../security/audit-chain.md)
