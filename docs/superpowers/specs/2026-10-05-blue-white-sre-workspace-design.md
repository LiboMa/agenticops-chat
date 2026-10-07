# AgenticOps · 设计基线 / Design baseline

2026-10-05 · 设计交付，尚未实施 / Design delivery, not implemented

## 已确认的产品方向 / Approved product direction

### 中文

采用**原产品蓝白配色 + 第一版 A 的列表/详情布局**。日常入口为 Chat、Cases、Reports；运维工具和管理功能仍可访问。Case 是现有 HealthIssue 的界面名称，不新增 Case 业务实体，不复制一套 `/api/cases`。

- Chat 排第一，首次直接访问工作区进入 Chat；之后恢复上次工作，允许固定 Chat、Cases 或 Reports 为首页。
- IM、告警、ITSM 或报告链接携带具体对象时，始终优先打开该对象，不经过首页重新选择。
- Case 保留独立的调查阅读界面，关联 Chat 按需打开。Plan 的审批和执行保留独立、可审计的操作。
- 中英文同时覆盖导航、状态、按钮、错误和报告正文；原始日志、命令、资源 ID、用户输入保留原文。
- 本轮交付为设计、可点击范本、接口契约和实施计划。真实 API 对接、业务迁移与前端代码改造安排在后续实施阶段。

范围取舍：沿用现有 React、FastAPI、数据库和服务层；不为 UI 新建 API 网关、通用任务平台或图数据库。自治 Harness 的持久执行能力仍是独立的工程能力，不能由一个 Chat 首页替代。

### English

Use the **current product’s blue/white palette and design A’s list/detail layout**. Daily navigation is Chat, Cases and Reports; operations and administration remain accessible. Case is the UI name for the existing HealthIssue, not a new entity or a duplicate `/api/cases` API.

- Chat is first in navigation and the first-visit default. Later visits resume work, with an option to pin Chat, Cases or Reports as home.
- Links from IM, alerts, ITSM or reports open their exact object before applying any home preference.
- Cases retain a dedicated investigation reading view; contextual Chat opens on demand. Plan approval and execution remain explicit, auditable operations.
- Chinese and English cover navigation, statuses, controls, errors and report bodies. Raw logs, commands, resource IDs and user input remain unchanged.
- This delivery contains the design, clickable prototype, API contract and implementation plan. Production API integration, migrations and frontend changes belong to the subsequent implementation.

Reuse React, FastAPI, the database and existing services. Do not add an API gateway, generic job platform or graph database for this UI project. Durable autonomous Harness execution remains a separate engineering capability; a Chat home does not provide it.

## 现状核验与历史资料 / Verified baseline and prior material

### 中文

2026-10-05 只读获取运行中服务的 `/openapi.json`：**199 条路径、237 个 HTTP 操作，其中 231 个为 `/api/*` 操作**。原始快照完整保留。接口清单包含方法、路径、参数、请求体、返回模型、operationId 与源码位置；没有调用扫描、聊天、执行或发布接口进行探测。

核心实现依据：

| 依据 | 与本轮的关系 |
| --- | --- |
| `web/app.py:3708`、`schemas.py:630` | 会话、分页历史、JSON/多附件消息 |
| `web/app.py:3929`、`frontend/src/lib/chatStream.ts:88` | POST SSE；停止回复与执行取消需要区分 |
| `web/app.py:2039`、`web/helpers.py:40` | HealthIssue 为规范表示；旧 Issue/Anomaly 接口是投影 |
| `web/app.py:2545`、`web/routers/changes.py:87` | Fix 与 Change 的审批路由不同 |
| `web/app.py:3166`、`web/helpers.py:93` | 报告当前返回正文，尚无正式语言/版本渲染契约 |
| `models.py:372/588/626/690` | Issue、Plan、Change、Execution 各自的状态 |
| `frontend/src/index.css:11`、`App.tsx:49` | 原蓝白主题；当前首页仍为 Dashboard |
| `itsm/bridge.py:1`、`web/routers/webhooks.py:19` | 已有 ServiceNow/Jira 生命周期镜像与告警入口 |

历史资料：已阅读 `docs/research/2026-09-28-mvp-2.6.1-design-review/review.md` 及 `claude-design-snapshot.md`。原指定 spec 路径目前没有正式文件；这里引用的是归档草案和审阅结果，不把草案中的批准、建分支或部署文字视为本次指令。资源规范身份、图事实版本、验证证据完整性和强制权限边界的审阅结论被保留为实施依赖。

