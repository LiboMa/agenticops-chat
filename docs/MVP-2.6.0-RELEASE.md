# MVP-2.6.0 Release Notes — 变更管理（Change Management / ITSM）

> Version: 2.6.0 · Branch: `MVP-2.5.0`（变更管理落在此分支；未单独开 MVP-2.6.0 分支） · Date: 2026-09-26（草稿日期；push 时按主人确认日期回填） · 主题：日常变更走 ITSM 变更流，不再冒充事件
>
> **状态：P1 后端（Plan B）与前端（Plan C，Task 1–6）已全部实现，作为 `MVP-2.5.0` 分支上的本地提交存在（未 push）；已通过单元/API/pipeline/迁移回归 + 前端 `tsc` / `vitest` / `vite build` / locale-parity 四道门；真实账户 live E2E 尚待与主人联合验证。** 依 `docs/MVP-2.5.0-RELEASE.md` 与主人的铁律，只有真实 E2E 通过且当面确认后才 `git push --no-verify`。测量数字（测试计数、E2E 证据）在提交前由控制器据实填入 —— 本文不预填未验证的数字。
>
> P1 详细实施设计：`docs/superpowers/specs/2026-09-16-change-management-p1-design.md`
> Live E2E 证据（待产出）：`docs/MVP-2.6.0-E2E-REPORT.md`

## 一句话

给一个正在运行的系统做**日常变更**（例：给几台 EC2 加 tag、扩缩容、改配置），过去只有两条路——要么先造一个假 HealthIssue 走事件修复流（把变更记成事故），要么在 Chat 里直接写命令（不留任何变更记录）。MVP-2.6.0 补上第三条、也是正确的一条：**工单 → SRE 合法性审核 → 审批 → Executor**，全程有账、有审批人身份、有回滚与验证，且**不需要任何 HealthIssue**。

## 定位（为什么做、做给谁）

这是 ITSM 意义上的 **Change**，与既有的 **Incident（事件修复流）** 并列而非混用：

| 维度 | Incident（既有自动修复流） | Change（本版新增） |
|------|---------------------------|--------------------|
| 起点 | 告警 / 异常 → HealthIssue → RCA | 人（或未来的 Webhook）主动发起的变更意图 |
| 计划来源 | RCA 结论驱动 | SRE 合法性审核驱动 |
| 是否需 HealthIssue | 是 | **否** |
| 审批 | L0/L1 自动、L2/L3 人工 | 默认全部人工；standard 变更可选自动（双开关） |
| 账本 | pipeline_events + fix_executions | audit_logs（决策）+ command_audits（命令）+ pipeline_events |

**交付形状「方案 A」**：一张 Plan 表两种来源（`fix_plans.plan_kind` = `fix` | `change`）+ 一张独立的 `change_requests` 工单表，并顺手补齐 FixPlan 一直缺的地基（状态机校验器、reject 路径、审批人身份绑定、审计写入）。

## 六个可达面（逐行 —— 每个面显式写「做」或「非目标」）

> 规则：**Web API 与 Web UI 永远是两行**，绝不合并成「Web」。

