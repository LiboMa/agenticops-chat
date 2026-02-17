---
title: "Security Group Misconfiguration Blocking RDS PostgreSQL Access"
resource_type: SecurityGroup / RDS
severity: high
region: us-east-1
root_cause: misconfiguration
confidence: 0.90
date: 2026-02-10
tags: [security-group, rds, connectivity, misconfiguration, port-mismatch]
---

# Security Group Misconfiguration Blocking RDS PostgreSQL Access

## Symptoms
- Application servers returning `connection timed out` errors when connecting to RDS PostgreSQL endpoint
- RDS instance (`myapp-prod-db`) shows status **available** in console
- Error started immediately after a scheduled "security group cleanup" change window
- No changes to application code or RDS configuration
- CloudWatch `DatabaseConnections` metric dropped to 0 at the time of the SG change

## Root Cause
During a security group cleanup, the inbound rule on the RDS security group (`sg-0a1b2c3d4e5f`) was modified:
- **Before**: TCP port **5432** (PostgreSQL) from app-server security group `sg-app-servers`
- **After**: TCP port **3306** (MySQL) from `sg-app-servers`

The engineer performing the cleanup mistakenly changed the port from 5432 to 3306, likely confusing the PostgreSQL RDS instance with a MySQL instance in the same VPC. This silently broke all application-to-database connectivity since PostgreSQL listens on port 5432.

VPC Flow Logs confirmed TCP SYN packets from application servers to the RDS ENI on port 5432 were being **rejected** after the change.

## Resolution Steps
1. Identify the RDS instance security group: `aws ec2 describe-security-groups --group-ids sg-0a1b2c3d4e5f --region us-east-1`
2. Verify the incorrect rule: confirm inbound allows TCP 3306 instead of TCP 5432
3. Fix the inbound rule:
   ```bash
   aws ec2 revoke-security-group-ingress --group-id sg-0a1b2c3d4e5f \
     --protocol tcp --port 3306 --source-group sg-app-servers
   aws ec2 authorize-security-group-ingress --group-id sg-0a1b2c3d4e5f \
     --protocol tcp --port 5432 --source-group sg-app-servers
   ```
4. Verify connectivity: `psql -h myapp-prod-db.xxxx.us-east-1.rds.amazonaws.com -p 5432 -U appuser -d myapp`
5. Confirm CloudWatch `DatabaseConnections` metric recovers

## Prevention
- Tag security groups with the database engine type (e.g., `Engine: postgresql`) to avoid port confusion
- Use AWS Config rule to detect security group changes and alert on unexpected port modifications
- Implement change approval workflow for production security groups
- Document all RDS security group rules in IaC (Terraform/CloudFormation) to prevent manual drift
- Enable VPC Flow Logs and set up CloudWatch alarms on rejected traffic spikes

## Related
- Applies to any scenario where security group port rules are changed during maintenance windows
- Similar issue can occur with Aurora, ElastiCache (Redis port 6379 vs Memcached port 11211), or OpenSearch (port 443/9200)
