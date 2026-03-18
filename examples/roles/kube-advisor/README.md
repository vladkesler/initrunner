# Kubernetes Troubleshooting Agent

Point this at your cluster and describe the problem. It runs kubectl, cross-references troubleshooting guides, identifies the root cause, and gives you exact commands to fix it. Remembers past incidents so recurring patterns get diagnosed faster.

## Quick start

```bash
# Install
initrunner install vladkesler/kube-advisor

# Interactive session (with memory)
initrunner run kube-advisor -i

# One-shot question
initrunner run kube-advisor -p "My pod is CrashLoopBackOff in payments"

# Team mode -- triage, diagnosis, and fix by 3 specialist agents
initrunner run kube-advisor --file team.yaml --task "Pods are pending in staging"
```

Requires `kubectl` configured with cluster access. Optional: `helm`, `metrics-server`.

## Example prompts

```
My pod payment-service-7d4b8 is CrashLoopBackOff in payments
Services in staging can't reach the database
Pods are stuck Pending, nothing is scheduling
I'm getting OOMKilled on the recommendation-engine pod
DNS resolution is failing for cross-namespace calls
PVCs are stuck Pending after we changed the StorageClass
What's the overall health of my cluster?
```

## What's inside

**Interactive mode** (`role.yaml`): Single agent with kubectl/helm access, 6 diagnostic scripts (cluster health, pod diagnostics, networking, resources, storage, events), curated troubleshooting guides, web search fallback, and incident memory across sessions.

**Team mode** (`team.yaml`): Three personas work sequentially -- triage gathers cluster state, diagnostician identifies root cause, advisor writes fix commands with rollback plans.

**Kubernetes skill** (`skills/kubernetes/`): Reusable skill with kubectl/helm tools and diagnostic methodology. Reference it from your own agents:

```yaml
spec:
  skills:
    - vladkesler/kube-advisor:kubernetes
```

## Safety

Read-only by default. Before any mutation the agent explains what will change, shows current state, and waits for confirmation. Shell restricted to `kubectl` and `helm` only. Python tool runs sandboxed with no network.

## Changing the model

Edit `spec.model` in `role.yaml` or `team.yaml`. Memory uses embeddings that inherit from the model provider -- Anthropic falls back to OpenAI embeddings (`OPENAI_API_KEY` needed). See the [helpdesk README](../helpdesk/README.md) for embedding provider details.
