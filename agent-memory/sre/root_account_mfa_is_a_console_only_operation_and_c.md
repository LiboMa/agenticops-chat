---
agent: sre
confidence: 5
created_at: '2026-03-29'
last_confirmed: '2026-03-29'
related_issue_id: 29
source: chat
status: active
type: pattern
---

Root Account MFA is a CONSOLE-ONLY operation and cannot be automated via AWS CLI or SDK. When generating fix plans involving Root MFA enablement, always mark Step 1 as MANUAL with explicit instructions: 'Login to AWS Console as Root > My Security Credentials > Activate MFA'. Never include Root MFA as an automated execution step. Flag this as a human escalation requirement in the plan summary.
