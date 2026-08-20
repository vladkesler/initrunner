# Grouped Agents -- Deploying Several Agents as One Unit

A group file lists agent files. That is all it does.

```yaml
# desk.yaml
name: desk
agents:
  intake:
    use: roles/intake.yaml
  researcher:
    use: roles/researcher.yaml
  writer:
    use: roles/writer.yaml
```

There is no orchestration here. Members never hand off to each other, never see each other's output, and run exactly as they would on their own. What a group gives you is one file to deploy, one process to run, and one place to say what the agents share.

Use it when you have several unrelated agents and one place to put them: a container image, a Kubernetes Deployment, a laptop. If instead the agents should work on a task together, you want [team mode](team_mode.md) (one shot, personas hand off) or [flows](flow.md) (long-running, explicit edges).

## A directory of agents is already a group

You do not need the file to get the packing. Point `run` at a directory holding
several agent files and it serves all of them from one process:

```bash
$ ls agents/
intake.yaml  researcher.yaml  writer.yaml

$ initrunner run agents/ --serve
Serving group agents at http://127.0.0.1:8000
  Model ID: intake
  Model ID: researcher
  Model ID: writer
```

The rule: a directory with no `agent.yaml` or `role.yaml`, holding **two or more
top-level agent documents and no team, flow or group document beside them**, is
a group. Other files are ignored, YAML or not. `--serve`, `--daemon`,
`--agent <name>` and `--sense` all work exactly as they do on a group file.

- **Top-level only.** Nested directories are ignored, because that is where a
  team's personas and a flow's steps live, and those are not agents anyone meant
  to serve on their own.
