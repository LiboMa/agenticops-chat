# P1 设计 — Change Management：ITSM 变更流（工单 → SRE 审核 → 审批 → Executor）+ 审计账本 + RBAC 接口

> Date: 2026-09-16 · 版本: MVP-2.6.0 P1 · 上位基线: `docs/MVP-2.5.0-RELEASE.md`（最新发布）、
> `docs/superpowers/plans/2026-09-09-harness-engineering-architecture-update.md`（Trust Kernel 不变量：终态由代码写、agent 不能自我提权）
>
> 本文是 P1 的可实施设计（writing-plans 的输入）。P2（Runbook 模板库 + Webhook 触发部署变更）与
> P3（逐步交互执行 + IM 审批卡片）各自另起 spec；本文只在数据模型上为它们预留，不实现。

## 0. 问题与决策记录（brainstorm 2026-09-16）

**问题**：今天对现有系统做一个日常变更（例：给几台 EC2 加 tag）只有两条路——(a) 先造一个 HealthIssue，走
RCA → FixPlan → Executor 的**事件修复流**；(b) 在 Chat 里让 `sre_query` 用 `run_aws_cli(require_confirmation=True)`
**直接写**，不留任何变更记录。(a) 把 Change 记成 Incident，(b) 没有审计。二者都不是 ITSM 意义上的 Change。

**现状事实（决定设计起点）**：
- 仓库里已有一根 ITIL 形状的审批脊柱：`services/policy_engine.py` + `config/policies.yaml`（auto_approve / require_human /
  require_itsm_change / block / escalate、冻结窗口、`itsm_change_type: standard|normal|emergency`）和 `itsm/bridge.py`；但唯一消费者是
  `pipeline_service.trigger_auto_approve`，一切都绑在 HealthIssue + RCA 上。
- 硬约束：`fix_plans.health_issue_id` 与 `rca_result_id` NOT NULL（`models.py:476-477`）；`pipeline_events.health_issue_id` NOT NULL（`:554`）；
  FixPlan **没有状态转换校验器**（状态在 6 处直接赋值）；没有 reject 路径；审批人是自由文本（前端写死 `"web-user"`，
  `components/chat/ContextPanel.tsx:383`），L2/L3 只靠 `agent:` 前缀防护。
- 身份：`APIAuthMiddleware` 可选（`api_auth_enabled` 默认 false），`request.state.user` 下游无人消费；`users.permissions` 是
  `["read","write","admin"]` JSON；`require_auth/require_admin`（`auth/service.py:403,440`）零调用；无 Role 表。
- 审计：`audit_logs` 表 + `AuditService.log` + `/api/audit*` + Settings→Audit tab **全部就位但零写入**；工具层无命令日志，
  唯一命令记录是 agent 自报的 `fix_executions.step_results`。
- Harness 计划只定义 Investigation / Remediation 两种 loop；Change 是第三种，可复用 Remediation 尾段。

**决策**（每条对应一次用户确认）：
1. 「Runbook」三义都要：计划即 Runbook（批量执行）/ 参数化模板库 / 逐步交互执行 → 分别落 P1 / P2 / P3。
2. Chat 直接写路径**保留**，但每条写级命令在工具层落审计；只有用户明确要求、或命令命中高风险模式（`change_required`）时才必须走 Change。
3. RBAC 做到「接口 + 身份绑定 + SoD」：单一 `authz.check`、actor 来自认证会话而非请求体、YAML 矩阵映射到现有 `users.permissions`、
   不建 Role 表、`rbac_enforce` 默认关（影子模式）。
4. 审批模型复用 policy_engine：L0/L1 = standard、L2/L3 = normal、申请人可标 emergency；`change_auto_approve_standard` 默认 **false**；
   emergency 仍需人工审批但可穿越冻结窗口。
5. 入口面：Chat（Web + CLI）与 Web UI 表单 做；IM 审批卡片 → P3；Webhook（GitHub push → 部署变更）→ P2，P1 只预留 `source` 与统一入口；
   Schedule 变更窗口 非目标。
6. 架构取方案 A：**一张 Plan 表两种来源 + 独立 ChangeRequest 工单**，并顺手补 FixPlan 缺的地基（校验器 / reject / 身份 / 审计）。

## 1. 目标与非目标

**目标**（P1 交付 6 件事）：
1. `ChangeRequest` 工单 + 泛化的 Plan（`plan_kind` fix|change），两个代码级状态机校验器；Executor 门 `get_approved_fix_plan` 只做一处等价放宽——同时接受 `executing`（队列路线入队时已把计划标为 executing，而 executing 只能从 approved 经校验器到达；顺带修掉今天队列路线里 Executor 第一步被自己的门拒绝的既有 bug）。
2. SRE 新增「变更审核」模式：目标资源 grounding（fail-closed）→ 风险定级 → 策略判定 → 出计划（rollback 必填）→ 提交结论；仍然只读。
3. 身份与授权：Actor 解析 + Run Context + `authz.check` 影子模式 + `config/rbac.yaml` + SoD；审批人绑定认证身份。
4. 两本账：`audit_logs` 真正写入（所有人工/自动决策，与状态变更同事务）+ 新表 `command_audits`（工具层写级命令，覆盖 fix / change / Chat 直接写三条路）。
5. 六个面：Chat（Web + CLI 斜杠命令）、Web API `/api/changes/*`、Web UI 新页 `/app/plans`（Fix Plans / Change Plans / Audit）+ `/app/changes/:id`、
   Agent tools、Notification 三点；`GET /api/plans/stats` 统计。
6. 测试：单元 + API + pipeline（mock agents）+ 迁移 + 提示词预算 + 前端构建；真实账户 live E2E（tag 变更加/删）。

**非目标（P1 明确不做）**：Schedule 变更窗口（Scheduler 今天只有立即执行的 `@once`，`scheduler/scheduler.py:230,251`）；
IM 审批卡片与 IM 发送者身份落库（P3）；`POST /api/webhooks/change/{source}`（P2）；Runbook 模板库（P2）；逐步交互执行 / Chat 内审批卡 / HITL 接线（P3）；
Role 表与用户角色管理 UI；SecurityRecommendation → Change（`source` 是字符串列，日后加值即可）；ITSM bridge 对 Change 的映射（`itsm_enabled` 默认 false，
bridge 只订阅带 `health_issue_id` 的事件，P1 忽略 CR 事件）；非 REPL 的 `aiops changes …` 子命令。

### 1.1 六个可达面（逐行，做 / 非目标）

