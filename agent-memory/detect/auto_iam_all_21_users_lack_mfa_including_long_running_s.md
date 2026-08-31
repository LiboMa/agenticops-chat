---
agent: detect
confidence: 2
created_at: '2026-07-22'
created_by: user
last_confirmed: '2026-07-22'
last_used: '2026-08-26'
related_issue_id: 3
resource_pattern: 533267047935/*
source: auto
status: active
type: feedback
---

IAM: All 21 Users Lack MFA — Including Long-Running Service Accounts

All 21 IAM users lack MFA. This includes long-running service accounts (sa-malibo created 2024-04-19, cline-coder-agent 2024-12-16, eksadmin/eksopsuser 2024-09-21) and multiple Bedrock/Mantle API key users. No MFA on service accounts that also have access keys is a high-risk IAM posture finding — a leaked key provides full unchallenged access. Recommend: enforce MFA on all human/interactive users (eksadmin, eksopsuser, sa-malibo, cline-coder-agent) via IAM policy. For API-only users, ensure no console access and apply strict access key rotation.

Auto-learned: issue I#3 was dismissed by user.
