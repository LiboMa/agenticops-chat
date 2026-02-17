---
title: "NAT Gateway Port Exhaustion Causing Lambda Timeouts"
resource_type: NATGateway / Lambda
severity: critical
region: us-west-2
root_cause: port_exhaustion
confidence: 0.85
date: 2026-01-22
tags: [nat-gateway, lambda, port-exhaustion, timeout, vpc, scaling]
---

# NAT Gateway Port Exhaustion Causing Lambda Timeouts

## Symptoms
- Lambda functions in private subnets failing with `Task timed out after 30.00 seconds`
- Errors are intermittent, worsening during peak traffic hours (10 AM - 2 PM UTC)
- Functions that call external APIs (payment gateway, third-party webhooks) are most affected
- Functions calling internal AWS services via VPC endpoints are unaffected
- CloudWatch metric `ErrorPortAllocation` on the NAT Gateway spiking to > 0 during failures

## Root Cause
The architecture used a **single NAT Gateway** in one AZ (`us-west-2a`) for all private subnets across 3 AZs. During peak traffic:

1. ~2,000 concurrent Lambda invocations each open 1-3 outbound connections through the NAT Gateway
2. Each connection consumes a unique source port (ephemeral port range: 1024-65535)
3. The NAT Gateway has a hard limit of **55,000 simultaneous connections** per unique destination
4. With multiple external API endpoints, the aggregate connections exceeded the port allocation limit
5. New connections were dropped, causing Lambda functions to timeout waiting for TCP handshake

CloudWatch metrics confirmed:
- `ActiveConnectionCount` sustained above 50,000 during incidents
- `ErrorPortAllocation` > 0 correlated exactly with Lambda timeout spikes
- `PacketsDropCount` increased proportionally

## Resolution Steps
1. **Immediate mitigation**: Add a second NAT Gateway in `us-west-2b`:
   ```bash
   aws ec2 create-nat-gateway --subnet-id subnet-0b2b2b2b --allocation-id eipalloc-0xxxx
   ```
2. Update route tables for subnets in `us-west-2b` and `us-west-2c` to use the new NAT Gateway
3. **Split subnets across AZs**: Ensure each AZ's private subnets route through their own NAT Gateway (one NAT per AZ pattern)
4. **Implement connection pooling** in Lambda functions using HTTP keep-alive:
   ```python
   import urllib3
   http = urllib3.PoolManager(maxsize=10)  # Reuse connections
   ```
5. Add CloudWatch alarm on `ErrorPortAllocation` > 0 for early warning
6. Monitor `ActiveConnectionCount` and set threshold alarm at 40,000 (72% capacity)

## Prevention
- Deploy NAT Gateways in a 1-per-AZ pattern from the start for production workloads
- Use VPC endpoints for AWS services (S3, DynamoDB, SQS, etc.) to avoid NAT Gateway traffic entirely
- Implement connection pooling in all Lambda functions making outbound HTTP calls
- Set up CloudWatch alarms on NAT Gateway `ErrorPortAllocation` and `ActiveConnectionCount` metrics
- Consider AWS PrivateLink for frequently called third-party services

## Related
- Applies to any high-concurrency Lambda workload in private subnets using NAT Gateways
- Similar port exhaustion can occur with NAT instances (worse limits than managed NAT Gateway)
- ECS/EKS tasks in private subnets can exhibit the same pattern under high connection counts
