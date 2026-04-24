# Human-in-the-Loop Approval

Add `approval: required` to a tool in `role.yaml` to pause the run every time the model wants to call it. The pending calls surface as a structured "paused" state; a human approves or denies them out of band, and the run resumes from exactly where it stopped — no re-prompting, no lost context.

This is the PydanticAI `DeferredToolRequests` / `DeferredToolResults` contract, the same interop surface AG-UI and the Vercel AI SDK use. Every runner mode speaks it.

## When to use it

Use it when the *argument pattern* can't be decided in advance:

- Shell commands whose safety depends on the target path
- Writes to a production store where the diff matters
- Money-moving API calls
- Anything you'd want a human to glance at before it goes through

If the answer is always the same regardless of arguments, [tool permissions](./tool_permission_system.md) are a better fit — they run before approval and short-circuit denials without bothering a human.

## Configuration

```yaml
tools:
  - type: shell
    working_dir: .
    approval: required
```

`approval` accepts `auto` (default, no gating) and `required`. It composes with `permissions:` — deny rules short-circuit first, so a human is never asked to approve a call that would have been blocked anyway.

## How it looks

### REPL

Approval prompts inline, resumes in place:

```
> delete /tmp/scratch

Run abc123 paused — 1 tool call(s) need approval.

  shell  call_01HW9Q
  {'command': 'rm -rf /tmp/scratch'}
  Approve? [y/N]: y

Agent: Deleted /tmp/scratch.
```

### Single-shot

Prints pending calls, exits 2, writes state to audit SQLite:

```bash
$ initrunner run demo.yaml -p "delete /tmp/scratch"

Run abc123 paused — 1 tool call awaiting approval.
  call_01HW9Q  shell  {'command': 'rm -rf /tmp/scratch'}

Resume with: initrunner approve abc123 --all

$ initrunner pending
Pending approvals (1)
┏━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┓
┃ run_id     ┃ tool_call… ┃ tool  ┃ agent ┃ created_at                 ┃ arguments           ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━┩
│ abc123     │ call_01HW… │ shell │ demo  │ 2026-04-24T14:21:08.947991 │ {"command":"rm -rf… │
└────────────┴────────────┴───────┴───────┴────────────────────────────┴─────────────────────┘

$ initrunner approve abc123 --all
Resumed.
Deleted /tmp/scratch.
```

Deny with `--deny`, or resolve a specific call with `--tool-call-id ID` (any other pending calls for the same run default to denied).

### Daemon / triggers

When a cron or webhook-fired run pauses, the daemon persists state and continues accepting other triggers. Conversational triggers (Slack, Discord, Telegram) get a one-liner reply:

```
Awaiting approval for 1 tool call(s). Resume: initrunner approve abc123 --all
```

The `--no-audit` flag disables persistence; in that mode a paused daemon run reports that it cannot be resumed rather than silently losing state.

### Dashboard

The dashboard (`initrunner dashboard`) has two approval surfaces, both driven by the same `/api/approvals/*` router:

**Inline in RunPanel.** When a run kicked off from the agent detail page pauses, the `approval_required` SSE event slots a card group into the run panel in place of the "thinking" state. Each pending call carries a 2px left state bar (unset = muted, approved = lime, denied = fail-red), a tool-templated argument preview (e.g. `rm -rf /tmp/cache` rather than JSON), and an Approve/Deny pair with `<kbd>` chip hints. Submit fires only when every card has a decision; re-pauses update the group in place.

**Queue view (`/approvals`).** Reviewers see every paused run across the daemon, API, and other sessions, grouped by run_id. Single-call runs have inline Approve/Deny; multi-call runs open a right-side drawer that shows the originating prompt and per-call controls. A sidebar badge under Operate surfaces the pending count (steady lime; polled every 20s and bumped immediately by SSE). A `?` overlay anywhere in the dashboard shows the full keyboard grammar (`j`/`k` navigate, `A`/`D` decide, `⇧ A`/`⇧ D` bulk, `↵` submit, `Esc` close).

**Absent-Kicker toasts.** A session-local registry of run_ids you kicked off diffs against each poll; if a run *you* started shows up in the pending list while you're on a different page, a toast links back to `/approvals/{run_id}`. Runs other operators started get only the badge — no noise for work you didn't trigger.

### OpenAI-compatible API

`POST /v1/chat/completions` returns HTTP 200 with an extended body when the model pauses:

```json
{
  "id": "chatcmpl-...",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": ""},
    "finish_reason": "tool_calls_pending_approval"
  }],
  "run_id": "abc123",
  "pending_approvals": [
    {"tool_call_id": "call_01HW9Q", "tool_name": "shell",
     "arguments": {"command": "rm -rf /tmp/scratch"}}
  ]
}
```

Streaming requests get a final SSE event before `[DONE]`:

```
data: {"event":"approval_required","run_id":"abc123","pending_approvals":[...]}
data: {"id":"chatcmpl-...","choices":[{"delta":{},"finish_reason":"tool_calls_pending_approval"}]}
data: [DONE]
```

Resume with a map of `{tool_call_id: bool}`:

```bash
curl -X POST http://localhost:8000/v1/approvals/abc123 \
  -H 'content-type: application/json' \
  -d '{"call_01HW9Q": true}'
```

Every pending `tool_call_id` on that run must carry a decision — `false` denies. The response mirrors a regular chat completion (or paused shape on re-pause). Optional `X-Resolved-By` header records the operator in the audit trail.

## How it works

1. `ApprovalToolset` (in `initrunner/agent/tools/registry.py` when `tool.approval == "required"`) flips `ToolDefinition.kind = "unapproved"` on every wrapped tool.
2. The agent's `output_type` is widened to `[original, DeferredToolRequests]` at build time.
3. When the model decides to call an unapproved tool, PydanticAI returns a `DeferredToolRequests` instead of executing it.
4. The executor detects this in `_process_agent_output` and sets `RunResult.status = "paused"` + `pending_approvals`.
5. The runner mode persists the pause to the audit SQLite `pending_approvals` table (one row per pending call, carrying the full message history as JSON).
6. `initrunner approve` / the HTTP route load the row, build a `DeferredToolResults(approvals={id: bool, ...})`, and call `agent.run_sync(message_history=..., deferred_tool_results=...)`. If the model pauses again, the cycle repeats.

## Composition with other gates

The wrapper stack is builder → `PolicyToolset` → `PermissionToolset` → `ApprovalToolset` → observable events. Decisions go:

1. Identity-based policy (Cedar, if enabled) rejects calls the principal isn't allowed to make at all.
2. Permission rules reject calls whose arguments match deny globs.
3. Approval marks whatever survives as `unapproved`, which PydanticAI surfaces to the human.

A call that would be denied by policy or permissions never bothers a reviewer.

## Audit trail

Resumed runs log with `trigger_type="resume"` and a synthetic prompt of the form `(resume: call_id:approve, call_id:deny, ...)` so the audit row is self-describing. The `pending_approvals` table keeps resolved rows with `resolved_at`, `resolved_by`, and `decision` ∈ {`approve`, `deny`}, so the approval history survives pruning of the runs themselves.

## Not yet supported

- Per-role or per-skill approval defaults (today approval is declared per tool entry).
- Expiry sweeper for pending approvals older than N hours.
- Attribution in "already resolved" toasts (the second operator sees a generic message; the resolver's id is in the audit trail but not surfaced on the UI race path).
- Destructive-verb highlighting in arg previews (`rm`, `drop`, `delete` flagged in red). Deferred to avoid false-confidence from an inevitably incomplete lexicon.