- **CLI** — 做。REPL 斜杠命令：`/change <描述> [--account NAME] [--emergency]`（开单并立即审核）、`/changes [STATUS]`（列表）、`/approve <plan_id|C<id>> [理由]`（fix 计划或变更单，变更理由必填）、`/reject C<id> <理由>`、`/execute <plan_id|C<id>>`。actor 固定为 `cli:<os user>`，不再询问审批人名字。非 REPL 的 `aiops changes …` 子命令：**非目标**。
- **Web API** — 做。新路由 `web/routers/changes.py`（`/api/changes` 全生命周期）+ `/api/plans/stats`（`web/routers/plans.py`）+ `/api/audit`、`/api/audit/entity/{type}/{id}`、`/api/audit/stats`、`/api/command-audits`（`web/routers/audit.py`）；FixPlan 端点加固（approve 取会话身份 + 可选 reason、新增 reject、`PUT` 不再收 `status`/`approved_by`、list 加 `kind` 筛选）；全局搜索加 `change_requests` 组。所有写端点过 `authz.check`。
- **Web UI** — 做。新页 `/app/plans`（`PlansAndChanges.tsx`，三个 tab：Fix Plans / Change Plans / Audit）+ `/app/changes/:id`（`ChangeDetail.tsx`，Stepper + 请求/审核/计划/审批/执行卡 + 时间线）；侧栏新增 `plans` 项（clipboard 图标）；`components/plans/` 抽出 13 个组件（Stepper、ReasonDialog、NewChangeDialog、AuditTab 等）；Dashboard「Active Plans」卡改为 fix+change 两类合并、按 `plan_kind` 显示 `C#N`/`I#N` 徽标并点击跳到对应详情页；Audit tab 渲染决策/命令两本账 + `/api/plans/stats` 统计（KPI + 图表 + 账本表）；旧界面（IssueDetail、Chat 内 FixPlanCard）审批改走 `ReasonDialog`，未认证时可填 claimed-approver（仅记 `details.claimed_name`，绝不进 `approved_by`）。全部随 Plan C Task 1–6 落地（本地提交，含 `6cb61cc`）。`C#N` 在聊天渲染中自动链接到 `/app/changes/N`。
- **Agent tool** — 做。Main 智能体（仅在 `change_management_enabled` 时注入，与提示词同步）：`request_change` / `review_change` / `get_change_request` / `list_change_requests` / `execute_change`（前四个在 `tools/change_tools.py`，`review_change` 来自 SRE）。SRE 智能体：`ground_change_targets` / `attach_change_target` / `evaluate_change_policy` / `submit_change_review` + `save_fix_plan(plan_kind="change", change_request_id=…)`，经新入口 `sre_agent_review_change` 以 agents-as-tools 暴露给 Main。审批/拒绝**不是** agent 能做的动作。
- **Schedule** — **非目标**。「变更窗口在 T 时刻执行一次」不做（Scheduler 今天只有 `@once` 立即执行）；`change_requests` 表不预留 window 列（未来是 ADD COLUMN 级小事）。
- **Notification** — 做。三个通知点：`change_requested`、`change_pending_approval`（正文含风险、计划摘要、深链 `{web_base_url}/app/changes/{id}`）、`change_result`。severity 由风险映射（未定级 medium，L0/L1 low，L2 medium，L3 high，`failed`/`rolled_back` 一律 high）。IM 审批卡片：**非目标**（P3）。
- **Webhook**（第七面，明确列出）— **非目标**。GitHub push → 部署变更留给 P2；P1 仅预留 `change_requests.source` 的 `webhook` 枚举值与统一入口 `change_service.create_change_request(source, actor, …)`。

## 架构与数据流

```
入口   Chat(Web SSE / CLI "/change")   Web 表单 POST /api/changes   [P2 Webhook]   [P3 IM]
  └─ change_service.create_change_request(source, actor, …)   [代码] authz change.request · CR=draft · audit change.requested · notify
       └─ start_review(sync)                                   CR=under_review · 看门狗 change_review_timeout_seconds
            └─ sre_agent  Mode C（只读）
                 ├─ ground/attach 目标      [代码, fail-closed] 目标必须落库存或经代码只读 describe 实证，否则不出计划
                 ├─ 风险 L0–L3 + action_type [LLM 判定，量表同 fix]
                 ├─ evaluate_change_policy  [代码] policy_engine(plan_kind=change, emergency, action_type, 冻结, 爆炸半径)
                 ├─ save_fix_plan(change)   [代码强制 rollback_plan + post_checks 非空]
                 └─ submit_change_review    [代码写状态；策略在此重评，以代码结果为准]
                      ├─ rejected / needs_clarification → audit + notify
                      └─ planned →  policy=auto_approve ∧ change_auto_approve_standard ?
                                     自动审批(agent:auto-pipeline，记规则名) → 入队
                                   : plan=pending_approval · notify(深链)
                                        └─ 人工审批 Web/CLI [authz change.approve + SoD · 理由必填 · audit] → plan=approved · CR=approved
                                             └─ request_execution → FixExecution(pending) → ExecutorService 队列
                                                  └─ executor_agent(fix_plan_id)  [不改；get_approved_fix_plan 门不改]
                                                       └─ on_execution_result  [代码终态映射器，唯一写 CR 终态处]
                                                            completed | needs_review | failed | rolled_back → audit + notify

命令账本   run_aws_cli / run_on_host / run_kubectl / run_skill_script
             └─ command_audit.record_command(...)  ← Run Context(actor, fix_plan_id, change_request_id, trace_id, agent)
             └─ 命中 policies.yaml change_required 且无已审批计划上下文 → 拒绝(outcome=refused) 并提示 "/change"
```

