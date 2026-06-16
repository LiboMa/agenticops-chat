---
agent: executor
confidence: 5
created_at: '2026-05-24'
created_by: user
last_confirmed: '2026-05-24'
last_used: '2026-06-09'
source: chat
status: active
type: pattern
---

【日期精确性规则】任何涉及日期、时间、执行窗口、超时计算的操作，必须先通过工具（sre_query执行`date`命令 或 datetime工具）获取真实系统时间，严禁猜测、推断或基于上下文估算日期。执行时间窗口判断错误可能导致在错误的时间执行变更。
