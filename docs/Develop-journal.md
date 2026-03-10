# AgenticOps 开发日志

> 每日开发更新摘要，按时间倒序排列。

---

## 2026-03-10 — MVP 1.0.0 收口：FixPlan 去重 + 代码瘦身 + 重构规划

### FixPlan 一对一去重（Replace Mode）
- `save_fix_plan()` 新增 dedup 逻辑：Draft → 原地更新；Locked → 拒绝；Terminal → 允许新建
- 三组状态常量：`FIXPLAN_TERMINAL_STATUSES`、`FIXPLAN_REPLACEABLE_STATUSES`、`FIXPLAN_LOCKED_STATUSES`
- SRE Agent 提示词更新：Step 7 要求每个 Issue 只生成一个合并的修复计划
- Pipeline guard：`trigger_auto_sre()` 在有非终态 FixPlan 时跳过
- API guard：`POST /api/fix-plans` → 409；`generate-fix-plan` → 409（locked 时）
- 17 个新测试全部通过

### 代码瘦身
- 根目录 4 个旧文档 + docs/ 12 个早期文档归档至 `docs/archive/`
- CLAUDE.md 从 839 行精简至 ~130 行（仅保留架构、模块、配置、命令）
- 添加受保护文件声明：`RAW-Idea-latest-v3.md`、`docs/use-cases/*`
- 清理 4 个 .DS_Store 文件

### 1.0.1 重构路线图
- `web/app.py`（4017 行）→ app.py + schemas.py + 8 个 router 模块
- `cli/main.py`（4325 行）→ main.py + commands.py + slash.py + service.py + renderers.py
- `notify/notifier.py`（1408 行）和 `tools/metadata_tools.py`（1350 行）可选拆分

### 其他
- `context.py` 修复 sonnet 模型 alias（补 `-v1` 后缀）
- Scan Focus 功能上线（computing/networking/databases/storage/security/billing/all）
- 新建 `docs/MVP-1.0.0-RELEASE.md`（中文版架构与功能报告）

---

## 2026-03-09 — Pipeline 生命周期追踪 + Trace ID 关联

### PipelineEvent Timeline
- 新增 `PipelineEvent` 模型：`health_issue_id` 为自然追踪 ID，12 种事件类型横跨 6 个阶段
- `log_event()` best-effort 记录（不抛异常），12 个调用点全部接入
- 前端 `AnomalyDetail.tsx` 新增垂直时间线组件（15 秒自动刷新）

### Pipeline Trace ID
- `TRC-{uuid4.hex[:8]}` 格式，ContextVar 管理
- DB 列：HealthIssue、PipelineEvent、AlertEvent 三张表
- 线程传播：显式 `trace_id=` 参数（ContextVar 不跨线程）
- API：`GET /api/trace/{trace_id}`、`?trace_id=` 过滤、webhook 响应包含 trace_id
- 前端：可复制 trace_id 徽章 + 时间线事件显示

### aiops service CLI
- `aiops service start/stop/status/restart/logs` 命令
- 守护进程/前台模式，每组件独立日志（backend.log, frontend.log, feishu_ws.log）

### aiops init 交互式向导
- 4 步引导配置：Bedrock → Profile → Accounts → Pipeline

---

## 2026-03-08 — Agent-Based IM 告警路由 + 双 RCA 管线

### Feature A 重设计
- 删除旧的 `alert_classifier.py`（305 行正则分类器，误报严重）
- 新方案：所有 IM 消息经 Main Agent；告警频道消息包裹 `_ALERT_CHANNEL_PROMPT`（5 步验证）
- Agent 分析全文 → 验证严重性 → 决定是否 `create_health_issue`
- 54 个测试通过（含 6 个新 `TestBuildAgentInput` 测试）
- 实测验证：CloudWatch ALARM → Agent → HealthIssue → RCA 流水线成功触发

### 双 RCA 管线架构
- Pipeline 1（Webhook）：parsers → alert_processor → rca_service（无 LLM 成本）
- Pipeline 2（IM Agent）：feishu_ws → Main Agent → create_health_issue → 同一管线
- `AIOPS_ALERT_PIPELINE_MODE`：event_driven / channel_driven / both（默认）
- HealthIssue 指纹去重防止跨管线重复

---

## 2026-03-06 — 闭环验证完成 10/10

### 验证结果
- 10 个案例全部 5/5 通过
- 自动修复率：10/10（目标 ≥7）
- 平均检测时间：~2 分钟（目标 ≤3）
- 平均 MTTR：~6.3 分钟（目标 ≤10）
- 每周期成本：~$2-3（目标 ≤$3）