| 面 | P1 | 内容 |
|---|---|---|
| **CLI** | 做 | REPL 斜杠：`/change <描述>`、`/changes [status]`、`/approve C<id> [理由]`、`/reject C<id> <理由>`、`/execute C<id>`；actor = `cli:<os user>`。非 REPL 子命令：非目标 |
| **Web API** | 做 | `/api/changes/*`（§3.7）、`/api/plans/stats`、`/api/command-audits`；FixPlan 端点加固（approve 取会话身份 + reason、新 reject、`PUT` 不再收 status/approved_by、list 加 `kind`） |
| **Web UI** | 做 | 新页 `/app/plans`（三 tab）与 `/app/changes/:id`；侧栏 `plans` 项；Dashboard「Active Plans」；ContextPanel / IssueDetail 审批卡改身份绑定；`C#N` 自动链接（§3.9） |
| **Agent tool** | 做 | Main：`request_change` / `review_change` / `get_change_request` / `list_change_requests` / `execute_change`；SRE：`ground_change_targets` / `attach_change_target` / `evaluate_change_policy` / `submit_change_review`；`save_fix_plan` 扩展 |
| **Schedule** | **非目标** | 变更窗口"在 T 时刻执行一次"。CR 表不预留 window 列（以后是 ADD COLUMN 级小事） |
| **Notification** | 做 | `change_requested` / `change_pending_approval`（附深链）/ `change_result`；IM 卡片非目标（P3） |
| **Webhook** | **非目标** | P2 做端点 + HMAC + GitHub push 解析；P1 预留 `change_requests.source` 枚举值 `webhook` 与统一入口 `change_service.create_change_request(source, actor, payload)` |

## 2. 架构与数据流

```
入口  Chat(Web SSE / CLI REPL "/change")   Web 表单 POST /api/changes   [P2 Webhook]   [P3 IM]
  └─ change_service.create_change_request(source, actor, …)       [代码] authz change.request · CR=draft · audit change.requested · notify
       └─ change_service.start_review(cr_id, sync)                 CR=under_review · 看门狗 change_review_timeout_seconds
            └─ sre_agent  Mode C（只读）
                 ├─ ground_change_targets / attach_change_target   [代码, fail-closed] 目标必须落库存或经代码 describe 实证
                 ├─ 风险 L0-L3 + action_type                        [LLM 判定，量表同 fix]
                 ├─ evaluate_change_policy                          [代码] policy_engine(plan_kind=change, emergency, action_type, 冻结, 爆炸半径)
                 ├─ save_fix_plan(plan_kind="change", change_request_id) [代码强制 rollback_plan 非空、post_checks 非空]
                 └─ submit_change_review(verdict, risk, reasons)     [代码写状态；策略在此处重新评估，以代码结果为准]
                      ├─ rejected / needs_clarification → audit + notify
                      └─ planned →  policy=auto_approve ∧ change_auto_approve_standard ?
                                     自动审批(actor agent:auto-pipeline, 记规则名) → 入队
                                   : plan=pending_approval · notify change_pending_approval(深链)
                                        └─ 人工审批 Web/CLI  [authz change.approve + SoD · 理由必填 · audit] → plan=approved · CR=approved
                                             └─ request_execution → FixExecution(pending)  ← 唯一路线：ExecutorService 队列
                                                  └─ executor_agent(fix_plan_id)   [不改；get_approved_fix_plan 门不改]
                                                       └─ save_execution_result → change_service.on_execution_result  [代码终态映射器]
                                                            completed | needs_review | failed | rolled_back → audit + notify change_result

命令账本   run_aws_cli / run_on_host / run_kubectl / run_skill_script
             └─ command_audit.record_command(write|unknown|blocked, outcome)  ← Run Context(actor, fix_plan_id, change_request_id, trace_id, agent)
             └─ 命中 policies.yaml change_required 且 Run Context 无已审批计划 → 拒绝（outcome=refused）并提示 "/change"
```

三条不变量（对齐 Trust Kernel）：**CR 终态只由 `on_execution_result` 写**；**任何目标资源不可实证则不出计划**；
**自动审批必须同时满足 yaml 规则与 settings 开关**。

## 3. 组件详细设计

### 3.1 `services/change_service.py`（新；状态机与事务的唯一所有者）

| 函数 | 行为 |
|---|---|
| `create_change_request(*, source, actor, title, description, account_name=None, targets: list[str], requested_change_type="normal", justification="", chat_session_id=None) -> ChangeRequest` | `authz.check(actor, "change.request")`；账户存在且启用（`credentials/resolver.list_enabled_accounts`）否则 400；`trace_id` 取当前或 `generate_trace_id()`；写 CR(draft) + `audit_logs(change.requested)` **同一 session**；`pipeline_events(change_requested, stage=intake)`；`notify_change_requested`。返回后调用方决定 `start_review(sync)` |
| `start_review(cr_id, *, sync: bool)` | `draft|needs_clarification → under_review`；`sync=True`（Main 的 `review_change` 工具，同一轮返回结论）直接调 `sre_agent_review_change`；`sync=False`（Web/CLI/API）起 daemon 线程（仿 `pipeline_service.py:77-89`），线程内 `set_trace_id` + Run Context(actor=`agent:sre`)。看门狗线程：超时仍 under_review → `draft` + `review_failed` 事件 + notify |
| `ground_targets(cr) -> (grounded, unresolved)` | 确定性：`aws_resources.resource_id` 精确 / ARN 尾段 / Name tag 匹配（限 CR 账户）。只返回，不写 |
| `attach_target(cr_id, resource_id, resource_type, *, actor)` | **代码自己**经 provider 层跑一次只读 describe（类型映射表：ec2 instance / security-group / subnet / vpc / rds / eks cluster / s3 bucket / lambda / asg；ARN 走 `resourcegroupstaggingapi get-resources --resource-arn-list`），成功才写入 `target_resources`（带 `evidence` = 命令 + 返回摘要）。失败 → 返回 not found，不写 |
| `evaluate_policy(cr, risk_level, action_type) -> PolicyDecision` | 组装 `PolicyEngine.evaluate(risk_level, provider, resource_id=首个目标, blast_radius=图引擎, plan_kind="change", emergency=(requested_change_type=="emergency"), action_type)`；结果写 `pipeline_events(policy_decision)`（沿用 `pipeline_service.py:236-251` 形状） |
| `submit_review(cr_id, *, verdict, risk_level, action_type, reasons, actor)` | `authz.check(actor, "change.review")`；`under_review → planned|needs_clarification|rejected`；`approved_for_planning` 时要求：存在 `plan_kind=change` 的 draft 计划、`rollback_plan` 与 `post_checks` 非空、`target_resources` 非空，否则 409；**重新**调 `evaluate_policy`（LLM 只是被告知，代码结果为准），写 `risk_level / action_type / effective_change_type / review_*`；`block` → 强制 rejected；然后审批路由：`auto_approve ∧ settings.change_auto_approve_standard` → `approve(actor="agent:auto-pipeline", reason=rule)` + `request_execution`；否则 plan → `pending_approval`，`notify_change_pending_approval` |
| `approve(cr_id, *, actor, reason)` | `authz.check(actor, "change.approve", subject=cr)`（含 SoD）；reason 必填（空 → 422）；乐观锁 `UPDATE … WHERE status='planned'`；plan `pending_approval|draft → approved`（走校验器）；CR → approved；audit `change.approved`（old/new 状态、reason、rule）；CR 与 plan 的 approved_by 都写 actor 字符串 |
| `reject / cancel(cr_id, *, actor, reason)` | 同上形状；`reject` 允许于 planned（审批人）；`cancel` 允许于 draft / needs_clarification / planned / approved（申请人或 admin）；对应 plan → rejected |
| `clarify(cr_id, *, actor, message)` | `needs_clarification` 时申请人补充：追加到 description（时间戳分节）→ `start_review(sync=False)` |
| `request_execution(cr_id, *, actor)` | `authz.check(actor, "change.execute")`；仅 approved；插入 `FixExecution(pending, executed_by=actor)`（复用 `app.py:2442-2477` 的队列形状）；CR → executing；audit `change.execution_started` |
| `resolve_review(cr_id, *, actor, outcome, reason)` | `needs_review` 的人工裁定：`authz.check(actor, "change.approve")`；`outcome ∈ {completed, failed}`，reason 必填；audit `change.completed/failed(details.resolved_by_human=true)`。**不提供重跑**——要重做就新建变更单（可在详情页一键"复制为新变更"预填表单） |
| `restart_review(cr_id, *, actor)` | `draft` 的（重新）发起审核：`authz.check(actor, "change.request")`；用于 Main 未调 `review_change` 留下的草稿、以及看门狗回退的草稿；内部就是 `start_review(sync=False)` |
| `on_execution_result(plan, execution)` | **终态映射器**（唯一写 CR 终态处）：`succeeded ∧ post_checks 非空 ∧ post_check_results 条数 ≥ post_checks 条数 ∧ 全部 pass` → completed；`succeeded` 但结果缺失/部分 → needs_review；`failed` → failed；`rolled_back` → rolled_back；`aborted` → failed(reason=aborted)。写 audit + notify `change_result`。被 `save_execution_result`（`metadata_tools.py:1200-1205` 之后）、`executor_service._mark_crashed/_mark_timed_out`（`:189-216`）调用 |

