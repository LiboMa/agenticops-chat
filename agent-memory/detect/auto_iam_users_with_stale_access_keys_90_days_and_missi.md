---
agent: detect
confidence: 2
created_at: '2026-04-02'
created_by: user
last_confirmed: '2026-04-02'
last_used: '2026-07-07'
related_issue_id: 323
resource_pattern: iam-users-stale-keys/*
source: auto
status: active
type: feedback
---

IAM Users With Stale Access Keys (>90 Days) and Missing MFA

Multiple IAM hygiene issues found in credential report (generated 2026-04-02):

**Stale Access Keys (>90 days since rotation):**
- eksadmin: key rotated 2024-09-21 (~6 months ago), last used 2025-03-30
- sa-malibo: key rotated 2024-04-19 (~1 year ago), last used 2026-04-02 (active!)
- cline-coder-agent: key rotated 2024-12-16 (~3.5 months ago), last used 2025-05-29

**Users Without MFA Enabled:**
- BedrockAPIKey-2idq (created 2026-03-03, no MFA)
- BedrockAPIKey-brtk (created 2026-01-06, no MFA)
- BedrockAPIKey-ony6 (created 2026-03-03, no MFA)
- cline-coder-agent (no MFA)
- eksopsuser (no MFA)

Recommendation: Rotate stale keys immediately, enforce MFA policy for all IAM users, or convert API-only users to use IAM roles where possible.

Auto-learned: issue I#323 was dismissed by user.
