# MVP-2.7.0 Release Notes — 蓝白工作台 + 核心信任加固（分阶段交付）

> Version: 2.7.0 · Branch: `MVP-2.7.0`（从 `MVP-2.6.1` 的 `1ec53b3` 切出）· 起始日期：2026-10-05 · 主题：先把会「假通过」「串号」「多进程失效」的核心信任问题修掉，再按主人 10-05 交付的蓝白设计包分阶段改造界面
>
> **状态：S1（核心信任加固）已实现，作为 `MVP-2.7.0` 分支上的本地提交存在（未 push），等主人手动验收。S2–S7 尚未开始：每个阶段开工前先交详细计划给主人批准，上一阶段验收通过才进下一阶段。** 依主人铁律，只有 E2E 通过且当面确认后才 `git push --no-verify` / 打 `v2.7.0` tag。
>
> 全链规划（含 S1 详细计划）：`docs/superpowers/plans/2026-10-05-mvp-2.7.0-roadmap.md`
> 设计输入：`docs/AgenticOps_BlueWhite_Review.zip`、`docs/superpowers/specs/2026-10-05-blue-white-sre-workspace-design.md`、`docs/ui-contracts/2026-10-05/`

## 一句话

蓝白设计包里大约 65% 的工作量是界面与交付体验，真正动核心的只有几项；而其中三项是已经复核的缺陷：执行验收会被重复结果凑数通过、chat 会话对所有人可见、四个 worker 让内存态保证悄悄失效。MVP-2.7.0 把这三项作为第一阶段（S1）先修，再按「单位时间收益」逐阶段推进界面改造。

## 阶段与状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| **S1 核心信任加固** | 验收逐项绑定 check_id；会话归属 + private/workspace；单进程运行 + 事件循环不阻塞 | **已实现，待主人验收** |
| S2 蓝白外壳与导航（P0+P1） | 配色、字体本地化、分组侧栏、顶栏、首页解析器、登录回跳、`/app/overview`、bootstrap + 偏好接口 | 未开始 |
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
- 可见性检查放在第一步：读上传、`/channel`、`/send_to`、streaming 409 都在它之后。
- 列表计数改为一次分组查询；删除时一并删除 `SessionSummary`。
- CLI：`/session list`、无参 `/session resume`、按名字片段恢复、`aiops chat --resume`、启动时的「最近会话」提示都只看 workspace 会话；精确 id / UUID 仍可恢复任意会话（CLI 是有库访问权的本地操作员）。
- Web UI：登录后会话行标「工作区」或「他人私有」（只有 admin 看得到后者）；owner 在会话悬停菜单里切换 私有 / 工作区；通过链接打开、不在前 50 条列表里的会话也能显示名称和「存为报告」；私有会话存为报告前提示「报告对工作区所有人可见」。
- 顺手修的两个 detached 实例问题：`validate_api_key`（PARK-S5）和 `create_user`（注册接口）。

**迁移**：`chat_sessions.owner_user_id`（可空）+ `visibility`（`NOT NULL DEFAULT 'workspace'`），幂等，每进程每数据库 URL 执行一次。

**已知缺口**：`GET /api/agent-logs` 仍把每轮对话前 500 字的摘要返回给所有人（运维指标视图，收紧需要单独决定）；报告本身没有归属（S6 再议）；IM 会话仍出现在 web 列表中。

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
2. **会话隔离**：本地 `AIOPS_API_AUTH_ENABLED=true` 起服务，注册 alice、bob；alice 新建会话（默认私有），bob 的列表里没有，直接打开 URL 显示不存在；alice 切成工作区可见后 bob 能看到；用 API key 调会话接口返回 200；关闭认证重启，所有会话照旧可见。
3. **单进程**：三处部署文件都是 `--workers 1`；同一 data_dir 再起一个进程，日志出现 ERROR；`pytest tests/test_single_process.py` 证明 STS / 告警判官 / IM agent 慢的时候其他请求不被卡住。
4. **门禁**：见下。

## S1 门禁结果

（T9 填入：后端全量 pytest 对比基线 6378 passed / 85 skipped，vitest，tsc，build。）