所有状态变更用 `UPDATE … WHERE id=:id AND status=:expected` + rowcount 校验（仿 `executor_service.py:117-128`），防双批双执。

### 3.2 状态机校验器（`models.py`）

```
CHANGE_TRANSITIONS = {
  draft:               {under_review, cancelled},
  under_review:        {planned, needs_clarification, rejected, draft},   # draft = 看门狗回退
  needs_clarification: {under_review, cancelled},
  planned:             {approved, rejected, cancelled},
  approved:            {executing, cancelled},
  executing:           {completed, failed, rolled_back, needs_review},
  needs_review:        {completed, failed},                              # 人工裁定；重跑 = 新建变更单
  completed/failed/rolled_back/rejected/cancelled: {}                     # 终态
}
PLAN_TRANSITIONS = {
  draft:            {pending_approval, approved, rejected},
  pending_approval: {approved, rejected},
  approved:         {executing, rejected},                                # rejected 于 approved = 撤回
  executing:        {executed, failed},
  executed/failed/rejected: {}
}
```
`validate_change_transition(old, new)` / `validate_plan_transition(old, new)` 与 `validate_status_transition`（`models.py:393-413`）同形，非法 → `ValueError`，API 层 409。
替换 6 处直接赋值：`tools/metadata_tools.py:923-935, 1044, 1051, 1201-1204`、`services/pipeline_service.py:147`、`web/app.py:2402, 2467`、`cli/main.py:2302, 2361`、
`services/executor_service.py:201`。`FIXPLAN_*_STATUSES` 三个集合保留（dedup 逻辑不变）。

### 3.3 身份与授权：`auth/actor.py`、`run_context.py`、`auth/authz.py`、`config/rbac.yaml`

**Actor**（dataclass：`kind, id, user_id, permissions, display`；`str(actor)` = `kind:id`）：

| 来源 | actor 字符串 | permissions 来源 |
|---|---|---|
| Web，`api_auth_enabled=true` | `user:<email>` | `request.state.user.permissions`（API key 时与 key 权限求交，沿用 `auth/service.py:418-421`） |
| Web，认证关闭 | `web:anonymous` | `rbac.yaml` 的 `subjects.anonymous` |
| CLI | `cli:<getpass.getuser()>` | `subjects.cli`（默认 read/write/admin，本机可信） |
| Agent 自动路径 | `agent:<name>`（auto-pipeline / sre / executor） | `subjects.agents` |
| IM（P1） | `im:<platform>:<chat_id>`（P3 换 open_id，格式不变） | `subjects.im` |
| Webhook（P2） | `webhook:<source>` | `subjects.webhook` |

**Run Context**（`run_context.py`，一个 ContextVar，`RunContext(actor, trace_id, agent_name, fix_plan_id, change_request_id, chat_session_id, on_behalf_of)`）：
入口设置点——Web 请求依赖项 `current_actor(request)`（同时 set）；Chat SSE 处理器（`web/app.py:3844` 设 trace 的旁边）；CLI（`cli/main.py:3820` 旁）；
IM（`im/feishu_ws.py:292`、`im/slack_ws.py:296` 旁）；`ExecutorService._run_executor`（actor=`agent:executor`，`on_behalf_of=plan.approved_by`，plan/CR/trace 从行读）；
`change_service.start_review` 线程；`pipeline_service` 各线程沿 trace_id 的显式传递一并传 actor。工具内**只读**（Strands 同步工具在 `copy_context` 里跑，读得到、写不出，
与今天 trace_id 一致）。

**authz**（`auth/authz.py`）：`Permission` 枚举 `change.request / change.review / change.approve / change.reject / change.cancel / change.execute /
plan.approve / plan.reject / plan.execute / audit.read`；`check(actor, permission, *, subject=None) -> None`，拒绝抛 `AuthzDenied`（API 层 403）。
判定：矩阵要求的标志 ⊆ actor.permissions，且通过 `rules` 里的 SoD 约束。`settings.rbac_enforce=false` 时**影子模式**：照常判定，拒绝只写
`audit_logs(authz.denied_shadow)` 并放行——行为与今天完全一致；`true` 时抛出。