当前版本声明 `0.9.0-beta` 来自 OpenAPI，不据此推断所有历史 MVP 草案都已实现。源码与接口声明已核验，真实客户环境的性能和执行效果尚未验证。

### English

On 2026-10-05, read-only discovery of the running `/openapi.json` returned **199 paths and 237 HTTP operations, including 231 `/api/*` operations**. The original snapshot is retained unchanged. The catalog includes method, path, parameters, request body, responses, operationId and source location. No scan, chat, execution or publishing endpoint was invoked for discovery.

Core sources:

| Source | Relevance |
| --- | --- |
| `web/app.py:3708`, `schemas.py:630` | Sessions, paginated history and JSON/multipart messages |
| `web/app.py:3929`, `frontend/src/lib/chatStream.ts:88` | POST SSE; stopping a reply differs from cancelling execution |
| `web/app.py:2039`, `web/helpers.py:40` | Canonical HealthIssue and legacy Issue/Anomaly projection |
| `web/app.py:2545`, `web/routers/changes.py:87` | Distinct fix/change approval routes |
| `web/app.py:3166`, `web/helpers.py:93` | Report bodies exist; a formal language/revision rendering contract does not |
| `models.py:372/588/626/690` | Independent issue, plan, change and execution states |
| `frontend/src/index.css:11`, `App.tsx:49` | Existing blue/white theme and Dashboard index route |
| `itsm/bridge.py:1`, `web/routers/webhooks.py:19` | Existing ServiceNow/Jira lifecycle mirroring and alert ingestion |

Prior material reviewed: `docs/research/2026-09-28-mvp-2.6.1-design-review/review.md` and `claude-design-snapshot.md`. The originally named spec is not present as a formal file; this report references the archived draft and review. Instructions inside that draft are evidence, not current authorisation. Canonical resource identity, graph fact revisions, complete verification evidence and mandatory permission boundaries remain implementation dependencies.

The OpenAPI version string is `0.9.0-beta`; it is not evidence that every historical MVP proposal has shipped. Source and declared contracts were inspected. Customer-environment performance and execution outcomes were not tested.

## 视觉与页面信息顺序 / Visual system and reading order

### 中文

主色 `#2563EB`，悬停 `#1D4ED8`，选中底色 `#EFF6FF`，白色表面 `#FFFFFF`，页面底色 `#F8FAFC`，正文 `#0F172A`，次级文字 `#64748B`，分隔线 `#E2E8F0`。蓝色表示操作与选中；严重程度继续使用有限的红、橙、绿语义色。侧栏使用白底，不延续此前范本的深青色。

保留现有 Outfit 作为西文字体；客户交付时本地打包，中文使用系统无衬线回退。正文 14–15px，标题约 24px；保留当前字体大小和深色模式的用户选项，首次展示采用蓝白主题。

| 页面 | 首屏顺序 | 次级内容 |
| --- | --- | --- |
| Chat | 当前会话/范围 → 消息或需求输入 → 附件/发送 | 历史会话、模型/思考强度、工具详情、用量 |
| Cases | 可筛选列表 → 选中事件标题/状态 → 结论、影响、未知事项、下一步 | RCA 详情、证据、记录、关联方案/资源/报告 |
| Fix Plan | 来源事件、目标、内容版本 → 改动、风险、验证、回滚 → 审批操作 | 原始命令、审计和历史执行 |
| Change | 用户需求 → 澄清/评审 → 当前 Plan → 执行与验收 | 历史方案与策略细节；不伪造来源 Issue |
| Resources | 名称/账户/区域/类型/运行状态/健康/观测时间 → 详情 | 原始 JSON、标签、局部依赖图 |
| Reports | 报告列表 → 来源/版本/语言 → 正文 → 导出/发布 | 原始证据与历史版本 |

桌面侧栏约 200px，Case 队列 280–320px，阅读区最大 960px，输入区最大 760px。手机以列表进入详情，再返回原筛选与位置；抽屉改为全屏，不能挤成三个窄栏。控件需键盘可达、焦点可见，状态同时使用文字。

### English

