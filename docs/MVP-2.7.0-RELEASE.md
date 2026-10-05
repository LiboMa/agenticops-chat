# MVP-2.7.0 Release Notes — 蓝白工作台 + 核心信任加固（分阶段交付）

> Version: 2.7.0 · Branch: `MVP-2.7.0`（从 `MVP-2.6.1` 的 `1ec53b3` 切出）· 起始日期：2026-10-05 · 主题：先把会「假通过」「串号」「多进程失效」的核心信任问题修掉，再按主人 10-05 交付的蓝白设计包分阶段改造界面
>
> **状态：S1（核心信任加固）已于 2026-10-05 由主人验收通过；S2（蓝白外壳与导航）已实现，作为 `MVP-2.7.0` 分支上的本地提交存在（未 push），等主人手动验收。S3–S7 尚未开始：每个阶段开工前先交详细计划给主人批准，上一阶段验收通过才进下一阶段。** 依主人铁律，只有 E2E 通过且当面确认后才 `git push --no-verify` / 打 `v2.7.0` tag。
>
> 全链规划（含 S1 详细计划）：`docs/superpowers/plans/2026-10-05-mvp-2.7.0-roadmap.md`
> 设计输入：`docs/AgenticOps_BlueWhite_Review.zip`、`docs/superpowers/specs/2026-10-05-blue-white-sre-workspace-design.md`、`docs/ui-contracts/2026-10-05/`

## 一句话

蓝白设计包里大约 65% 的工作量是界面与交付体验，真正动核心的只有几项；而其中三项是已经复核的缺陷：执行验收会被重复结果凑数通过、chat 会话对所有人可见、四个 worker 让内存态保证悄悄失效。MVP-2.7.0 把这三项作为第一阶段（S1）先修，再按「单位时间收益」逐阶段推进界面改造。

## 阶段与状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| **S1 核心信任加固** | 验收逐项绑定 check_id；会话归属 + private/workspace；单进程运行 + 事件循环不阻塞 | **已验收（2026-10-05）** |
| **S2 蓝白外壳与导航**（P0+P1） | 配色、字体本地化、分组侧栏、顶栏、首页解析器、登录回跳、`/app/overview`、bootstrap + 偏好接口 | **已实现，待主人验收** |
| S3 方案枢纽 + 待办（P4） | `/app/plans` 三标签 + `/app/plans/:id`、`GET /api/ui/attention`、方案编辑防过期 | 未开始 |
| S4 Cases 与 Resources（P3） | 队列 + 阅读区双栏（保留 2.6.1 阶段卡）、HealthIssue hooks、笔记接口、账户范围 | 未开始 |
| S5 Chat（P2） | 会话上下文与账户范围、`client_message_id` 幂等、附件、流错误 | 未开始 |
| S6 报告与双语（P5） | 渲染服务 + 翻译、导出、发布确认 | 未开始 |
| S7 联合验收与发布（P6） | 文档、live E2E、版本串、`v2.7.0` tag | 未开始 |

---

## S1a 执行验收逐项绑定

**之前**：`verification.evaluate` 只比较「结果条数」与「声明的检查条数」。声明 A、B 两项检查，执行器上报 [A 通过, A 通过]，判定为 `passed`（9 月审阅的反例，`docs/research/2026-10-05-mvp-2.6.1-assessment.md`）。另外，`get_approved_fix_plan` 把整份方案 JSON 截到 4000 字符，`steps` 和 `post_checks` 排在说明文字之后，长方案交到执行器手里时步骤或检查本身就是残缺的。

**现在**：

