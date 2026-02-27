# Node Diagnostics Deep Dive

## Kubelet Logs

The kubelet is the primary node agent. Its logs are the first place to look when a node
is misbehaving.

### Accessing Kubelet Logs

```bash
# On the node (if SSH is available)
journalctl -u kubelet --since "1 hour ago" --no-pager
journalctl -u kubelet -f  # follow live

# Via kubectl (if node is still accessible to the API server)
kubectl get --raw "/api/v1/nodes/NODE/proxy/logs/messages" | tail -100

# EKS managed nodes: use SSM Session Manager
aws ssm start-session --target INSTANCE_ID
sudo journalctl -u kubelet --since "1 hour ago"

# Common log patterns to search for
journalctl -u kubelet | grep -i "error\|failed\|oom\|evict\|taint"
```

### Key Kubelet Log Messages

| Log Pattern | Meaning | Action |
|-------------|---------|--------|
| `PLEG is not healthy` | Pod Lifecycle Event Generator stalled | Check container runtime (containerd/docker) |
| `NodeHasSufficientMemory` -> `NodeHasInsufficientMemory` | Memory pressure triggered | Check pod memory usage, evictions incoming |
| `evicting pod` | Kubelet evicting a pod | Check which QoS class, fix resource limits |
| `Failed to pull image` | Container image pull failed | Check ECR auth, image exists, network |
| `Orphaned pod found` | Pod directory exists but pod is gone | Usually self-healing, check disk space if persistent |
| `Failed to create sandbox` | CNI network setup failed | Check CNI plugin (aws-node), IP exhaustion |

## Node Conditions

Each node reports its health via conditions. These are the authoritative status indicators.

```bash
# View all node conditions
kubectl describe node NODE | grep -A20 "Conditions:"

# Programmatic access to conditions
kubectl get node NODE -o jsonpath='{range .status.conditions[*]}{.type}: {.status} ({.reason}) - {.message}{"\n"}{end}'
```

### Condition Reference

| Condition | Healthy Value | Unhealthy Means |
|-----------|--------------|-----------------|
| Ready | True | Node cannot accept pods; kubelet or runtime is down |
| MemoryPressure | False | True = node is running low on memory, evictions imminent |
| DiskPressure | False | True = root or image filesystem is low on space |
| PIDPressure | False | True = too many processes on the node |
| NetworkUnavailable | False | True = CNI not configured, node network is broken |

### When a Node Goes NotReady

```bash
# Step 1: Check node conditions for the specific reason
kubectl describe node NODE | grep -B5 -A5 "Ready"

# Step 2: Check kubelet status on the node
systemctl status kubelet

# Step 3: Check container runtime
systemctl status containerd  # or docker
crictl ps  # list running containers via CRI

# Step 4: Check system resources
free -h          # memory
df -h            # disk
ps aux | wc -l   # process count

# Step 5: Check network connectivity
ping -c3 APISERVER_IP
curl -k https://APISERVER:6443/healthz
```

## Taints and Tolerations

Taints on nodes repel pods that do not have matching tolerations. This is a common
cause of "Pending" pods.

### Viewing Taints

```bash
# View taints on all nodes
kubectl get nodes -o custom-columns='NAME:.metadata.name,TAINTS:.spec.taints'

# View taints on a specific node
kubectl describe node NODE | grep -A5 Taints

# Common built-in taints
# node.kubernetes.io/not-ready                 - Node is not ready
# node.kubernetes.io/unreachable               - Node is unreachable from controller
# node.kubernetes.io/memory-pressure            - Node has memory pressure
# node.kubernetes.io/disk-pressure              - Node has disk pressure
# node.kubernetes.io/pid-pressure               - Node has PID pressure
# node.kubernetes.io/unschedulable              - Node is cordoned
```

### Taint Effects

| Effect | Behavior |
|--------|----------|
| NoSchedule | New pods without toleration will not be scheduled here |
| PreferNoSchedule | Scheduler tries to avoid but may schedule if no other option |
| NoExecute | Existing pods without toleration are evicted, new ones not scheduled |

