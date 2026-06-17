---
agent: shared
confidence: 5
created_at: '2026-03-29'
created_by: user
last_confirmed: '2026-03-29'
last_used: '2026-06-17'
source: chat
status: active
type: pattern
---

AWS China regions (cn-north-1, cn-northwest-1) use separate credentials from global regions. CloudWatch Alarms and some APIs may return auth failures when accessed from global account credentials. Always use the AgenticOps-CN account credentials for China region operations, and AgenticOps-Global for global regions. Never mix credentials across partitions.