三条不变量（对齐 Trust Kernel）：**CR 终态只由 `on_execution_result` 写**；**任何目标资源不可实证则不出计划**；**自动审批必须同时满足 yaml 规则与 settings 开关**。

## Plan 统一（plan_kind）与 change_requests 工单

- `fix_plans` 加 `plan_kind String(10) default "fix"`、`change_request_id FK`、`rejected_by/rejected_at/rejection_reason`、`updated_at`；`health_issue_id`/`rca_result_id` 改可空。
- CHECK 约束 `ck_fix_plans_origin` 强制二选一来源：`plan_kind='fix'` 必须有 issue+rca 且无 CR，`plan_kind='change'` 必须有 CR 且无 issue/rca。数据库层杜绝“既是修复又是变更”的畸形行。
- 新表 `change_requests`：工单（title/description/justification/source/requested_by/account_id/target_hints/target_resources/requested_change_type/effective_change_type/risk_level/action_type/status/review_*/policy_*/approved_*/rejected_*/closed_at/trace_id/chat_session_id）。`target_resources` 只装 grounding 通过、带 `evidence` 的资源。
- `review_attempt` 计数键住所有回滚（看门狗/worker 无结论/崩溃/stale 恢复都以 `(status='under_review', review_attempt=发起它的那次)` 为条件更新），迟到的回滚对下一次评审是 0 行 no-op。

## Change 状态机（12 态）与 Plan 状态机

两个代码级校验器，与既有 `validate_status_transition` 同形（非法 → `InvalidStatusTransition`，API 层 409）：

```
CHANGE_TRANSITIONS
  draft               → under_review, cancelled
  under_review        → planned, needs_clarification, rejected, draft(看门狗回退)
  needs_clarification → under_review, cancelled
  planned             → approved, rejected, cancelled
  approved            → executing, cancelled
  executing           → completed, failed, rolled_back, needs_review
  needs_review        → completed, failed          # 人工裁定；重跑 = 新建变更单
  completed / failed / rolled_back / rejected / cancelled → 终态

PLAN_TRANSITIONS
  draft               → pending_approval, approved, rejected
  pending_approval    → approved, rejected
  approved            → executing, rejected        # rejected 于 approved = 执行前撤回
  executing           → executed, failed
  executed / failed / rejected → 终态
```

`transition_change` / `transition_plan` 在应用状态时顺手 stamp `updated_at`（终态再 stamp `closed_at`）。所有状态变更走 `UPDATE … WHERE id=:id AND status=:expected` + rowcount 校验，防并发双批/双执。

## SRE 合法性审核（Mode C）

SRE 智能体新增 **MODE C — CHANGE REVIEW PROTOCOL**（六步，仍然只读）：目标 grounding（不可实证 → `needs_clarification`，安全侧失败）→ 风险 L0–L3 + action_type → 策略判定 → 出计划（`rollback_plan` 与 `post_checks` 必填，否则 `submit_change_review` 返回 409，LLM 无法绕过）→ 提交结论（代码在此**重新**跑一次策略，以代码结果为准，`block` 强制 rejected）。Mode A / Mode B 与全部既有 guardrails 不变。

