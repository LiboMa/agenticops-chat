---
resource_type: ELB
issue_pattern: unhealthy_targets
severity: high
keywords: [elb, alb, nlb, load balancer, unhealthy, target, health check, 502, 503, 504, draining, deregistration, target group]
---

# ELB Unhealthy Targets - Standard Operating Procedure

## Symptoms
- UnHealthyHostCount > 0 in CloudWatch for the target group
- HTTP 502/503/504 errors from the load balancer
- TargetResponseTime increasing or timing out
- Application intermittently unreachable behind the LB
- Targets stuck in "draining" state

## Diagnostic Steps

1. **Check Target Health**: Call describe_load_balancers to get target health per target group.
   - Identify which targets are unhealthy and their health check failure reason.
   - Common reasons: "Elb.InitialHealthChecking", "Target.Timeout", "Target.FailedHealthChecks", "Target.ResponseCodeMismatch".

2. **Check Health Check Configuration**: Verify health check settings match application behavior.
   - Path: Does the health check endpoint exist and return 200?
   - Port: Is the health check port correct (traffic port vs custom)?
   - Interval/Timeout: Is the timeout shorter than the interval?
   - Healthy/Unhealthy threshold: How many consecutive checks to mark healthy/unhealthy?

3. **Check Security Groups**: Call describe_security_groups for both the LB and target instances.
   - LB SG must allow inbound from clients (0.0.0.0/0 for internet-facing).
   - Target SG must allow inbound from the LB's security group on the target port AND health check port.
   - Common mistake: target SG allows traffic from LB SG on port 80 but health check uses port 8080.

4. **Check Target Instance/Container State**: Verify the target is actually running.
   - EC2: instance state should be "running"
   - ECS: task should be in "RUNNING" state
   - Check if the application process is listening on the expected port

5. **Check AZ Distribution**: Verify targets are distributed across all LB-enabled AZs.
   - If an AZ has no healthy targets, the LB will return 503 for requests routed to that AZ.
   - Cross-zone load balancing can mitigate this (enabled by default for ALB).

## Common Root Causes
- **Health check misconfiguration**: Wrong path, port, or expected response code
- **Security group mismatch**: Target SG doesn't allow traffic from LB SG
- **Application crash**: Target application is down or not listening on the port
- **Resource exhaustion**: Target instance out of memory/CPU, cannot respond to health checks
- **Deployment in progress**: New targets still initializing, old targets draining
- **AZ imbalance**: All targets in one AZ, other AZ has no healthy targets

## Resolution

1. **Health check fix**: Update health check path/port/response code to match application.
2. **Security group fix**: Add inbound rule to target SG allowing LB SG on target + health check ports.
3. **Application restart**: Restart the application process or replace the unhealthy instance.
4. **Scale out**: Add more targets to handle load and provide AZ redundancy.
5. **Deregistration delay**: Adjust deregistration delay if targets are stuck in "draining" too long (default 300s).

## Prevention
- Use a dedicated /health endpoint that checks downstream dependencies
- Set CloudWatch alarm on UnHealthyHostCount > 0
- Enable access logging to identify 5XX patterns
- Use ALB request tracing (X-Amzn-Trace-Id) to correlate failures
- Implement gradual deployments (rolling update) to avoid all targets being unhealthy simultaneously