`config/rbac.yaml`（随仓库提交，`settings.rbac_file`）：
```yaml
version: 1
permissions:            # 权限项 → 需要的 users.permissions 标志
  change.request: [read]
  change.review:  [write]
  change.approve: [write]
  change.reject:  [write]
  change.cancel:  [write]
  change.execute: [write]
  plan.approve:   [write]
  plan.reject:    [write]
  plan.execute:   [write]
  audit.read:     [admin]
subjects:               # 无 users 行的内置主体
  anonymous: [read, write, admin]     # 认证关闭时等价于今天
  cli:       [read, write, admin]
  agents:    [read, write]
  im:        [read]
  webhook:   [read]
rules:                  # 只有两种结构化规则类型，没有表达式求值器
  - name: sod-change-approver-not-requester
    permission: change.approve
    type: actor_must_differ_from_field      # str(actor) != getattr(subject, field)
    field: requested_by
  - name: no-agent-approval-above-l1        # 收编现有 "agent:" 前缀检查 (app.py:2396, metadata_tools.py:1043)
    permission: [plan.approve, change.approve]
    type: deny_actor_kind_when_risk_in      # actor.kind == actor_kind and subject.risk_level in risk_levels
    actor_kind: agent
    risk_levels: [L2, L3]
```
`rules` 里的 `subject` 是 `check(..., subject=)` 传入的 ORM 对象（ChangeRequest 或 FixPlan）；未知 `type` 在加载时报错并回退到内置默认矩阵（fail-closed 到"与今天一致"）。
检查点调用位置：`routers/changes.py` 全部写端点；`app.py` fix-plan approve/reject/execute；CLI 斜杠命令；agent 工具 `approve_fix_plan`、`request_change`、
`submit_change_review`、`execute_change` 内部（agent 路径受同一矩阵约束）。

**审批人绑定**：`PUT /api/fix-plans/{id}/approve`（`app.py:2378`）与 `/api/changes/{id}/approve` 一律取 Run Context 的 actor；认证关闭时请求体中的名字
只作 `details.claimed_name` 记入审计，不进 `approved_by`。

### 3.4 命令账本：`services/command_audit.py` + `models.CommandAudit`

`record_command(*, tool, tier, command, outcome, account="", region="", target="", exit_code=None, output_excerpt="", duration_ms=0, reason="")`：
读 Run Context 填 actor / agent_name / fix_plan_id / change_request_id / trace_id；命令与摘要过 `security/redaction.redact_secrets`；摘要截 2000 字符；
**fail-soft**（任何异常只 `logger.debug`，永不影响工具返回）；`settings.command_audit_enabled=false` 时直接返回。

| 调用点 | 何时 | outcome |
|---|---|---|
| `tools/aws_cli_tool.run_aws_cli`（`:253-313`） | tier ∈ {write, unknown, blocked}：blocked → `blocked`；未确认 → `refused(reason=confirmation)`；命中 `change_required` 且无已审批计划 → `refused(reason=change_required)`；执行后 → `executed` / `error` | 见左 |
| `skills/execution.run_on_host`（tier 于 `:136`）、`run_kubectl`（`:384`） | 同上三档（用 `classify_shell_command` / `classify_kubectl_command`） | 同上 |
| `skills/sandbox.run_script` | 每次 | executed / error / refused |
| `run_aws_cli_readonly`、readonly 档 | 不记 | — |

`change_required` 判定：`policy_engine.change_required_match(command) -> Optional[str]`（返回命中的模式）；"已审批计划上下文" = Run Context 的 `fix_plan_id` 对应计划
`status in (approved, executing)`。Executor 在计划内执行不受限。

### 3.5 策略引擎扩展（`services/policy_engine.py`、`config/policies.yaml`）

- `evaluate(..., plan_kind: str = "fix", emergency: bool = False, action_type: Optional[str] = None)`；`match` 新增 `plan_kind: [fix, change]`、
  `action_type: [tag, scale, config, network, iam, delete, other]`、`emergency: true|false`；省略即匹配一切（**现有规则与 `DEFAULT_POLICY` 对 fix 流行为不变**）。
- `in_change_freeze` 在 `emergency=True` 时**不匹配**（yaml 注释写明；emergency 仍由 `require_human` 兜底）。
- 新段 `change_required:`（字符串前缀/子串列表，默认保守）：`aws ec2 modify-security-group`、`aws ec2 revoke-`、`aws ec2 authorize-`、`aws rds modify-`、
  `aws rds reboot-`、`aws autoscaling update-`、`aws autoscaling set-`、`aws lambda update-`、`aws eks update-`、`kubectl delete`、`kubectl drain`、
  `systemctl stop`、`systemctl restart`、`reboot`、`shutdown`（与 SRE 量表一致：L1 级的 tag / 单工作负载 `kubectl scale` 不在清单里）。`validate_policy` 校验新字段类型。
- `PolicyDecision.to_dict()` 不变；`policy_decision` 事件对 CR 写到 `change_request_id`。

### 3.6 Agents

**Main（`agents/main_agent.py`）**：工具列表加 `request_change`、`review_change`、`get_change_request`、`list_change_requests`、`execute_change`；
提示词加规则 **5.7**：「没有 HealthIssue 上下文的修改类意图（加/删 tag、扩缩容、改配置/参数）、或用户说"变更 / change request / CR"、或消息以
`[CHANGE REQUEST]` 开头 → `request_change` → `review_change` → 展示结论、风险、计划摘要、`C#N`、审批入口（Web `/app/plans` 或 `/approve C<N>`）；
绝不为这类意图让 `sre_query` 执行写命令」；规则 10 加一句「`sre_query` 报告写命令被 `change_required` 拒绝时，建议用户创建变更单」；
OUTPUT FORMATTING 加 `C#N`。工具 docstring 带路由关键词（`tests/test_prompt_budget.py::test_docstring_routing_keywords` 会检查）。

**SRE（`agents/sre_agent.py`）**：提示词加 **MODE C — CHANGE REVIEW PROTOCOL**（六步，见 §2；强调：不可实证的目标 → `needs_clarification`；
计划必须含能证明变更生效的 post_checks，如 `describe-tags`；rollback 必填）；工具列表（`:220-274`）加 `get_change_request`、`ground_change_targets`、
`attach_change_target`、`evaluate_change_policy`、`submit_change_review`；`save_fix_plan` 增参 `plan_kind: str = "fix"`、`change_request_id: int = 0`
（`plan_kind=change` 时 `health_issue_id/rca_result_id` 传 0 并忽略；dedup 按 `change_request_id` 维度，规则同 issue 维度）。
新入口 `sre_agent_review_change(change_request_id) -> str`（同一 agent 构建，不同调用提示），以 agents-as-tools 形式暴露给 Main 作 `review_change`。
Mode A / Mode B 与全部 guardrails 不变。

**Executor**：agent、提示词、工具、`get_approved_fix_plan`（`metadata_tools.py:1092-1136`）不改。变更计划只走队列路线；
`save_execution_result`（`:1138-1262`）在 plan 状态更新后、`executor_auto_resolve` 之前加分支：`plan.plan_kind == "change"` → `change_service.on_execution_result`，
跳过 issue 相关逻辑（auto_resolve / `trigger_post_resolution` / issue 状态同步）。`ExecutorService._run_executor` 设 Run Context。

