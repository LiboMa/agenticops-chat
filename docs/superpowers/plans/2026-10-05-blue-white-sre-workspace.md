# AgenticOps · 实施计划 / Implementation plan

2026-10-05 · 设计交付，尚未实施 / Design delivery, not implemented

## 分阶段实施计划 / Phased implementation plan

### 中文

| 阶段 | 范围与主要文件 | 完成条件 | 依赖 |
| --- | --- | --- | --- |
| P0 基线 | 冻结 OpenAPI/源码指纹；确认旧链接与状态；生成契约类型；准备隔离样例 | 现有/扩展/新增一一对应；不连接云执行 | 无 |
| P1 外壳 | App.tsx、AppShell/NavItems、index.css、LocaleContext；新增 HomeResolver、偏好/能力接口 | 蓝白主题、三主入口、恢复/固定首页、登录回跳、旧链接正常 | P0 |
| P2 Chat | Chat.tsx、ChatComposer、chatStream.ts、useChatMessages/useSessionStream；会话上下文/身份/幂等扩展 | 独立与关联会话、真实多附件、流错误/中断、不重复提交、范围隔离 | P1 |
| P3 Cases/Resources | IssuesAndPlans、IssueDetail、ResourceDetail；新增 useHealthIssues 与只读适配器；notes/summary | 列表详情、真实证据/状态、资源身份歧义、完整保留操作入口 | P1，可与 P2 分支并行 |
| P4 Plans/Attention | PlansAndChanges、ChangeDetail、components/plans；版本/验证服务、条件写入和待办 | 版本过期拒绝、并发唯一执行、Fix/Change 正确路由、验证不可伪造 | P2/P3 的上下文与类型 |
| P5 Reports/双语 | Reports、ReportDetail、报告生成/发布；ContentRendering 与 export | zh/en/zh-en 同源版本；导出/打印；明确的真实发布确认 | P3/P4 内容版本 |
| P6 联合验收/发布 | API/前端测试、构建、客户同源部署、迁移与回退演练 | 所有验收通过，默认只读演练完成，目标环境写操作另行启用 | P1–P5 |

建议每阶段独立 PR，先交付可体验的外壳与只读页面，再开放写操作。后端接口与对应前端一起验收，避免一次全量重写。工作量与日历日期在 P0 基线测试后估算；本计划不以未测量的工期承诺替代依赖关系。

### English

| Phase | Scope and main files | Exit condition | Dependency |
| --- | --- | --- | --- |
| P0 Baseline | Freeze OpenAPI/source fingerprints, old links/states; derive types and isolated fixtures | Existing/extended/new mapping; no cloud execution | None |
| P1 Shell | App.tsx, AppShell/NavItems, index.css, LocaleContext; HomeResolver, preferences/capabilities | Blue/white, three primary entries, restore/pin home, login return, compatible links | P0 |
| P2 Chat | Chat.tsx, ChatComposer, chatStream.ts, history/stream hooks; context/identity/idempotency | Independent/context chats, real attachments, errors/interruption, no duplicate dispatch, scoped access | P1 |
| P3 Cases/Resources | IssuesAndPlans, IssueDetail, ResourceDetail; canonical hooks/read adapters; notes/summary | List/detail, real evidence/state, identity ambiguity, retained operations | P1; may branch in parallel with P2 |
| P4 Plans/Attention | PlansAndChanges, ChangeDetail, plan components; revision/verification services, conditional writes, attention | Stale revision rejection, one concurrent execution, correct fix/change routing, valid evidence checks | P2/P3 context and types |
| P5 Reports/languages | Reports, ReportDetail, generator/publisher; ContentRendering/export | Same-source zh/en/zh-en, export/print, explicit real publication | P3/P4 content revisions |
| P6 Integration/release | API/UI tests, build, customer same-origin deployment, migration/rollback rehearsal | Acceptance passes, read-only rehearsal, deliberate enablement of target-environment writes | P1–P5 |

Use one reviewable PR per phase. Deliver the shell and read views before opening write actions. Accept backend and corresponding UI together instead of a full rewrite. Estimate calendar effort after P0 baseline testing; this plan does not substitute an unmeasured deadline for dependencies.

## 可执行任务与验收 / Executable work items and acceptance

### 中文

