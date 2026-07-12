---
agent: executor
confidence: 5
created_at: '2026-03-29'
created_by: user
last_confirmed: '2026-03-29'
last_used: '2026-07-12'
related_issue_id: 29
source: chat
status: active
type: pattern
---

When AWS CLI tool returns "tool result was too large" error: 1) Retry the command with --query JMESPath filter to reduce output size. 2) Use --output text instead of --output json for simple values. 3) Add --max-items 50 and --page-size 50 for list-* commands. 4) Use targeted get-*/describe-* commands instead of broad list-* commands. 5) If all retries fail, abort current step, record which steps completed, and report partial execution status for manual follow-up.
