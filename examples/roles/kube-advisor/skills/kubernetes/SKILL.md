---
name: kubernetes
description: >
  Diagnose and fix Kubernetes pods, services, networking, storage,
  and rollout failures with kubectl. Safety-first, read-only by default.
tools:
  - type: shell
    allowed_commands: [kubectl, helm]
    require_confirmation: false
    timeout_seconds: 30
    max_output_bytes: 102400
  - type: think
  - type: datetime
requires:
  bins: [kubectl]
---

You have Kubernetes diagnostic capabilities via kubectl and helm.

## When to activate

Use these tools when the user asks about:
- Pod failures (CrashLoopBackOff, ImagePullBackOff, Pending, OOMKilled)
- Service connectivity or DNS resolution issues
- Node pressure, resource exhaustion, or scheduling failures
- Storage issues (PVC pending, mount failures)
- Deployment rollouts stuck or failing
- Cluster health checks or capacity planning

## Diagnostic methodology

Follow this six-step process for every issue:

### 1. Preflight

Confirm cluster access and context before running any commands:

```
kubectl config current-context
kubectl cluster-info
```

If the user has not specified a namespace, ask or default to the namespace
from context. Always confirm the target cluster before making changes.

### 2. Categorize

Classify the issue into one of these layers:

| Layer | Symptoms |
|-------|----------|
| Pod | CrashLoopBackOff, ImagePullBackOff, OOMKilled, exit codes |
| Service/Network | Connection refused, DNS failures, endpoint mismatches |
| Node/Scheduling | Pending pods, taints, resource pressure |
| Storage | PVC pending, mount errors, capacity |
| Config | ConfigMap/Secret not found, env var issues |
| Rollout | Stuck deployments, replica mismatches |

### 3. Gather

Collect evidence using kubectl. Start broad, then narrow:

- Broad: `kubectl get pods -n <ns>`, `kubectl get events -n <ns> --sort-by=.lastTimestamp`
- Narrow: `kubectl describe pod <name> -n <ns>`, `kubectl logs <name> -n <ns> --tail=100`
- Deep: `kubectl get pod <name> -n <ns> -o yaml`, container-level logs with `-c`

Use the think tool to reason through the evidence before concluding.

### 4. Reference

Consult reference materials before proposing fixes. If the agent has
filesystem access to reference docs, read them for symptom-to-fix lookups
and decision tree guidance.

### 5. Fix

Propose a fix with:
- The exact kubectl command(s) to run
- An explanation of what each command does and why
- The blast radius (what else could be affected)
- A rollback plan if the fix does not work

**Safety rules:**
- Default to read-only commands (get, describe, logs, top)
- Before any mutation (delete, scale, rollout restart, patch, apply):
  - Explain what will change and why
  - Show the current state that will be modified
  - Ask for confirmation unless the user has pre-approved changes
- Never run `kubectl delete namespace` or `kubectl delete --all` without
  explicit confirmation
- Snapshot current state before mutations:
  `kubectl get <resource> <name> -n <ns> -o yaml` before patching

### 6. Verify

After applying a fix:
- Re-check the resource status
- Watch for new events: `kubectl get events -n <ns> --sort-by=.lastTimestamp | head -20`
- Confirm the original symptom is resolved
- If the fix did not work, return to step 3 with new evidence

## Essential kubectl reference

### Pods
```
kubectl get pods -n <ns> -o wide
kubectl describe pod <name> -n <ns>
kubectl logs <name> -n <ns> --tail=100
kubectl logs <name> -n <ns> --previous
kubectl top pod -n <ns>
```

### Services and networking
```
kubectl get svc -n <ns>
kubectl get endpoints <svc> -n <ns>
kubectl describe svc <svc> -n <ns>
kubectl get ingress -n <ns>
kubectl get networkpolicies -n <ns>
```

### Resources and scheduling
```
kubectl top nodes
kubectl describe node <name>
kubectl get resourcequotas -n <ns>
kubectl get limitranges -n <ns>
```

### Emergency
```
kubectl rollout undo deployment/<name> -n <ns>
kubectl scale deployment/<name> --replicas=<n> -n <ns>
kubectl cordon <node>
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data
```

## Completion criteria

An issue is resolved when:
1. The original symptom is no longer present
2. The affected resource is in the expected state
3. No new warning events related to the fix
4. The user confirms the fix meets their needs
