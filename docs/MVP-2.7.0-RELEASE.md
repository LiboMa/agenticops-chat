# MVP-2.7.0 Release Notes — 蓝白工作台 + 核心信任加固（分阶段交付）

> Version: 2.7.0 · Branch: `MVP-2.7.0`（从 `MVP-2.6.1` 的 `1ec53b3` 切出）· 起始日期：2026-10-05 · 主题：先把会「假通过」「串号」「多进程失效」的核心信任问题修掉，再按主人 10-05 交付的蓝白设计包分阶段改造界面
>
> **状态：S1（核心信任加固）已于 2026-10-05、S2（蓝白外壳与导航）已于 2026-10-06 由主人验收通过；S3（方案与变更枢纽 +「需要你处理」）、S4（Cases 与 Resources）与 S5（Chat：会话上下文 + 账户绑定 + 幂等发送，含真实模型 E2E）已于 2026-10-07 由主人验收通过；S1–S5 已经主人同意推送到 `origin/MVP-2.7.0`（`5d82aec`）。S6–S7 尚未开始：每个阶段开工前先交详细计划给主人批准。** **10-06 追加核心能力轨 A1–A4（变更感知的系统模型，spec 已批准），与界面阶段并行推进；A1 详细计划待出、出后交主人批准（见文末「核心能力轨」节）。** 依主人铁律，只有 E2E 通过且当面确认后才 `git push --no-verify` / 打 `v2.7.0` tag。
>
> 全链规划（含 S1 详细计划）：`docs/superpowers/plans/2026-10-05-mvp-2.7.0-roadmap.md`
> 设计输入：`docs/AgenticOps_BlueWhite_Review.zip`、`docs/superpowers/specs/2026-10-05-blue-white-sre-workspace-design.md`、`docs/ui-contracts/2026-10-05/`

## 一句话

蓝白设计包里大约 65% 的工作量是界面与交付体验，真正动核心的只有几项；而其中三项是已经复核的缺陷：执行验收会被重复结果凑数通过、chat 会话对所有人可见、四个 worker 让内存态保证悄悄失效。MVP-2.7.0 把这三项作为第一阶段（S1）先修，再按「单位时间收益」逐阶段推进界面改造。

## 阶段与状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| **S1 核心信任加固** | 验收逐项绑定 check_id；会话归属 + private/workspace；单进程运行 + 事件循环不阻塞 | **已验收（2026-10-05）** |
| **S2 蓝白外壳与导航**（P0+P1） | 配色、字体本地化、分组侧栏、顶栏、首页解析器、登录回跳、`/app/overview`、bootstrap + 偏好接口 | **已验收（2026-10-06）** |
| **S3 方案枢纽 + 待办**（P4） | `/app/plans` 三标签 + `/app/plans/:id`、`GET /api/ui/attention` + 顶栏「需要你处理」、如实的批准措辞 + 核对勾选、方案状态 CAS、编辑防过期 | **已验收（2026-10-07）** |
| **S4 Cases 与 Resources**（P3） | 队列 + 阅读区双栏（保留 2.6.1 阶段卡）、HealthIssue 读取、补充说明、顶栏账户范围、询问 Agent、Resources 表格 | **已验收（2026-10-07）** |
| **S5 Chat**（P2） | 会话上下文与账户绑定、补充说明进上下文、`client_message_id` 幂等、派发状态与中断、流错误分类、草稿、附件规则、蓝白 Chat 页 | **已验收（2026-10-07）** |
| S6 报告与双语（P5） | 渲染服务 + 翻译、导出、发布确认 | 未开始 |
| S7 联合验收与发布（P6） | 文档、live E2E、版本串、`v2.7.0` tag | 未开始 |
| **A1 账本与分钟级**（核心能力轨） | `change_events` 账本 + 感知度（资源属性）+ Sensing Worker（CloudTrail / K8s events 拉取、增量刷新）+ RCA 接入 + 三端点 / CLI / Settings 感知卡 / 资源与问题页 | **spec 已批准（10-06），详细计划待出** |
| A2 live 级（核心能力轨） | live 探针、预算降级、`request_sensitivity`、两种端点采集、`VOLATILE_KEYS` 补齐 | 未开始 |
| A3 覆盖面（核心能力轨） | 锚定缺口重测、九种解析器、ALB → 目标组 | 未开始 |
| A4 评测门禁（核心能力轨） | 每夜 $0 指标、三个感知场景、`--assert`、再议 `sensing_enabled` 默认值 | 未开始 |

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

## S3 方案与变更枢纽 +「需要你处理」

设计：`docs/superpowers/specs/2026-10-06-mvp-2.7.0-s3-plans-attention-design.md`；实施计划：`docs/superpowers/plans/2026-10-06-mvp-2.7.0-s3-plans-attention.md`（主人 10-06 批准）。主人决定：
- 版式用**列表 + 独立详情页**（设计稿的双栏留到 S4 和 Cases 一起做）；
- 「需要你处理」**与详情页的「等你」口径一致**；
- **所有批准对话框**都要勾选核对项，并按真实效果写「批准」或「批准并执行」。

### 改了什么

- **方案与变更枢纽** `/app/plans?tab=fix|changes|audit`：
  - **修复方案标签**：修复方案第一次有了列表，筛选（状态分组 / 风险 / 账户 / 搜索编号、标题或资源）都写在 URL 里。
  - **变更标签**：原 Changes 列表 +「新建变更」。
  - **审计标签**：原 Audit；认证开启时只给管理员看，方案引用可点到方案页。
  - 标签上的数字 = 该标签里「需要你处理」的条数。
  - 侧栏「运维工具」里的变更 + 审计合成一项「方案与变更」：旧路径仍归它高亮；已保存的排序原位保留（v1 / v2 迁移都改名）。
  - `/app/changes`、`/app/audit` 跳到对应标签并保留查询串；`/app/changes/:id` 不变；面包屑修好（`/app/changes/3` 显示「方案与变更 / C#3」）。
