---
name: aws-compute
description: "AWS compute troubleshooting — covers EC2 (launch failures, instance status checks, EBS issues, networking), ECS (task placement, service events, container health), EKS (node scaling, cluster issues), and Lambda (cold starts, timeouts, concurrency, memory tuning). Includes decision trees for common failure modes."
metadata:
  author: agenticops
  version: "1.0"
  domain: compute
---

# AWS Compute Skill

## Quick Decision Trees

### EC2 Instance Issues

1. Check status: `aws ec2 describe-instance-status --instance-ids ID`
2. **System status check failed** (AWS infrastructure issue):
   - Stop/start instance (migrates to new host) -- NOT reboot
   - If EBS-backed: stop then start. If instance-store: data loss risk
   - Check `StatusCheckFailed_System` CloudWatch metric for historical pattern
   - If recurring, file AWS Support case -- may be degraded hardware
3. **Instance status check failed** (OS-level issue):
   - Check system logs: `aws ec2 get-console-output --instance-id ID`
   - Common causes: kernel panic, fstab error, full disk, corrupted boot volume
   - Fix: detach root volume, attach to rescue instance, mount and repair, reattach
   - For fstab: comment out bad entries, ensure `nofail` option on non-critical mounts
   - For full disk: clear /tmp, rotate logs, expand volume
4. **Launch failure**:
   - `InsufficientInstanceCapacity` -- try different AZ or instance type, use capacity reservations
   - `InstanceLimitExceeded` -- request service quota increase via Service Quotas console
   - `InvalidParameterValue` -- check AMI exists in region, subnet is in correct VPC, SG in same VPC
   - `Client.InvalidParameterCombination` -- instance type not available in AZ
   - `UnauthorizedOperation` -- check IAM permissions for ec2:RunInstances
5. **Cannot connect (SSH/RDP)**:
   - Security group: inbound rule for port 22 (SSH) or 3389 (RDP) from your IP
   - NACL: check both inbound AND outbound rules (stateless, both directions needed)
   - Public IP/EIP assigned if connecting from internet
   - Key pair matches, permissions on .pem file (`chmod 400 key.pem`)
   - Route table: subnet has route to IGW (public subnet) or NAT (private subnet)
   - OS firewall: iptables/firewalld/ufw may be blocking
   - SSM Session Manager: alternative when SSH is not feasible
6. **Instance stuck in stopping/shutting-down**:
   - Force stop: `aws ec2 stop-instances --instance-ids ID --force`
   - If stuck for >20 min, file AWS Support case
   - Check if instance has instance store volumes (cannot be stopped, only terminated)

### ECS Task Failures

1. `aws ecs describe-services --cluster CLUSTER --services SVC` -- check events field
2. **Task placement failure**:
   - "no container instances met all requirements" -- check:
     - ASG desired count and instance health
     - CPU/memory available vs task definition requirements
     - Port conflicts (host networking mode)
     - Placement constraints (distinctInstance, memberOf expressions)
   - Fargate: check subnet has routes, NAT gateway for internet, VPC endpoints for ECR/S3/CloudWatch Logs
   - Capacity providers: check weight and base settings
3. **Task crashes** (STOPPED status):
   - `aws ecs describe-tasks --cluster CLUSTER --tasks TASK_ARN` -- check `stoppedReason` and `containers[].reason`
   - "Essential container in task exited" -- check CloudWatch Logs for the container
   - "OutOfMemoryError: Container killed due to memory usage" -- increase task memory definition
   - "CannotPullContainerError" -- ECR permissions (ecr:GetDownloadUrlForLayer, ecr:BatchGetImage), NAT/VPC endpoint
   - "ResourceInitializationError: unable to pull secrets" -- Secrets Manager/SSM permissions, VPC endpoints
   - Exit code 137: OOM killed. Exit code 1: application error. Exit code 139: segfault
4. **Service unstable** (keeps restarting):
   - Health check misconfiguration: ALB target group health check path returning non-200
   - Health check grace period too short for application startup time
   - Resource starvation: container memory/CPU limits too low
   - Dependency failure: database/cache not reachable from task subnet
   - Check deployment circuit breaker settings
5. **Deployment stuck**:
   - `aws ecs describe-services --cluster CLUSTER --services SVC` -- check `deployments` array
   - PRIMARY deployment not reaching steady state -- check events for placement failures
   - Minimum healthy percent and maximum percent settings
   - Rolling update blocked by insufficient capacity for new + old tasks simultaneously
   - Force new deployment: `aws ecs update-service --cluster CLUSTER --service SVC --force-new-deployment`

### Lambda Issues

1. **Timeout**:
   - Check function timeout setting vs actual duration in CloudWatch `Duration` metric
   - VPC Lambda: NAT gateway required for internet access, VPC endpoints for AWS services
   - Cold start in VPC: ENI creation adds 1-10s (improved with Hyperplane ENIs)
   - Downstream dependency slow: database connection pooling, API call timeouts
   - Increase timeout (max 900s / 15 min) or optimize code paths
   - Use X-Ray tracing to identify slow segments
