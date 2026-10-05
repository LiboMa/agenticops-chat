# AgenticOps · API 对接契约 / API integration contract

2026-10-05 · 设计交付，尚未实施 / Design delivery, not implemented

## 现有接口对接矩阵 / Existing API integration matrix

### 中文

**以已有接口为主体，补齐少量读取和版本契约。** 完整 231 个 API 操作见接口目录与原始 OpenAPI；以下是新界面的主要调用链。路径中的 ID 类型以 OpenAPI 为准，不能把范本中的 `I-2401/P-126` 字符串直接作为真实主键发送。

| 能力 | 已有方法与路径 | 调用约定 |
| --- | --- | --- |
| 登录/用户 | POST `/api/auth/login`；GET `/api/users/me` | 登录字段为 email/password；复用 Bearer，账号输入可以是当前系统支持的 admin |
| 会话管理 | GET/POST `/api/chat/sessions`；GET/PATCH/DELETE `/api/chat/sessions/{session_id}` | session_id 为 UUID 字符串，不是会话表整数 ID |
| 历史与发送 | GET/POST `/api/chat/sessions/{session_id}/messages` | GET 返回 messages/has_more/next_cursor；POST 返回 SSE |
| Cases | GET `/api/health-issues`、`/{issue_id}` | 返回 HealthIssue；旧 `/api/issues`、`/api/anomalies` 兼容保留 |
| RCA/方案生成 | GET/POST `/api/health-issues/{issue_id}/rca`；POST `/{issue_id}/generate-fix-plan` | GET RCA 是列表；生成请求不等于完成 |
| 事件关联 | GET `/api/health-issues/{issue_id}/fix-plans`、`/executions`、`/timeline` | 选定事件后按需读；列表摘要使用批量投影 |
| 反馈 | POST `/api/health-issues/{issue_id}/rca-feedback`、`/feedback` | 保留现有反馈语义，身份由服务端确定 |
| 修复方案 | GET `/api/fix-plans`、`/{plan_id}`；PUT `/{plan_id}` | 只编辑允许的内容字段；状态变更走专用操作 |
| 修复审批/执行 | **PUT** `/api/fix-plans/{plan_id}/approve`；POST `/reject`、`/execute` | 修复批准是 PUT；不能统一改成 POST |
| 变更工作流 | GET/POST `/api/changes`；GET `/{cr_id}`；POST `/approve`、`/reject`、`/clarify`、`/review`、`/execute`、`/cancel`、`/resolve-review` | 变更审批/执行始终使用 ChangeRequest ID |
| 执行 | GET `/api/fix-executions`、`/{execution_id}`；POST `/{execution_id}/cancel` | POST execute 的 202 返回执行记录；取消是独立操作 |
| 资源 | GET `/api/resources`、`/{resource_id}`、`/issues`、`/fix-plans`、`/related` | 列表是 `{total,items}`，不同于 Issue/Plan 的数组 |
| 报告 | GET `/api/reports`、`/{report_id}`；POST `/generate`、`/from-session`、`/{report_id}/publish` | 发布会调用外部渠道；浏览、导出和发布分开 |
| 搜索/审计 | GET `/api/search`；现有 audit、command-audits、trace 路由 | 搜索结果保留对象类型与 ID；权限由服务端裁剪 |
| Graph/其他 | 现有 `/api/graph/*`、`/api/galaxy/*`、Schedules、Skills、Security、Messaging、Accounts、Settings | 全部保留；局部图不作为首屏阻塞请求 |

通用 API 客户端目前默认 JSON，不用于 multipart 或二进制下载。实施时拆分 `requestJson`、`requestMultipart`、`requestStream`、`downloadBlob`，共用认证、401 回跳、错误解码和 trace ID；保留 TanStack Query 和现有会话流 store。

### English

**Reuse existing APIs and add a small set of read/revision contracts.** The full 231-operation API inventory is included with the unchanged OpenAPI. This table covers the main UI journeys. ID types follow OpenAPI; sample labels such as `I-2401/P-126` must not be sent as real primary keys.