## RBAC 影子模式与审批人身份绑定

- 单一 `authz.check(actor, permission, subject=…)`，actor 来自认证会话而非请求体；`config/rbac.yaml` 把权限项映射到既有 `users.permissions`（`read`/`write`/`admin`），不建 Role 表。
- **影子模式**（`rbac_enforce=false`，默认）：照常判定，拒绝只写 `audit_logs(authz.denied_shadow)` 并放行 —— 行为与今天完全一致；`true` 时抛 403。
- Actor 六种来源：`user:<email>`（认证开）/ `web:anonymous`（认证关，全权，等价今天）/ `cli:<user>` / `agent:<name>` / `im:…`（P1 到 chat_id）/ `webhook:…`（P2）。
- 结构化规则（见 `config/rbac.yaml`）三类：`approver_must_differ_from_field`（审批人不得等于申请人）；`actor_must_match_field_unless_admin`（只有申请人或 admin 可 `change.cancel`/`change.clarify`）；带 `enforce: always` 的 `no-agent-approval-above-l1`（agent 不得审批 L2/L3，**影子模式下也生效**，且该权限缺 subject 时 fail-closed）。匿名 web actor 跳过需要身份的规则（认证关时 SoD 无意义）。
- 审批人绑定：`/api/fix-plans/{id}/approve` 与 `/api/changes/{id}/approve` 一律取 Run Context 的 actor 写入 `approved_by`；认证关闭时请求体里的名字只作 `details.claimed_name` 记入审计，进不了 `approved_by`。

## 两本账（审计）与统计

- **决策账本 `audit_logs`**（新增 `actor` 列）：所有人工/自动决策（requested/reviewed/approved/rejected/execution_started/completed/failed/…、`authz.denied` / `authz.denied_shadow`）与状态变更**同事务**写入 —— 审计写失败则一起回滚，状态不变。
- **命令账本 `command_audits`**（新表）：工具层每条写级命令（`run_aws_cli` / `run_on_host` / `run_kubectl` / `run_skill_script`），记 tier / outcome（executed/refused/blocked/error）/ 脱敏后的命令 / actor / fix_plan_id / change_request_id / trace_id。只读命令不记录。**fail-soft**（异常只 debug，永不影响工具返回）。命中 `policies.yaml` `change_required` 且 Run Context 无已审批计划 → 拒绝（`outcome=refused`）并提示走 `/change`。
- **统计** `GET /api/plans/stats`（`services/plan_stats_service.py`，纯聚合）：`totals.by_kind_status`、`approvals`（auto/human/rejected/authz_denied/authz_denied_shadow）、`lead_time`（p50/p90）、`outcomes`（success_rate/rollbacks/needs_review）、`breakdown`（by_actor/risk/change_type/action_type/account）、`series`（分桶时序）、`commands`（by_outcome/by_tool）。Web UI 的 Audit tab 渲染之。

## 配置（`config/settings.yaml`；`config.py` 只定义 schema）

| 键 | 默认 | 说明 |
|---|---|---|
| `change_management_enabled` | `true` | 总开关：关闭时 Main 不注入变更工具、`/api/changes` 404、CLI 斜杠命令提示未启用、Web UI 的 Changes tab 隐藏。fix 流与审计加固仍生效 |
| `change_auto_approve_standard` | `false` | 策略为 auto_approve 的 standard 变更是否免人工审批；必须与 yaml 规则**同时**满足才自动 |
| `change_review_timeout_seconds` | `600` | SRE 审核看门狗；超时 CR 回退 draft + `review_failed` 事件 + notify |
| `rbac_enforce` | `false` | false = 影子模式（判定 + `authz.denied_shadow` 审计，放行）；true = 403 + SoD |
| `rbac_file` | `config/rbac.yaml` | 权限矩阵 + 内置主体 + 结构化 SoD 规则 |
| `command_audit_enabled` | `true` | 工具层写级命令账本 |
| `audit_retention_days` | `365` | `audit_logs` 与 `command_audits` 每日清理（0 = 永久保留） |