| 任务 | 实施与验收要求 |
| --- | --- |
| P0.1 契约基线 | 重新导出 OpenAPI，与本次快照 diff；测试命令/环境记录在 PR；识别用户既有未提交修改 |
| P0.2 类型与样例 | 为 SSE、ResourcePage、HealthIssue、Change、版本渲染补类型；正常/空/失败/无权限样例不使用客户敏感数据 |
| P1.1 导航/路由 | 主入口与工具分组；保留全部已有模块；迁移拖动排序；覆盖首访、固定首页、恢复、404/403、登录深链 |
| P1.2 样式/i18n | 复用蓝白 token，统一间距、状态、焦点；中英文键完整；本地字体与已有字体大小设置 |
| P2.1 上下文 | DTO、数据库字段、服务端解析和工具 RunContext；自由需求不创建 Issue；不能跨账户借用上下文 |
| P2.2 生命周期 | 会话创建/改名/置顶/收藏/归档/删除仍可用；明确 private/workspace 可见性；旧会话迁移不任意归属 |
| P2.3 发送与文件 | 5 文件、类型/字节限制、粘贴/拖入/移除；JSON与multipart；非文本内容传给真实多模态通路 |
| P2.4 流与幂等 | UTF-8/跨包解析、401/429/5xx、断网、重复 client_message_id、会话并发、刷新中断；停止回复不显示云回滚成功 |
| P3.1 Cases | 从 Anomaly 类型迁移；筛选/分页/选择状态在 URL 中；最新 RCA 与执行按明确排序选取；原始证据按需加载 |
| P3.2 Resources | integer ref 与 native ID 分开；同名跨账户/区域/类型测试；无法锚定时显示候选，不跳第一个匹配 |
| P3.3 说明/状态 | 说明追加时间线；source/status/timestamp 保留；关闭/误报/反馈遵守现有服务语义与权限 |
| P4.1 版本迁移 | Plan 内容快照、scope hash、Execution 引用、稳定 check_id；旧不可证实结果保留 inconclusive |
| P4.2 决策操作 | 过期页面、双人并发、重复按钮、同 key 不同 body、auto-execute、Change旁路拒绝；校验必须在事务内 |
| P4.3 验收/待办 | 重复检查/缺项/旧结果/迟到回调/人工接受；待办计数与授权列表一致，终态后移除 |
| P5.1 渲染 | 源版本和受保护值指纹；缺翻译、失败、stale；双语共享引用，不触发再次调查 |
| P5.2 报告交付 | HTML/PDF/DOCX依能力；下载认证；版本和语言固定；发布失败/部分成功/幂等/目标确认 |
| P6.1 回归 | 现有 test_chat_api、test_changes_api、test_fix_plan_hardening_api、test_resource_detail_api 等按改动运行；新增契约/并发/验证测试 |
| P6.2 UI与部署 | npm test、npm run build；浏览器主流程、390/768/1280/1600宽度、键盘；反向代理SSE与深链；保留回退制品 |

未来新增文件建议：`web/routers/ui.py`、`web/routers/content.py`、`services/ui_read_service.py`、`services/content_rendering_service.py`、`services/plan_revision_service.py`、`services/verification_service.py`。这些是**拟新增**，不是当前已有模块。不要把新的页面逻辑继续堆入 21 万字节的 web/app.py。

完成定义：页面上每一个真实可点击操作都有接口、权限、版本和失败语义；未接入项明确禁用/说明。样式通过不能替代接口和执行结果验证。

### English

| Task | Implementation and acceptance |
| --- | --- |
| P0.1 Baseline | Re-export/diff OpenAPI; record test environment in PR; preserve existing user changes |
| P0.2 Types/fixtures | Type SSE, ResourcePage, HealthIssue, Change and renderings; normal/empty/error/denied fixtures without customer-sensitive data |
| P1.1 Navigation | Primary/tool groups, all modules retained, migrate ordering; first visit, pinned/resume home, 404/403, login deep link |
| P1.2 Style/i18n | Reuse blue/white tokens, spacing/status/focus, complete locale keys, local fonts and font-size preferences |
| P2.1 Context | DTO/storage/resolution/tool RunContext; independent request creates no Issue; no cross-account scope borrowing |
| P2.2 Lifecycle | Preserve create/rename/pin/star/archive/delete; explicit private/workspace visibility; deliberate legacy-session migration |
| P2.3 Files/send | Five files, types/byte caps, paste/drop/remove, JSON/multipart; real multimodal processing |
| P2.4 Stream/idempotency | UTF-8/chunks, 401/429/5xx, offline, duplicate client IDs, concurrent sessions, refresh interruption; stopping text does not imply cloud rollback |
| P3.1 Cases | Replace Anomaly view types, URL-backed filters/selection, explicit latest-result ordering, lazy evidence |
| P3.2 Resources | Integer reference versus native ID; same-name account/region/type collisions; show candidates rather than first-match links |
| P3.3 Notes/state | Attributed timeline notes and source/time preservation; existing service semantics and permissions for dismissal/feedback |
| P4.1 Revisions | Plan snapshots/scope hash, execution binding, stable check IDs; legacy unverifiable data is inconclusive |
| P4.2 Decisions | Stale pages, concurrent approvers, duplicate clicks, key/body conflict, auto-execute and Change bypass; transactional guards |
| P4.3 Verification/attention | Duplicate/missing/stale/late checks and manual acceptance; authorised counts match rows and remove terminal work |
| P5.1 Rendering | Source/protected-value fingerprints, missing/failed/stale translations, same evidence refs without another investigation |
| P5.2 Delivery | Capability-aware formats, authenticated download, pinned language/revision, failure/partial-success/idempotency/destination confirmation |
| P6.1 Regression | Relevant existing chat/change/fix-plan/resource API suites plus new contract/concurrency/verification tests |
| P6.2 UI/deployment | npm test/build; browser journeys at 390/768/1280/1600, keyboard, proxy SSE/deep links, retained rollback artifacts |