**引用语法**：`chat/preprocessor.py:26-27` 旁加 `CHANGE_REF_PATTERN = r"\bC#(\d+)\b"` → 解析为 `<referenced_change>` 块（标题、状态、风险、目标、计划摘要）；
前端 `lib/renderMarkdown.ts:52-54` 旁加 `C#N → /app/changes/N` 自动链接。

### 3.7 Web API（新 `web/routers/changes.py`；`web/schemas.py`）

| 方法 路径 | authz | 请求体 | 响应 / 状态 |
|---|---|---|---|
| `POST /api/changes` | change.request | `ChangeRequestCreate{title, description, account_name?, targets: [str], requested_change_type: normal\|emergency, justification?}` | 201 `ChangeRequestResponse`；后台 `start_review(sync=False)` |
| `GET /api/changes` | — | query `status, account_id, requested_by, period, limit, offset` | `List[ChangeRequestResponse]` |
| `GET /api/changes/{id}` | — | | `ChangeRequestDetail`（CR + plans + executions + policy_decision） |
| `POST /api/changes/{id}/approve` | change.approve (+SoD) | `{reason}`（必填） | 200；409 非法状态；403 拒绝；422 缺 reason |
| `POST /api/changes/{id}/reject` | change.reject | `{reason}` | 200 / 409 / 403 |
| `POST /api/changes/{id}/cancel` | change.cancel | `{reason}` | 200 / 409 |
| `POST /api/changes/{id}/clarify` | change.request（须为申请人或 admin） | `{message}` | 202 |
| `POST /api/changes/{id}/execute` | change.execute | — | 202 `FixExecutionResponse` |
| `POST /api/changes/{id}/review` | change.request | — | 202；仅 draft（重新发起审核） |
| `POST /api/changes/{id}/resolve-review` | change.approve | `{outcome: completed\|failed, reason}` | 200；仅 needs_review |
| `GET /api/changes/{id}/timeline` | — | | `[{ts, kind: event\|audit, type, actor, status, detail}]`（pipeline_events by change_request_id ∪ audit_logs by entity，按时间合并） |
| `GET /api/plans/stats` | — | `period=7d\|30d\|90d, kind=all\|fix\|change, bucket=day\|week` | §5 结构 |
| `GET /api/command-audits` | audit.read | `actor, tool, outcome, fix_plan_id, change_request_id, period, limit, offset` | `List[CommandAuditResponse]` |

FixPlan 端点加固（`web/app.py`）：`PUT /api/fix-plans/{id}/approve`（`:2378-2424`）身份取 Run Context、体加可选 `reason`、写 audit `plan.approved`、
走校验器；新增 `POST /api/fix-plans/{id}/reject {reason}`；`PUT /api/fix-plans/{id}`（`:2362-2375`）的 `FixPlanUpdate` **删掉** `status` 与 `approved_by`
（`schemas.py:344-345`）；`POST /api/fix-plans/{id}/execute`（`:2442`）`executed_by` 改取 actor；`GET /api/fix-plans`（`:2264`）加 `kind` 筛选；
`FixPlanResponse`（`schemas.py:348-367`）：`health_issue_id/rca_result_id` 改 Optional，加 `plan_kind, change_request_id, rejected_by, rejected_at,
rejection_reason, updated_at`。`FixExecutionResponse.health_issue_id` 改 Optional。全局搜索（`routers/search.py:44-57`）加 change_requests 标题。

### 3.8 CLI（`cli/main.py`）

- `/change <描述>` → 向 Main 发送 `[CHANGE REQUEST] <描述>`（走规则 5.7，结论在同一轮返回）。
- `/changes [status]` → 表格：C#、标题、状态、风险、类型、申请人、更新时间。
- `/approve <id|C<id>> [理由]`（扩展 `:2260-2314`）：`C` 前缀走 `change_service.approve`；变更理由必填、fix 可选；不再询问审批人名字（actor 固定为 `cli:<user>`）。
- `/reject C<id> <理由>`、`/execute C<id>`（复用 `:2317-2370` 的入队路径，`executed_by` = actor）。
- 启动处（`:3820` 设 trace 旁）设 Run Context actor。

### 3.9 Web UI（`web/frontend/src/`）

| 文件 | 改动 |
|---|---|
| `App.tsx:53-181` | 路由 `plans` → `PlansAndChanges`，`changes/:id` → `ChangeDetail` |
| `components/layout/NavItems.tsx:10-20` | issues 后加 `{ id: "plans", to: "/app/plans", icon: "clipboard", labelKey: "nav.plans" }`；`ICON_PATHS.clipboard`；`nav.issues` 文案改 "Issues"（id 不变，`aiops-nav-order` 已存排序不受影响） |
| `pages/PlansAndChanges.tsx`（新） | Radix Tabs 三 tab：**Fix Plans**（`useFixPlans({kind:"fix"})` 扁平 DataTable：I# 链接、风险、状态、审批人/时间；行内 approve / reject / execute，approve/reject 弹 `ReasonDialog`）；**Change Plans**（`useChanges()` DataTable：C#、标题、`ChangeStepper` 迷你态、风险、类型、申请人、更新时间；筛选 status / account / 申请人；右上「New change request」→ `NewChangeDialog`）；**Audit**（`AuditTab`，§5） |
| `pages/ChangeDetail.tsx`（新） | 顶部 `ChangeStepper`（Requested → Reviewed → Planned → Approved → Executed → Completed；rejected / failed / rolled_back / cancelled 红标，needs_review 琥珀）；请求卡（申请人 / 时间 / 来源 / 类型 / 目标资源 R# 链接 / 理由）；审核卡（结论、理由列表、风险、action_type、命中的策略规则）；计划卡（复用 `components/plans/*`）；审批卡（approve / reject / cancel，`ReasonDialog` 理由必填；`needs_clarification` 时显示补充输入框 → clarify；`draft` 时显示「Start review」→ review；`needs_review` 时显示「Mark completed / Mark failed」→ resolve-review，以及「复制为新变更」预填 `NewChangeDialog`）；执行卡（approved 时 Execute；执行历史表复用 IssueDetail `:764-841` 的抽取）；时间线（`useChangeTimeline`，复用 `PipelineTimeline` 的抽取，audit 条目用不同图标）。非终态 5s 轮询 |
| `components/plans/`（新目录） | 从 `pages/IssueDetail.tsx:1092-1200` 抽出 `RunbookStep`、`CheckItem`、`RollbackPlan`、`PipelineTimeline`；新增 `ChangeStepper`、`ReasonDialog`（slideInRight + ESC，textarea 必填）、`NewChangeDialog`（标题、描述、账户下拉 `useAccounts`、目标资源多选带库存搜索 `useResources`、类型 normal/emergency、理由）、`ChangeStatusBadge` |
| `components/plans/AuditTab.tsx`（新） | §5 的 KPI + Recharts + 两张 DataTable |
| `hooks/useChanges.ts`、`usePlanStats.ts`、`useCommandAudits.ts`、`useChangeTimeline.ts`（新） | TanStack Query，key 形如 `["changes", filters]` |
| `hooks/useFixPlans.ts:34,49` | approve 体改 `{reason?}`（去掉 `approved_by`）；reject 改调 `POST /fix-plans/:id/reject {reason}` |
| `api/types.ts` | `FixPlan` 加 `plan_kind, change_request_id, rejected_*`，`health_issue_id/rca_result_id` 可空；新 `ChangeRequest`、`ChangeRequestDetail`、`PlanStats`、`CommandAudit`、`ChangeTimelineEntry`；`IssueStatus` 补 `fix_executing` |
| `pages/Dashboard.tsx:165-200` | 「Active Fix Plans」→「Active Plans」，两种 kind 徽标，change 卡链到 `/app/changes/:id` |
| `components/chat/ContextPanel.tsx:324-411` | FixPlanCard 去掉 `"web-user"`（`:383`），approve / reject 走 `ReasonDialog` |
| `pages/IssueDetail.tsx:65-66, 692-745` | 认证开启（`useAuth`）时隐藏审批人输入框；reject 走新端点并要求理由 |
| `lib/renderMarkdown.ts:52-54` | `C#N` 自动链接 |
| `locales/en.json`、`zh.json` | `nav.plans`、plans/changes/audit 页全部文案 |