| Capability | Existing method/path | Contract |
| --- | --- | --- |
| Login/user | POST `/api/auth/login`; GET `/api/users/me` | email/password input; existing Bearer token |
| Sessions | GET/POST `/api/chat/sessions`; GET/PATCH/DELETE `/api/chat/sessions/{session_id}` | UUID session_id, not the integer session table key |
| History/send | GET/POST `/api/chat/sessions/{session_id}/messages` | GET: messages/has_more/next_cursor; POST: SSE |
| Cases | GET `/api/health-issues`, `/{issue_id}` | Canonical HealthIssue; retain legacy `/api/issues` and `/api/anomalies` |
| RCA/plan generation | GET/POST `/api/health-issues/{issue_id}/rca`; POST `/{issue_id}/generate-fix-plan` | RCA GET returns a list; accepted generation is not completion |
| Related case data | GET `/api/health-issues/{issue_id}/fix-plans`, `/executions`, `/timeline` | Fetch after selection/on demand; batch summaries for the queue |
| Feedback | POST `/api/health-issues/{issue_id}/rca-feedback`, `/feedback` | Preserve semantics; actor comes from the server |
| Fix plans | GET `/api/fix-plans`, `/{plan_id}`; PUT `/{plan_id}` | Content-only edits; dedicated lifecycle actions |
| Fix approval/execution | **PUT** `/api/fix-plans/{plan_id}/approve`; POST `/reject`, `/execute` | Fix approval is PUT, not POST |
| Changes | GET/POST `/api/changes`; GET `/{cr_id}`; POST `/approve`, `/reject`, `/clarify`, `/review`, `/execute`, `/cancel`, `/resolve-review` | Always act with ChangeRequest ID through the Change service |
| Executions | GET `/api/fix-executions`, `/{execution_id}`; POST `/{execution_id}/cancel` | Execute 202 returns an execution record; cancellation is separate |
| Resources | GET `/api/resources`, `/{resource_id}`, `/issues`, `/fix-plans`, `/related` | List shape is `{total,items}`, unlike issue/plan arrays |
| Reports | GET `/api/reports`, `/{report_id}`; POST `/generate`, `/from-session`, `/{report_id}/publish` | Publication sends externally; reading/export/publication are separate |
| Search/audit | GET `/api/search`; existing audit, command-audits and trace routes | Typed object references and server-side access filtering |
| Graph/others | Existing graph, galaxy, schedules, skills, security, messaging, accounts and settings | Retained; local graph does not block the first screen |

The current API helper assumes JSON. Separate `requestJson`, `requestMultipart`, `requestStream` and `downloadBlob`, sharing auth, login return routes, error decoding and trace IDs. Retain TanStack Query and the existing session stream store.

## 必须修正的契约差异 / Contract gaps that affect implementation

### 中文

| 编号 | 当前观察 | 实施决定 |
| --- | --- | --- |
| G1 | `/api/issues` 使用 AnomalyResponse 投影；前端仍用 useAnomalies | 新 Cases 使用 HealthIssue 类型/接口；旧入口留作兼容 |
| G2 | 发送消息运行时是 POST SSE，但 OpenAPI 声明为 JSON 且缺请求体 | 补 JSON/multipart/SSE 文档，保留实际协议与事件名 |
| G3 | ChatSessionCreate 只有 name，没有账户/对象上下文；会话列表查询未按所有者裁剪 | 增加 context、scope 和可见性规则，所有会话读写检查身份；不要仅把标题放进 prompt |
| G4 | FixPlanResponse 没有内容版本；approve 会调用 trigger_auto_execute | 版本/范围与并发条件写入服务层；确认按钮显示“批准”或“批准并排队执行”的真实效果 |
| G5 | 报告有正文与格式转换，但没有正式的中英文版本读取契约 | 以源版本生成语言渲染；导出/发布绑定版本、语言、格式 |
| G6 | HealthIssueUpdate 状态 pattern 缺 dismissed；模型状态机有 dismissed | 对齐可执行状态与权限；关闭不能用任意字符串 PUT 绕过状态机 |
| G7 | ReportGenerateRequest 接受的类型多于 generate handler 实际处理的类型 | 修正声明或实现支持；前端仅显示已支持的生成类型 |
| G8 | 现有 Chat 停止方式为 AbortController；刷新断流不等于持久任务恢复 | 保留跨路由流 store；刷新后读历史并标识中断；禁止自动重新提交写操作 |
| G9 | 规范资源锚定、图事实新鲜度、验收绑定在历史审阅中仍有缺口 | 先显式 unknown/ambiguous；依赖它们的写操作在条件满足后启用 |
| G10 | 企业微信 GET/POST 回调在 OpenAPI 中共用 operationId | P0 给两个操作分配独立编号，仅修正文档，不改变回调行为 |
| G11 | RCA 触发的 202 被声明为 RCAResponse，实际返回 message/health_issue_id；方案生成也返回受理对象 | P0 对齐受理响应；前端通过结果/时间线读取完成情况 |

这些属于源码/声明的核对结果，不代表本次已修复。身份隔离、写操作并发与验证完整性属于客户上线门槛；页面视觉改造不应掩盖这些条件。

### English

