# ECS Task Placement Deep Dive

## Task Placement Strategies

ECS uses placement strategies to determine which container instances receive tasks.
Strategies are evaluated in order -- first strategy is primary, subsequent are tiebreakers.

### Spread Strategy
Distributes tasks evenly across the specified field:

```bash
# Spread across Availability Zones (most common for HA)
aws ecs create-service --cluster my-cluster --service-name my-svc \
  --task-definition my-task:5 --desired-count 6 \
  --placement-strategy type=spread,field=attribute:ecs.availability-zone

# Spread across instances (maximizes fault tolerance)
aws ecs create-service --cluster my-cluster --service-name my-svc \
  --task-definition my-task:5 --desired-count 6 \
  --placement-strategy type=spread,field=instanceId

# Spread across AZs then across instances within each AZ
aws ecs create-service --cluster my-cluster --service-name my-svc \
  --task-definition my-task:5 --desired-count 6 \
  --placement-strategy type=spread,field=attribute:ecs.availability-zone \
  --placement-strategy type=spread,field=instanceId
```

### Binpack Strategy
Places tasks on instances with the least available amount of the specified resource:

```bash
# Pack by memory first (maximizes instance utilization)
aws ecs create-service --cluster my-cluster --service-name my-svc \
  --task-definition my-task:5 --desired-count 10 \
  --placement-strategy type=binpack,field=memory

# Pack by CPU
aws ecs create-service --cluster my-cluster --service-name my-svc \
  --task-definition my-task:5 --desired-count 10 \
  --placement-strategy type=binpack,field=cpu
```

Binpack is cost-optimized -- fewer instances running, better utilization.

### Random Strategy
Randomly places tasks (useful for testing, simple workloads):

```bash
aws ecs create-service --cluster my-cluster --service-name my-svc \
  --task-definition my-task:5 --desired-count 6 \
  --placement-strategy type=random
```

## Placement Constraints

### distinctInstance
Ensures each task is placed on a different container instance:

```bash
aws ecs create-service --cluster my-cluster --service-name my-svc \
  --task-definition my-task:5 --desired-count 3 \
  --placement-constraints type=distinctInstance
```

### memberOf (Cluster Query Language)
Uses expressions to select instances:

```bash
# Only place on instances in a specific AZ
aws ecs create-service --cluster my-cluster --service-name my-svc \
  --task-definition my-task:5 --desired-count 3 \
  --placement-constraints \
    "type=memberOf,expression=attribute:ecs.availability-zone == us-east-1a"

# Only place on GPU instances
aws ecs create-service --cluster my-cluster --service-name my-svc \
  --task-definition my-task:5 --desired-count 2 \
  --placement-constraints \
    "type=memberOf,expression=attribute:ecs.instance-type =~ g5.*"

# Only place on instances with specific custom attribute
aws ecs create-service --cluster my-cluster --service-name my-svc \
  --task-definition my-task:5 --desired-count 4 \
  --placement-constraints \
    "type=memberOf,expression=attribute:stack == production"

# Set custom attributes on instances
aws ecs put-attributes --cluster my-cluster --attributes \
  name=stack,value=production,targetId=arn:aws:ecs:us-east-1:123456789012:container-instance/abc123
```

## Capacity Providers

Capacity providers manage the infrastructure for ECS tasks:

### EC2 Capacity Provider

```bash
# Create capacity provider backed by ASG
aws ecs create-capacity-provider --name cp-ec2-main \
  --auto-scaling-group-provider '{
    "autoScalingGroupArn": "arn:aws:autoscaling:us-east-1:123456789012:autoScalingGroup:xxx:autoScalingGroupName/ecs-asg",
    "managedScaling": {
      "status": "ENABLED",
      "targetCapacity": 80,
      "minimumScalingStepSize": 1,
      "maximumScalingStepSize": 10,
      "instanceWarmupPeriod": 300
    },
    "managedTerminationProtection": "ENABLED"
  }'

# Associate with cluster
aws ecs put-cluster-capacity-providers --cluster my-cluster \
  --capacity-providers cp-ec2-main FARGATE FARGATE_SPOT \
  --default-capacity-provider-strategy \
    capacityProvider=cp-ec2-main,weight=1,base=2
```

`targetCapacity` of 80 means ECS will scale the ASG to keep 80% utilization --
leaving 20% headroom for burst.

### Fargate Capacity Provider

```bash
# Use Fargate with Fargate Spot fallback
aws ecs create-service --cluster my-cluster --service-name my-svc \
  --task-definition my-task:5 --desired-count 10 \
  --capacity-provider-strategy \
    capacityProvider=FARGATE,weight=1,base=3 \
    capacityProvider=FARGATE_SPOT,weight=3

# base=3: first 3 tasks always on Fargate (guaranteed capacity)
# weight ratio 1:3: remaining tasks split 25% Fargate, 75% Fargate Spot
```

Fargate Spot: up to 70% discount, but tasks can be interrupted with 30-second warning.
Use for fault-tolerant workloads (queue processors, batch jobs).

## Service Discovery

ECS integrates with AWS Cloud Map for DNS-based service discovery:

```bash
# Create service with service discovery
aws ecs create-service --cluster my-cluster --service-name api-service \
  --task-definition api-task:3 --desired-count 3 \
  --service-registries registryArn=arn:aws:servicediscovery:us-east-1:123456789012:service/srv-abc123 \
  --network-configuration '{
    "awsvpcConfiguration": {
      "subnets": ["subnet-abc123", "subnet-def456"],
      "securityGroups": ["sg-abc123"],
      "assignPublicIp": "DISABLED"
    }
  }'

# Tasks register automatically, accessible via:
# api-service.my-namespace.local (A records for awsvpc, SRV records for bridge/host)
```

