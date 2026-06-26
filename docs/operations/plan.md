# `initrunner plan`

`initrunner plan <role.yaml>` is a static dry-run. It reads a role and predicts what running it would involve, without calling the model: which tools are reachable, which initguard policies would fire, which guardrails apply, which sandbox engages, which triggers are armed, and a heuristic token/USD cost. It is a plan you read before you run.

```bash
initrunner plan support-agent.yaml
initrunner plan support-agent.yaml --prompt "refund order 1234"
initrunner plan support-agent.yaml --json
```

## What it reports

**Reachable tools.** The set of tools the model could call, listed at the function level. `plan` builds each configured tool with a no-op backend and reads its function names, so a `type: custom` module shows its actual functions, a skill shows the tools it contributes, and auto-wired capabilities (retrieval when `ingest` is set, long-term memory when `memory` is set, `search_tools` when `tool_search` is enabled, `activate_skill` when `auto_skills` is on) appear too. Reachable means "the model may call this", not "the model will". With `--prompt` and `tool_search` enabled, the tools that the BM25 search would surface for that prompt are marked with `*` (a deterministic ranking, still not a guarantee the model calls them).

**initguard policy.** When `INITRUNNER_POLICY_DIR` is set, `plan` constructs the agent principal from the role metadata and evaluates each reachable function against the policy engine, showing `allow` or `deny` with the reason. With no policy directory configured, the panel reports that policy is inactive (all tools allowed at runtime).

**Guardrails.** The token, tool-call, timeout, and budget limits from `spec.guardrails`.

**Sandbox.** The backend that would engage (`none`, `bwrap`, `docker`, `ssh`) and a non-raising availability probe. A backend that is configured but unavailable on the host is reported, not raised, so the command always completes.

**Triggers.** Each armed trigger with its summary. Cron and heartbeat triggers are `scheduled` (their cadence is known); file-watch, webhook, and chat triggers are `event` (armed, but their firing is not predictable).

**Cost.** A heuristic estimate from `initrunner cost estimate`: estimated input/output tokens and per-run USD (plus per-day/month when triggers imply a cadence). It excludes skill content and counts tools coarsely, so treat it as a planning aid, not an exact figure. `--prompt` sizes the user-prompt portion.

## Options

| Option | Effect |
|---|---|
| `--prompt`, `-p` | Size the cost estimate to a real prompt, and drive `tool_search` surfacing |
| `--no-introspect` | List tools at the type level only; skips building any tool (no construction side effects) |
| `--no-sandbox-probe` | Skip the host sandbox availability probe (the one step that touches host binaries) |
| `--skill-dir` | Extra directory to resolve skills from |
| `--json` | Emit the full plan as JSON for tooling |

## Honesty and side effects

`plan` never calls the model, so it cannot say which tools the model will actually choose. Function-level introspection does construct each tool. For most tools that is pure and in-process, but a tool that opens a client at build time (some `api`, `http`, or `mcp` tools) may attempt a connection. Any tool whose builder fails or connects is caught, reported at the type level, and noted in the caveats; the command never blocks. Use `--no-introspect` to avoid all construction. The sandbox probe is the only other host-touching step; use `--no-sandbox-probe` to skip it.

## See also

- [`initrunner validate`](../getting-started/cli.md) checks a role for correctness; `plan` predicts its behavior.
- [Cost tracking](../core/cost-tracking.md) for how the estimate is computed.
- [Agent policy](../security/agent-policy.md) for how initguard decisions are made.