| ID | Current observation | Implementation decision |
| --- | --- | --- |
| G1 | `/api/issues` exposes an AnomalyResponse projection; frontend uses useAnomalies | New Cases use HealthIssue types/endpoints; retain compatibility |
| G2 | Message POST is SSE at runtime; OpenAPI declares JSON without its body | Document JSON/multipart/SSE, preserving actual event names |
| G3 | Chat creation has only name; no object/account context, and session listing is not owner-filtered | Add validated context/scope/visibility and check every session read/write; a prompt title is insufficient |
| G4 | FixPlanResponse has no content version; approve invokes trigger_auto_execute | Bind revision/scope atomically; confirmation reflects approve-only versus approval plus execution queuing |
| G5 | Reports support bodies/formats but lack a formal bilingual revision contract | Render from a source version; pin export/publication to version, language and format |
| G6 | HealthIssueUpdate excludes dismissed although the model state machine supports it | Align supported actions and permission checks; no arbitrary state-string bypass |
| G7 | ReportGenerateRequest allows more report types than the handler implements | Align declaration/implementation; expose only supported generation options |
| G8 | Chat stop uses AbortController; refresh/disconnect is not durable task recovery | Keep the route-independent stream store, reconcile history and label interrupted turns; never automatically resubmit writes |
| G9 | Prior review identifies gaps in resource identity, graph freshness and verification binding | Show unknown/ambiguous explicitly; enable dependent writes only after their prerequisites are met |
| G10 | WeCom GET/POST callbacks share an OpenAPI operationId | Assign distinct IDs in P0; documentation-only repair, preserving callback behavior |
| G11 | RCA trigger declares RCAResponse for 202 but returns message/health_issue_id; plan generation also returns acceptance | Align accepted-response schemas in P0; read completion from results/timeline |

These are source/contract observations, not fixes completed in this delivery. Identity isolation, write concurrency and complete verification are customer-release gates; visual changes must not conceal them.

## 新增接口：8 个操作 / New APIs: eight operations

### 中文

目标 OpenAPI 明确标记 `proposed-new` / `proposed-extension` / `existing-retained`。**拟新增 8 个操作，扩展 37 个现有操作；其余保持原路由。** 目标文件是设计合同，不是已运行服务。

扩展清单中 4 项仅修正文档：企业微信 GET/POST 的独立 operationId，以及 RCA/方案生成的 202 受理响应。它们不改变运行行为。

| 方法/路径 | 目的 | 阶段 |
| --- | --- | --- |
| GET `/api/ui/bootstrap` | 当前身份、能力开关、实际上传策略、偏好；不暴露渠道密钥 | P1 |
| GET `/api/users/me/preferences` | 当前用户首页、语言、合法恢复路由与版本 | P1 |
| PATCH `/api/users/me/preferences` | 更新偏好；If-Match 防止多标签覆盖 | P1 |
| GET `/api/ui/attention` | 统一权限/账户范围的可操作待办 | P4 |
| POST `/api/health-issues/{issue_id}/notes` | 向现有时间线追加有操作者的说明 | P3 |
| GET `/api/content/{entity_type}/{entity_id}/rendering` | 读取指定版本的 zh/en 展示正文；GET 不调用模型 | P5 |
| POST `/api/content/{entity_type}/{entity_id}/translations` | 保证指定源版本的语言渲染存在，返回 ready/pending；可幂等重用 | P5 |
| GET `/api/reports/{report_id}/export` | 下载固定 version/language/format 的文件，不发布 | P5 |

`entity_type` 限定 health_issue、fix_plan、change_request、report。共用渲染服务，避免为每个页面各建翻译 API。`language=zh-en` 仅用于导出两份已准备好的语言正文，翻译任务仍分别生成 zh 和 en。

GET bootstrap 的字段表示**有效能力**：例如 revision_guards、context_chat、content_rendering。未部署的新接口不能被前端乐观假定为存在。P1 可先接旧读取能力；P4 写操作仅在版本保护被后端实际启用后开放。

### English

Target OpenAPI marks `proposed-new`, `proposed-extension` and `existing-retained`. **Eight operations are proposed as new; 37 existing operations are extended; remaining routes are retained.** The target document is a design contract, not the running service.

Four extensions are documentation-only: separate WeCom GET/POST operation IDs and the accepted-response schemas for RCA/plan generation. They do not change runtime behavior.

| Method/path | Purpose | Phase |
| --- | --- | --- |
| GET `/api/ui/bootstrap` | Identity, effective capabilities, upload policy and preferences; no connector secrets | P1 |
| GET `/api/users/me/preferences` | Home, locale, allow-listed last route and revision | P1 |
| PATCH `/api/users/me/preferences` | Update preferences with If-Match concurrency | P1 |
| GET `/api/ui/attention` | Actionable work under one actor/account scope | P4 |
| POST `/api/health-issues/{issue_id}/notes` | Append an attributed note to the existing timeline | P3 |
| GET `/api/content/{entity_type}/{entity_id}/rendering` | Read zh/en presentation for an exact source version; no model call on GET | P5 |
| POST `/api/content/{entity_type}/{entity_id}/translations` | Ensure requested source-version renderings; return ready/pending and deduplicate | P5 |
| GET `/api/reports/{report_id}/export` | Download a pinned version/language/format without publishing | P5 |