- **修复方案详情** `/app/plans/:id`，按设计稿首屏顺序：
  - 页头：方案标签、风险、状态、执行状态；
  - 来源事件、目标资源（只有已锚定时才可点）、region、内容哈希；
  - 改什么 / 检查项 / 回滚（复用 PlanView）；
  - 审批记录（含审批理由）、执行记录；
  - 页脚说明「审批绑定当前版本和目标范围」。
  - 变更方案的 id 跳到它的变更单。不存在或无权查看时提示，不报错。
- **如实的批准**：
  - 批准按钮和对话框的标题、说明，按服务端给的效果写：自动执行开着写「批准并执行」，关着写「批准」，并说明「批准后需要再点执行」。覆盖事件详情、变更详情、方案详情和 Chat 面板四处。
  - 四处批准都要先勾选「我已核对当前版本、目标范围、风险及恢复验证条件」。
  - Chat 面板的执行确认不再是写死的英文；运行中、执行器关闭时不显示执行按钮。
- **顶栏「需要你处理」**：
  - 按钮在搜索左边，数字 = 弹框行数，≤1100px 只显示数字。
  - 点开是一个模态框，每个工作项一行：标题、编号、一句话理由。点一行直接到决定它的位置（批准在方案页，澄清、验收、生成方案在对应卡片）。弹框里不直接批准。
  - 每 30 秒刷新一次；批准、驳回、执行、变更动作、验收、事件状态、RCA 评价、设置改动之后立即刷新。
- **防并发**：FixPlan 状态写入改为条件更新（`UPDATE … WHERE status=旧值`，0 行 → 409）。两个人同时批准同一方案时只有一个成功，只起一个执行；Web、CLI、agent、变更服务所有入口一起受保护。
- **两个死角修好**：
  - 方案被驳回后，事件页给「生成方案」（不再是没有按钮的「等审批人」）。
  - 撤回已批准方案后，事件回到「已定位根因」（不再给出必然失败的「重试」）。
- **「等谁」前后端一份规则**：`services/work_phases.py` 逐输入移植了前端的 `issuePhases` / `changePhases` / `currentFixPlan` / `inFlightAutoRun` / `notQueuedFrom`。两边共用夹具 `tests/fixtures/work_item_phase_cases.json` 和 `auto_run_cases.json`，pytest 与 vitest 各跑一遍。

### 接口与契约补充

- `GET /api/ui/attention?account_id&limit&cursor`（契约 `AttentionPage`）：
  - 每行带 `ref`（`I#12` / `C#3`）和 `reason_detail`。
  - `reason` 在契约四个值之外，多了 `review_required` 和 `execution_not_started`。
  - 谁能看到按严格策略判断：申请人看不到自己变更的审批；草稿与澄清只给申请人（申请人不是登录用户时给管理员）。
  - 行不因配置隐藏：执行器关闭时照样显示，动作标 `allowed:false`。
  - 共约 6 个批量查询，不调模型，不访问云。
  - bootstrap 的 `features.attention` 改为 true。
- `GET /api/fix-plans` 与 `GET /api/fix-plans/{id}`：
  - 每行带 `issue_title`、`issue_status`、`target` 和 `available_actions`（`{action, allowed, reason_code, effect}`）。
  - `status` 接受逗号分隔的多个值（未知值返回 422）；新增 `q`。
  - 改为普通 `def`，查询数固定。
- `GET /api/changes/{id}` 带 `available_actions`。
- 动作评估只用 `RbacPolicy.decide()`，看页面不会写审计行。`allowed` 等于路由实际行为；影子模式下仅靠宽容放行的动作标 `reason_code: "policy_shadow"`。
- `PUT /api/fix-plans/{id}`：改内容字段必须带读取时的 `content_hash`，缺失返回 422，过期返回 409。`status:"rejected"` 别名不受影响。
- `revision_guards` 仍为 false：防过期靠 `content_hash`，不用 If-Match。

### S3 六个可达面

- **CLI** — 非目标：`/approve` 的输出已经如实（修复方案只批准；变更会说明是否已排队）。CAS 在模型层自动覆盖 CLI。
- **Web API** — 做：见上节。新端点的界面在下一行。
- **Web UI** — 做：枢纽三标签、`/app/plans/:id`、跳转、侧栏合并、顶栏待办和弹框、四处批准、Chat 面板执行确认。
- **Agent tool** — 非目标：agent 不看个人待办。CAS 在模型层覆盖 agent 的批准。
- **Schedule** — 非目标。
- **Notification** — 非目标：通知深链 `/app/changes/N`、`/app/issues/N` 行为不变。

### 升级注意

1. `/app/changes` 与 `/app/audit` 现在是枢纽的两个标签（旧链接自动跳转）；修复方案有自己的页面 `/app/plans/:id`。
2. `PUT /api/fix-plans/{id}` 改内容要带 `content_hash`（仓库里没有界面或 CLI 调它；外部脚本需要补上）。
3. 不需要迁移数据库。

### 已知缺口

- 事件上「等你」的几步（生成方案、重跑 RCA、标记解决、RCA 评价）后端没有权限检查，所以待办对所有登录用户显示。
- 认证关闭时，所有人看到同一份全权列表（`web:anonymous`）。
- CLI 批准修复方案不会自动执行，与 Web 不一致（既有行为）。
- `generate-fix-plan`、`rca`、`PUT /api/health-issues/{id}`、`rca-feedback` 四个处理器仍是 `async def` 里做同步 DB 操作（S1 遗留）。

### S3 验收清单（主人手动）

见设计文档 A6 的十条：
1. 侧栏与跳转
2. 修复方案标签
3. 方案详情
4. 如实措辞（自动执行开 / 关）
5. 防重复批准
6. 待办（谁看得到、处理完减一、数字等于行数）
7. 审计标签权限
8. 编辑防过期
9. 撤回死角
10. 中英文

### S3 门禁结果

2026-10-06，在 `MVP-2.7.0` 上（S3 全部提交、含审查修复之后，主检出）：

