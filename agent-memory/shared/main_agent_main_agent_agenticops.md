---
agent: shared
confidence: 5
created_at: '2026-05-24'
created_by: user
last_confirmed: '2026-05-24'
last_used: '2026-06-02'
source: chat
status: active
type: pattern
---

【日期精确性规则 - Main Agent】Main Agent（即 AgenticOps 主路由 Agent）在任何涉及日期、时间、倒计时、剩余天数的回答中，必须先通过 sre_query 执行 `date` 命令获取真实系统时间，严禁基于训练数据、上下文对话或推断来估算当前日期。例如：计算证书剩余天数、SLA倒计时、变更窗口判断等，都必须先查询真实时间再输出结果。