- **check_id = 声明位置**：`pc-1 … pc-n`。`post_checks` 参与内容哈希，审批后冻结，所以同一次执行内位置稳定；存储内容不变，重复的声明检查也各有 id。
- **一对一绑定**：一条结果只算给它点名的那个 `check_id`。某项检查没有结果或有多条、结果点了不存在的检查、结果不带 `check_id`、或方案在审批后被改动（`approval_drift`），都只能是 `pending_acceptance`，原因句点名具体的 id（例如 `no result for post-check pc-2; post-check pc-1 reported more than once`）。任何一条结果失败仍是 `failed`。不做按位置回退。
- **执行器拿到完整方案**：`get_approved_fix_plan` 不再截断，执行需要的字段排在前面（steps、带 `check_id` 的 post_checks、pre_checks、rollback），超大方案被 SDK 的 ContextOffloader 转存时预览里仍是这些字段。执行器提示词要求「每个 check_id 恰好一条结果」。
- **写库前校验**：成功的执行若没有一对一覆盖声明的检查，`save_execution_result` 返回 `INVALID`、不写库，执行器在同一次执行里改正；同一次执行第二次仍不覆盖则照常记录为 `pending_acceptance`，结果永远不会丢。
- **一次判决**：变更路径不再重算，`on_execution_result(judged=)` 用执行行上存的那一个判决。
- **API / UI**：`FixExecutionResponse.post_check_binding`（服务端用判决的同一个函数配对：每个声明检查一行，再列游离结果）；执行证据区按 `pc-n` 逐项显示「无结果 / 上报了 N 次 / 不是声明的检查 / 未带 check_id」；方案页给每条 post-check 标 `pc-n`；2.7.0 之前没有 id 的执行按上报顺序列出并注明。主 agent 的 `get_plan` / `get_execution_result` 也带 id 与配对。
- **单一读法**：`verification.declared_checks` 是 `post_checks` 唯一的读取函数，`FixPlanResponse` 用同一个 `decode_legacy_json` 解码旧数据，页面和判决数的是同一批检查。

**非目标**：独立探针重新观察系统（Harness Trust Kernel 的 VerifyGate）；评判 `pre_checks`；扩展验证状态集。

## S1b chat 会话归属与可见性

**之前**：`ChatSession` 没有归属，7 个 chat 接口都不识别调用者，所有会话对所有人可见；发消息接口在检查会话之前就读上传、执行 `/channel`、`/send_to`；列表每个会话一次计数查询；删除会话留下 `SessionSummary`；用 API key 调用、以及 `POST /api/auth/register`，都会因 SQLAlchemy 的 detached 实例报错（注册每次都返回 400）。

**现在**：

- 已登录用户新建的会话归本人、`private`（本人和 admin 可见）；没有单一主人的会话（2.7.0 之前的所有会话、认证关闭时 / IM / CLI 建的会话）是 `workspace`，与以前一样所有人可见。认证关闭时所有调用者都是 `web:anonymous`，所有会话照旧可见。
- `services/chat_access` 是唯一规则：列表、读取、历史、发消息、修改、删除、存为报告全部经过它；看不见的会话一律 404，响应与不存在的会话完全相同。
- 只有 owner 或 admin 能改 `visibility`（`PATCH /api/chat/sessions/{id}`），无主会话不能改成 private（409）。
- **共享的是阅读，不是管理**（独立审查后收紧，偏离 S1b 计划第 4 条「可见即可改名 / 删除」）：有主的会话即使共享给工作区，改名、置顶、归档、切换模型 / 思考强度、删除仍只属于 owner 或 admin（其他人 403——他们本来就看得见，不泄露信息）；其他人可以阅读、继续对话。无主会话照旧任何人可管理。响应带 `can_manage`，界面只给能管理的人显示这些操作。
- 可见性检查放在第一步：读上传、`/channel`、`/send_to`、streaming 409 都在它之后。
- 列表计数改为一次分组查询；删除时一并删除 `SessionSummary`。
- CLI：`/session list`、无参 `/session resume`、按名字片段恢复、`aiops chat --resume`、启动时的「最近会话」提示都只看 workspace 会话；精确 id / UUID 仍可恢复任意会话（CLI 是有库访问权的本地操作员）。
- Web UI：登录后会话行标「工作区」或「他人私有」（只有 admin 看得到后者）；owner 在会话悬停菜单里切换 私有 / 工作区；通过链接打开、不在前 50 条列表里的会话也能显示名称和「存为报告」；私有会话存为报告前提示「报告对工作区所有人可见」。
- 顺手修的两个 detached 实例问题：`validate_api_key`（PARK-S5）和 `create_user`（注册接口）。
- 退出登录改为整页刷新、登录时清空查询缓存：之前在同一个标签页里，下一个登录的人能从前端缓存看到上一个人的私有会话与消息。
- 主 chat 每轮的 AgentLog 之前把 User 对象当 `actor_id` 写进字符串列，开启认证后每一行都插入失败并被静默吞掉（成本统计偏少）；现在记 actor 的 key，且私有会话那一轮不记对话摘要（token / 成本照记），因为 `GET /api/agent-logs` 对所有人可见。