2. **Throttling** (429 TooManyRequestsException):
   - Concurrent executions at account limit (default 1000, can request increase)
   - Reserved concurrency set too low on function
   - Provisioned concurrency for consistent latency-sensitive workloads
   - Check `Throttles` metric and `ConcurrentExecutions` metric
   - SQS trigger: reduce batch size or max concurrency
   - API Gateway: check stage throttling settings
3. **Memory/OOM**:
   - "Runtime exited with error: signal: killed" = OOM
   - "RequestId: xxx Process exited before completing request" = likely OOM
   - Increase memory setting (also increases proportional CPU allocation)
   - Check CloudWatch `MaxMemoryUsed` metric vs configured memory
   - Memory/CPU scaling: 128MB is approx 0.08 vCPU, 1769MB is 1 full vCPU, 10240MB is 6 vCPU
   - Profile with Lambda Power Tuning to find optimal memory/cost balance
4. **Permission errors**:
   - Execution role missing required IAM policies
   - Resource-based policy needed for cross-account invocation or service triggers
   - VPC Lambda: role needs `ec2:CreateNetworkInterface`, `ec2:DescribeNetworkInterfaces`, `ec2:DeleteNetworkInterface`
   - KMS: if using encrypted env vars, role needs `kms:Decrypt`
   - Check CloudWatch Logs -- permission errors appear as stack traces
5. **Deployment issues**:
   - Package too large: 50MB zipped direct, 250MB unzipped, 10GB container image
   - Layer version limit: 5 layers per function
   - Alias/version: traffic shifting for safe deployments
   - `aws lambda get-function --function-name NAME` -- check `LastUpdateStatus`

### EKS Node Scaling

1. **Cluster Autoscaler vs Karpenter**:
   - Cluster Autoscaler (CA): manages ASG min/max, respects node groups, slower (minutes)
   - Karpenter: provisions EC2 directly, more flexible instance selection, faster (seconds)
   - CA: better for homogeneous workloads. Karpenter: better for diverse/dynamic workloads
2. **Scaling not happening**:
   - Check pending pods: `kubectl get pods --field-selector=status.phase=Pending`
   - CA logs: `kubectl logs -n kube-system deployment/cluster-autoscaler`
   - Node group max reached: check ASG `MaxSize`
   - Pod requests too large: no instance type can satisfy CPU/memory requests
   - Pod affinity/anti-affinity preventing scheduling
   - Taints on nodes preventing scheduling: `kubectl describe node NODE | grep Taints`
3. **Scale-down issues** (nodes not removed):
   - PodDisruptionBudget (PDB) blocking eviction
   - Local storage pods (emptyDir with data)
   - Pods without controller (bare pods, not managed by Deployment/ReplicaSet)
   - Pods with `cluster-autoscaler.kubernetes.io/safe-to-evict: "false"` annotation
   - Scale-down utilization threshold (default: 50%)
   - Scale-down delay after scale-up (default: 10 min)
4. **Node not joining cluster**:
   - Check node instance profile has EKS worker node policy
   - `aws-auth` ConfigMap must include node IAM role
   - Node security group must allow communication with control plane
   - Check kubelet logs: `journalctl -u kubelet` on the node
   - DNS resolution: node must resolve cluster API endpoint

## Common Patterns

### EC2 Performance Optimization

- Enhanced networking: verify ENA driver with `ethtool -i eth0 | grep driver`
- Placement groups: cluster (low latency HPC), spread (HA, max 7 per AZ), partition (large distributed)
- Burst credits (T3/T3a): check `CPUCreditBalance` metric, enable unlimited mode for sustained workloads
- EBS-optimized: verify instance type supports it (most current gen do by default)
- Instance store: NVMe SSDs for temp/cache/scratch -- data lost on stop/terminate
- Nitro instances: better networking, EBS, and security compared to Xen

### ECS Capacity Planning

- Task CPU/Memory: 1 vCPU = 1024 CPU units
- Fargate sizes: 0.25-16 vCPU, 0.5-120 GB memory (specific valid combinations only)
- Service auto-scaling: target tracking on CPUUtilization, MemoryUtilization, or custom CloudWatch metrics
- Step scaling: for more granular control over scaling behavior
- Scheduled scaling: for predictable load patterns
- Container Insights: detailed metrics per task, service, cluster

### Lambda Best Practices

- Minimize deployment package size (exclude dev dependencies, use layers for shared code)
- Reuse connections: initialize SDK clients and DB connections outside handler
- Environment variables for configuration (encrypted with KMS for secrets)
- Dead letter queues (DLQ) or destinations for async invocation failures
- Use /tmp for ephemeral storage (512MB default, up to 10GB configurable)
- ARM64 (Graviton2): up to 34% better price-performance

### EKS Operational Patterns

- Managed node groups: AWS handles AMI updates, node draining
- Fargate profiles: serverless pods, no node management
- Pod topology spread constraints for even distribution
- Resource quotas and limit ranges per namespace
- Horizontal Pod Autoscaler (HPA) + Cluster Autoscaler = full auto-scaling
- IRSA (IAM Roles for Service Accounts) for least-privilege pod permissions
