---
agent: scan
confidence: 5
created_at: '2026-05-24'
created_by: user
last_confirmed: '2026-05-24'
last_used: '2026-07-04'
source: chat
status: archived
type: pattern
---

【日期精确性规则】任何涉及日期、时间、扫描时间戳、资源创建时间比较的操作，必须先通过工具（sre_query执行`date`命令 或 datetime工具）获取真实系统时间，严禁猜测、推断或基于上下文估算日期。扫描时间戳错误会导致资源状态判断失准。