弹层一律遵守 house rule（`animate-[slideInRight_0.2s_ease-out]` + ESC 关闭）。

### 3.10 Notification（`services/notification_service.py`）

三个便捷函数（仿 `:183-260`，不经 `_buffer_or_send` 的 issue 缓冲，直接 `notify_event`）：
`notify_change_requested(cr)`、`notify_change_pending_approval(cr, plan)`（正文含风险、计划摘要、深链 `{settings.web_base_url}/app/changes/{id}`）、
`notify_change_result(cr, outcome)`。`:156-158` 的 `notification_sent` 元组扩展：事件类型以 `change_` 开头时按 `change_request_id` 记时间线。
渠道路由沿用现有 severity / channel_names（不加事件类型路由）；severity 由风险映射：未定级 → medium，L0/L1 → low，L2 → medium，L3 → high，
`failed / rolled_back` 结果一律 high。

## 4. 数据模型（`models.py`；迁移在 `init_db`）

**新表 `change_requests`**

| 列 | 类型 | 说明 |
|---|---|---|
| id | PK | |
| title | String(300) | |
| description | Text | 自然语言意图；clarify 追加分节 |
| justification | Text default "" | |
| source | String(20) | chat / web / cli / im / webhook / api |
| requested_by | String(100) index | actor 字符串 |
| requester_user_id | Integer nullable | `users.id`（无 FK，与 `api_keys.user_id` 同法） |
| requested_at | DateTime | |
| account_id | Integer FK accounts.id nullable | |
| target_hints | JSON list | 申请人给出的原始资源标识字符串（ID / ARN / 名称），供 grounding 匹配 |
| target_resources | JSON list | `[{resource_id, resource_type, db_id?, region?, evidence}]`，仅 grounding 通过的 |
| requested_change_type | String(20) | normal / emergency |
| effective_change_type | String(20) nullable | standard / normal / emergency（策略决定） |
| risk_level | String(20) nullable | L0-L3 |
| action_type | String(20) nullable | tag / scale / config / network / iam / delete / other |
| status | String(30) index default "draft" | §3.2 |
| review_verdict | String(30) nullable | approved_for_planning / needs_clarification / rejected |
| review_reasons | JSON list | |
| review_attempt | Integer default 0 | 每次进入 `under_review` +1；所有回滚（看门狗 / worker 无结论 / 崩溃 / stale 恢复）都以 `(status='under_review', review_attempt=发起它的那次)` 为条件更新，迟到的回滚对下一次评审是 0 行 no-op（Plan B Task 3 round 2 裁定） |
| reviewed_by, reviewed_at | String(100) / DateTime nullable | |
| policy_rule, policy_action | String(100) / String(30) nullable | 命中规则与动作 |
| approved_by, approver_user_id, approved_at, approval_reason | 同上形状 | |
| rejected_by, rejected_at, rejection_reason | 同上 | reject 与 cancel 共用（details 区分） |
| closed_at | DateTime nullable | 进入终态时间 |
| trace_id | String(20) index nullable | |
| chat_session_id | String(64) nullable | Chat 来源 |
| created_at, updated_at | DateTime | |

关系：`plans = relationship("FixPlan", back_populates="change_request")`。索引：status、requested_by、account_id、created_at。

**`fix_plans` 改动**：`health_issue_id`、`rca_result_id` 改 nullable；加 `plan_kind String(10) default "fix" index`、`change_request_id Integer FK change_requests.id nullable index`、
`rejected_by String(100)`、`rejected_at DateTime`、`rejection_reason Text`、`updated_at DateTime`；CHECK `ck_fix_plans_origin`：
`(plan_kind='fix' AND health_issue_id IS NOT NULL AND rca_result_id IS NOT NULL AND change_request_id IS NULL) OR (plan_kind='change' AND change_request_id IS NOT NULL AND health_issue_id IS NULL AND rca_result_id IS NULL)`。
`health_issue` / `rca_result` relationship 改 Optional。

**`fix_executions.health_issue_id`** 改 nullable。**`pipeline_events.health_issue_id`** 改 nullable，加 `change_request_id Integer index nullable`；
`services/pipeline_events.log_event(health_issue_id: Optional[int], …, change_request_id: Optional[int] = None)` 二选一（都空 → 只记日志不落库）；
`get_timeline` 加 `change_request_id` 参数。

**`audit_logs`** 加 `actor String(100) index nullable`（`ALTER TABLE ADD COLUMN`，现有机制）；`AuditService.log(..., actor=None)`；
`Actions` 加 `CHANGE_REQUESTED/REVIEWED/CLARIFIED/APPROVED/REJECTED/CANCELLED/EXECUTION_STARTED/COMPLETED/FAILED/ROLLED_BACK/NEEDS_REVIEW`、
`PLAN_APPROVED/REJECTED/EXECUTE_REQUESTED`、`AUTHZ_DENIED`、`AUTHZ_DENIED_SHADOW`；`EntityTypes` 加 `CHANGE_REQUEST`、`FIX_PLAN`。