Supported entity_type values are health_issue, fix_plan, change_request and report. A shared rendering service avoids separate translation APIs per page. `language=zh-en` is an export of two prepared renderings; translation produces zh and en separately.

Bootstrap advertises **effective capabilities** such as revision_guards, context_chat and content_rendering. The frontend must not assume undeployed APIs exist. P1 may use existing reads; P4 writes open only after the backend actually enforces revision protection.

## Chat、附件与流式契约 / Chat, attachments and streaming

### 中文

新会话仍使用现有 POST，拟增加可验证的上下文。以下是**目标契约示例**，不能向当前服务发送后就假定 context 已被执行：

```json
{
  "name": "订单服务排查",
  "response_language": "zh",
  "context": {
    "primary": {"entity_type": "health_issue", "entity_id": 42, "content_version": 1},
    "account_id": 3,
    "region": "ap-southeast-1"
  }
}
```

独立请求使用 `primary:null`；关联对象的范围由服务端解析。首次发送后上下文锁定，改范围创建新会话；每次工具调用仍检查当前权限与范围，不能靠前端下拉框实现隔离。

发送消息：`POST /api/chat/sessions/{session_id}/messages`，文本为 `{content, client_message_id, scan_focus?}`；多附件为 multipart，字段 `content`、`client_message_id`、重复的 **file**。当前服务上限 5 个。原生图片与原生文档 5 MiB，文本回退 512 KiB；`.txt/.md/.csv/.html` 当前优先走原生文档分支，不要用“所有文本都 512 KiB”的错误规则。

复用 `text`、`tool_start`、`tool_end`、`session_renamed`、`done`、`error` 事件。新增 accepted 帧和稳定消息/调用标识；传输层按完整 SSE 帧解析，支持 UTF-8 拆包、跨 chunk、CRLF 和未知事件。`tool_end` 不能仅凭工具名称表达成功。

`client_message_id` 在同一会话唯一；事务中记录请求指纹与 dispatch 状态。已完成的重复请求可重放持久消息，正在执行/状态不确定的重复请求返回 409，不能再次启动 Agent。断线不自动 POST 重试。终止回复标为 interrupted；已有工具副作用需回到 Case/Execution 核对。

第一阶段不新增 `/runs` 平台、不承诺刷新后无损 SSE 回放、不增加语音/视频入口。当前附件元数据只有文件名/大小/类型，不能伪装成可重下载的附件 ID。持久附件与真正后台可恢复 Chat 作为后续独立阶段。

### English

Keep the existing create-session POST and extend it with validated context. This is a **target example**; sending it to the current service does not mean context enforcement exists:

```json
{
  "name": "Order service investigation",
  "response_language": "en",
  "context": {
    "primary": {"entity_type": "health_issue", "entity_id": 42, "content_version": 1},
    "account_id": 3,
    "region": "ap-southeast-1"
  }
}
```

Independent requests use `primary:null`. The server resolves linked-object scope. Lock context after the first send; create a new session to change it. Every tool call checks current permissions and scope. A frontend selector is not an isolation boundary.

POST messages as JSON `{content, client_message_id, scan_focus?}` or multipart fields `content`, `client_message_id` and repeated **file**. The existing limit is five files. Native images/documents allow 5 MiB; text fallback allows 512 KiB. `.txt/.md/.csv/.html` currently dispatch to native documents first; “all text is limited to 512 KiB” would be incorrect.

Reuse text, tool_start, tool_end, session_renamed, done and error. Add accepted and stable message/tool-call identifiers. Parse complete SSE frames across UTF-8/chunk boundaries and CRLF; tolerate unknown events. A tool_end name alone cannot imply success.

client_message_id is unique within the session, with an atomic request fingerprint and dispatch state. Completed duplicates may replay persisted output; active/uncertain duplicates return 409 and never restart the Agent. Do not retry POST automatically after disconnect. Label interrupted replies and inspect Case/Execution for effects already performed.

The first release adds no generic `/runs` platform, lossless refresh-time SSE replay, voice or video. Current attachment metadata has filename/size/type rather than retrievable attachment IDs. Durable attachment storage and independently resumable background Chat remain separate follow-up work.

## 审批、执行与验收契约 / Approval, execution and verification contract

### 中文

保留现有操作方法，增加强 ETag 和条件请求。示例中的 ETag 是说明用值：

```http
GET /api/fix-plans/126
Authorization: Bearer <token>

HTTP/1.1 200 OK
ETag: "plan-126-v3-state7-scope9"
```

```http
PUT /api/fix-plans/126/approve
Authorization: Bearer <token>
If-Match: "plan-126-v3-state7-scope9"
Idempotency-Key: 35ac86c5-5779-4462-a815-d635f87cf09b
Content-Type: application/json

{"reason":"已核对目标、验证和回滚条件"}
```

