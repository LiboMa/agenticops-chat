---
agent: detect
confidence: 5
created_at: '2026-07-31'
created_by: user
last_confirmed: '2026-07-31'
last_used: '2026-08-26'
related_issue_id: 1
resource_pattern: IAM/sa-malibo
source: chat
status: active
type: baseline
---

【告警基线 — sa-malibo 合法流量】账号 533267047935 的 CIS-UnauthorizedAPICalls 告警长期由服务账号 sa-malibo 的合法跨境调用（约 180 次/小时，香港/新加坡 IP）触发，用户已确认为正常业务。检测时应将此类流量视为已知基线，不再生成 high 严重度安全事件；如需上报，降级为 low/medium 的"配置卫生"类问题（陈旧密钥、权限过大、缺少 IP 条件键）。同理，涉及 sa-malibo 的 GuardDuty S3 AnomalousBehavior.Write 与 cn-northwest-1 KMS 密钥（2026-05-07 创建）均为误报，勿判定为攻击。注意：真实且独立有效的暴露风险仍须照常上报 —— 包括 sg_all 全协议 0.0.0.0/0（Aurora PostgreSQL 暴露）、sg_web 与 nexus-ai-pharmaron 的 SSH 22 全网开放、Root 账号未启用 MFA、ECR 镜像 CVE。