### Managing Taints

```bash
# Add a taint to a node
kubectl taint nodes NODE key=value:NoSchedule

# Remove a taint from a node (note the trailing dash)
kubectl taint nodes NODE key=value:NoSchedule-

# Add toleration to a pod spec
# tolerations:
# - key: "key"
#   operator: "Equal"
#   value: "value"
#   effect: "NoSchedule"
```

## Node Affinity

Node affinity rules control which nodes a pod can be scheduled on, based on node labels.

### Checking Node Labels

```bash
# View all labels on a node
kubectl get node NODE --show-labels

# Common labels
# kubernetes.io/os                    - linux, windows
# kubernetes.io/arch                  - amd64, arm64
# topology.kubernetes.io/zone         - us-east-1a, us-east-1b
# topology.kubernetes.io/region       - us-east-1
# node.kubernetes.io/instance-type    - m5.xlarge
# eks.amazonaws.com/nodegroup         - my-nodegroup
# eks.amazonaws.com/capacityType      - ON_DEMAND, SPOT

# Find nodes matching a label selector
kubectl get nodes -l topology.kubernetes.io/zone=us-east-1a
```

### Pod Scheduling Algorithm

The Kubernetes scheduler follows this sequence to place a pod:

1. **Filtering**: Eliminate nodes that cannot run the pod
   - Insufficient resources (CPU, memory, ephemeral storage)
   - Node taints without matching tolerations
   - Node affinity rules not satisfied
   - Pod anti-affinity rules violated
   - PVC zone constraints (EBS volumes are AZ-bound)
2. **Scoring**: Rank remaining nodes
   - LeastRequestedPriority (spread pods across nodes)
   - BalancedResourceAllocation (balance CPU/memory ratio)
   - NodeAffinityPriority (prefer nodes matching preferred affinity)
   - PodTopologySpread (respect topology spread constraints)
3. **Binding**: Assign pod to highest-scoring node

### Debugging Scheduling Failures

```bash
# Check scheduler events for a pending pod
kubectl describe pod POD | grep -A10 Events

# Check if any node satisfies the pod's requirements
kubectl get nodes -o custom-columns='NAME:.metadata.name,CPU:.status.allocatable.cpu,MEM:.status.allocatable.memory,PODS:.status.allocatable.pods'

# Simulate scheduling (requires scheduler extender or descheduler)
# Alternative: check node fit manually
kubectl describe node NODE | grep -A10 "Allocated resources"
```

## kube-proxy Modes

kube-proxy implements Services by configuring network rules on each node.

### iptables Mode (Default)

- Creates iptables rules for each Service ClusterIP and NodePort
- O(N) rule lookup time where N = number of services
- Works well for < 5000 services
- Rules visible with: `iptables -t nat -L KUBE-SERVICES`

### IPVS Mode

- Uses Linux IPVS (IP Virtual Server) kernel module
- O(1) lookup time using hash tables
- Better performance for large clusters (> 5000 services)
- Supports multiple load balancing algorithms: rr, lc, dh, sh, sed, nq
- Check mode: `kubectl get configmap kube-proxy -n kube-system -o yaml | grep mode`
- IPVS rules: `ipvsadm -Ln`

### Diagnosing kube-proxy Issues

```bash
# Check kube-proxy pods
kubectl get pods -n kube-system -l k8s-app=kube-proxy

# Check kube-proxy logs
kubectl logs -n kube-system -l k8s-app=kube-proxy --tail=50

# Verify iptables rules exist for a service
iptables -t nat -L KUBE-SERVICES | grep SERVICE_NAME

# Check conntrack table (connection tracking)
conntrack -L | wc -l  # total entries
conntrack -S           # stats including drops

# Common issue: conntrack table full -> connections drop silently
# Fix: increase net.netfilter.nf_conntrack_max sysctl
```

