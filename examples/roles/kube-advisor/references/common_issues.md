# Common Kubernetes Issues

Quick symptom-to-fix reference for the most frequent Kubernetes problems.

---

## CrashLoopBackOff

### Symptoms
- Pod status shows `CrashLoopBackOff`
- Container restarts count increasing
- Back-off delay growing between restarts

### Common causes
1. Application error on startup (missing config, bad entrypoint)
2. Liveness probe failing (wrong port, path, or too-tight thresholds)
3. OOMKilled (exit code 137) -- container exceeding memory limits
4. Missing dependencies (database not reachable, secret not mounted)
5. Incorrect command or args in the pod spec

### Debugging commands
```bash
kubectl describe pod <name> -n <ns>          # Check events and probe config
kubectl logs <name> -n <ns> --tail=100       # Current container logs
kubectl logs <name> -n <ns> --previous       # Previous crash logs
kubectl get pod <name> -n <ns> -o yaml       # Full spec with exit codes
```

### Solutions
- **Bad entrypoint**: Fix the command/args in the deployment spec
- **Probe failure**: Adjust `initialDelaySeconds`, `timeoutSeconds`, or fix the endpoint
- **OOMKilled**: Increase `resources.limits.memory` or fix the memory leak
- **Missing config**: Verify ConfigMaps/Secrets exist and are mounted correctly
- **Dependency failure**: Check the dependency is reachable from the pod network

### Done when
- Pod status is `Running`, restart count stabilizes, no new CrashLoopBackOff events

---

## ImagePullBackOff / ErrImagePull

### Symptoms
- Pod status shows `ImagePullBackOff` or `ErrImagePull`
- Events show "Failed to pull image" or "unauthorized"

### Common causes
1. Image tag does not exist in the registry
2. Missing or incorrect `imagePullSecrets`
3. Private registry requires authentication
4. Registry is unreachable (network policy, DNS, firewall)
5. Typo in image name

### Debugging commands
```bash
kubectl describe pod <name> -n <ns>          # Check image name and events
kubectl get pod <name> -n <ns> -o jsonpath='{.spec.containers[*].image}'
kubectl get secrets -n <ns>                  # Verify pull secrets exist
```

### Solutions
- **Wrong tag**: Verify the tag exists in the registry, fix the image reference
- **Auth failure**: Create or update the `imagePullSecret`, ensure it is referenced in the pod spec
- **Network issue**: Check DNS resolution and network policies from the node
- **Typo**: Correct the image name in the deployment spec

### Done when
- Pod pulls the image successfully, status moves past `Init` or `ContainerCreating`

---

## Pending Pods (Scheduling Failures)

### Symptoms
- Pod stuck in `Pending` status
- Events show "FailedScheduling" or "Insufficient cpu/memory"

### Common causes
1. Insufficient cluster resources (CPU, memory, GPU)
2. Node taints without matching tolerations
3. NodeSelector or affinity rules that no node satisfies
4. PVC not bound (waiting for storage)
5. ResourceQuota exceeded

### Debugging commands
```bash
kubectl describe pod <name> -n <ns>          # Scheduling events and conditions
kubectl get nodes -o wide                    # Node status and capacity
kubectl top nodes                            # Current resource usage
kubectl get resourcequotas -n <ns>           # Quota usage
kubectl describe node <node-name>            # Taints, allocatable, conditions
```

### Solutions
- **Insufficient resources**: Scale up the cluster or reduce resource requests
- **Taints**: Add matching tolerations to the pod spec or remove the taint
- **Affinity/selector**: Relax the constraints or label appropriate nodes
- **PVC pending**: See the Storage section below
- **Quota exceeded**: Increase the ResourceQuota or free up existing resources

### Done when
- Pod is scheduled and moves to `ContainerCreating` or `Running`

---

## OOMKilled (Exit Code 137)

### Symptoms
- Container terminated with exit code 137
- `reason: OOMKilled` in pod status
- Pod may enter CrashLoopBackOff

### Common causes
1. Memory limit set too low for the workload
2. Memory leak in the application
3. JVM heap not aligned with container limits (`-Xmx` too high)
4. Sidecar containers consuming unexpected memory

### Debugging commands
```bash
kubectl describe pod <name> -n <ns>          # Check termination reason
kubectl get pod <name> -n <ns> -o jsonpath='{.status.containerStatuses[*].lastState}'
kubectl top pod <name> -n <ns> --containers  # Per-container memory usage
```

### Solutions
- **Limit too low**: Increase `resources.limits.memory` (check actual usage first)
- **Memory leak**: Profile the application, check for unbounded caches or connections
- **JVM**: Set `-Xmx` to ~75% of the container memory limit
- **Sidecars**: Review sidecar resource usage and set appropriate limits

### Done when
- Container runs without OOMKilled, memory usage stays within limits

---

## Service Not Accessible

### Symptoms
- Connection refused or timeout when accessing a Service
- `curl <service>:<port>` fails from within the cluster

### Common causes
1. Selector mismatch -- Service labels do not match Pod labels
2. No ready endpoints (all backing pods are down)
3. Wrong port or targetPort in the Service spec
4. NetworkPolicy blocking traffic
5. Pod not passing readiness probe

### Debugging commands
```bash
kubectl get svc <name> -n <ns>               # Service type, ports, selector
kubectl get endpoints <name> -n <ns>         # Backing pod IPs
kubectl describe svc <name> -n <ns>          # Full spec and events
kubectl get pods -n <ns> -l <selector>       # Pods matching the selector
kubectl get networkpolicies -n <ns>          # Network restrictions
```