## Task Networking Modes

### awsvpc (recommended)
Each task gets its own ENI with a private IP in the VPC:

```json
{
  "networkMode": "awsvpc",
  "containerDefinitions": [{
    "name": "app",
    "image": "my-app:latest",
    "portMappings": [{"containerPort": 8080, "protocol": "tcp"}]
  }]
}
```
- Required for Fargate
- Each task has its own security group
- Uses VPC subnet IPs (watch for IP exhaustion)
- Best isolation and security

### bridge (default for EC2)
Docker's built-in virtual network with port mapping:

```json
{
  "networkMode": "bridge",
  "containerDefinitions": [{
    "name": "app",
    "image": "my-app:latest",
    "portMappings": [{
      "containerPort": 8080,
      "hostPort": 0,
      "protocol": "tcp"
    }]
  }]
}
```
- `hostPort: 0` for dynamic port mapping (required for multiple tasks per instance)
- Uses instance's security group
- Works with ALB dynamic port detection

### host
Container shares the host's network namespace:

```json
{
  "networkMode": "host"
}
```
- Best performance (no NAT overhead)
- Only one task per port per instance
- No port mapping, container binds directly to host port
- Use case: high-throughput networking applications

## ECS Exec for Debugging

Interactive shell access to running containers:

```bash
# Enable ECS Exec on service (requires SSM permissions)
aws ecs update-service --cluster my-cluster --service-name my-svc \
  --enable-execute-command

# Or enable in task definition (for run-task)
aws ecs run-task --cluster my-cluster --task-definition my-task:5 \
  --enable-execute-command --count 1

# Execute command in container
aws ecs execute-command --cluster my-cluster --task TASK_ID \
  --container app --interactive --command "/bin/sh"

# Required IAM permissions for the task role:
# ssmmessages:CreateControlChannel
# ssmmessages:CreateDataChannel
# ssmmessages:OpenControlChannel
# ssmmessages:OpenDataChannel

# Required: SSM agent sidecar (automatically injected by ECS)
# Verify exec is enabled:
aws ecs describe-tasks --cluster my-cluster --tasks TASK_ID \
  --query 'tasks[].containers[].managedAgents'
```

Troubleshooting ECS Exec:
1. Task role must have SSM permissions
2. Task must be in RUNNING state
3. Platform version must be 1.4.0+ (Fargate) or ECS agent 1.50.2+ (EC2)
4. VPC needs SSM endpoints or NAT gateway for internet access

## Deployment Types

### Rolling Update (default)
```bash
aws ecs create-service --deployment-configuration '{
  "deploymentCircuitBreaker": {"enable": true, "rollback": true},
  "minimumHealthyPercent": 100,
  "maximumPercent": 200
}'
```
- `minimumHealthyPercent=100`, `maximumPercent=200`: deploys new tasks before removing old (zero downtime, needs 2x capacity)
- `minimumHealthyPercent=50`, `maximumPercent=100`: removes half old tasks first (saves capacity, brief reduced capacity)
- Circuit breaker: auto-rollback if new tasks keep failing

### Blue/Green (with CodeDeploy)
```bash
aws ecs create-service --deployment-controller type=CODE_DEPLOY \
  --load-balancers '{
    "targetGroupArn": "arn:...",
    "containerName": "app",
    "containerPort": 8080
  }'
```
- Requires ALB with two target groups
- CodeDeploy shifts traffic (all-at-once, linear, canary)
- Automatic rollback on CloudWatch alarm or deployment failure
- Test traffic on replacement target group before switching

### External
```bash
aws ecs create-service --deployment-controller type=EXTERNAL
```
- Third-party controller manages deployments
- Use with custom deployment tools or service mesh

## Troubleshooting Placement Failures

When tasks cannot be placed, check systematically:

```bash
# 1. Check available resources across instances
aws ecs list-container-instances --cluster my-cluster --status ACTIVE | \
  xargs -I {} aws ecs describe-container-instances --cluster my-cluster \
    --container-instances {} \
    --query 'containerInstances[].{id:ec2InstanceId,cpu:remainingResources[?name==`CPU`].integerValue,mem:remainingResources[?name==`MEMORY`].integerValue,ports:remainingResources[?name==`PORTS`]}'

# 2. Check task definition requirements
aws ecs describe-task-definition --task-definition my-task:5 \
  --query 'taskDefinition.{cpu:cpu,memory:memory,containers:containerDefinitions[].{name:name,cpu:cpu,memory:memory}}'

# 3. Check service events for specific errors
aws ecs describe-services --cluster my-cluster --services my-svc \
  --query 'services[].events[:10]'

# 4. Verify capacity provider status
aws ecs describe-capacity-providers --capacity-providers cp-ec2-main \
  --query 'capacityProviders[].{name:name,status:status,scaling:autoScalingGroupProvider.managedScaling}'
```

Common placement failure causes and fixes:
- **No instances registered**: ASG desired=0, or instances failing health checks
- **Insufficient CPU/memory**: task requires more than any single instance can offer
- **Port conflict**: host networking with same port, check hostPort mappings
- **Constraint not satisfiable**: placement constraint expression matches no instances
- **Attribute missing**: custom attribute not set on any instance
- **AZ imbalance**: spread constraint with uneven AZ capacity