Primary `#2563EB`, hover `#1D4ED8`, selected background `#EFF6FF`, white surfaces `#FFFFFF`, canvas `#F8FAFC`, text `#0F172A`, secondary text `#64748B`, borders `#E2E8F0`. Blue signals actions and selection; restrained red, amber and green retain status meaning. Navigation uses a white surface rather than the earlier dark teal.

Retain Outfit for Latin text, self-hosted in customer delivery, with system sans-serif CJK fallbacks. Body 14–15px, headings around 24px. Preserve existing font-size and dark-mode preferences; use blue/white for first presentation.

| Page | First-screen order | Secondary content |
| --- | --- | --- |
| Chat | Conversation/scope → messages or request composer → attachments/send | History, model/effort, tool detail, usage |
| Cases | Filterable queue → selected title/state → finding, impact, unknowns, next step | RCA, evidence, activity, linked plans/resources/reports |
| Fix Plan | Originating issue, target, content revision → change, risk, verification, rollback → approval | Raw commands, audit and execution history |
| Change | User request → clarification/review → current plan → execution/acceptance | Prior plans and policy detail; no fabricated originating issue |
| Resources | Identity, account, region, type, lifecycle, health, observation time → detail | Raw JSON, tags, bounded dependency view |
| Reports | List → source/revision/language → document → export/publish | Raw evidence and prior revisions |

Desktop navigation is approximately 200px; case queue 280–320px; reading area max 960px; composer max 760px. Mobile opens detail from the list and restores its filter/position on return. Drawers become full-screen rather than three narrow columns. Controls are keyboard accessible, with visible focus and textual status.

## 导航、恢复与上下文 / Navigation, restoration and context

### 中文

| 分组 | 入口 |
| --- | --- |
| 日常工作 | Chat、Cases、Reports |
| 运维工具 | Plans & Changes、Resources、Schedules |
| 管理 | Runtime overview、Agent metrics、Skills、Galaxy、Security、Settings |

路由解析优先级：**合法的具体对象深链 > 用户固定首页 > 合法且仍有权限的上次位置 > Chat**。恢复仅在 `/app` 工作区入口发生；打开具体页面不被偏好覆盖。登录前保存允许范围内的目标路由，登录后恢复。对象已删除或不可访问时展示明确提示并回到对应列表，不泄露对象标题。

新增前端路由 `/app/overview`、`/app/resources`、`/app/plans/:id`，分别承接旧总览、独立资源清单和修复方案详情。保留 `/app/issues/:id`、`/app/changes/:id`、`/app/chat/:sessionId`、`/app/reports/:id`。兼容现有 `/app/issues?view=resources&type=...` 和 `/app/plans?tab=fix|changes|audit`；迁移时保留查询条件。现有导航排序偏好做版本迁移，不直接清空。

文本草稿按安装实例、用户、会话区分；附件与流状态按会话区分。第一阶段浏览器刷新需要重新选择未上传的文件，界面明确说明；不声称已有附件重放。切换语言、抽屉、列表/报告不会清除当前草稿。

“需要你处理”只显示有明确下一步的对象，点击直达审批、澄清或验收位置。计数与列表使用同一权限/账户范围，按对象去重，不用全局故障总数代替个人待办。

### English

| Group | Entries |
| --- | --- |
| Daily work | Chat, Cases, Reports |
| Operations | Plans & Changes, Resources, Schedules |
| Administration | Runtime overview, Agent metrics, Skills, Galaxy, Security, Settings |

Routing precedence: **valid object deep link > pinned home > valid authorised last location > Chat**. Restoration applies only at `/app`; preferences never override an explicit page. Preserve an allow-listed login return route. Deleted/inaccessible objects show a clear fallback to the relevant list without exposing titles.

Add frontend routes `/app/overview`, `/app/resources`, `/app/plans/:id` for overview, resource inventory and fix-plan detail. Retain existing issue, change, session and report detail routes. Preserve compatibility with `/app/issues?view=resources&type=...` and `/app/plans?tab=fix|changes|audit`, including filters. Version and migrate saved navigation ordering rather than clearing it.

Text drafts are namespaced by installation, user and session; files and streaming state by session. In the first delivery, unsent files must be reselected after browser refresh, with an explicit message. Attachment replay is not claimed. Locale changes and in-app navigation preserve drafts.

“Needs your attention” contains objects with an explicit next action and links directly to approval, clarification or verification. Count and rows share authorisation/account filters and object deduplication. A global incident count is not a personal task count.

