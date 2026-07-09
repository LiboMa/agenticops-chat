---
agent: shared
confidence: 5
created_at: '2026-03-27'
created_by: user
last_confirmed: '2026-03-27'
last_used: '2026-07-09'
source: chat
status: active
type: pattern
---

【Context 过载防护规则】
1. sre_query 必须始终携带精确的 --query 和 --output text 参数，禁止宽泛查询，避免返回全量 JSON 导致 context 爆炸。
2. activate_skill 会加载完整 SKILL.md（约8000+ token），非必要不调用，且不能与大型查询工具在同一轮并发调用。
3. 任何工具调用失败（尤其是 tool result was too large）后，最多重试1次（换精确参数），仍失败则立即停止并告知用户开新会话，禁止反复重试。
4. 单次会话内大型工具调用（sre_query/scan_agent/detect_agent/activate_skill）累计不超过5次，超限前主动提醒用户开新会话。
5. 工具报错 'The tool result was too large' 时，原始数据已进入 context window 无法释放，继续重试只会加速过载，必须停止。