服务端从登录身份确定 actor；忽略客户端自报 approved_by 作为权限依据。版本、目标范围、策略与状态在**同一事务**中核对和转移。内容改变递增 content_version；审批记录保留版本与范围指纹；执行记录引用批准的不可变快照。

| 返回 | 前端行为 |
| --- | --- |
| 202 | 已受理，追踪返回的 execution_id；不能立即显示执行成功 |
| 403 | 显示不可执行原因，保留只读上下文 |
| 409 | 状态冲突/重复请求，读取最新对象并说明原因 |
| 412 | 已审阅版本过期，刷新差异后重新确认 |
| 428 | 缺少版本条件；不静默降级为无条件写入 |

Idempotency-Key 是本项目拟实施的服务层契约，不是已有中间件能力。幂等记录绑定 actor、路由、规范请求体与结果；同 key 不同内容返回 409。升级顺序为服务端可选能力 → 新前端携带条件 → 迁移 CLI/IM/旧前端 → 全局强制。

特别处理：Fix approve 当前可能自动排队执行。读取 `available_actions.effect` 决定确认文字和后续界面；不要批准后再自动发一次 execute。Change 的 approve/execute 委托 Change 服务，不能通过其底层 FixPlan 绕行。

任何“恢复通过”必须由 verification_service 检查当前执行、版本、稳定 check_id、唯一覆盖、目标和工具证据。重复 A 缺少 B、旧执行迟到结果、失败执行带 pass 字段、人工接受都不得自动变成机器 passed。已有 Change resolve-review 复用该服务。

### English

Preserve current methods and add strong ETags/preconditions. The ETag below is illustrative:

```http
GET /api/fix-plans/126
Authorization: Bearer <token>

HTTP/1.1 200 OK
ETag: "plan-126-v3-state7-scope9"
```

```http
PUT /api/fix-plans/126/approve
Authorization: Bearer <token>
If-Match: "plan-126-v3-state7-scope9"
Idempotency-Key: 35ac86c5-5779-4462-a815-d635f87cf09b
Content-Type: application/json

{"reason":"Reviewed target, verification and rollback"}
```

The server derives the actor from authentication. Client-claimed approved_by is not authority. Check revision, scope, policy and state **in the same transaction** as transition. Content changes increment content_version; approval records bind version/scope; execution references the approved immutable snapshot.

| Response | UI behavior |
| --- | --- |
| 202 | Accepted; track execution_id, not success |
| 403 | Show denial reason while retaining read context |
| 409 | State/duplicate conflict; read latest object and explain |
| 412 | Reviewed revision is stale; refresh differences and reconfirm |
| 428 | Revision precondition missing; no silent unconditional fallback |

Idempotency-Key is a proposed application-service contract, not existing middleware. Bind actor, route, canonical request and result. Same key with different content returns 409. Roll out optional backend capability, conditional new frontend, migration of CLI/IM/old clients, then global enforcement.

Fix approval may currently auto-queue execution. Use available_actions.effect for confirmation and follow-up; do not automatically call execute again after approval. Change actions delegate to the Change service rather than its underlying FixPlan endpoints.

verification_service checks current execution/version, stable unique check IDs, complete coverage, target and tool evidence. Duplicate A with missing B, late old attempts, failed execution with pass text and human acceptance cannot manufacture machine passed. Existing Change resolve-review delegates to this service.

## 双语正文、报告与下载 / Bilingual content, reports and download

### 中文

UI 字典沿用现有 LocaleContext/locales；规范 API 状态与 ID 不翻译。Case 结论、Plan 说明、Change 需求说明和 Report 正文使用共用 ContentRendering，键为 `(entity_type, entity_id, source_version, language)`，同时保存 source_hash 与受保护事实的指纹。

新内容生成后准备 zh/en 两个渲染；切换语言只读取已生成内容。历史单语言内容缺翻译时显示“翻译准备中/不可用”和源语言入口，不静默混排，也不重新做 RCA 或生成另一份方案。原始用户请求保留原文，译文明确作为展示内容。

渲染不改变命令、标识、证据引用、检查项 ID、数值和状态。渲染的 ready 状态要求源 hash 与受保护字段核对通过。源发生变化时旧渲染标记 stale。报告语言版本不作为新的批准对象。

```http
GET /api/content/report/42/rendering?version=2&language=zh
GET /api/reports/42/export?version=2&language=zh-en&format=html
```

导出用带认证的 fetch 获取 Blob，再用 Content-Disposition 保存；普通 JSON 客户端不能直接处理。下载路径不携带 token。HTML/PDF/DOCX 三种格式延续既有报告转换能力；能力不可用时明确禁用对应格式。首次交付必须通过 HTML 和浏览器打印验收，PDF/DOCX 在客户安装对应依赖后验证。

