---
title: "Lambda VPC Cold Start Causing API Gateway 504 Timeouts"
resource_type: Lambda / VPC
severity: medium
region: us-east-1
root_cause: vpc_cold_start
confidence: 0.80
date: 2026-02-08
tags: [lambda, vpc, cold-start, timeout, eni, api-gateway]
---

# Lambda VPC Cold Start Causing API Gateway 504 Timeouts

## Symptoms
- API Gateway returning HTTP 504 (Gateway Timeout) errors intermittently
- Errors predominantly affect requests after periods of low traffic (early morning, post-deployment)
- Lambda function `api-handler` CloudWatch Logs show `Init Duration` of 15,000-30,000 ms on cold starts
- API Gateway has a hard 29-second integration timeout; cold starts exceeding this cause 504
- Warm invocations complete in 200-500 ms — performance is excellent once the function is warm
- CloudWatch `Duration` metric shows bimodal distribution: ~300ms (warm) and ~18,000ms (cold)

## Root Cause
The `api-handler` Lambda function is configured to run inside a VPC to access RDS and ElastiCache in private subnets. VPC-attached Lambda functions require an Elastic Network Interface (ENI) to be created in the subnet:

1. **ENI creation** (legacy networking): When a new execution environment is provisioned, Lambda must create/attach an ENI in the VPC subnet, taking 10-20 seconds
2. **Runtime initialization**: Python runtime + application dependencies (~3-5 seconds)
3. **Total cold start**: 15-25 seconds, frequently exceeding API Gateway's 29-second timeout

The Lambda function was using the **legacy VPC networking model** (pre-2019 improvements). The account had not been migrated to Hyperplane ENI (shared ENI) architecture, which reduces VPC cold starts to 1-2 seconds.

Contributing factors:
- Lambda function allocated only 256 MB memory (CPU is proportional to memory; low memory = slow init)
- No provisioned concurrency configured
- Java/Python dependencies with heavy import-time initialization

## Resolution Steps
1. **Verify networking model**: Check if the function is using Hyperplane ENI:
   ```bash
   aws lambda get-function-configuration --function-name api-handler \
     --query 'VpcConfig'
   ```
2. **Enable Hyperplane ENI** (if not already active — this is automatic for most accounts post-2019, but some legacy accounts need re-deployment):
   - Delete and recreate the Lambda function's VPC configuration
   - Or redeploy via CloudFormation/Terraform to trigger ENI migration
3. **Increase memory allocation** to 1024 MB or higher for faster CPU-bound initialization:
   ```bash
   aws lambda update-function-configuration --function-name api-handler \
     --memory-size 1024
   ```
4. **Enable provisioned concurrency** for the production alias to eliminate cold starts:
   ```bash
   aws lambda put-provisioned-concurrency-config --function-name api-handler \
     --qualifier prod --provisioned-concurrent-executions 10
   ```
5. **If Java**: Enable SnapStart for near-instant cold starts:
   ```bash
   aws lambda update-function-configuration --function-name api-handler \
     --snap-start ApplyOn=PublishedVersions
   ```
6. Optimize application initialization: move heavy imports outside the handler, lazy-load non-critical modules
7. Monitor `InitDuration` metric and verify cold starts drop below 3 seconds

## Prevention
- Always verify VPC Lambda functions use Hyperplane ENI networking (default for accounts created after 2019)
- Configure provisioned concurrency for latency-sensitive Lambda functions behind API Gateway
- Allocate sufficient memory (512 MB+) for VPC Lambda functions to speed up initialization
- Use Lambda Powertools or middleware to log and track cold start occurrences
- Set API Gateway timeout to match the expected worst-case Lambda duration
- Consider placing non-VPC-dependent logic in a separate non-VPC Lambda function to avoid unnecessary cold start penalties
- Use SnapStart (Java) or Lambda Extensions (Python) to optimize initialization time

## Related
- Applies to any VPC-attached Lambda function with latency-sensitive callers (API Gateway, Step Functions)
- ECS Fargate tasks have similar (longer) cold start issues but are not constrained by API Gateway timeouts
- Lambda@Edge and CloudFront Functions do not support VPC attachment and are not affected
