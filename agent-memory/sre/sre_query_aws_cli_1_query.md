---
agent: sre
confidence: 5
created_at: '2026-03-27'
created_by: user
last_confirmed: '2026-03-27'
last_used: '2026-08-12'
source: chat
status: active
type: pattern
---

【sre_query 查询规范】
所有 AWS CLI 查询必须包含：
1. --query 参数精确指定所需字段，例如 --query "Reservations[].Instances[].{ID:InstanceId,State:State.Name,PublicIP:PublicIpAddress}"
2. --output text 或 --output table（禁止 --output json 用于宽泛查询）
3. 查询特定资源时必须提供 --instance-ids / --load-balancer-arns 等 ID 过滤，禁止全量 describe。
违反以上规范会导致返回结果过大，引发 context 过载。