| 门禁 | 结果 | S2 结束时 |
|---|---|---|
| 后端全量 `pytest tests/` | **6695 passed / 85 skipped / 3 failed**，三条都与 S3 无关：<br>· 两条由主检出里主人未提交的文件引起：`test_claude5_bedrock_models::test_defaults_upgraded`（`config/settings.yaml` 改了模型）、`test_prompt_budget::test_no_cjk_in_base_prompts`（`reporter_agent.py` 新增一行中文提示词）；<br>· 一条是本机 DNS 的已知假失败：`test_web_tools::test_invalid_headers_json`，example.com 被解析到 198.18.0.x，SSRF 守卫先拦下 | 6516 passed / 0 failed（worktree，无主人改动） |
| `npx tsc --noEmit` | 0 错误 | 0 |
| `npm test`（vitest） | **48 个文件 / 610 个测试全过** | 44 / 520 |
| `npm run build` | 成功；产物无外部字体地址 | 成功 |

另做了：
- **无头浏览器走查**（1440 / 1100 / 768 / 390，admin 与 alice）：
  - 旧链接跳转时保留查询串；面包屑正确；侧栏合并成一项；
  - 筛选写进 URL，标签上有计数，点击行进入详情；
  - 自动执行关闭时，方案页按钮写「Approve」，不勾选核对项不能确认；
  - 变更方案的 id 跳到对应变更单；不存在的 id 有提示；
  - 待办：数字 8 = 8 行，点一行跳转并关闭弹框；
  - 窄屏只显示数字、没有横向滚动；中文、深色正常；
  - 零外部请求，零页面报错；alice 看不到审计标签。
- **独立审查**（整个 S3 分支）：0 严重 / 6 重要 / 13 次要。6 条重要全部修复，另有 2 条次要因影响按重要处理，也一并修复。每条都先有失败测试：
  1. CLI `/execute` 在并发失败时让对话会话崩溃 → 改为提示「已被他人处理」。
  2. 变更标签保留了查询串但不按它筛选 → 筛选写进 URL。
  3. 方案页不显示它在哪个账户执行 → 补上（账户是审批绑定的内容之一）。
  4. 自动执行关闭或方案被撤回后，过闸门的诊断永远「等 SRE agent」 → 改为等你，并进入待办，理由「诊断已过闸门，需要生成方案」。
  5. 自动执行运行中仍可撤回 → 409，按钮同时说明原因。
  6. 输掉并发的批准不刷新页面 → 任何结果都重新读取方案；每个批准对话框都发送打开时显示的那个哈希。
  7. 方案页在执行过程中不刷新 → 运行期间轮询。
  8. 自动执行关闭时，③ 卡片仍提示「L0/L1 会自动执行」 → 按真实开关措辞。

  其余次要问题写进下方已知缺口。

审查后的次要问题（13 条）：
- 10 条已修复：
  - 方案页标题不再重复；
  - 撤回的方案显示撤回人和理由；
  - 搜索区分 `I#`（事件）和 `P#` / `#`（方案）前缀；
  - 没有哈希的旧方案编辑一次被拒后就能拿到哈希；
  - 遗留的非对象 `metric_data` 不再导致列表报错；
  - 「已批准未开始」计入修复方案标签；
  - 弹框打开时不再位移（S2 的首页对话框一并修好）；
  - 标签栏有 tabpanel 和方向键操作，待办按钮加载时不再读作 0；
  - 200 行上限会给出提示，搜索框跟随浏览器前进后退；
  - 非管理员在加载期间不再闪现审计标签。
- 仍未修的已知缺口：
  - 修复方案的批准、驳回、执行和 PUT 处理器，与上文四个处理器一样，仍是 `async def` 里做同步 DB 操作（S1 遗留）。
  - 标签计数取自前 100 条待办。

验收中发现的旧缺陷（2.6.0 起）：事件详情页的「生成方案」「重跑 RCA」「标记已解决」一律返回 500。
- 原因：`/api/issues/{id}` 和 `/api/anomalies/{id}` 这几个别名路由直接调用底层处理器，执行者参数没传下去（`d23bce3` 给底层处理器加执行者依赖时漏改了别名）。
- 已修（`c8162b1`）：五个别名都改为传入会话执行者，并加了一条扫描测试——以后任何路由直接调用带 `Depends` 参数的处理器而没把参数传全，测试都会失败。

---

## S4 Cases 与 Resources

设计：`docs/superpowers/specs/2026-10-07-mvp-2.7.0-s4-cases-resources-design.md`；实施计划：`docs/superpowers/plans/2026-10-07-mvp-2.7.0-s4-cases-resources.md`（主人 10-07 批准；按主人指示在 S3 验收前开工）。主人决定：
- 顶栏**一个全局账户范围**，替换各页自己的账户筛选；按用户存在本浏览器。
- 补充说明**只追加**，进处理记录，带作者和时间，不能改也不能删；写入要 write 权限。
- S4 里 **Agent 不读补充说明**（S5 随 Chat 上下文一起做）；「询问 Agent」只负责带着事件打开 Chat。
- 队列**保留现有筛选**（运维 / 安全 / 全部、状态、严重度、搜索），全部改为服务端筛选并写进 URL；一次最多 200 条，超过时提示。
- 事件详情保留 2.6.1 的阶段卡，不做标签页。

### 改了什么

- **Cases 双栏** `/app/issues`：
  - 屏幕 ≥1280px 时左边是队列（300px，≤1350px 时 280px），右边是阅读区（最宽 960px）。没选中时阅读区提示「请选择列表中的记录」。
  - `issues` 改成嵌套路由：换事件时队列不重新挂载；阅读区每个事件挂一个新的 IssueDetail（`key = id`），切换时对话框、草稿、滚动位置都不会带到下一个事件。
  - 两栏各自滚动，整页不滚。
  - 队列每行是真链接（可中键开新标签），带编号、严重度、标题、「资源 · 状态 · ×N」、等谁；选中行 `aria-current`。上下键只移动焦点，回车或点击才选中。
  - 筛选（运维 / 安全 / 全部、状态分组、严重度、排序、搜索）都写进 URL，刷新后保持；选中一条时保留查询串。搜索支持 `I#3` / `3` 直接找到编号。
  - 行内快捷操作和选项旁的计数去掉了：操作都在阅读区；计数以前只数已加载的 50 条，本来就不准。
