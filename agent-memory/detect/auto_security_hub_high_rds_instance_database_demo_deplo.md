---
agent: detect
confidence: 2
created_at: '2026-07-08'
created_by: user
last_confirmed: '2026-07-08'
last_used: '2026-07-13'
related_issue_id: 417
resource_pattern: arn:aws:rds:us-east-1:533267047935:db:database-demo/*
source: auto
status: active
type: feedback
---

Security Hub HIGH: RDS Instance 'database-demo' Deployed in Public Subnet with IGW Route

Security Hub finding (EC2.2 / RDS.46 HIGH): RDS DB instance 'database-demo' (us-east-1) is deployed in a public subnet with a route to an internet gateway, violating AWS security best practices and regulatory standards. This exposes the database endpoint to potential direct internet access, significantly increasing the attack surface. Recommend: migrate the RDS instance to private subnets with no IGW route, use a bastion host or AWS Systems Manager for access, and apply restrictive security group rules.

Auto-learned: issue I#417 was dismissed by user.