**新表 `command_audits`**：id、created_at index、actor String(100) index、actor_user_id nullable、on_behalf_of String(100) nullable、agent_name String(50) nullable、
tool String(30)、tier String(10)、account String(100)、region String(30)、target String(200)、command Text（脱敏）、outcome String(10) index、reason String(50) nullable、
exit_code Integer nullable、output_excerpt Text、duration_ms Integer、trace_id String(20) index nullable、fix_plan_id Integer index nullable、change_request_id Integer index nullable。

**迁移（`init_db`，`models.py:915` 起）**：
- 现有 `ALTER TABLE ADD COLUMN` 幂等模式处理所有新增列与 `audit_logs.actor`；新表由 `create_all` 建。
- **NOT NULL → NULL 与 CHECK**（fix_plans / fix_executions / pipeline_events）：SQLite 不支持，走 sqlite.org 官方 12 步重建，封装为
  `_sqlite_rebuild_table(conn, table: Table)`：`PRAGMA foreign_keys=OFF` → 按 `table` 的元数据 `CREATE TABLE <name>__new`（不带索引）→
  `INSERT INTO <name>__new (<共有列>) SELECT <共有列> FROM <name>` → `DROP TABLE <name>`（连带旧索引）→ `ALTER TABLE <name>__new RENAME TO <name>`
  （新→旧名方向，避免 SQLite ≥3.26 改写他表 FK 引用）→ 重建索引 → `PRAGMA foreign_key_check` → `PRAGMA foreign_keys=ON`。
  触发条件按 `PRAGMA table_info` 的 `notnull` 判断（幂等）；重建前把 SQLite 文件复制为 `<db>.bak-pre-2.6.0`（仅首次）。
- PostgreSQL：`ALTER TABLE … ALTER COLUMN … DROP NOT NULL` + `ADD CONSTRAINT ck_fix_plans_origin CHECK (…)`（`IF NOT EXISTS` 语义用 `information_schema` 判断）。
- 失败即抛出、进程不启动（不带半迁移 schema 运行）。

## 5. 配置（`config/settings.yaml`；`config.py` 只定义 schema）

| 键 | 默认 | 说明 |
|---|---|---|
| `change_management_enabled` | `true` | 总开关：关闭时 Main 不注入变更工具、`/api/changes` 返回 404、CLI 斜杠命令提示未启用 |
| `change_auto_approve_standard` | `false` | 策略为 auto_approve 的 standard 变更是否免人工审批；与 yaml 规则**同时**满足才自动 |
| `change_review_timeout_seconds` | `600` | SRE 审核看门狗 |
| `rbac_enforce` | `false` | false = 影子模式（判定 + `authz.denied_shadow` 审计，放行）；true = 403 + SoD |
| `rbac_file` | `config/rbac.yaml` | 权限矩阵 |
| `command_audit_enabled` | `true` | 工具层写级命令账本 |
| `audit_retention_days` | `365` | `audit_logs` 与 `command_audits` 每日清理（仿 `signal_gate.py:342-361`，接通已存在的 `AuditService.cleanup_old_logs`） |

`config/policies.yaml` 追加 `change_required:` 段与三个 match 字段（§3.5）。`GET /api/settings` 暴露以上键；Web Settings 页在既有 pipeline 开关卡加
`change_auto_approve_standard`、`rbac_enforce` 两个开关（写回 YAML，与其他开关一致）。CLAUDE.md 配置表加行。

**`GET /api/plans/stats` 返回结构**（`services/plan_stats_service.py`，分桶用 `cost_service.py:15-21` 的可移植写法）：
```
{ period, kind,
  totals:    { by_kind_status: {fix:{draft:n,…}, change:{…}}, open: n },
  approvals: { auto: n, human: n, rejected: n, authz_denied: n, authz_denied_shadow: n },
  lead_time: { request_to_approve_p50_s, request_to_approve_p90_s, approve_to_start_p50_s, exec_duration_p50_s },
  outcomes:  { success_rate, rollbacks, needs_review },
  breakdown: { by_actor: {requesters:[…], approvers:[…], executors:[…]}, by_risk:{}, by_change_type:{}, by_action_type:{}, by_account:{} },
  series:    [{bucket, created, completed, failed}],
  commands:  { by_outcome: {executed, refused, blocked, error}, by_tool: {} } }
```

## 6. 错误处理 / 失败模式

| 场景 | 行为 |
|---|---|
| SRE 审核抛异常 / 超时 | 看门狗：CR `under_review → draft`，`review_failed` 事件（detail 含 error），notify；绝不永久停在 under_review |
| 目标 grounding 失败 | 结论 `needs_clarification`，`review_reasons` 列出未解析目标；不出计划；申请人 clarify 后重审 |
| 策略 block（含冻结窗口） | 结论 rejected，`policy_rule` 记规则名；emergency 不受冻结规则约束但仍 require_human |
| SRE 提交结论但计划缺 rollback / post_checks / 目标为空 | `submit_review` 409，SRE 收到明确错误再补；LLM 无法绕过 |
| 审批人 = 申请人 | `rbac_enforce=false`：放行 + `authz.denied_shadow` 审计；`true`：403 |
| Executor 崩溃 / 超时 | 沿用 `_mark_crashed / _mark_timed_out` → plan failed → `on_execution_result` → CR failed |
| post_checks 结果缺失 | CR `needs_review`（不是 completed）；人工在详情页裁定 completed / failed（`resolve-review`），要重做则「复制为新变更」 |
| 审计写入失败 | 决策类审计与状态变更同事务（一起回滚 → API 500，状态不变）；`command_audits` fail-soft 只记日志 |
| 并发双批 / 双执 | `UPDATE … WHERE status=:expected` rowcount=0 → 409 |
| 迁移失败 | `init_db` 抛出，进程不启动；日志给出 `.bak-pre-2.6.0` 路径 |
| `change_management_enabled=false` | 全部新面不可达；fix 流与审计加固（§3.2-3.4）仍生效 |

## 7. 测试计划

- **单元**：`test_change_state_machine.py`（两个校验器全部合法边 + 非法边 ValueError，与 `test_state_machine.py` 同形）；`test_authz.py`（矩阵、SoD、
  agent L2/L3 拒绝、影子模式写审计、actor 解析六种来源）；`test_policy_engine_change.py`（`plan_kind/action_type/emergency` 匹配、emergency 穿越冻结、
  `change_required_match`、旧 yaml 兼容）；`test_change_service.py`（grounding、`attach_target` 只在 describe 成功时写、`submit_review` 409 条件、
  终态映射器五分支、乐观锁）；`test_command_audit.py`（三档记录、readonly 不记、fail-soft、脱敏、Run Context 归属）；`test_run_context.py`（线程显式传递、工具内只读）。