Proposed new modules: web/routers/ui.py, web/routers/content.py, services/ui_read_service.py, services/content_rendering_service.py, services/plan_revision_service.py and services/verification_service.py. These are **planned**, not existing. Avoid adding more page logic to the already large web/app.py.

Definition of done: every real enabled action has an API, permission, revision and failure contract. Unintegrated actions are explicit. Passing a visual review does not substitute for integration and execution-result validation.

## 客户环境部署与回退 / Customer deployment and rollback

### 中文

沿用当前同源部署：浏览器访问 `/app/*` 和 `/api/*`，React 构建进入现有 wheel/镜像的 frontend/dist，由 FastAPI 提供。客户反向代理负责 HTTPS、深链和流式转发；初期不拆前后端域名，也不要求客户安装新的数据库。

1. **部署基线**：复用现有容器/EC2 compose 路径，使用客户自己的配置与持久卷。静态字体本地打包。确认 `AIOPS_API_AUTH_ENABLED` 与 `AIOPS_RBAC_ENFORCE` 的有效值；源码默认值不代表客户实例当前值。
2. **启动模型**：现有会话 Agent、后台执行器、scheduler 和 ITSM bridge 存在进程内状态。第一阶段以单应用进程部署；不通过加多个 web worker 伪装扩容，以免重复调度和会话漂移。真正多副本/后台可恢复任务单独设计。
3. **兼容迁移**：先加可空字段/新表，再回填版本与权限数据，最后开 capability。Plan 旧内容可建立迁移快照，但没有执行绑定的历史检查不能回填为 passed。历史会话设为明确的 legacy shared 或经确认的所有者。
4. **隔离验证**：复制脱敏数据库或 fixtures，关闭会触发扫描/执行/外部通知的测试启动项。只读/演示模式验收；真实发送 IM、邮件、ITSM 写入和云变更不是本次文档验证的一部分。
5. **灰度**：按用户/部署 feature flag 开启新壳、Chat、Cases、Plans、Reports；错误率、SSE 中断、重复执行、权限拒绝、导出失败进入上线观测。
6. **回退**：保留旧前端构建与容器制品；关闭新 UI feature flag、恢复旧首页路由。数据库只使用向后兼容增加项，避免当天删列。若已产生新版本审批，不允许回退到会绕过版本保护的写接口；此时保留后端保护、回退 UI 为只读。

已有 ServiceNow/Jira bridge 是 best-effort 生命周期镜像，不等同于已验证的可靠双向审批系统。IM、监控 webhook 与 ITSM 凭据留在服务端。若客户要求可靠外部回调审批，需另行验收签名/防重放、外部身份映射、幂等与状态冲突；禁止浏览器直接连接 ServiceNow 并持有密钥。

UI 可先交付；客户写操作上线必须通过权限、方案版本和验证完整性门槛。Graph 身份/事实服务未满足审阅约束时，相关区块明确降级，不能展示“影响为零”并据此自动批准。

### English

Retain same-origin deployment: `/app/*` and `/api/*`, with the React build included in the current wheel/image frontend/dist and served by FastAPI. The customer reverse proxy handles HTTPS, deep links and streaming. No separate frontend domain or new database is required initially.

