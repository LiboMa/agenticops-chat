---
agent: detect
confidence: 2
created_at: '2026-05-29'
created_by: user
last_confirmed: '2026-05-29'
last_used: '2026-08-13'
related_issue_id: 363
resource_pattern: EC2-fleet/*
source: auto
status: active
type: feedback
---

EC2 Tag Compliance: Missing Project_env tag on all 26 instances

All 26 EC2 instances across 5 regions (ap-southeast-1, cn-north-1, cn-northwest-1, us-east-1, us-west-2) are missing the required tag Project_env=demo-purpose. This tag needs to be added to all instances for project identification and cost allocation purposes. Affected instances: ap-southeast-1 (14), cn-north-1 (1), cn-northwest-1 (2), us-east-1 (1), us-west-2 (8).

Auto-learned: issue I#363 was dismissed by user.