- **API**：`test_changes_api.py`（全端点、reason 缺失 422、SoD 403、非法状态 409、timeline 合并排序、stats 结构、command-audits 筛选）；
  `test_fix_plan_hardening_api.py`（`PUT` 不再接受 status、新 reject、approve 身份来自会话、`kind` 筛选、响应新字段）。
- **pipeline**：`test_change_pipeline.py`（mock SRE / Executor，SQLite，仿 `test_auto_fix_pipeline.py`）：主路 request → review → planned → pending_approval →
  approve → execute → completed；支路 auto-approve（开关 + 规则）、needs_review、needs_clarification → clarify → planned、policy block → rejected、看门狗回退。
- **迁移**：`test_migration_2_6_0.py`：用 2.5 时期的 `CREATE TABLE` 语句造旧库并插数据 → `init_db` → 三表列可空、CHECK 存在、行数与内容一致、索引重建、
  他表 FK 引用仍指向新表、二次运行无操作、`.bak` 文件存在。
- **提示词预算**：`tests/test_prompt_budget.py` 现有金标覆盖 Main / SRE 增量与新工具 docstring 关键词。
- **回归**：全量 `pytest tests/`（约 2 分钟，输出重定向到文件再看；唯一预期失败为 `test_web_tools` 的本机 DNS 假失败）。
- **前端**：`npx tsc --noEmit && npm run build`。
- **Live E2E**（dev 账户，按 `docs/MVP-2.5.0-E2E-REPORT.md` 体例写 `docs/MVP-2.6.0-E2E-REPORT.md`）：
  1. Chat：「给 i-xxx 加 tag ChangeTest=2026-09」→ 收到 `C#N`、审核结论、风险 L1、计划含 describe-tags post_check 与 rollback（delete-tags）。
  2. `command_audits` 中该 trace 在审批前**零条 executed 写命令**。
  3. Web `/app/changes/N` 审批（填理由）→ 入队 → Executor 执行 → `aws ec2 describe-tags` 实证 tag 存在 → CR completed。
  4. Audit tab：决策账本 ≥ 6 条（requested / reviewed / approved / execution_started / completed + notification），命令账本含 create-tags 行且 `change_request_id=N`。
  5. 第二个变更删除该 tag（同路径），stats 出现 2 条 completed。
  6. 临时 `rbac_enforce=true`：同一 actor 审批 → 403；恢复 false。
  7. Chat 直接写：`aws ec2 create-tags …` 经确认执行后 `command_audits` 有 `executed` 行；`aws ec2 modify-security-group-rules …` 被 `change_required` 拒绝并提示 `/change`。

## 8. 验收标准

1. 一个自然语言变更请求从 Chat 到 completed 全程不需要 HealthIssue；`fix_plans` 中该计划 `plan_kind=change`、`health_issue_id IS NULL`。
2. 在 CR 进入 approved 之前，该 trace 的 `command_audits` 没有 `outcome=executed` 的写命令。
3. `approved_by` 等于认证 actor 字符串，客户端无法通过请求体指定；`rbac_enforce=true` 时申请人自批 403、agent 批 L2/L3 403。
4. CR `completed` 仅在 post_checks 全部通过时出现；缺结果 → `needs_review`。
5. `audit_logs` 中每个 CR 生命周期 ≥ 5 条决策记录，且每条 `actor` 非空；fix 流的人工审批同样入账。
6. `GET /api/plans/stats` 的 `totals.by_kind_status` 与数据库直接聚合一致；Audit tab 渲染无控制台错误。
7. 旧 SQLite 库经 `init_db` 迁移后数据零丢失，现有全量测试通过（除已知 DNS 假失败）。
8. `change_management_enabled=false` 时现有 fix 流行为与 2.5.0 一致（测试套件绿）。

## 9. 实施顺序（每阶段可独立验证）

| 阶段 | 内容 | 验证 |
|---|---|---|
| **S0 地基** | §4 模型 + 迁移 + 两个校验器 + 6 处赋值改走校验器 + `audit_logs.actor` | 迁移测试、状态机测试、全量回归绿；行为零变化 |
| **S1 身份与账本** | Actor / Run Context / authz 影子 / rbac.yaml；fix-plan approve/reject/execute 写 `audit_logs`；`command_audits` 三工具接入；`change_required` 拒绝 | 既有 fix 流开始有账；`test_authz`、`test_command_audit` |
| **S2 后端闭环** | `change_service` + policy 扩展 + SRE Mode C + Main 工具 + `save_fix_plan` 扩展 + `on_execution_result` + CLI 斜杠 | `test_change_pipeline` 主路与支路；CLI 手动走通 |
| **S3 Web API** | `routers/changes.py` + schemas + fix-plan 端点加固 + stats + command-audits | `test_changes_api`、`test_fix_plan_hardening_api` |
| **S4 Web UI** | `/app/plans` 三 tab、`/app/changes/:id`、`components/plans/` 抽取、Dashboard / ContextPanel / IssueDetail 改动、`C#` 链接、locales | `tsc` + build；浏览器走通 |
| **S5 通知与文档** | 三个通知点；`MVP-2.6.0-RELEASE.md`、WORKFLOW.md Change loop、README/README_CN 同步、docs/README.md 地图、CLAUDE.md、harness 计划附注 | 文档互链检查 |
| **S6 Live E2E** | §7 七步 → `MVP-2.6.0-E2E-REPORT.md` | **E2E 通过且主人确认后**才 `git push --no-verify` |

## 10. 风险与开放问题

- **SQLite 表重建**是仓库首次；风险由迁移测试 + 重建前 `.bak` 副本 + 幂等判断兜住。PostgreSQL 路径只做 `DROP NOT NULL`，风险低。
- **提示词膨胀**：Main 加一条规则与 5 个工具、SRE 加 Mode C，`test_prompt_budget` 金标可能需要上调；应控制在现有 20,000 字符总预算内。
- **grounding 覆盖面**：`attach_target` 的类型映射表有限；映射不到的类型走 ARN 的 tagging API，再不行就 `needs_clarification`（安全侧失败）。
- **`change_required` 默认清单**偏保守，可能漏判高风险命令；这是 yaml 可调项，不是代码常量。
- **Run Context 跨线程**：所有新线程必须显式传递并 set（与 trace_id 同纪律）；遗漏会让命令账本归属到"unknown"，测试覆盖 ExecutorService 与审核线程。
- **IM actor 在 P1 只到 chat_id**，SoD 粒度粗；P3 落 open_id 后自然收紧，字段格式不变。
- **与 Harness 计划的关系**：Change loop 是第三种 loop，`on_execution_result` 是 Trust Kernel VerifyGate 的雏形；Phase 1 落地 VerifyGate 时把它收编，不另起一套。
- **两条执行路线**（fix 的线程路线 vs 队列路线）本次不统一，只让 change 走队列；统一留给 Harness Phase 2。
