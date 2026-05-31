---
agent: rca
confidence: 5
created_at: '2026-05-24'
created_by: user
last_confirmed: '2026-05-24'
last_used: '2026-05-24'
source: chat
status: active
type: pattern
---

【日期精确性规则】任何涉及日期、时间、事件时序、持续时长的分析，必须先通过工具（sre_query执行`date`命令 或 datetime工具）获取真实系统时间，严禁猜测、推断或基于上下文估算日期。RCA时间线分析若日期错误将导致根因判断失误。
