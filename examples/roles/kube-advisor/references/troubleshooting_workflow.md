# Kubernetes Troubleshooting Workflows

Decision trees and step-by-step workflows for systematic Kubernetes debugging.

---

## General Debugging Workflow

Use this as the entry point for any issue.

```
Start
  |
  v
1. Confirm cluster access (kubectl cluster-info)
  |
  v
2. Identify the scope
   - Single pod? --> Pod Lifecycle Workflow
   - Service unreachable? --> Network Workflow
   - Whole namespace affected? --> Resource & Performance Workflow
   - Storage issue? --> Storage Workflow
   - Deployment not progressing? --> Rollout Workflow
  |
  v
3. Gather baseline
   kubectl get pods -n <ns>
   kubectl get events -n <ns> --sort-by=.lastTimestamp
  |
  v
4. Follow the appropriate workflow below
  |
  v
5. Verify fix and check for cascading effects
```

---

## Pod Lifecycle Workflow

### Pod stuck in Pending

```
Pod is Pending
  |
  v
kubectl describe pod <name> -n <ns>
  |
  +-- "Insufficient cpu/memory"
  |     --> kubectl top nodes
  |     --> Scale cluster or reduce requests
  |
  +-- "node(s) had taint" / "didn't match node selector"
  |     --> kubectl describe node <name>
  |     --> Add tolerations or fix nodeSelector/affinity
  |
  +-- "persistentvolumeclaim not found" / "unbound"
  |     --> Go to Storage Workflow
  |
  +-- "exceeded quota"
        --> kubectl get resourcequotas -n <ns>
        --> Increase quota or free resources
```

### Pod in CrashLoopBackOff

```
Pod is CrashLoopBackOff
  |
  v
kubectl logs <name> -n <ns> --previous
  |
  +-- Application error visible in logs
  |     --> Fix the application code or configuration
  |     --> Check ConfigMap/Secret mounts
  |
  +-- No useful logs
  |     |
  |     v
  |   kubectl describe pod <name> -n <ns>
  |     |
  |     +-- Exit code 137 (OOMKilled)
  |     |     --> kubectl top pod <name> -n <ns> --containers
  |     |     --> Increase memory limits or fix leak
  |     |
  |     +-- Exit code 1 (generic error)
  |     |     --> Check command/args in pod spec
  |     |     --> Verify entrypoint script exists and is executable
  |     |
  |     +-- Liveness probe failed
  |           --> Check probe config (port, path, delays)
  |           --> Increase initialDelaySeconds or timeoutSeconds
  |
  +-- Permission denied / exec format error
        --> Check image architecture (amd64 vs arm64)
        --> Check file permissions in the image
```

### Pod in ImagePullBackOff

```
Pod is ImagePullBackOff
  |
  v
kubectl describe pod <name> -n <ns>
  |
  +-- "unauthorized" / "access denied"
  |     --> kubectl get secrets -n <ns> | grep docker
  |     --> Create or fix imagePullSecrets
  |
  +-- "not found" / "manifest unknown"
  |     --> Verify image:tag exists in the registry
  |     --> Check for typos in the image reference
  |
  +-- "timeout" / "connection refused"
        --> Check node network access to the registry
        --> Check DNS resolution from the node
        --> Check firewall or proxy settings
```

---

## Network Troubleshooting Workflow

### Service connectivity

```
Service not responding
  |
  v
kubectl get endpoints <svc> -n <ns>
  |
  +-- Endpoints list is empty
  |     |
  |     v
  |   kubectl get svc <svc> -n <ns> -o yaml   # Check selector
  |   kubectl get pods -n <ns> -l <selector>   # Match pods
  |     |
  |     +-- No pods match selector
  |     |     --> Fix Service selector or Pod labels
  |     |
  |     +-- Pods exist but not Ready
  |           --> Debug pods (see Pod Lifecycle)
  |           --> Check readiness probe
  |
  +-- Endpoints exist but connection fails
        |
        v
      Check port mapping
        kubectl get svc <svc> -n <ns> -o yaml  # port vs targetPort
        |
        +-- Port mismatch
        |     --> Fix port or targetPort in Service spec
        |
        +-- Ports correct
              |
              v
            Check NetworkPolicies
              kubectl get networkpolicies -n <ns>
              |
              +-- Policy blocking traffic
              |     --> Add ingress/egress rule
              |
              +-- No blocking policies
                    --> Test from within the cluster:
                    kubectl exec <pod> -- curl <svc>:<port>
                    --> Check if the application is listening on the right port
```

### DNS troubleshooting