1. **Baseline:** reuse current container/EC2 compose delivery with customer configuration and persistent volumes. Bundle fonts locally. Verify effective API authentication and RBAC settings; source defaults do not reveal the customer runtime values.
2. **Process model:** session Agents, executor, scheduler and ITSM bridge have process-local state. Use one application process initially. Multiple web workers could duplicate scheduling or lose session affinity; real replicas/durable background work need a separate design.
3. **Compatible migration:** add nullable fields/tables, backfill revisions/access data, then advertise capability. Snapshot legacy plan content, but never mark unbound historical checks passed. Classify legacy sessions explicitly as shared or with a confirmed owner.
4. **Isolation:** use redacted database copies/fixtures and disable test-startup scan/execution/notification triggers. Validate read/demo mode. Real IM/email/ITSM/cloud writes are not part of this document’s verification.
5. **Rollout:** enable shell/Chat/Cases/Plans/Reports by user/deployment flags; observe errors, stream interruption, duplicate execution, denials and export failures.
6. **Rollback:** retain the old frontend build/image and disable new UI flags. Keep schema additions backward-compatible. If new revision-bound approvals exist, do not roll back to unguarded writes: retain backend protection and fall back to a read-only UI.

The existing ServiceNow/Jira bridge is best-effort lifecycle mirroring, not proof of reliable bidirectional approval. IM, webhook and ITSM credentials stay server-side. Reliable external approval requires separate signature/replay protection, identity mapping, idempotency and conflict acceptance. Browsers never connect directly with connector secrets.

UI delivery may proceed before customer writes are enabled. Write release requires identity, revision and verification gates. Where graph identity/facts do not meet the prior review requirements, show explicit degradation rather than zero impact and automatic approval.

## 交接与后续执行顺序 / Handoff and execution sequence

### 中文

后续从 **P0 → P1** 开始：先确认最新代码/契约差异，再落地蓝白外壳和导航。随后先接只读 Cases/Resources 与已有 Chat 基础流，按 P2/P3 完成上下文和状态契约，再开放 P4 决策操作，最后完成 P5 双语报告交付。P2/P3 可独立分支推进，写操作必须等待共同依赖。

本次文件：

- `ui-refinement.html`：蓝白版可点击范本；所有对话/审批/发布仍是本地演示。
- `implementation-review.html`：中英文切换的综合审阅报告，含 API 搜索目录。
- `DESIGN.md`、`API_CONTRACT.md`、`IMPLEMENTATION_PLAN.md`：双语可版本管理文档。
- `api/existing-openapi.json`：原始服务快照。
- `api/target-openapi.json`：整体目标合同；`proposed-delta.openapi.json` 仅包含 45 个拟变更操作。
- `api/endpoint-catalog.json`、`change-register.json`、`state-mapping.json`、`design-tokens.json`：机器可读对接依据。

验证分界：本次检查范本交互、双语/响应式布局、OpenAPI 内部引用和契约样例。**没有对尚未实现的接口声称集成测试通过。** 真实产品运行代码、业务数据库和云环境不在本轮修改范围内。

协议依据：OpenAPI 3.1.0 官方规范；MDN 的 SSE 帧与 If-Match/412 说明。本文对 POST SSE 的实现以现有 fetch-stream 源码为准，不误用只适合 GET 的浏览器 EventSource 发送带附件消息。

### English

Start implementation with **P0 → P1**: reconcile the latest code/contract, then implement the blue/white shell and navigation. Connect read-only Cases/Resources and existing Chat streaming, finish P2/P3 context/state contracts, open P4 decisions, then deliver P5 bilingual reporting. P2/P3 may branch independently; writes wait for shared prerequisites.

Deliverables:

- ui-refinement.html: clickable blue/white prototype; Chat, approval and publication remain local demos.
- implementation-review.html: language-switchable integrated report with a searchable API catalog.
- DESIGN.md, API_CONTRACT.md, IMPLEMENTATION_PLAN.md: bilingual version-controlled documents.
- api/existing-openapi.json: unchanged live snapshot.
- api/target-openapi.json: full target contract; proposed-delta.openapi.json contains the 45 changed operations only.
- endpoint-catalog.json, change-register.json, state-mapping.json and design-tokens.json: machine-readable implementation inputs.

Verification boundary: prototype interactions, bilingual/responsive rendering, OpenAPI internal references and contract examples. **Unimplemented APIs are not claimed to have passed integration tests.** No production runtime code, business database or cloud environment is changed in this delivery.

Protocol references: OpenAPI 3.1.0 and MDN’s SSE framing and If-Match/412 documentation. POST SSE implementation follows the existing fetch-stream source; browser EventSource is not used to send multipart POST messages.


## 实施依据 / Implementation inputs

- [Design](../specs/2026-10-05-blue-white-sre-workspace-design.md)
- [API contract](../../ui-contracts/2026-10-05/API_CONTRACT.md)
- [Target OpenAPI](../../ui-contracts/2026-10-05/target-openapi.json)