**迁移**：`chat_sessions.owner_user_id`（可空）+ `visibility`（`NOT NULL DEFAULT 'workspace'`），幂等，每进程每数据库 URL 执行一次。

**已知缺口（需主人决定）**：
- `GET /api/agent-logs` 对所有人可见：工作区会话每轮的前 500 字摘要仍在其中（私有会话已不记摘要）。
- 报告没有归属：私有会话存成的报告对工作区可见（界面会提示），S6 再议。
- 私有会话里的内容可能经 agent 写出的东西流向工作区：agent 记忆（`memory_manage` / `record_agent_feedback` 写进 `agent-memory/*`，所有人可读并注入每个人的 agent）、从对话里提的变更单（标题 / 理由）、从对话里建的 issue。
- 「私有」的强度取决于 admin 账户：admin 能看所有私有会话，而未设置 `AIOPS_ADMIN_PASSWORD` 时种子 admin 的密码是默认值 `aiops2026`；`POST /api/auth/register` 公开可注册（得到 read/write）。建议开启认证的部署设置 admin 密码、并决定是否关闭自助注册。
- IM 会话仍出现在 web 列表中。

## S1c 单进程运行 + 事件循环不阻塞

**之前**：镜像 CMD 和 deploy-sg 的 systemd 单元都是 `uvicorn --workers 4`，`deploy.sh` 每次部署还会强制改回 4；而 chat / IM agent 缓存、连接器 / Galaxy / intake / Signal Gate 的锁、`PATCH /api/settings` 改的运行时设置都只存在于单个进程的内存里：相邻两轮对话落到不同 worker 时上下文分叉，同一指纹的两条告警可能建出两个 issue，打开 `rbac_enforce` 只在四分之一的 worker 生效。

**现在**：

- 所有部署都是一个 worker：`docker/Dockerfile`、`iac/deploy-sg/user_data.sh`、`iac/deploy-sg/deploy.sh`；`iac/eks` 的 `replicas` 和 `iac/ecs` 的 `desired_count` 校验为 ≤ 1，K8s 用 `Recreate`、ECS 用 0% / 100%，发布时不会短暂出现两个进程。
- 调度器的 flock（`<data_dir>/.scheduler.lock`）就是实例锁：持有者运行调度器，同一 data_dir 上的其他进程在启动时打 ERROR。删除了没有文档、还会让 shutdown 崩溃的 `AIOPS_SCHEDULER_WORKER`。
- 单进程下，`async def` 里的阻塞调用会卡住所有请求（包括 SSE 流），所以这些调用移出了事件循环：IM 回调的整轮 agent（原来在事件循环里直接跑）、告警 webhook 与 `POST /api/health-issues`（Signal Gate 持锁调用 Bedrock）、`/api/health` 的 STS、graph 拓扑接口、变更接口、技能生成、账户连接测试、报告生成、RAG pipeline，以及 chat 流里的 `/channel`、`/send_to` 和会话 agent 的构建。
- 事件循环的默认线程池（Strands 每个模型流和同步工具都会长期占一个线程）大小由 `event_loop_executor_threads` 决定（settings.yaml 默认 64）。

**非目标**：连接器 / Galaxy / intake 的数据库级锁与唯一索引；多副本 / 粘性路由 / 设置热重载；liveness 探针不再调 STS；IM WebSocket 在 `feishu_ws_enabled=false` 时仍会自启（单独问题）。

---

## S1 六个可达面（逐行）

- **CLI** — 做：`/session list` / resume / 名字回退 / `aiops chat --resume` 跳过私有会话。非目标：执行与 `/accept` 的行为不变（判决走同一函数）；`aiops web` / `service start` 本来就是单进程。
- **Web API** — 做：`FixExecutionResponse.post_check_binding`；`verification_reason` 改为逐 id 的句子；7 个 chat 接口与 `/api/reports/from-session` 走 `chat_access`，响应加 `visibility` / `owned_by_me`，PATCH 收 `visibility`；API key 调用与注册不再报错。没有新增端点。
- **Web UI** — 做：执行证据逐项配对、方案页 `pc-n`；会话可见性标记、切换、分享链接取名、存报告提示。单进程是部署形态，无 UI。
- **Agent tool** — 做：`get_approved_fix_plan` 完整且带 check_id；`save_execution_result` 写库前校验；`get_plan` / `get_execution_result` 带 id 与配对；执行器提示词。非目标：agent 不列举会话。
- **Schedule** — 做：调度器 flock 兼作单实例检测；删除 `AIOPS_SCHEDULER_WORKER`。
- **Notification** — 非目标：pending-acceptance 通知本来就带原因句，现在自动变成逐 id 的句子。