```
DNS resolution failing
  |
  v
kubectl get pods -n kube-system -l k8s-app=kube-dns
  |
  +-- CoreDNS pods not running
  |     --> kubectl describe pod -n kube-system -l k8s-app=kube-dns
  |     --> Check CoreDNS resource limits and node resources
  |     --> kubectl rollout restart deployment/coredns -n kube-system
  |
  +-- CoreDNS pods running
        |
        v
      kubectl exec <pod> -n <ns> -- nslookup kubernetes.default
        |
        +-- Fails --> Pod DNS config issue
        |     kubectl exec <pod> -- cat /etc/resolv.conf
        |     --> Fix dnsPolicy or dnsConfig on the pod
        |
        +-- Succeeds --> Service-specific issue
              kubectl exec <pod> -- nslookup <svc>.<ns>.svc.cluster.local
              --> Verify the Service exists in the correct namespace
              --> Use FQDN for cross-namespace resolution
```

---

## Resource and Performance Workflow

### High resource usage

```
Resource pressure detected
  |
  v
kubectl top nodes
  |
  +-- Node CPU > 90%
  |     --> kubectl top pods -A --sort-by=cpu | head -20
  |     --> Identify hot pods, scale horizontally or optimize
  |
  +-- Node memory > 90%
  |     --> kubectl top pods -A --sort-by=memory | head -20
  |     --> Check for OOMKilled pods
  |     --> Right-size memory limits
  |
  +-- Nodes look fine but pods are slow
        --> kubectl describe node <name>   # Check allocatable vs requests
        --> Pods may be CPU-throttled due to limits
        --> Consider removing CPU limits (keep requests)
```

### Node exhaustion

```
Node showing pressure conditions
  |
  v
kubectl describe node <name>
  |
  +-- MemoryPressure: True
  |     --> Eviction threshold reached
  |     --> Pods will be evicted by priority
  |     --> Scale up cluster or reduce workload
  |
  +-- DiskPressure: True
  |     --> Clean up unused images: crictl rmi --prune
  |     --> Check for pods writing large volumes of logs
  |     --> Increase node disk size
  |
  +-- PIDPressure: True
        --> Check for fork bombs or runaway processes
        --> kubectl top pods on the node
        --> Set PID limits in the container runtime
```

---

## Storage Workflow

### PVC binding issues

```
PVC stuck in Pending
  |
  v
kubectl describe pvc <name> -n <ns>
  |
  +-- "no persistent volumes available"
  |     --> kubectl get pv   # Check available PVs
  |     --> Verify size, accessMode, and storageClass match
  |     --> Create a matching PV or fix the PVC spec
  |
  +-- "storageclass not found"
  |     --> kubectl get sc
  |     --> Create the StorageClass or fix the name in the PVC
  |
  +-- "waiting for first consumer"
  |     --> Normal for WaitForFirstConsumer binding mode
  |     --> PVC will bind when a pod using it is scheduled
  |
  +-- "exceeded quota" / provisioning failed
        --> Check cloud provider disk quotas
        --> kubectl get resourcequotas -n <ns>
        --> Request quota increase or free existing volumes
```

---

## Deployment and Rollout Workflow

### Stuck rollout

```
Deployment not progressing
  |
  v
kubectl rollout status deployment/<name> -n <ns>
  |
  v
kubectl get rs -n <ns> -l <selector>
  |
  +-- New ReplicaSet has 0 ready replicas
  |     --> Debug the new pods (see Pod Lifecycle)
  |     --> Common: ImagePullBackOff on new image tag
  |
  +-- Old ReplicaSet not scaling down
  |     --> kubectl get pdb -n <ns>
  |     --> PDB may be blocking eviction
  |     --> Temporarily relax PDB or scale up first
  |
  +-- Both ReplicaSets partially scaled
        --> Check maxSurge and maxUnavailable settings
        --> kubectl describe deployment <name> -n <ns>
        --> May need more cluster headroom for surge

If stuck, rollback:
  kubectl rollout undo deployment/<name> -n <ns>

Verify:
  kubectl rollout status deployment/<name> -n <ns>
  kubectl get pods -n <ns> -l <selector>
```

---

## Quick Reference Commands

### Cluster overview
```bash
kubectl cluster-info
kubectl get nodes -o wide
kubectl top nodes
kubectl get pods -A | grep -v Running | grep -v Completed
```

### Namespace overview
```bash
kubectl get all -n <ns>
kubectl get events -n <ns> --sort-by=.lastTimestamp | tail -30
kubectl top pods -n <ns>
```

### Resource audit
```bash
kubectl get resourcequotas -n <ns>
kubectl describe resourcequota -n <ns>
kubectl get limitranges -n <ns>
```

### Emergency commands
```bash
kubectl rollout undo deployment/<name> -n <ns>
kubectl scale deployment/<name> --replicas=<n> -n <ns>
kubectl cordon <node>
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data
kubectl delete pod <name> -n <ns> --grace-period=0 --force
```