### Solutions
- **Selector mismatch**: Align Service selector with Pod labels
- **No endpoints**: Fix the backing pods (check CrashLoopBackOff, Pending, etc.)
- **Wrong port**: Correct the port/targetPort in the Service spec
- **NetworkPolicy**: Add an ingress rule allowing traffic from the source
- **Readiness probe**: Fix the probe or adjust thresholds

### Done when
- `kubectl get endpoints` shows ready IPs, Service responds to requests

---

## DNS Resolution Failures

### Symptoms
- `nslookup <service>` fails from a pod
- "Name or service not known" errors in application logs

### Common causes
1. CoreDNS pods not running or crashing
2. Service name typo or wrong namespace qualifier
3. NetworkPolicy blocking DNS (UDP 53)
4. Pod DNS config overridden incorrectly

### Debugging commands
```bash
kubectl get pods -n kube-system -l k8s-app=kube-dns   # CoreDNS status
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=50
kubectl exec <pod> -n <ns> -- nslookup <service>      # Test from the pod
kubectl exec <pod> -n <ns> -- cat /etc/resolv.conf     # Pod DNS config
```

### Solutions
- **CoreDNS down**: Restart CoreDNS, check its resource limits and logs
- **Wrong name**: Use `<service>.<namespace>.svc.cluster.local` for cross-namespace
- **NetworkPolicy**: Allow egress to `kube-dns` on UDP/TCP 53
- **DNS config**: Remove custom `dnsConfig` or fix it

### Done when
- DNS resolves correctly from the affected pod

---

## PVC Pending

### Symptoms
- PersistentVolumeClaim stuck in `Pending`
- Pod referencing the PVC also stuck in `Pending`

### Common causes
1. No matching PersistentVolume (wrong size, accessMode, storageClass)
2. StorageClass does not exist or has no provisioner
3. Cloud provider quota exceeded (disk limits)
4. WaitForFirstConsumer binding mode and no pod scheduled yet

### Debugging commands
```bash
kubectl get pvc -n <ns>                      # PVC status and storage class
kubectl describe pvc <name> -n <ns>          # Binding events
kubectl get pv                               # Available PersistentVolumes
kubectl get sc                               # StorageClasses
kubectl get events -n <ns> --field-selector reason=ProvisioningFailed
```

### Solutions
- **No matching PV**: Create one with correct size, accessMode, and storageClass
- **Bad StorageClass**: Fix the name or create the StorageClass
- **Quota**: Request a quota increase from the cloud provider
- **WaitForFirstConsumer**: Normal behavior -- PVC binds after pod is scheduled

### Done when
- PVC status is `Bound`, pod using it moves to `Running`

---

## Deployment Stuck / Not Rolling Out

### Symptoms
- `kubectl rollout status` hangs
- New ReplicaSet has 0 ready replicas
- Old pods still running, new pods not starting

### Common causes
1. New pods failing (CrashLoopBackOff, ImagePullBackOff)
2. PDB (PodDisruptionBudget) blocking eviction of old pods
3. Insufficient resources for new pods
4. `maxUnavailable: 0` with no room for new pods

### Debugging commands
```bash
kubectl rollout status deployment/<name> -n <ns>
kubectl get rs -n <ns> -l <selector>         # ReplicaSets and readiness
kubectl describe deployment <name> -n <ns>   # Conditions and events
kubectl get pdb -n <ns>                      # Disruption budgets
```

### Solutions
- **New pods failing**: Debug the new pods (see relevant sections above)
- **PDB blocking**: Temporarily relax the PDB or scale up first
- **No resources**: Free up resources or scale the cluster
- **Strategy**: Adjust `maxSurge`/`maxUnavailable` for the rollout

### Rollback
```bash
kubectl rollout undo deployment/<name> -n <ns>
```

### Done when
- All new replicas are ready, old ReplicaSet scaled to 0

---

## High CPU/Memory Usage

### Symptoms
- Nodes showing pressure conditions
- Pods being evicted
- Application latency increasing

### Debugging commands
```bash
kubectl top nodes                            # Node-level usage
kubectl top pods -n <ns> --sort-by=memory    # Top memory consumers
kubectl top pods -n <ns> --sort-by=cpu       # Top CPU consumers
kubectl describe node <name>                 # Conditions, allocatable vs capacity
```

### Solutions
- **Hot pods**: Scale horizontally (HPA) or increase resource limits
- **Node pressure**: Add nodes, cordon and drain overloaded nodes
- **Resource drift**: Review requests vs actual usage, right-size containers

### Done when
- Node conditions clear, no evictions, application latency normal

---

## ConfigMap/Secret Not Found

### Symptoms
- Pod events show "ConfigMap not found" or "Secret not found"
- Container fails to start or environment variables are empty

### Debugging commands
```bash
kubectl get configmaps -n <ns>               # List available ConfigMaps
kubectl get secrets -n <ns>                  # List available Secrets
kubectl describe pod <name> -n <ns>          # Mount and env references
```

### Solutions
- **Missing resource**: Create the ConfigMap/Secret in the correct namespace
- **Wrong name**: Fix the reference in the pod spec
- **Wrong namespace**: Resources must be in the same namespace as the pod
- **Optional flag**: Set `optional: true` on the volume or envFrom if appropriate

### Done when
- Pod starts successfully with the correct config/secrets mounted