发布扩展已有 `/api/reports/{id}/publish`：固定 version、language、formats、channel_name 和幂等键。展示实际目的地后才发送。已有 publish 支持 sns-report / ses 渠道，不把所有 IM 频道假设为发布目标。普通分享功能保留，但不能绕开报告版本绑定。

### English

Reuse LocaleContext/locales for UI text; never translate canonical status values or IDs. Case findings, plan explanations, change request descriptions and report bodies share ContentRendering keyed by `(entity_type, entity_id, source_version, language)`, with source_hash and a protected-facts fingerprint.

Prepare zh/en renderings after new source content is generated. Locale switching only reads prepared content. Legacy content without a translation shows preparing/unavailable plus an explicit source-language option; it never silently mixes languages, restarts RCA or creates another plan. Preserve original user requests; translated text is presentation.

Rendering must not alter commands, identifiers, evidence/check references, values or states. Ready requires source-hash and protected-value validation. Source changes mark old renderings stale. Report language variants do not become new approval objects.

```http
GET /api/content/report/42/rendering?version=2&language=zh
GET /api/reports/42/export?version=2&language=zh-en&format=html
```

Download via authenticated fetch/Blob and Content-Disposition, not the JSON helper. Do not place tokens in URLs. Reuse existing HTML/PDF/DOCX conversion capabilities and disable unavailable formats. HTML and browser printing are required initially; validate PDF/DOCX where customer dependencies are installed.

Extend existing report publication with pinned version, language, formats, channel_name and idempotency. Show the actual destination before sending. Existing publish supports sns-report/ses; do not assume all IM channels are publishing targets. Retain general sharing without bypassing report revision binding.

## 查询、缓存与错误处理 / Queries, caching and errors

### 中文

- 列表默认 50 条、服务端筛选和分页。Case 队列所需状态批量查询；禁止每条记录再请求 RCA、Plan、Execution。
- 进入详情后并行读取独立信息；原始日志、大 JSON、时间线旧页和图在展开时加载。图请求限制深度、节点数和账户范围，并显示截断。
- Query key 包含对象 ID、账户范围、语言和内容版本；UI 语言缓存与事实查询分离，切语言不重新执行诊断。
- 复用已有会话流 store，页面离开不销毁流。执行中的记录使用短轮询，终态停止；重新聚焦时检查失效数据。
- 写操作成功后刷新关联 Case、Plan、Change、Execution 与待办；不能只更新一个绿色徽标。状态冲突必须重新读服务端。
- 统一加载、空、无权限、已删除、离线、部分失败和翻译准备状态。新错误结构为 detail/code/trace_id，适配器同时识别已有 FastAPI 422 和旧 error 格式。

验收预算属于**目标而非测量结果**：在客户约定的本地数据规模下，50 条 Case 首屏接口 p95 ≤500ms、详情数据 p95 ≤800ms；不计云实时诊断时间。记录请求数、SQL 次数、正文/图 payload、浏览器长任务和首次可操作时间。未达预算时先修 N+1、分页、索引和懒加载，不先更换数据库。

### English

- Default to 50-row server-filtered pages. Batch case-queue status summaries; do not fetch RCA/Plan/Execution once per row.
- Fetch independent detail data concurrently. Load raw logs, large JSON, old timeline pages and graphs on demand. Bound graph depth/nodes/account and disclose truncation.
- Query keys include object, account, language and content revision. Separate translation caches from fact queries; locale changes do not run diagnosis.
- Retain the existing session stream store across navigation. Poll active executions briefly, stop at terminal states and reconcile stale data on focus.
- Mutations invalidate related case, plan, change, execution and attention data, not just one badge. State conflicts trigger a server re-read.
- Provide loading, empty, denied, deleted, offline, partial-failure and translation-preparing states. New errors use detail/code/trace_id while adapters retain FastAPI 422 and legacy error support.

Acceptance budgets are **targets, not measurements**: with an agreed customer-local dataset, p95 ≤500ms for a 50-case page and ≤800ms for detail data, excluding live cloud investigation. Measure requests, SQL counts, payloads, browser long tasks and time to first action. Address N+1, pagination, indexing and lazy loading before changing storage engines.

## 逐项变更登记 / Operation change register