## 升级注意

1. **部署形态**：只能跑一个进程。自定义了 `--workers` 的部署请改为 1；第二个进程会在日志里打 ERROR。
2. **执行器结果形状**：每条 post-check 结果必须带 `check_id`（`get_approved_fix_plan` 列出的 `pc-n`）。不带 id 的结果不再能让执行 `passed`。
3. **会话可见性**：开启认证后，新会话默认私有；已有会话都是工作区会话，可见范围不变。
4. **数据库迁移**：启动时自动加两列，无需手工操作。

## S1 验收清单（主人手动）

1. **假通过已堵**：`pytest tests/test_post_check_binding.py tests/test_execution_verification.py -v` 中，9 月反例判 `pending_acceptance` 且原因点名 `pc-2`；本地起服务打开造好的 Issue，证据区 pc-2「无结果」、pc-1「上报了 2 次」，验收卡要求人工判断；6 kB 方案的测试证明执行器拿到全部步骤与 check_id。
2. **会话隔离**：本地 `AIOPS_API_AUTH_ENABLED=true` 起服务，注册 alice、bob；alice 新建会话（默认私有），bob 的列表里没有，直接打开 URL 显示不存在；alice 切成工作区可见后 bob 能看到、能继续对话，但没有改名 / 删除 / 切换模型的入口（API 返回 403）；alice 退出后 bob 在同一标签页登录，看不到 alice 的任何私有会话；用 API key 调会话接口返回 200；关闭认证重启，所有会话照旧可见。
3. **单进程**：三处部署文件都是 `--workers 1`；同一 data_dir 再起一个进程，日志出现 ERROR；`pytest tests/test_single_process.py` 证明 STS / 告警判官 / IM agent 慢的时候其他请求不被卡住。
4. **门禁**：见下。

## S1 门禁结果

2026-10-05，在 `MVP-2.7.0` 上（S1 全部提交之后）：

| 门禁 | 结果 | 基线（`1ec53b3`） |
|---|---|---|
| 后端全量 `pytest tests/` | **6449 passed / 85 skipped / 0 failed** | 6378 passed / 85 skipped |
| `npx tsc --noEmit` | 0 错误 | 0 |
| `npm test`（vitest） | **41 个文件 / 429 个测试全过**（含 locale 中英成对） | 39 个文件 / 418（另有 1 个 Playwright 脚本被误收集、恒失败，已在 `e9d4f48` 排除） |
| `npm run build` | 成功 | 成功 |

另做了两件事：
- **独立安全审查**（只审 S1b）：用真实认证中间件、真实登录和 API key 探测，确认 7 个路由上私有会话的 404 与不存在的会话完全相同；它提出的 2 个重要、2 个次要问题已在 `f154005` 修复，其余写进上面的已知缺口。
- **本地页面走查**：用临时库和真实执行路径造了 9 月反例，Issue 页显示「no result for post-check pc-2; post-check pc-1 reported more than once」、pc-1「reported 2 times」、pc-2「no result」，标题计数在 `a097d4c` 修正为「1 pass · 1 no result」（之前按原始条数写成「2 pass」）。

---

## S2 蓝白外壳与导航

计划：`docs/superpowers/plans/2026-10-05-mvp-2.7.0-s2-shell.md`（已批准；对抗审查 21 条修订已吸收）。主人决定：去掉 52px 图标折叠态和悬停预览卡；**深色模式保持绿色主色**（只有浅色变蓝白）；S2 仍把 Changes 与 Audit 分开放，S3 再合成「Plans & changes」。

**S2 只换外壳**：各页面内部版面不变（S3–S6 逐页改），但每个页面都落进新外壳、新配色。

### 改了什么