- **窄屏**（<1280px）：`/app/issues` 只显示列表，`/app/issues/:id` 显示全屏详情（打开时滚到顶部，有 hash 时除外）。
  - 从队列进入的返回走浏览器历史；深链进入的返回到带同一查询串的列表。
  - 回到列表时恢复滚动位置，焦点回到原来那一行（按查询串分键存在 sessionStorage，用一次即清）。
- **顶栏账户范围**（「需要你处理」和搜索之间；手机上在头像菜单里）：
  - 事件队列、修复方案标签、变更标签、资源表格、「需要你处理」（按钮计数、弹框、枢纽标签计数）都只看这个账户。弹框写明「已按 X 筛选」。
  - 详情页上变灰（「详情页显示该记录自己的账户」）；宽屏双栏下仍可用，因为队列就在旁边。
  - 总览、安全、全景图、Chat、设置等不受它约束的页面也变灰，并提示「本页不按账户筛选」。
  - 存的账户已经不存在时回到「全部账户」；账户列表加载中保留原选择。
  - 旧链接里修复方案的 `?account=`、变更的 `?account_id=`：进入时读一次，设为全局范围，从 URL 里去掉，并提示「已按链接设置账户范围」。
- **补充说明**：
  - 事件处理记录卡里有输入框（你有 note 权限时才出现），保存后作为单独一条显示：「补充说明」、原文、作者、时间。
  - 只按纯文本渲染（`<script>` 原样显示）；永不合并成 ×N，也不会因为和状态句相同而隐藏。
- **询问 Agent**：事件 ⋯ 菜单 →「询问 Agent」打开 `/app/chat?ref=I<id>`：
  - 不恢复上次会话，打开新对话，上下文面板显示这个事件；
  - `ref` 读完就从 URL 去掉；什么都不自动发送；
  - 在欢迎页发第一条消息（手打或点面板「让 Agent 核对」）后，新会话页上面板仍然开着。
- **Resources 表格** `/app/resources`：
  - 列：名称（下一行原生 id）、类型、账户、区域、生命周期（存在 / 已消失）、健康（四值徽标 + 未结事件数）、最近观测（`scanned_at`）。
  - 健康：没有未结事件显示「未知」，**永不显示「健康」**。
  - 每行是真链接（名称链接撑满整行）；筛选和页码写进 URL；全部文案走 locale；表头点击排序去掉了（它只能排当前这一页）。
- **全部改读 HealthIssue**：
  - `useAnomalies` 和 `Anomaly` 类型删除。新 `useHealthIssues` 的查询键仍以 `["anomalies", …]` 开头，所有已有的失效调用照常生效。
  - 顺带修好：全景图的事件对话框以前把 HealthIssue 当 Anomaly 读，指标、类型、区域全空；现在从 `metric_data` 读出。

### 接口与契约补充

- `GET /api/health-issues`：
  - 改为普通 `def`；
  - 新增 `scope=ops|security|all`（默认 `all`，与 `/api/anomalies` 共用 `web/helpers.issue_scope_filter`）；
  - `status`、`severity` 接受逗号列表，未知值返回 422；
  - `q`：标题、资源 id 的 ILIKE（转义 `%` `_`），`I#12` / `12` 匹配编号；
  - `sort=newest|oldest|severity`；`limit` ≤ 500。
  - 返回形状不变。
- `POST /api/health-issues/{id}/notes`（`services/issue_notes.py`）：
  - 请求体 `{content}`，`extra="forbid"`，作者是会话执行者，不取请求体。
  - 内容去掉首尾空白后 1–8000 字；拒绝 NUL 和除 `\t` `\n` `\r` 外的控制字符。
  - 顺序：404 → `authz.check(issue.note)` 403 → 内容 422。
  - 在请求自己的事务里插入一条 `note_added` PipelineEvent（不经 `log_event`，它会吞错）；返回 201 `IssueNote {event_id, health_issue_id, content, actor, created_at}`。不改事件状态。
- 新权限 `issue.note: [write]`：`authz.PERMISSIONS`、`DEFAULT_POLICY`、`config/rbac.yaml` 同一提交。
- `GET /api/health-issues/{id}`：改为普通 `def`，带 `available_actions: [{action:"note", allowed, reason_code, effect:"update"}]`，用 `ui_actions.route_allows` 计算（看页面不写审计行）。
- `GET /api/resources`：
  - 改为普通 `def`，按 `(resource_type, id)` 排序，翻页不重复也不漏；
  - 每行带 `open_issues` 和 `health`（`graph/query_service.health_overlay`，与全景图同一个四值定义：只算未结、同账户、按 `resource_ref` 锚定的事件；没有 = `unknown`）。

### S4 六个可达面

- **CLI** — 非目标：CLI 没有事件详情视图；补充说明是 Web 上的人工动作（以后可以加 `/note`）。
- **Web API** — 做：见上节。
- **Web UI** — 做：Cases 双栏与窄屏全屏、顶栏账户范围、补充说明、询问 Agent、Resources 表格、HealthIssue 迁移（含全景图对话框修复）。
- **Agent tool** — 非目标：S4 不读补充说明（主人决定，S5 做）。
- **Schedule** — 非目标。
- **Notification** — 非目标：通知深链 `/app/issues/N` 在宽屏打开双栏、窄屏打开全屏，行为兼容。

### 升级注意

1. 事件列表的账户下拉、修复方案标签和变更标签的账户下拉、资源页的账户下拉都没了，改用顶栏的账户范围。旧链接里的账户参数会被自动采纳。
2. `GET /api/health-issues` 默认 `scope=all`，其他调用方行为不变；Web 队列默认 `ops`。
3. 不需要迁移数据库。