## Node Drain Procedure

Draining a node safely moves all pods off before maintenance.

```bash
# Step 1: Cordon the node (prevent new pods from scheduling)
kubectl cordon NODE

# Step 2: Drain the node (evict existing pods)
kubectl drain NODE --ignore-daemonsets --delete-emptydir-data --timeout=300s

# If drain hangs: check PDBs that might be blocking eviction
kubectl get pdb --all-namespaces

# Step 3: Perform maintenance

# Step 4: Uncordon the node (allow scheduling again)
kubectl uncordon NODE
```

### Drain Flags Reference

| Flag | Purpose |
|------|---------|
| `--ignore-daemonsets` | Skip DaemonSet pods (they will be recreated) |
| `--delete-emptydir-data` | Delete pods using emptyDir volumes (data will be lost) |
| `--force` | Force delete pods not managed by a controller |
| `--grace-period=N` | Override pod termination grace period |
| `--timeout=Ns` | Timeout for the entire drain operation |
| `--pod-selector=key=val` | Only drain pods matching the selector |
| `--disable-eviction` | Use DELETE instead of Eviction API (bypasses PDBs) |

## Graceful Shutdown

When a pod is terminated, Kubernetes follows this sequence:

1. Pod is set to "Terminating" state
2. Endpoints are removed from Services (traffic stops being routed)
3. PreStop hook runs (if defined)
4. SIGTERM is sent to PID 1 in each container
5. Grace period countdown starts (default: 30 seconds)
6. If still running after grace period: SIGKILL is sent

### Common Shutdown Issues

```bash
# Pod takes too long to terminate
# Check terminationGracePeriodSeconds in pod spec
kubectl get pod POD -o jsonpath='{.spec.terminationGracePeriodSeconds}'

# Application does not handle SIGTERM
# Fix: add a signal handler, or use a preStop hook:
# lifecycle:
#   preStop:
#     exec:
#       command: ["/bin/sh", "-c", "sleep 5 && kill -TERM 1"]

# Connections still routing during shutdown
# Fix: add a preStop sleep to allow endpoint propagation:
# lifecycle:
#   preStop:
#     exec:
#       command: ["sleep", "15"]
```

## Node Auto-Repair

### EKS Managed Node Group Auto-Repair

EKS managed node groups automatically replace unhealthy instances:

```bash
# Check node group health
aws eks describe-nodegroup --cluster-name CLUSTER --nodegroup-name NG \
  --query 'nodegroup.health'

# Check ASG instance health
aws autoscaling describe-auto-scaling-instances \
  --query 'AutoScalingInstances[?AutoScalingGroupName==`ASG_NAME`].[InstanceId,HealthStatus,LifecycleState]' \
  --output table

# Check EC2 instance status checks
aws ec2 describe-instance-status --instance-ids INSTANCE_ID \
  --query 'InstanceStatuses[*].[InstanceId,InstanceStatus.Status,SystemStatus.Status]' \
  --output table
```

### Cluster Autoscaler vs Karpenter

| Feature | Cluster Autoscaler | Karpenter |
|---------|-------------------|-----------|
| Scaling unit | ASG / Managed Node Group | Individual EC2 instances |
| Scale-up speed | 2-5 minutes | 30-90 seconds |
| Instance selection | Fixed per node group | Dynamic (best-fit from all types) |
| Consolidation | Limited | Aggressive bin-packing + deprovisioning |
| EKS integration | Via addon | Via Helm chart |

```bash
# Check Cluster Autoscaler status
kubectl get configmap cluster-autoscaler-status -n kube-system -o yaml

# Check Karpenter provisioner status
kubectl get provisioners
kubectl get machines  # Karpenter v1beta1+
kubectl describe machine MACHINE_NAME

# Check scaling events
kubectl get events --field-selector reason=TriggeredScaleUp -n kube-system
kubectl get events --field-selector reason=ScaledDown -n kube-system
```