| 状态 / Status | Phase | Method | Path | Contract |
| --- | --- | --- | --- | --- |
| new | P1 | GET | `/api/ui/bootstrap` | Read authenticated UI capabilities and effective upload policy. |
| new | P1 | GET | `/api/users/me/preferences` | Read per-user navigation/locale preferences. |
| new | P1 | PATCH | `/api/users/me/preferences` | Update allow-listed navigation/locale preferences. |
| new | P4 | GET | `/api/ui/attention` | Read actionable work for this actor; no model calls or cloud scans. |
| new | P5 | GET | `/api/content/{entity_type}/{entity_id}/rendering` | Read a source-version-bound language rendering; GET never invokes a model. |
| new | P5 | POST | `/api/content/{entity_type}/{entity_id}/translations` | Ensure language renderings for this source revision; deduplicate by entity/version/language. |
| new | P3 | POST | `/api/health-issues/{issue_id}/notes` | Append an attributed note to the existing issue timeline. |
| new | P5 | GET | `/api/reports/{report_id}/export` | Download an already-rendered report revision in one or both languages; no publication. |
| extend | P2 | POST | `/api/chat/sessions` | Server-validated object context and scope, visibility/ownership checks, per-session response language. Shared legacy sessions are explicitly classified; no arbitrary owner assignment. |
| extend | P2 | GET | `/api/chat/sessions` | Server-validated object context and scope, visibility/ownership checks, per-session response language. Shared legacy sessions are explicitly classified; no arbitrary owner assignment. |
| extend | P2 | GET | `/api/chat/sessions/{session_id}` | Server-validated object context and scope, visibility/ownership checks, per-session response language. Shared legacy sessions are explicitly classified; no arbitrary owner assignment. |
| extend | P2 | PATCH | `/api/chat/sessions/{session_id}` | Server-validated object context and scope, visibility/ownership checks, per-session response language. Shared legacy sessions are explicitly classified; no arbitrary owner assignment. |
| extend | P2 | DELETE | `/api/chat/sessions/{session_id}` | Server-validated object context and scope, visibility/ownership checks, per-session response language. Shared legacy sessions are explicitly classified; no arbitrary owner assignment. |
| extend | P2 | GET | `/api/chat/sessions/{session_id}/messages` | Server-validated object context and scope, visibility/ownership checks, per-session response language. Shared legacy sessions are explicitly classified; no arbitrary owner assignment. |
| extend | P2 | POST | `/api/chat/sessions/{session_id}/messages` | Document existing POST SSE and multipart behavior. Add per-session client_message_id deduplication and dispatch state. No resumable stream is promised; reconnect reads persisted history. |
| extend | P3 | GET | `/api/health-issues` | Use the canonical HealthIssue representation. Add batched workflow summary and scoped search without per-row requests. |
| extend | P3 | PUT | `/api/health-issues/{issue_id}` | Align dismissed with the model state machine; route lifecycle changes through the shared transition/authorisation service. Content editing must not become a status bypass. |
| extend | P3/P4 | GET | `/api/health-issues/{issue_id}` | Add validated read metadata, content revision and available actions; preserve raw lifecycle status and independently describe recovery verification. |
| extend | P3/P4 | GET | `/api/health-issues/{issue_id}/timeline` | Add validated read metadata, content revision and available actions; preserve raw lifecycle status and independently describe recovery verification. |
| extend | P3/P4 | GET | `/api/fix-plans` | Add validated read metadata, content revision and available actions; preserve raw lifecycle status and independently describe recovery verification. |
| extend | P3/P4 | GET | `/api/fix-plans/{plan_id}` | Add validated read metadata, content revision and available actions; preserve raw lifecycle status and independently describe recovery verification. |
| extend | P3/P4 | GET | `/api/changes` | Add validated read metadata, content revision and available actions; preserve raw lifecycle status and independently describe recovery verification. |
| extend | P3/P4 | GET | `/api/changes/{cr_id}` | Add validated read metadata, content revision and available actions; preserve raw lifecycle status and independently describe recovery verification. |
| extend | P3/P4 | GET | `/api/fix-executions/{execution_id}` | Add validated read metadata, content revision and available actions; preserve raw lifecycle status and independently describe recovery verification. |
| extend | P4 | PUT | `/api/fix-plans/{plan_id}` | Atomic revision/scope/policy check in the shared service. If-Match is checked in the same transaction as the state transition. Idempotency keys bind actor, route and canonical body; duplicate requests must not enqueue another execution. Fix-plan approval may auto-queue execution: show available_actions.effect before confirmation. |
| extend | P4 | PUT | `/api/fix-plans/{plan_id}/approve` | Atomic revision/scope/policy check in the shared service. If-Match is checked in the same transaction as the state transition. Idempotency keys bind actor, route and canonical body; duplicate requests must not enqueue another execution. Fix-plan approval may auto-queue execution: show available_actions.effect before confirmation. |
| extend | P4 | POST | `/api/fix-plans/{plan_id}/reject` | Atomic revision/scope/policy check in the shared service. If-Match is checked in the same transaction as the state transition. Idempotency keys bind actor, route and canonical body; duplicate requests must not enqueue another execution. Fix-plan approval may auto-queue execution: show available_actions.effect before confirmation. |
| extend | P4 | POST | `/api/fix-plans/{plan_id}/execute` | Atomic revision/scope/policy check in the shared service. If-Match is checked in the same transaction as the state transition. Idempotency keys bind actor, route and canonical body; duplicate requests must not enqueue another execution. Fix-plan approval may auto-queue execution: show available_actions.effect before confirmation. |
| extend | P4 | POST | `/api/changes/{cr_id}/approve` | Atomic revision/scope/policy check in the shared service. If-Match is checked in the same transaction as the state transition. Idempotency keys bind actor, route and canonical body; duplicate requests must not enqueue another execution. Fix-plan approval may auto-queue execution: show available_actions.effect before confirmation. |
| extend | P4 | POST | `/api/changes/{cr_id}/reject` | Atomic revision/scope/policy check in the shared service. If-Match is checked in the same transaction as the state transition. Idempotency keys bind actor, route and canonical body; duplicate requests must not enqueue another execution. Fix-plan approval may auto-queue execution: show available_actions.effect before confirmation. |
| extend | P4 | POST | `/api/changes/{cr_id}/cancel` | Atomic revision/scope/policy check in the shared service. If-Match is checked in the same transaction as the state transition. Idempotency keys bind actor, route and canonical body; duplicate requests must not enqueue another execution. Fix-plan approval may auto-queue execution: show available_actions.effect before confirmation. |
| extend | P4 | POST | `/api/changes/{cr_id}/clarify` | Atomic revision/scope/policy check in the shared service. If-Match is checked in the same transaction as the state transition. Idempotency keys bind actor, route and canonical body; duplicate requests must not enqueue another execution. Fix-plan approval may auto-queue execution: show available_actions.effect before confirmation. |
| extend | P4 | POST | `/api/changes/{cr_id}/review` | Atomic revision/scope/policy check in the shared service. If-Match is checked in the same transaction as the state transition. Idempotency keys bind actor, route and canonical body; duplicate requests must not enqueue another execution. Fix-plan approval may auto-queue execution: show available_actions.effect before confirmation. |
| extend | P4 | POST | `/api/changes/{cr_id}/execute` | Atomic revision/scope/policy check in the shared service. If-Match is checked in the same transaction as the state transition. Idempotency keys bind actor, route and canonical body; duplicate requests must not enqueue another execution. Fix-plan approval may auto-queue execution: show available_actions.effect before confirmation. |
| extend | P4 | POST | `/api/changes/{cr_id}/resolve-review` | Atomic revision/scope/policy check in the shared service. If-Match is checked in the same transaction as the state transition. Idempotency keys bind actor, route and canonical body; duplicate requests must not enqueue another execution. Fix-plan approval may auto-queue execution: show available_actions.effect before confirmation. |
| extend | P3 | GET | `/api/resources` | Document the existing {total,items} response; bound pagination. Resource health, inventory lifecycle and observation freshness remain distinct. |
| extend | P5 | GET | `/api/reports` | Document current ReportResponse shape and expose source revision. Related-object IDs and account are explicit metadata; never guess a report by title similarity. |
| extend | P5 | GET | `/api/reports/{report_id}` | Document current ReportResponse shape and expose source revision. Related-object IDs and account are explicit metadata; never guess a report by title similarity. |
| extend | P5 | POST | `/api/reports/generate` | Store a source revision and enqueue paired renderings after source generation. Align allowed report_type values with the actual generator; locale changes never restart RCA. |
| extend | P5 | POST | `/api/reports/from-session` | Store a source revision and enqueue paired renderings after source generation. Align allowed report_type values with the actual generator; locale changes never restart RCA. |
| extend | P5 | POST | `/api/reports/{report_id}/publish` | Publish exactly the selected report version and ready language renderings; preserve channel restrictions. Show destination, format and language before sending; do not substitute generic /api/share for versioned publication. |
| extend | P0 | GET | `/api/im/wecom/callback` | Documentation-only repair: give GET and POST distinct operationId values. Preserve callback behavior and authentication. |
| extend | P0 | POST | `/api/im/wecom/callback` | Documentation-only repair: give GET and POST distinct operationId values. Preserve callback behavior and authentication. |
| extend | P0 | POST | `/api/health-issues/{issue_id}/rca` | Documentation-only repair: actual 202 response is {message,health_issue_id}, not a completed RCA/Plan. Read the result/timeline endpoints after acceptance. |
| extend | P0 | POST | `/api/health-issues/{issue_id}/generate-fix-plan` | Documentation-only repair: actual 202 response is {message,health_issue_id}, not a completed RCA/Plan. Read the result/timeline endpoints after acceptance. |

## 协议参考 / Protocol references

- OpenAPI 3.1.0: `https://spec.openapis.org/oas/v3.1.0.html`
- SSE framing: `https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events`
- If-Match / 412: `https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/If-Match`