### 已知缺口

- 影子模式（`rbac_enforce=false`）下，没有 write 的用户写补充说明也会成功（审计为 `authz.denied_shadow`），与全平台一致。
- 没有账户的事件和变更（`account_id` 为空）在选了某个账户后看不到。
- 总览、安全、全景图、侧栏红点不按账户范围筛选（页面上会提示）。
- `/api/resources/{id}/issues`（资源详情的事件标签、全景图节点面板）仍按资源 id 字符串匹配，和健康列按锚点的口径不同。
- `HealthIssue` 的 `detected_at` 和 `account_id` 没有索引，`q` 用 ILIKE：在当前规模下可以接受。
- 队列搜索不再匹配区域（旧列表在浏览器端能搜到区域）：区域存在 `metric_data` JSON 里，服务端搜索只查标题、资源 id 和编号。

### S4 验收清单（主人手动）

见设计文档 A3 的九条：
1. 双栏
2. 筛选
3. 窄屏
4. 账户范围
5. 补充说明
6. 询问 Agent
7. Resources
8. 全景图对话框
9. 中英文

### S4 门禁结果

2026-10-07，在 `MVP-2.7.0` 上（S4 全部提交、含审查修复之后，主检出）：

| 门禁 | 结果 | S3 结束时 |
|---|---|---|
| 后端全量 `pytest tests/` | **6730 passed / 85 skipped / 3 failed**，三条与 S3 时相同、都与 S4 无关：两条由主人未提交的 `config/settings.yaml` / `reporter_agent.py` 引起，一条是本机 DNS 的已知假失败（`test_web_tools::test_invalid_headers_json`） | 6695 passed / 3 failed |
| `npx tsc --noEmit` | 0 错误 | 0 |
| `npm test`（vitest） | **51 个文件 / 659 个测试全过** | 48 / 610 |
| `npm run build` | 成功；产物无外部字体地址 | 成功 |

另做了：
- **无头浏览器走查**（1440 / 1366→1024 / 1000 / 390，admin 与 alice，中文与深色）：36 项检查全过，其中：
  - 双栏选中保留查询串、切换事件阅读区回到顶部、整页不滚；
  - 超过 200 条有提示且只显示 200 条；`I#3` 搜索写进 URL、刷新后保持；严重度服务端筛选；
  - 1000 / 390：全屏详情在顶部，页内返回与浏览器后退都回到原滚动位置、焦点回到原行，深链返回到带同一查询串的列表，无横向滚动；
  - 账户范围：事件、资源跟随；方案标签没有自己的账户下拉；待办弹框写明「已按 s4-prod 筛选」；详情页锁定、总览变灰；旧链接 `?account=2` 被采纳、去掉并提示；刷新后保持；
  - 补充说明：alice 与 admin 各写一条，作者分别是 `user:alice@…` 与 `user:admin`；`<script>` 原样显示为文本；
  - 询问 Agent：⋯ →「询问 Agent」打开 `/app/chat`，面板显示 I#7，零 POST（即使存着上次会话）；
  - Resources：七列齐全、无事件显示「未知」、整行可点、已消失的资源只在勾选后出现、筛选写进 URL；
  - 全景图事件对话框：指标名、实际值、期望值、偏差、类型、区域都有值；
  - 零页面报错、零外部请求。
- **独立审查**（整个 S4 分支 `56bc977..dc894d1`）：0 严重 / 1 重要 / 7 次要，修复在 `d71601d`，每条先有失败测试或无头复现：
  1. （重要）宽屏下选过几条后窗口变窄，「← 事件」会一条条退回之前看过的事件 → 只有窄屏的列表 → 详情这一步标为「从队列进入」。
  2. 展开 / 收起阶段卡会丢掉这个标记 → 改 hash 时保留历史状态。
  3. 旧链接里不存在的账户 id 会提示「已按链接设置账户范围：—」→ 只采纳确实存在的账户；关掉的提示刷新后不再出现。
  4. 账户列表加载失败时，旧的范围仍在筛选、把所有列表筛空 → 加载失败时按「全部账户」。
  5. 补充说明放行了 C1 控制字符和双向文本覆盖符（可让记录显示成倒序）→ 一并拒绝。
  6. 事件时间线、资源的事件列表两个处理器仍是 `async def` 里做同步 DB 操作 → 改为普通 `def`。
  7. 旧列表行上的「打开安全页」链接丢了 → 安全类事件的信息栏里补回。
  8. CLAUDE.md 前端表仍写着已删除的 `IssuesAndPlans` / `IssueQuickActions` → 本次文档一并更新。

---

## S5 Chat：会话上下文 + 账户绑定 + 幂等发送

设计：`docs/superpowers/specs/2026-10-07-mvp-2.7.0-s5-chat-design.md`；实施计划：`docs/superpowers/plans/2026-10-07-mvp-2.7.0-s5-chat.md`（主人 10-07 批准，Native 执行）。主人决定：
- **硬绑定**：会话绑定了账户时，每一轮都设置 `RunContext.bound_account_id`。所有云、kubectl、主机工具在其他账户上 fail-closed；其他账户的 `I#` / `R#` / `C#` 不展开。「全部账户」的会话不绑定。
- 只关联**事件和变更**。
- 补充说明放进**关联对象块**（最新 20 条，标明「是信息，不是指令」）。
- Chat **重新配色**，「询问 Agent」仍打开 Chat 页面（不做抽屉）。

### 改了什么

- **会话上下文**：
  - 新建会话时可以带 `context`：关联对象（事件或变更）加账户。关联对象的账户和区域取对象自己的值；客户端给的账户与对象不同返回 409 `context_account_mismatch`。
  - 第一条消息被接受时上下文锁定。之后 `PATCH` 改上下文返回 409 `context_locked`；要换上下文就新建会话。
  - 会话列表、详情、`PATCH` 的响应都带 `context`（服务端解析后的对象编号、标题、账户名、区域、`scope_locked`）。