- **配色与字体**：浅色主题是蓝白——页面底色 `#F8FAFC`（新 token `--canvas`，只给页面背景用，卡片 / 对话框 / 输入框仍是白），选中底色 `#EFF6FF`（`--selected`），按钮悬停 `#1D4ED8`（`--primary-hover`），每个控件都有可见的键盘焦点环。Outfit 字体随前端一起打包（`@fontsource/outfit`），不再请求 Google Fonts，中文回退苹方 / 微软雅黑，等宽字体用系统字体栈。深色模式外观不变。
- **主题与字号**：`ThemeProvider` 覆盖整个应用（登录页也生效）；首次进入是浅色，不再跟随系统深色；`index.html` 在首次绘制前就应用主题、字号和 `<html lang>`，刷新不闪；字号（小 / 中 / 大）终于有了入口（头像菜单）。
- **侧栏**：200px 白色（≤1100px 166px，≤800px 隐藏，改由顶栏的下拉菜单导航）。分组：
  - **日常工作**：对话、问题（有未结问题时显示红点）、报告；
  - **运维工具**（可折叠）：变更、审计、资源、定时任务；
  - **管理**（可折叠）：运行总览（原仪表盘，现在在 `/app/overview`）、Agent 指标、技能、全景图、安全、设置。

  当前页所在的组会自动展开（不写偏好），用户手动展开 / 收起的状态存进偏好。组内仍可拖拽排序；旧的单列表顺序会迁移：从没拖过的用户（旧侧栏首次加载就存了默认顺序）直接用新分组，拖过的用户组内相对顺序保留，原先固定在底部的「设置」放在组尾。底部「首页与语言」可固定 `/app` 的默认入口；页脚显示版本。
- **顶栏**：64px（≤800px 56px）。左侧面包屑「AgenticOps / 分区 / 对象」（`I#5`、`C#3`、资源 `R#12`、报告 `#7`），同时设置页面标题。右侧依次是：搜索按钮（⌘K / Ctrl K，打开原有搜索面板；≤1100px 只剩图标，≤600px 隐藏）、`中文 | English` 切换、头像菜单（账户、主题、字号、首页与语言、退出登录；手机上也有）。
- **`/app` 首页解析**：固定首页（对话 / 问题 / 报告）> 继续上次工作（这个浏览器里该用户最后打开的白名单页面；新设备用服务端记录；对象页先探测一次，已删除或无权访问时回到列表并提示，不显示对象标题）> 对话。显式地址永远原样打开。
- **登录回跳**：未登录访问任何页面（以及任何 401）都会带 `?next=` 去登录，登录后回到原页面（含查询串和 hash）；`next` 只接受同源的 `/app` 页面。登录失败用当前语言提示「邮箱或密码不正确」。
- **404**：未知的 `/app/*` 显示「页面不存在」和回到对话的入口（之前是白屏）；旧链接 `/anomalies`、`/anomaly/{id}` 改为落到问题页（之前指向前端从未有过的路由）。
- **偏好与 bootstrap 接口**（契约 `workspace-ui-1`）：
  - `GET /api/ui/bootstrap`：用户、`deployment_id`（数据库里的随机 id，容器重启不变）、只报已实现能力的 `features`（`revision_guards` / `attention` / `context_chat` / `content_rendering` / `report_export` 目前都是 false）、按服务端真实分流规则导出的上传策略、偏好；2.7.0 扩展字段 `user` / `auth_enabled` / `version`；不含任何密钥或连接器配置。
  - `GET`/`PATCH /api/users/me/preferences`（新表 `user_preferences`）：首页、语言、上次位置、展开的组。每次写入都要带 `If-Match`（`"N"`、`W/"N"`、`N`，或 `*` 只合并本次字段）；缺少返回 428，版本过期返回 412；`last_route` 只接受白名单内的 `/app` 只读路由（服务端与前端共用 `tests/fixtures/ui_last_route_cases.json` 测试）。认证开或关都能认出登录用户（Bearer）。
  - 前端每个标签页串行写偏好；上次位置最多 30 秒写一次，页面关闭时用 keepalive 补写；登录后若服务端从未保存过语言，就沿用这个浏览器的语言。
