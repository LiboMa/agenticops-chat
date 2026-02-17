---
title: "ALB Intermittent 502 Errors Due to Health Check Path Mismatch"
resource_type: ELB / EC2
severity: high
region: eu-west-1
root_cause: health_check_mismatch
confidence: 0.88
date: 2026-01-15
tags: [elb, alb, 502, health-check, target-group, intermittent]
---

# ALB Intermittent 502 Errors Due to Health Check Path Mismatch

## Symptoms
- Application Load Balancer (`app/myapp-prod-alb/abc123`) returning intermittent HTTP 502 errors
- Errors increase during traffic spikes but never fully resolve even during low traffic
- Backend EC2 instances are running and responsive when accessed directly
- ALB target group shows targets flapping between `healthy` and `unhealthy` states
- CloudWatch `HTTPCode_ELB_502_Count` averaging 50-200 per minute during incidents
- Users report "502 Bad Gateway" errors on approximately 5-15% of requests

## Root Cause
The ALB target group health check was configured with path `/health`, which is a lightweight endpoint that always returns HTTP 200. However, the **application's actual readiness** depends on `/api/health`, which checks database connectivity and downstream service health.

During traffic spikes:
1. The application's `/api/health` endpoint starts returning HTTP 503 due to increased backend latency
2. The ALB health check on `/health` continues to report targets as healthy
3. ALB routes traffic to targets that are technically running but unable to serve requests properly
4. The application returns 503 to the ALB, which the ALB translates to 502 (since the target responded with an error)

Additionally, the health check was configured with:
- **Interval**: 30 seconds (too long to detect degradation quickly)
- **Healthy threshold**: 5 (takes 2.5 minutes to mark a recovered target as healthy)
- **No deregistration delay**: Targets removed instantly, causing in-flight request failures

## Resolution Steps
1. Update ALB target group health check path to `/api/health`:
   ```bash
   aws elbv2 modify-target-group --target-group-arn arn:aws:elasticloadbalancing:eu-west-1:123456:targetgroup/myapp/xxxx \
     --health-check-path /api/health \
     --health-check-interval-seconds 10 \
     --healthy-threshold-count 2 \
     --unhealthy-threshold-count 3
   ```
2. Add deregistration delay to allow in-flight requests to complete:
   ```bash
   aws elbv2 modify-target-group-attributes --target-group-arn arn:aws:... \
     --attributes Key=deregistration_delay.timeout_seconds,Value=30
   ```
3. Verify target health stabilizes: `aws elbv2 describe-target-health --target-group-arn arn:aws:...`
4. Monitor `HTTPCode_ELB_502_Count` and `UnHealthyHostCount` metrics for 30 minutes
5. Confirm 502 rate drops to near zero

## Prevention
- Always align ALB health check paths with the application's true readiness endpoint
- Use health check paths that verify critical dependencies (database, cache, downstream services)
- Configure appropriate health check intervals (10-15s for production)
- Set deregistration delay (30-60s) to drain in-flight connections gracefully
- Implement health check endpoint that returns degraded status (HTTP 429) instead of hard failure during load spikes
- Add CloudWatch alarm on `UnHealthyHostCount` > 0 and `HTTPCode_ELB_502_Count` > threshold

## Related
- Applies to any ALB/NLB target group with mismatched health check paths
- Similar issue with ECS services where container health check differs from ALB health check
- Network Load Balancers have TCP health checks by default, which can mask application-level failures