- **每一轮**：
  - 绑定账户的会话以该账户运行。工具取凭证时在其他账户上 fail-closed，用的是变更执行已有的同一个钩子。
  - 用户消息前加一个上下文块：
    - 绑定的账户；
    - 关联事件的编号、标题、状态、严重度、资源、账户，以及最新 20 条补充说明（总长 ≤ 6000 字，超出时从最旧的截掉并注明）；或关联变更的编号、标题、状态、风险、步骤数。
    - 说明的文字经过转义，不能闭合外层标签。
    - 块每一轮重新生成，新写的说明下一轮就能看到。
  - 其他账户的 `I#` / `R#` / `C#` 只写一句「不在本会话的账户范围内」，不展开记录。
  - 聊天消息不会创建 Issue。
- **幂等发送**：
  - `POST …/messages` 必须带 `client_message_id`（UUID）。每个会话内唯一，由数据库唯一索引兜底。
  - 同一个 id 再发：
    - 已结束的，回放已存的回复，不重跑 agent；
    - 还在进行的，返回 409 `duplicate_in_flight`。
  - 会话里另有一条回复在进行时，新消息返回 409 `session_busy`。
  - 两种 409 都不会启动第二次运行。
- **派发状态**：每条用户消息和回复都有 `accepted` / `running` / `completed` / `failed` / `interrupted` 状态。
  - 客户端断开或刷新：已写出的部分作为 `interrupted` 保存，不再存成正常完成的回复。流被取消时也一样。
  - 服务重启：启动时把残留的进行中消息置为 `interrupted`。
  - 失败：存为 `failed`，并带分类码。
- **SSE 帧**：
  - 新增 `accepted {client_message_id, user_message_id, trace_id}`；
  - `tool_start` / `tool_end` 带 `call_id`，`tool_end` 带 `outcome`（`ok` / `error` / `unknown`，来自工具结果，不按工具名推断）；
  - `done` 带 `terminal_status` 和消息 id；
  - `error` 改为 `{code, message, trace_id}`，`code` ∈ `throttled` / `model_unavailable` / `context_too_long` / `internal`，异常原文只写日志。
- **前端流客户端**：
  - 新的完整帧 SSE 解析器：处理 CRLF、空行分帧、多行 data、跨块的 UTF-8。
  - 每次发送带 `client_message_id`。不自动重试；无论成功与否都重新读取历史。
  - 错误按代码显示本地化说明。
- **输入框**：
  - 草稿按「安装 + 用户 + 会话」存在本浏览器，换页、切换语言、刷新都在。
  - 附件按会话留在内存。刷新后提示「有 N 个附件未发送，请重新选择」，不声称附件可以重放。
  - 附件规则从 bootstrap 的 `upload_policy` 读取，与后端一致（`.html` / `.xlsx` / `.toml` 等以前前端拒绝的类型现在可以选）。
  - 按钮和占位文字走 locale。
- **蓝白 Chat 页面**：
  - 空状态：「想处理什么？」、三个起手提示（只填入输入框，不发送）、附件个数提示。
  - 输入框上方一行写明上下文：「关联：I#12 · 标题」、「环境：账户 · 已绑定到本对话」或「环境：全部账户」。
  - 关联会话的页头带编号、标题和「查看事件 / 变更」。
  - 中断和失败的回复有各自的标签。
  - 工具失败显示红点。
  - 会话列表每行写明关联编号，或「独立请求」。
  - 停止回复后提示「已经排队或在执行的操作不受影响」。
- **顶栏账户范围**：
  - 在 `/app/chat`（新会话）上可用，选中的值就是新会话的账户。
  - 打开的会话锁定显示该会话的账户。
  - 「询问 Agent」进入时，锁定显示事件或变更的账户。
- **顺带修好**：
  - 以表单编码 POST 消息、或 JSON 格式错误时，以前返回 500，现在返回 422。
  - `aiops quickstart --scan` 发送的扫描消息带上了 `client_message_id`，并检查返回；以前从不检查，失败了也说「已触发」。

### 接口与契约补充

- `ChatSessionCreate` / `ChatSessionUpdate` 新增 `context: {primary: {entity_type: health_issue|change_request, entity_id} | null, account_id, region}`，`extra="forbid"`。
- `ChatSessionResponse.context` 返回服务端解析后的上下文。
- `ChatMessageCreate.client_message_id`：必填，UUID；multipart 用同名表单字段。
- `ChatMessageResponse` 新增 `client_message_id`、`dispatch_state`。
- 409 的响应体为 `{"detail": {"detail", "code", "trace_id"?}}`，`code` ∈ `context_account_mismatch` / `context_locked` / `session_busy` / `duplicate_in_flight`；404 `context_not_found`；422 `unknown_account`。
- bootstrap `features.context_chat = true`；`chat_replay` 仍为 false（不承诺断线后的流重放）。
- 迁移：2.7.0 增量迁移，给 `chat_sessions` 加 5 列、给 `chat_messages` 加 2 列，再加唯一索引 `uq_chat_message_client_id`。旧行全部为 NULL（独立会话，状态视为已完成）。

### S5 六个可达面

- **CLI** — 非目标：CLI 对话没有会话上下文。`quickstart --scan` 已补上 `client_message_id`。
- **Web API** — 做：见上节。
- **Web UI** — 做：Chat 页面的上下文、草稿、附件、错误与中断显示、蓝白页面，以及顶栏范围在 Chat 上的启用和锁定。
- **Agent tool** — 做（间接）：绑定账户让所有带凭证的工具在其他账户上 fail-closed；上下文块把补充说明带给 agent。不新增工具。
- **Schedule** — 非目标。
- **Notification** — 非目标。

### 升级注意

1. `POST /api/chat/sessions/{id}/messages` 现在必须带 `client_message_id`（UUID），缺失返回 422。仓库内的调用方（Web、`aiops quickstart`）已更新；外部脚本需要补上。
2. 启动时会执行增量迁移（加列、加索引），不需要手工操作。

### 已知缺口

