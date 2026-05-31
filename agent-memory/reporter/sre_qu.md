---
agent: reporter
confidence: 5
created_at: '2026-05-24'
created_by: user
last_confirmed: '2026-05-24'
last_used: '2026-05-24'
source: chat
status: active
type: pattern
---

【日期精确性规则】任何涉及日期、时间、报告周期、数据统计时间范围的操作，必须先通过工具（sre_query执行`date`命令 或 datetime工具）获取真实系统时间，严禁猜测、推断或基于上下文估算日期。报告日期错误会导致数据对应时段混乱。