- **S1 遗留**：`GET /api/settings` 改为普通 `def`，两个异步处理器里的 `_allowed_model_ids()`（可能同步列 Bedrock 模型）移到线程；CORS 放行 PATCH 与 `If-Match`、暴露 `ETag`。
- **中英文**：外壳的全部文案（分组、菜单、对话框、搜索、404、面包屑、登录页、搜索面板）都走 locale；`Chat` 的「上次会话」与上次位置都按用户分键，共享浏览器不会打开上一个人的内容。CLI 启动横幅里的「Dashboard」改为「Web」。

### S2 六个可达面

- **CLI** — 做（仅文案）：启动横幅「Web: …/app/」。外壳与偏好只属于 Web。
- **Web API** — 做：`GET /api/ui/bootstrap`、`GET`/`PATCH /api/users/me/preferences`；`GET /api/settings` 不再阻塞；CORS；`/anomalies*` 重定向。三个新端点都由外壳使用（下一行）。
- **Web UI** — 做：新侧栏、顶栏、首页解析、登录回跳、404 页、首页与语言对话框、头像菜单、配色与字体、`/app/overview`、手机端导航。
- **Agent tool / Schedule** — 非目标。
- **Notification** — 非目标：通知里的深链（`/app/issues/N`、`/app/changes/N`）原样打开，不受首页偏好影响。

### 升级注意

1. `/app` 不再是仪表盘：仪表盘在 `/app/overview`（侧栏「管理」组的「运行总览」）。
2. 新表 `user_preferences`、`installation` 由 `init_db` 自动建立。
3. 前端新增依赖 `@fontsource/outfit`（`package-lock.json` 已更新，镜像构建用 `npm ci`）。

### 已知缺口

- 侧栏拖拽排序没有键盘操作方式。
- 问题入口的红点数的是全部 `open` 状态（含安全发现），列表默认只看运维事件——准确计数随 S4 的列表一起做。
- 深色模式下 7 处「执行中」徽章仍偏绿（主人决定深色保持现状）。
- Vite 开发服务器直接打开 `/app`（无结尾斜杠）返回 404（生产环境 FastAPI 会 307 到 `/app/`），开发时请用 `/app/`。

### S2 验收清单（主人手动）

见计划文件「S2 交给主人的验收清单」九条：首访进对话、恢复上次工作（含已删除对象与换账号）、固定首页 + 深链优先 + 跨浏览器、登录回跳与恶意 `next`、旧链接与 404、侧栏分组与排序迁移、外观（蓝白、深色照旧、字号、中英、零外部字体请求）、窄屏、多标签页。

### S2 门禁结果

2026-10-05，在 `MVP-2.7.0` 上（S2 全部提交之后）：

| 门禁 | 结果 | S1 结束时 |
|---|---|---|
| 后端全量 `pytest tests/` | **6516 passed / 85 skipped / 0 failed** | 6449 passed / 85 skipped |
| `npx tsc --noEmit` | 0 错误 | 0 |
| `npm test`（vitest） | **44 个文件 / 520 个测试全过**（含 locale 中英成对） | 41 个文件 / 429（合并 2.6.1 后 42 / 441） |
| `npm run build` | 成功；产物无任何外部字体地址 | 成功 |

另做了：
- **独立审查**（外壳 + 偏好接口）：0 严重 / 4 重要 / 12 次要。重要的 4 条全部修复（畸形 URL 让整个应用白屏、当前页所在组收不起来、首页对话框选择被后台写入重置、字号与主题在菜单里不能用键盘操作），次要的修了 10 条（`ad75605`），其余写进下方已知缺口。
- **无头浏览器走查**（1440 / 1280 / 1100 / 1000 / 768 / 390）：首访进对话、恢复上次位置（先探测对象）、404 页、未登录深链 → 登录 → 回到原页、外部 `next` 被拒、浅色 / 深色、中英切换后 `<html lang>` 随之变化、无外部请求、对话页与全景图正好占满一屏、各宽度都没有横向滚动。

审查后补充的已知缺口：
- 偏好接口的 401 / 422 仍是平台通用的 `{"detail": …}` 形状，没有统一成契约的 `UiError {detail, code, trace_id}`（428 / 412 已是）。
- 恢复上次位置时对象会被请求两次（探测一次、页面一次）。
- 两个标签页同时展开 / 收起侧栏分组时，412 后的重放会以整张列表覆盖另一个标签页的改动。
- 表单输入框保留原有的边框 + 阴影焦点样式（同样可见），没有改用新的焦点环。