- 「全部账户」的会话不绑定，工具照旧按显式 account → 库存反查 → 单账户默认解析。
- 关联对象自己没有账户时，会话不绑定。
- 绑定只约束工具取凭证和引用展开；agent 回复里提到的其他账户的已知事实（例如记忆）不在约束范围内。
- 补充说明总长有上限，超出时只给最新的部分。
- IM（飞书 / Slack）和 CLI 会话不带上下文，也不去重。
- 不提供断线后的流重放：刷新后只读取已保存的历史。
- 一条消息被认领后 60 秒内流还没开始，就当作已死，下一次发送会把它关闭为「已中断」。
- 工具「失败」的判定依赖结果文字（`Error:` 开头或绑定拒绝语句）；子 agent 用自己的话转述的失败可能显示为成功。

### S5 验收清单（主人手动）

见设计文档 §5 的十条：
1. 询问 Agent → 关联会话
2. 硬绑定
3. 账户不一致与锁定 409
4. 幂等
5. 中断
6. 错误分类
7. 草稿
8. 附件
9. 蓝白页面
10. 停止 ≠ 取消

### S5 门禁结果

2026-10-07，在 `MVP-2.7.0` 上（S5 全部提交、含审查修复之后，主检出）：

| 门禁 | 结果 | S4 结束时 |
|---|---|---|
| 后端全量 `pytest tests/` | **6813 passed / 85 skipped / 3 failed**，三条与 S3、S4 时相同、都与 S5 无关（主人未提交的 `config/settings.yaml` / `reporter_agent.py` 两条，加本机 DNS 的已知假失败） | 6730 passed / 3 failed |
| `npx tsc --noEmit` | 0 错误 | 0 |
| `npm test`（vitest） | **55 个文件 / 698 个测试全过** | 51 / 659 |
| `npm run build` | 成功；产物无外部字体地址 | 成功 |

另做了：
- **无头浏览器走查**：S5 共 23 项全过。验收环境的 agent 换成桩（`/tmp/aiops-s3-accept/stub/sitecustomize.py`，只在验收环境，不进产品代码），它回显收到的内容，所以走查不调用任何模型。覆盖：
  - 询问 Agent 后，补充说明到达 agent，顶栏锁定，`?ref` 离开 URL；
  - 绑定 s4-lab 的会话拒绝展开 s4-prod 的 `I#`，agent 收到 `bound_account_id=2`；
  - 账户不一致和锁定后的 `PATCH` 都返回 409；
  - 同一个 id 重复发送只回放、只存一条；
  - 中途刷新后显示「已中断」；
  - 限流显示本地化说明，不显示异常原文；
  - 停止后有提示；
  - 草稿跨换页、换语言、刷新都在，刷新后提示重新选择附件；
  - 第 6 个附件被拒，`.html` / `.xlsx` 可选；
  - 中文、深色、390px 无横向滚动；零页面报错，零外部请求。
  - S4 走查回归 36 项全过。
- **独立审查**（整个 S5 分支 `76f40f8..a230718`）：1 严重 / 5 重要 / 6 次要。严重和重要的全部修复，每条先有失败测试；另有 2 条次要按实际影响升级后修复：
  1. （严重）账户绑定只在凭证解析器一处检查。`sre_query`、扫描、RCA、执行器等子 agent 直接从 provider 构建 CLI 工具，绕过了检查：绑定 s4-lab 的会话仍能在 s4-prod 上执行命令。现在 `providers/base.get_provider()` 在绑定运行中拒绝其他账户（所有路径都经过这里）；并行巡检把运行上下文带进它的工作线程（`a2dbce7`，6 个测试）。
  2. agent 构建在 `try` 之外：构建失败时消息停在 `accepted`，会话一直「忙碌」。现在构建移入 `try`（失败即记为 `failed`）；「忙碌」只看本进程里活着的派发；没有活着派发的残留行会被关闭为「已中断」，不再挡住会话（`994beed`）。
  3. 回放可能拿到后一条消息的回复和错误状态。现在状态取原消息自己的，回复只取它自己的那条（`994beed`）。
  4. 重启中断的消息没有可以显示标签的回复。现在启动清理和死行关闭都补一条「已中断」的回复（`994beed`）。
  5. 被绑定拒绝的工具调用显示为成功（CLI 工具以 `Error:` 字符串返回）。现在 `Error:` 开头或带绑定拒绝语句的结果判为失败（`dcb6ffe`）。
  6. 草稿在发送成功前就被清除。现在 `chatStream.send` 返回服务端是否接受；被拒（409、网络、会话没建成）时输入框把文字和附件还回来（`80a7ac5`）。
  7. （次要升级）最新一条说明超过上限时，所有说明都不见了。现在截断这一条（`358f4de`）。
  8. （次要升级）事件块补上区域（设计 §2①）（`358f4de`）。
- **真实模型 E2E**（2026-10-07，验收环境换回真实 agent：main 为 Opus 5.5，Bedrock 用本机凭证；两个 `s4-*` 账户为禁用的假账户、所有定时任务已关，不会触达任何真实云账户；脚本 `/tmp/aiops-s3-accept/e2e_s5_real.py`）：
  - E1 关联 I#2 的会话，不调工具，问谁写了说明、写了什么：模型准确答出 alice 和 admin 各三条及其内容（53.5 秒）。
  - E3 用 E1 的同一个 `client_message_id` 再发：0.0 秒回放原回复，`replayed: true`，没有新的 token。
  - E2 绑定 s4-lab 的会话要求在 s4-prod 上跑 `aws ec2 describe-instances`：模型依据绑定说明拒绝执行，并说明原因。
    模型没有去调用工具，所以另外直接在同一绑定下调用真实 CLI 工具：工具返回 `Error: this run is bound to account id=2; refusing to resolve account 's4-prod' (id=1)`，在任何 AWS 调用之前就拒绝（`s4-prod` 只在这一次调用里临时启用，之后立即禁用）；`get_provider` 同样拒绝。
  - E5 同一会话问「I#2 是什么」：模型答「它属于另一个账户，详情没有加载到本对话」。
  - E4 回复中途客户端断开：用户消息和半截回复都存为 `interrupted`。
  - 顺带发现（S5 之外的既有问题）：Opus 5.5（`claude-opus-5-5`，主人未提交的 `settings.yaml` 给 main 设的模型）在计费表里没有价格，每条回复都按 $0.00 计费，即 CLAUDE.md 所说的「漏配的模型族静默计 $0」。未在 S5 内修复。