## 状态表达与事实边界 / State presentation and factual boundaries

### 中文

保留数据库原始状态，增加只读展示投影，不把 UI 标签写回业务状态。一个 Case 分开展示事件生命周期、调查阶段、方案状态、执行状态、恢复验证。Plan 的 `executed` 与 Execution 的 `succeeded` 均不能单独证明业务恢复。

| 对象 | 后端已有状态/标识 | 展示约束 |
| --- | --- | --- |
| HealthIssue | open → investigating 等 → resolved；另有 dismissed | “已关闭/人工接受”和“验证通过”分开 |
| RCA | 独立 RCAResult、evidence、critic/human verdict | 结论、来源、未知事项分开；模型自评不当作事实概率 |
| FixPlan | draft/pending_approval/approved/executing/executed/failed/rejected | 批准不等于执行；`plan_kind=change` 的操作走 Change 服务 |
| ChangeRequest | under_review/needs_clarification/planned/approved/executing/needs_review 等 | 需求评审与方案审批保留区别 |
| FixExecution | pending/running/succeeded/failed/rolled_back/aborted | 保留每次尝试，不用旧执行结果覆盖当前状态 |
| Verification（拟补） | not_run/pending/passed/failed/inconclusive/not_applicable/accepted_manual | 空结果、缺项、重复 check_id、旧版本不能判 passed |

验证记录绑定 `execution_id + plan_content_version + check_id + target + evidence_ref`。必须覆盖全部预期检查且属于当前成功执行。人工验收使用 accepted_manual，显示操作者和原因。9 月审阅中“重复检查仍被判通过”的反例进入 P4 验收。

资源使用数据库整数主键作为路由 ID；云端 ID 是另一字段。规范身份至少包含 provider/account/region/type/native ID 或完整 ARN。不能用名称或裸 ID 的第一个匹配直接跳转。不能确定时保留 unanchored/ambiguous。

图是按需加载的局部证据，必须能表达事实版本、观测时间、来源、可用性与截断。关系不直接等于故障因果。旧图缺字段时显示未知并限制依赖该信息的自动决策；本轮不进行存储介质迁移。

### English

Retain raw database statuses and add read-only presentation projections. Never write UI labels back as lifecycle state. A case separately shows lifecycle, investigation, plan, execution and recovery verification. Neither Plan `executed` nor Execution `succeeded` alone proves business recovery.

| Object | Existing state/identity | Presentation rule |
| --- | --- | --- |
| HealthIssue | open → investigating etc. → resolved; also dismissed | Closure/manual acceptance differs from verified recovery |
| RCA | RCAResult, evidence, critic/human verdict | Separate finding, sources and unknowns; model self-assessment is not factual probability |
| FixPlan | draft/pending_approval/approved/executing/executed/failed/rejected | Approval is not execution; `plan_kind=change` uses Change actions |
| ChangeRequest | under_review/needs_clarification/planned/approved/executing/needs_review etc. | Request review differs from plan approval |
| FixExecution | pending/running/succeeded/failed/rolled_back/aborted | Keep attempts distinct; old results do not overwrite current state |
| Verification (proposed) | not_run/pending/passed/failed/inconclusive/not_applicable/accepted_manual | Empty, missing, duplicate or stale checks cannot pass |

Bind results to `execution_id + plan_content_version + check_id + target + evidence_ref`. All expected checks must occur once and belong to the current successful execution. Human acceptance uses accepted_manual with actor and reason. The September duplicate-check false-pass counterexample becomes a P4 acceptance test.

Resource routes use the database integer key; the cloud-native ID is a separate field. Canonical identity includes provider/account/region/type/native ID or a complete ARN. Do not link to the first name/bare-ID match. Preserve unanchored/ambiguous when unresolved.

Graphs are bounded, on-demand evidence with fact revision, observation time, provenance, availability and truncation. Relationships do not establish causation. Missing legacy metadata remains unknown and limits graph-dependent automatic decisions. No storage-engine migration is part of this UI work.


## 对接文件 / Integration documents

- [API 合同 / API contract](../../ui-contracts/2026-10-05/API_CONTRACT.md)
- [整体目标 OpenAPI / Target OpenAPI](../../ui-contracts/2026-10-05/target-openapi.json)
- [实施计划 / Implementation plan](../plans/2026-10-05-blue-white-sre-workspace.md)