- **Members are keyed by the role's own `name:`**, which is the model ID a single
  agent already gets from `--serve`. Moving an agent into a directory does not
  change how clients address it. (A group *file* keys on the YAML key instead, so
  it can name a member something other than the role's name.)
- **One team or flow file in the directory and it stays an error** -- `pass one
  explicitly` -- rather than serving that document's component agents.
- **All or nothing.** One member that fails to load, or two roles sharing a
  `name:`, fails the whole thing rather than quietly serving the rest. A
  top-level YAML file that does not parse fails it too: nothing can tell
  whether an agent was hiding in it. This is why a directory of unrelated
  examples is not a deployable group -- `examples/roles` in this repository
  holds roles that need extras and a specific container runtime, so serving
  the whole directory fails on the first one that cannot load.
- **A group file beside agents keeps the old error.** Two documents where one
  is a group is ambiguous, so `initrunner run` asks you to pass one
  explicitly rather than guessing which the directory is about.

Write the file when you need something a directory cannot say: `shared_memory`,
`shared_documents`, group-level `observability`, listener `security`, member keys
that differ from role names, or members that live in different directories.

## How a file becomes a group

The shape of the file decides, so there is no `kind:` to set:

| What you wrote | What runs |
|---|---|
| Members are bare `use:` references, nothing else | **Group** of independent agents |
| Any member has `then:` or `after:` | [Flow](flow.md) |
| You wrote `run:` (`sequential`, `parallel`, `debate`, `ensemble`) | [Team](team_mode.md) |
| Members are inline prompts | [Team](team_mode.md), sequential |
| No `agents:` at all | A single agent |

A group of one is still a group, so adding a second member later does not change how the first is addressed.

Mixing bare references with inline members is an error, because the file no longer says which of the two you meant:

```yaml
name: desk
agents:
  intake:
    use: roles/intake.yaml     # a reference
  writer: "write the reply"    # inline -- error
```

Add `run: sequential` to make it a team, or move `writer` into its own role file to make it a group.

## What a group file may contain

Members carry `use:` and nothing else. A member with overrides is a persona, which is a team; keeping groups reference-only is what lets each member's skills, custom tools, `.env`, ingest sources and output schemas keep resolving against its own directory, and keeps `--dev` hot reload working.

At the top level a group may set:

| Field | Purpose |
|---|---|
| `name`, `description`, `tags`, `author`, `version`, `dependencies` | Metadata |
| `shared_memory` | One memory store for every member |
| `shared_documents` | One document store, ingested once |
| `observability` | Tracing for members that do not configure their own |
| `security.server`, `security.rate_limit` | The shared HTTP listener |

Anything else -- `model`, `tools`, `triggers`, `sinks`, `memory`, `guardrails`, `autonomy` -- is rejected rather than quietly ignored, because it belongs to a member's own role file. Each member's `security` still governs its own tools, sandbox, and content policy; group-level `security` only covers the listener they share.

## Running one agent

Name the member with `--agent`:

```bash
initrunner run desk.yaml --agent intake -p "my order never arrived"
initrunner run desk.yaml --agent researcher -i          # REPL
initrunner run desk.yaml --agent writer -a -p "draft the reply"
```

A selected member behaves exactly like `initrunner run roles/intake.yaml`: attachments, reports, autonomous mode, `--serve`, `--daemon` and `--bot` all work as usual, plus whatever the group shares.

Running a group without naming an agent lists the members and exits non-zero. It never picks one for you and never fans out to all of them:

```console
$ initrunner run desk.yaml -p "hello"
                     Agents in 'desk'
  Agent        Role              Description
  intake       desk-intake       Triages an incoming support request
  researcher   desk-researcher   Looks up the facts needed to answer
  writer       desk-writer       Writes the customer-facing reply

Run one agent:      initrunner run desk.yaml --agent intake
```

To let the prompt choose, use `--sense`. It scores the group's own members -- never the roles on disk:

```bash
initrunner run desk.yaml --sense -p "write the customer reply"
initrunner run desk.yaml --sense --confirm-role -p "..."   # ask before running
```

`--dry-run` keeps sensing to keyword scoring, with no model call for the tiebreak.

## Sharing memory and documents

```yaml
name: desk
shared_memory:
  enabled: true
shared_documents:
  enabled: true
  sources:
    - ./handbook
  embeddings:
    provider: openai
    model: text-embedding-3-small
agents:
  intake: {use: roles/intake.yaml}
  writer: {use: roles/writer.yaml}
```

What a member writes to memory, the others can read. Shared documents are ingested once and queried by every member, so three agents that need the same handbook embed it once. Paths default to the group's name (`~/.initrunner/memory/desk-shared.db`) and resolve relative to the group file when you set them yourself. A member's own `memory:` and `ingest:` settings are redirected to the shared store while it runs as part of the group.

## Validating and diagnosing

`initrunner validate` checks the group and every role it references, prefixing each member's problems with `agents.<name>.`:

```console
$ initrunner validate desk.yaml
  [ERROR] agents.writer.use
    Role file not found: /srv/desk/roles/writer.yaml
```

`doctor` and `plan` work on one agent at a time, so pointing them at a group prints the per-member command to run instead.

## Deploying with Kubernetes or Argo CD

Bake or mount the group file next to its role files and point the container at the group. Nothing about the image is group-specific: it is the normal InitRunner image with a different argument. Without a group file, point it at the directory instead -- `args: ["run", "/agents", "--serve", "--host", "0.0.0.0"]` -- and adding an agent is one new file in the ConfigMap.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: desk
spec:
  replicas: 1
  selector:
    matchLabels: {app: desk}
  template:
    metadata:
      labels: {app: desk}
    spec:
      containers:
        - name: initrunner
          image: ghcr.io/vladkesler/initrunner:latest
          args: ["run", "/agents/desk.yaml", "--serve", "--host", "0.0.0.0"]
          env:
            - name: INITRUNNER_API_KEY
              valueFrom:
                secretKeyRef: {name: desk-api, key: api-key}
            - name: OPENAI_API_KEY
              valueFrom:
                secretKeyRef: {name: desk-api, key: openai-key}
          ports:
            - containerPort: 8000
          readinessProbe:
            httpGet: {path: /health, port: 8000}
          resources:
            requests: {memory: 192Mi}
            limits: {memory: 256Mi}
          volumeMounts:
            - name: agents
              mountPath: /agents
      volumes:
        - name: agents
          configMap: {name: desk-agents}
```

Keep `desk.yaml` and the role files in one Git directory and let Argo CD sync it into the ConfigMap. Adding an agent is a new role file plus one line in the group; Argo CD restarts the Deployment and the new agent appears in `/v1/models`. Group membership is read at startup, so changing it means a restart -- which is what a rollout already does.

Check what came up with `GET /v1/models`; it lists one entry per member.

### Sizing the container

One container, not one per agent. The Python AI stack (provider SDK, PydanticAI, Pydantic) loads once and every member shares it, so members are nearly free after the first:

| Agents in the process | RSS (core install) | RSS (with the `mcp` extra) |
|---|---|---|
| 1 | 112 MB | 137 MB |
| 5 | 115 MB | 140 MB |
| 50 | 151 MB | 176 MB |

Under 1 MB per extra agent, so fifty agents fit in one 256 Mi container instead
of fifty. (Those rows measure one process building N agents; a live `--serve`
reads a few MB higher, and a container a few more again -- the slim image
serving a three-agent directory measures 141 MiB.) Size the limit from a real measurement of your own roles with roughly 30% headroom; a group of plain agents is comfortable at 256 Mi, and one that uses RAG or vector memory needs 512 Mi because LanceDB adds ~77 MB when it loads. See [Memory Footprint](../operations/memory-footprint.md).

## Limits

- Members must be agents, not nested groups, teams or flows.
- Member role names must be unique within a group, since runs, budgets and stores are recorded under them.
- Membership is fixed for the life of the process; a member's own file still hot-reloads if its role enables it.
- A2A serves one agent card, so `initrunner a2a serve desk.yaml --agent intake` needs the member named.
- OCI bundles and the role registry package one agent at a time; publish the member role files.