- 走查中发现并修复：
  - 被取消的流（刷新、断开）没有存下半截回复，也没法标「已中断」（`8a759da`）；
  - 被取消的流让会话一直忙碌（`6a48def`）；
  - `aiops quickstart --scan` 不带 `client_message_id`，失败了也报告成功（`a230718`）。
- 仍未修的次要问题（已知缺口）：
  - 流结束时的保存是事件循环上的同步 DB 调用（PostgreSQL 下是一次网络往返）；
  - 停止提示切换会话后不会消失；
  - 内存里的附件按会话、不按用户区分（同一标签页重新登录且未刷新时可能看到上一个用户「新会话」里未发送的附件）。

---

## 核心能力轨：变更感知的系统模型（A1–A4）

主人 10-06 批准 spec `docs/superpowers/specs/2026-10-06-change-aware-system-model-design.md`（10-05/06 架构讨论的收敛：三分法 A' 系统模型 → B RCA 调查运行时 → C 易用性并入验收），并裁定在 MVP-2.7.0 上实现、并入本发布规划。它与界面阶段并行，不改界面阶段的顺序；阶段编号用 A（= spec §12 的 P1–P4）以避开设计包的 P0–P6 和 S1–S7。路线图：`docs/superpowers/plans/2026-10-05-mvp-2.7.0-roadmap.md`「核心能力轨」节。

### 一句话

图只按小时轮询、RCA 看不到「告警前谁动了什么」、锚定率 66%：A' 给每个资源一个**感知度**（hourly / minute / live，系统零 LLM 自己维护，SRE 手设钉住），用一个常驻 **Sensing Worker** 按感知度拉取变更（CloudTrail 游标、K8s events、live 探针，**只拉取、不在客户账户部署任何东西**），写成**变更账本** `change_events`（证据，不驱动 Issue、不驱动执行），触发单资源增量刷新与 $0 的 rule-only 图刷新，并把真实的变更时间线（谁、何时、改了什么）放进 RCA 证据包。正确性仍由对账扫描保证，增量只负责新鲜度。`sensing_enabled` 默认 false 直到 A4 评测通过——关 = 2.6.1 行为。

### 阶段

| 阶段 | 内容 | 退出标准 | 状态 |
|---|---|---|---|
| **A1 账本与分钟级** | 两表 + 5 列与迁移；Curator 规则 1–4、6；Worker 的 CloudTrail / K8s events 拉取 + 增量刷新 + 预算计数 + 状态；status / changes / sensitivity 端点；CLI；Settings 感知卡；ResourceDetail 徽标与时间线；IssueDetail 窗口内变更；RCA 接入 | 实验室 K8s 变更 ≤ 2 min 可见；账本有真实 actor；AC@1 不退；全量测试绿 | **计划待出**（预定路径 `docs/superpowers/plans/2026-10-06-change-aware-a1-ledger-minute.md`） |
| A2 live 级 | 探针 + 预算降级 + `request_sensitivity` + 两种端点采集 + `VOLATILE_KEYS` 补齐 | live ≤ 60 s；Galaxy 每小时 LLM $0 | 未开始 |
| A3 覆盖面 | 重测 + 九种解析器 + ALB → 目标组 | 锚定率 ≥ 95% 或如实报告 | 未开始 |
| A4 评测门禁 | 每夜指标 + 三个感知场景 + `--assert` | 一次完整评测过阈值 | 未开始 |

### A1 六个可达面（spec §8；Web API 与 Web UI 两行）

- **CLI** — 做：`aiops sensing status`、`aiops sensing set <resource-id|R<n>> <hourly|minute|live|auto>`（`auto` = 交还系统；actor `cli:<user>`，写审计）。非目标：手动触发一轮拉取。
- **Web API** — 做：`GET /api/sensing/status`；`GET /api/resources/{id}/changes?window_minutes=&limit=`；`PUT /api/resources/{id}/sensitivity`（会话 actor；404 / 403（新权限 `resource.sensitivity`，影子模式照旧）/ 422；写审计）；`GET /api/resources[/{id}]` 多返回 5 个感知度字段。不新增其它端点。
- **Web UI** — 做：Settings → 常规加感知卡（总开关只读、每账户游标与滞后、预算、三级计数、worker 存活）；`ResourceDetail` 概览加感知度徽标（级别 + 原因 + 下次核对 + 手设 / 交还）与变更时间线；`IssueDetail` 诊断卡列出窗口内的 change_events；中英成对。
- **Agent tool** — 非目标（A2 才有 `request_sensitivity`）；RCA 的 `get_topology_evidence` 证据包多一种 `change_event`，提示词改为「先读证据包里的变更，再按需查 CloudTrail」。
- **Schedule** — 非目标（Worker 是常驻线程，不是调度行；`SensingMetrics` 每日一条在 A4）。
- **Notification** — 非目标：预算触顶、凭证失败只记日志与状态卡。
- **Webhook** — 非目标：推送接入；只保证 `change_events.source` 能容纳 `push`。

### A1 升级注意（预告）

1. 启动时自动迁移：`cloud_resources` 加 5 列（现有行按类型默认表回填感知度，`set_by=system`），新表 `change_events`、`change_cursors` 由 `init_db` 自动建立。
2. `sensing_enabled` 默认 false：不开就没有 Worker、没有新调用；`GET /api/sensing/status` 返回 `enabled=false`。
3. 开启后每账户每分钟只读调用数受 `sensing_max_calls_per_minute_per_account`（默认 60）限制；超了先推迟拉取，永不停对账。

门禁数字与验收清单在 A1 实现后回填。