`config/policies.yaml` 追加 `change_required:` 段与 `plan_kind` / `action_type` / `emergency` 三个 match 字段（现有 fix 流规则行为不变）。Web Settings 页在既有 pipeline 开关卡加 `change_auto_approve_standard`、`rbac_enforce` 两个开关（写回 YAML）。

## 迁移

- 新增列 + `audit_logs.actor` 走既有幂等 `ALTER TABLE ADD COLUMN`；新表由 `create_all` 建。迁移在 `init_db()` 里 `create_all` 之后调 `_migrate_2_6_0(engine)`，进程内按 DB URL 幂等一次。
- NOT NULL→NULL 与 CHECK（fix_plans / fix_executions / pipeline_events）：SQLite 走官方 12 步表重建 `_sqlite_rebuild_table`（`PRAGMA foreign_keys=OFF` → 建新表 → 拷数据 → 换名 → 重建索引 → `foreign_key_check`），重建前把库复制为 `<db>.bak-pre-2.6.0`（仅首次）；PostgreSQL 走 `ALTER … DROP NOT NULL` + `ADD CONSTRAINT`。迁移失败即抛出、进程不启动。

## 验收标准（对照设计 §8；E2E 待真实账户验证）

1. 一个自然语言变更请求从 Chat 到 completed 全程不需要 HealthIssue；该计划 `plan_kind=change`、`health_issue_id IS NULL`。
2. 在 CR 进入 approved 之前，该 trace 的 `command_audits` 没有 `outcome=executed` 的写命令。
3. `approved_by` 等于认证 actor，客户端无法经请求体指定；`rbac_enforce=true` 时申请人自批 403、agent 批 L2/L3 403。
4. CR `completed` 仅在 post_checks 全部通过时出现；缺结果 → `needs_review`。
5. `audit_logs` 中每个 CR 生命周期 ≥ 5 条决策记录且 `actor` 非空；fix 流人工审批同样入账。
6. `GET /api/plans/stats` 的 `totals.by_kind_status` 与数据库直接聚合一致。
7. 旧 SQLite 库经 `init_db` 迁移后数据零丢失，现有全量测试通过。
8. `change_management_enabled=false` 时现有 fix 流行为与 2.5.0 一致。

> **验收状态**：1–8 的代码路径已实现并有单元/API/pipeline/迁移测试覆盖；**真实账户 live E2E（设计 §7 七步：Chat 加/删 tag → 审批 → Executor `describe-tags` 实证 → completed；`change_required` 拒绝；`rbac_enforce=true` 自批 403）尚未进行**。依主人铁律，E2E 通过 + 当面确认后才 push，届时把证据写入 `docs/MVP-2.6.0-E2E-REPORT.md` 并回填测量数字。

## 明确不做（P1 边界）

- Schedule 变更窗口（Scheduler 只有 `@once`）；IM 审批卡片与 IM 发送者身份落库（P3）；`POST /api/webhooks/change/{source}`（P2）；Runbook 参数化模板库（P2）；逐步交互执行 / Chat 内审批卡 / HITL 接线（P3）；Role 表与用户角色管理 UI；SecurityRecommendation → Change（`source` 是字符串列，日后加值即可）；ITSM bridge 对 Change 的映射；非 REPL 的 `aiops changes …` 子命令。

## Future（后续期）

1. P2：Runbook 模板库 + Webhook（GitHub push → 部署变更，HMAC 校验）。
2. P3：逐步交互执行 + IM 审批卡片 + IM open_id 身份（收紧 SoD 粒度）。
3. 两条执行路线（fix 的线程路线 vs change 的队列路线）统一 —— 留给 Harness Phase 2。
4. `on_execution_result` 收编为 Trust Kernel 的 VerifyGate。
5. Role 表与角色管理 UI（如果影子模式实践证明需要更细的权限模型）。
