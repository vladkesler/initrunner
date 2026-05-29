# Blackboard: Shared State Inside a Flow Run

A blackboard is a small, structured key-value store that lives for the duration of one flow run. Agents post entries to it and read them back by key, so an upstream agent can hand a downstream agent a named, attributed value without that value being buried in prompt text.

Without a blackboard, the only thing flowing between flow agents is the prompt string on each edge. When a fan-out fans back in, those strings are concatenated. That is fine for prose, but it is a poor way to pass a decision, a chosen plan, or a structured artifact: the consumer has to parse it back out of free text. The blackboard gives the flow a typed side channel that survives the fan-out and is readable at the fan-in join.

The board is the flow graph's run state. pydantic-graph runs steps sequentially within a branch and merges branches at a join, so one step mutates the board at a time and no locking is needed. Each run starts with a fresh, empty board.

## When to use it

- A planner decides how to split work and the workers need the exact split, not a paraphrase of it.
- A fan-in join should merge based on a value an upstream agent computed (a mode, a budget, a chosen format).
- One of several parallel workers should claim a unit of work so no other worker also takes it.

If agents only need to pass prose forward, you do not need the blackboard. The default prompt-concatenation behavior already covers that.

## Enabling it

Add a `blackboard` tool to any flow agent that should read or write shared state. The tool is only active inside a flow; a standalone single-shot run has no board, so the tool is simply not built there.

```yaml
spec:
  tools:
    - type: blackboard
      max_entries: 50        # board capacity for this run (default 100)
      max_value_chars: 10000 # per-value size cap (default 10000)
```

Each agent that participates declares the tool. Agents that only need the merged result (like a final editor) can leave it off and still see posted entries folded into their input at the join.

## Tools the agent gets

| Tool | What it does |
|------|--------------|
| `blackboard_post(key, value)` | Add a new entry. Keys are letters, digits, and underscores, up to 64 characters. Posting a key that already exists is an error; claim the old entry first to replace it. |
| `blackboard_read(key)` | Return the entry as JSON (key, value, author, timestamp, entry_id) without removing it. |
| `blackboard_claim(key)` | Read the entry and remove it from the board so no other agent can claim it again. Use this for work-stealing handoffs. |
| `blackboard_list()` | List the keys currently on the board with a short value preview. |

Every entry records the agent that posted it (`author`) and an ISO-8601 UTC `timestamp`, so the board carries provenance, not just data.

## Example: planner posts, writers read, editor merges

A planner fans out to two writers that converge on an editor. The planner posts the work breakdown; the writers read it; the editor receives the merged drafts plus the shared board.

`flow.yaml`:

```yaml
apiVersion: initrunner/v1
kind: Flow
metadata:
  name: collab-writers
  description: Planner posts a shared plan, two writers read it, editor merges
spec:
  agents:
    planner:
      role: ./roles/planner.yaml
      sink:
        type: delegate
        target: [writer-a, writer-b]
    writer-a:
      role: ./roles/writer.yaml
      sink:
        type: delegate
        target: editor
    writer-b:
      role: ./roles/writer.yaml
      sink:
        type: delegate
        target: editor
    editor:
      role: ./roles/editor.yaml
```

`roles/planner.yaml`:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: planner
  description: Splits work and posts decisions to the shared blackboard
spec:
  role: |
    You break the task into parts. Use blackboard_post to record shared
    decisions other agents will need (post key "plan" with your breakdown).
  model:
    provider: openai
    name: gpt-5-mini
  tools:
    - type: blackboard
      max_entries: 50
```

`roles/writer.yaml`:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: writer
  description: Reads the shared plan and drafts a section
spec:
  role: |
    Use blackboard_read with key "plan" to see the planner's breakdown,
    then draft your section.
  model:
    provider: openai
    name: gpt-5-mini
  tools:
    - type: blackboard
```

`roles/editor.yaml` is a plain agent with no blackboard tool. When the two writer branches fan in, the join folds the still-posted entries into the editor's input under a `=== Shared blackboard ===` section, attributed by author:

```
draft-writer-a

---

draft-writer-b

---

=== Shared blackboard ===
- plan (by planner): section A=intro; section B=body
```

The editor therefore sees the planner's structured decision as named data, not as text it has to recover from a branch's prose.

## How fan-in joins read the board

A fan-in join still concatenates the branch outputs for the downstream agent, and it additionally reads the structured entries on the board and appends them as a dedicated section. Two consequences follow:

- An entry an upstream agent posted is visible to the join target as attributed data, even though it never appeared in any branch's prompt text.
- An entry that a branch agent claimed (with `blackboard_claim`) is gone from the board, so it does not reappear at the join. This is how a parallel worker signals "I took this" to its siblings and to the merge step.

Per-entry values are truncated in the join section so a large board cannot balloon the merged prompt.

## Persistence and audit

When a flow run finishes, the final board is recorded on the signed audit chain as one entry with trigger type `blackboard_state`. The snapshot holds the unclaimed entries (each with value, author, and timestamp) and the list of claimed keys. Values are truncated and secret-scrubbed before they enter the chain, and persistence never raises: a logging failure cannot crash a flow.

A run that uses no blackboard tool, or whose board stayed empty, writes nothing. Query the snapshot like any other audit record:

```python
from initrunner.audit.logger import AuditLogger

log = AuditLogger()
rows = log.query(trigger_type="blackboard_state")
```

## Limits

- Keys: letters, digits, and underscores, up to 64 characters.
- Values: strings, capped per the tool's `max_value_chars` (default 10000). Post JSON when you need structure.
- Board capacity: `max_entries` per run (default 100). A full board rejects further posts until something is claimed.
- The board is per run. It is not shared across separate flow runs and is not a substitute for the long-term memory store or shared documents.
