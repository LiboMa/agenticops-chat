---
agent: detect
confidence: 3
created_at: '2026-03-26'
created_by: user
last_confirmed: '2026-03-26'
last_used: '2026-05-31'
related_issue_id: 281
resource_pattern: vpc-01319a84eaaeb8d0d/*
source: user
status: active
type: feedback
---

3 Private Subnets Have No Outbound Route (No NAT/TGW) in cn-northwest-1

Route table rtb-08782f5e9296dd092 in vpc-01319a84eaaeb8d0d (project-vpc, cn-northwest-1) has ONLY a local route (10.120.0.0/16 → local) with NO default route (0.0.0.0/0) and no TGW route. Three subnets are affected: subnet-033389b51d721cbf6 (10.120.3.0/25, cn-northwest-1c), subnet-001789bef52625add (10.120.3.128/25, cn-northwest-1b), subnet-0393326dcc5ee8d49 (10.120.0.128/25, cn-northwest-1a). Resources in these subnets cannot reach the internet, AWS services, or cross-region peers (cn-north-1 10.110.0.0/16). The NAT nat-01e781a15e10f4419 and TGW tgw-087b9a83c90c01256 are available but not routed. Recommendation: add 0.0.0.0/0 → nat-01e781a15e10f4419 and 10.110.0.0/16 → tgw-087b9a83c90c01256 to rtb-08782f5e9296dd092.

Marked as false positive on issue I#281.