### 10 个验证案例
1. OOM Kill　2. Bad Image　3. Network Policy (Redis)　4. Node DiskPressure
5. Pod Pending　6. Unhealthy Targets　7. CoreDNS Down　8. PVC Pending
9. HPA Maxed Out　10. Service Deleted

### Bug 修复
- `mark_fix_executed()` 覆盖 resolved 状态 → 早期返回
- AlertEvent 去重阻止已终结 Issue 创建新 HealthIssue → 断开关联 + 透传

---

## 2026-03-03 — YAML-Only 通知频道 + /channel 命令

- `config/channels.yaml` 成为通知频道的唯一数据源，消除 DB 表
- `notify/im_config.py`：ChannelConfig、load_channels()、save_channel()、mtime 缓存
- NotificationManager 重构：从 YAML 读取，不再需要 DB session
- 6 个 API 端点改为按 `channel_name`（字符串）路由
- `/channel list|show|test|set` 斜杠命令（CLI + Web + IM）

---

## 2026-03-02 — 自动通知 + /send_to

- 7 个管线事件点的 fire-and-forget 通知（daemon thread）
- `/send_to <target> #R<id>, #D<id>, "text"` 命令（CLI + Web + IM）
- 新模型：LocalDoc（跟踪 agent 写入的文件）、IMAlias（友好名 → IM chat ID）

---

## 2026-03-01 — 自动修复管线 + 多后端执行器 + 工具截断

### Auto-Fix Pipeline
- 全链路：HealthIssue → RCA → SRE → Approve(L0/L1) → Execute → Resolve
- 三个开关：`auto_fix_enabled`、`executor_auto_approve_l0_l1`、`executor_enabled`
- L2/L3 需人工审批

### 多后端执行器
- Executor Agent 支持 AWS CLI + SSM/SSH + kubectl + Skills
- 动态工具加载：`activate_skill()` 运行时注册工具

### 工具输出截断
- metadata_tools.py 无输出限制导致上下文溢出（"内容过大被截断"）
- 新增 `_truncate()` MAX_RESULT_CHARS=4000, MAX_LIST_RESULT_CHARS=6000

---

## 2026-02-28 — 优化冲刺：状态机 + 认证 + 多模态

### HealthIssue 状态机
- 9 个有效状态，有向转移图，`validate_status_transition()` 违规返回 409
- 108 个新测试全部通过

### API 认证中间件
- `AIOPS_API_AUTH_ENABLED=true` 启用，`APIAuthMiddleware` 拦截 `/api/*`

### 多模态聊天
- 图片 + 文档作为 Strands SDK 原生 ContentBlock 发送
- 37 个多模态测试

### 可配置输出详细度
- concise / medium / detailed 三级，ContextVar + CLI + Web 全链路

---

## 2026-02-27 — Agent Skills 集成

- Skills = SKILL.md 包（Agent Skills 开放标准）
- 9 个领域技能：linux-admin、network-engineer、kubernetes-admin、database-admin、elasticsearch、monitoring、log-analysis、aws-compute、aws-storage
- Python 层：loader.py（发现+解析）、security.py（三级安全分类）、tools.py（3 个工具）、execution.py（run_on_host、run_kubectl）
- 渐进式加载：~636 token 系统提示词 + 按需加载 ~3-5K token

---

## 2026-02-26 — SRE 分析 + 拓扑图增强 + Chat 增强

### Graph Compute
- 12 种新节点类型（EC2、RDS、Lambda、EKS、ECS、ElastiCache、TargetGroup）
- 4 种 SRE 算法：dependency chain、SPOF 检测、capacity risk、change simulation
- 5 个新 API 端点 + 4 个新 agent 工具

### Chat 增强
- Headless 模式：`aiops chat "query"` / `aiops chat -q "query"` / pipe 支持
- @file/path 文件附加：CLI 中 `@/path/to/file` → 文件内容注入
- Web 文件上传：multipart/form-data + 附件指示
- I#N / R#N 引用解析：自动查询 HealthIssue / AWSResource 并注入上下文

---

## 2026-02-22 — Chat + Backend API

- Spinner 动画修复（Braille cycle + Rich Live）
- Token 追踪（Strands AgentResult.metrics）
- 27 个新 API 端点（HealthIssue、FixPlan、Schedule、Notification）
- Anomaly → HealthIssue 迁移（保留旧 URL 兼容）

---

## 2026-02-14 — Chat UI 体验优化

- 智能输出截断 `print_with_truncation()`
- 移除假思考动画（无 time.sleep）
- 简化响应展示（Rule 分隔符替代 Panel 边框）
- `/pager auto|on|off|<N>`、`/less` 带 markdown 渲染
