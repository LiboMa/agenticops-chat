---
agent: detect
confidence: 2
created_at: '2026-04-29'
created_by: user
last_confirmed: '2026-04-29'
last_used: '2026-04-29'
related_issue_id: 122
resource_pattern: sa-malibo/*
source: auto
status: active
type: feedback
---

GuardDuty: IAM User sa-malibo — Anomalous Impact Behavior (Severity 8.0)

GuardDuty detected that IAM user sa-malibo is anomalously invoking APIs commonly used in Impact tactics (e.g., data destruction, resource manipulation). Two separate high-severity (8.0) findings were raised (IDs: b8ced78f2ea6e66efac50df1a401bf7c, 1ece329a7b1f47e55a324244096b7a41). A third finding (84ce16abb89d22ad358f99efa93479fd, severity 5.0) flags PrivilegeEscalation:IAMUser/AnomalousBehavior for the same user. The user's password was last used 2025-10-27. Active access key (key1) was last used 2026-04-28 against Bedrock in us-east-1. This constitutes a potential active compromise — severity escalated to CRITICAL per escalation rules (active exploitation suspected on reachable service).

Auto-learned: issue I#122 was dismissed by user.
