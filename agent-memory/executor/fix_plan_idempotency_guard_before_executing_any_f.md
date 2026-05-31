---
agent: executor
confidence: 5
created_at: '2026-03-29'
created_by: user
last_confirmed: '2026-03-29'
last_used: '2026-03-29'
related_issue_id: 28
source: chat
status: active
type: pattern
---

Fix plan idempotency guard: Before executing ANY fix step, verify current resource state to prevent duplicate execution. Examples: before rotating IAM key, check if key already rotated (creation date changed); before attaching IAM policy, check if policy already attached; before modifying security group rules, check if rule already removed. If state already matches desired outcome, skip the step and log as SKIPPED (not FAILED). This prevents the Plan #21 repeated execution issue where the same fix was applied 4 times.
