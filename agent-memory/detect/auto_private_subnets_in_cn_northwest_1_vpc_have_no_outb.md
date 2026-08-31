---
agent: detect
confidence: 2
created_at: '2026-03-26'
created_by: user
last_confirmed: '2026-03-26'
last_used: '2026-07-07'
related_issue_id: 266
resource_pattern: vpc-01319a84eaaeb8d0d/*
source: auto
status: stale
type: feedback
---

Private Subnets in cn-northwest-1 VPC Have No Outbound Route (No NAT / TGW for 3 Subnets)

Three private subnets in vpc-01319a84eaaeb8d0d (project-vpc, cn-northwest-1) are associated with route table rtb-08782f5e9296dd092, which has ONLY a local route (10.120.0.0/16 → local) and NO default route (0.0.0.0/0). This means any resource in these subnets cannot reach the internet, AWS services, or cross-region TGW peers.

Affected subnets:
- subnet-033389b51d721cbf6 (10.120.3.0/25, cn-northwest-1c, 122 free IPs)
- subnet-001789bef52625add (10.120.3.128/25, cn-northwest-1b, 123 free IPs)
- subnet-0393326dcc5ee8d49 (10.120.0.128/25, cn-northwest-1a, 122 free IPs)

By contrast, rtb-0134cb4f715c26343 correctly routes private subnets (0462ba03fe5e6122f and 0b1578fb4a47b3cfb) via NAT nat-01e781a15e10f4419.

Note: The TGW route 10.110.0.0/16 → tgw-087b9a83c90c01256 is also missing from rtb-08782f5e9296dd092, so cross-region routing to cn-north-1 (10.110.0.0/16) is also unavailable for these subnets.

Recommendation: Add 0.0.0.0/0 → nat-01e781a15e10f4419 and 10.110.0.0/16 → tgw-087b9a83c90c01256 to rtb-08782f5e9296dd092 to restore outbound connectivity.

Auto-learned: issue I#266 was dismissed by user.
