# MVP-2.7.1 Release Notes — 变更感知的系统模型（核心能力轨 A1–A4）+ 2.7.0 的跟进项

> Version: 2.7.1（进行中）· Branch: `MVP-2.7.1`（10-09 从 `v2.7.0` = `a953e6b` 切出；**11-07 rebase 到 `main` = `bb01e5f`**，原工作树 `.worktrees/mvp-2.7.1` 已删，主检出就在本分支上；尚未推送）· 起始日期：2026-10-09
>
> **状态：2.7.0 E2E 观察第 1–5 条已修、受保护值按表格行比较已做（10-09；主人「修复之后，按计划进行」「先修复 E2E 的故障」，第 1、2 条的设计主人 10-09 确认：都做、回滚闸门拒绝保存），见下文三节「已修」；A1–A4 尚未开始。** 主人 10-08 把核心能力轨 A1–A4 从 v2.7.0 移到本版本（「complete the A1–A4's implementation within MVP-2.7.1」）。spec 已批准；A1 的详细实施计划待出，写好后交主人批准、选执行方式，批准前不动代码；A2–A4 各自开工前再出计划。依主人铁律，只有 E2E 通过且当面确认后才 `git push --no-verify`。
>
> **11-07：rebase 到最新 main**（主人「切换到 2.7.1 且 rebase 最新的 main branch」）。v2.7.0 之后在 main 上交付的工作随之进入 2.7.1，见下文「随 rebase 带入的 main 交付」。本版本自己的 5 个提交改写为 `9bc5249`（开版本）· `9d582e7`（命令分类与自动批准下限）· `76157c6`（代码记录的事实）· `d15fae5`（修复方案只恢复 + 回滚闸门）· `cd4f0d2`（表格逐行比较）；10-09 记录里的旧 SHA（`bb75bb5` / `27e9168` / `0fb090e` / `0a25f31`）已不存在。A1–A4 仍未开始。
>
> 设计输入：`docs/superpowers/specs/2026-10-06-change-aware-system-model-design.md`（A1–A4 = 其 §12 的 P1–P4）；来历：`docs/MVP-2.7.0-RELEASE.md` 与 `docs/superpowers/plans/2026-10-05-mvp-2.7.0-roadmap.md` 的「核心能力轨」节（10-06 并入 2.7.0、10-08 移出，正文已搬到本文件）。

## 本版本范围

| 项 | 内容 | 状态 |
|---|---|---|
| **A1 账本与分钟级** | `change_events` 账本 + 感知度（资源属性）+ Sensing Worker（CloudTrail / K8s events 拉取、增量刷新）+ RCA 接入 + 三端点 / CLI / Settings 感知卡 / 资源与问题页 | **计划待出**（预定路径 `docs/superpowers/plans/2026-10-06-change-aware-a1-ledger-minute.md`） |
| A2 live 级 | live 探针、预算降级、`request_sensitivity`、两种端点采集、`VOLATILE_KEYS` 补齐 | 未开始 |
| A3 覆盖面 | 锚定缺口重测、九种解析器、ALB → 目标组 | 未开始 |
| A4 评测门禁 | 每夜 $0 指标、三个感知场景、`--assert`、再议 `sensing_enabled` 默认值 | 未开始 |
| 受保护值按表格行比较 | 主人 10-08 决定（见下文「2.7.0 的跟进项」第 1 条） | **已做（10-09）**：逐行、行内逐单元格 |
| 2.7.0 E2E 观察 | 第 1 条（SRE 越界）、第 2 条（回滚复现故障）、第 3 条（命令分类器 + 自动批准下限）、第 4 条（RCA 模型 id）、第 5 条（执行时长）**已修** | 已修（10-09） |
| ChatGPT 风格的 Web Chat | 工作过程块（步骤、耗时、结果、过程话）+ 回答里的图表 / 流程图 + 输入框内附件 + 移动端（见下文「ChatGPT 风格的 Web Chat」） | **已做（11-07），E2E 通过，待主人验收** |
| 模型流读超时 + 思考摘要 | 修复「分析 HTML」一连三轮回复失败：读超时进 DB 配置、5.x 思考摘要、两个新错误码（见下文「模型流读超时与思考摘要」） | **已做（11-08）** |
| 编辑账户保留已存的密钥 + 账户审计 | 11-09 只改区域的编辑丢掉了 Global 账户的密钥：编辑改为合并、「Remove the stored keys」、增删改写审计（见下文「编辑账户不再丢掉已保存的密钥」） | **已做（11-09），待主人确认后推送** |
| v2.7.0 之后 main 上的交付 | 只读账户、Strands 1.64、模型配置一致性、聊天附件、开发机 Node 22 等（PR #28–#37，见「随 rebase 带入的 main 交付」） | **已在 main，11-07 随 rebase 带入** |

---

## 核心能力轨：变更感知的系统模型（A1–A4）

主人 10-06 批准 spec `docs/superpowers/specs/2026-10-06-change-aware-system-model-design.md`（10-05/06 架构讨论的收敛：三分法 A' 系统模型 → B RCA 调查运行时 → C 易用性并入验收），先并入 2.7.0 的规划；10-08 移到 MVP-2.7.1。阶段编号用 A（= spec §12 的 P1–P4）以避开蓝白设计包的 P0–P6 和 2.7.0 的 S1–S7。10-06 主人另定：控制器保持零-LLM 规则分档，不加 LLM 策略层。

### 一句话

图只按小时轮询、RCA 看不到「告警前谁动了什么」、锚定率 66%：A' 给每个资源一个**感知度**（hourly / minute / live，系统零 LLM 自己维护，SRE 手设钉住），用一个常驻 **Sensing Worker** 按感知度拉取变更（CloudTrail 游标、K8s events、live 探针，**只拉取、不在客户账户部署任何东西**），写成**变更账本** `change_events`（证据，不驱动 Issue、不驱动执行），触发单资源增量刷新与 $0 的 rule-only 图刷新，并把真实的变更时间线（谁、何时、改了什么）放进 RCA 证据包。正确性仍由对账扫描保证，增量只负责新鲜度。`sensing_enabled` 默认 false 直到 A4 评测通过——关 = 2.7.0 行为。

### 阶段

| 阶段 | 内容 | 估算（agent 工作日） | 依赖 | 退出标准 |
|---|---|---|---|---|
| **A1 账本与分钟级** | `change_events` / `change_cursors` 两表 + `cloud_resources` 5 列与迁移；感知度 Curator（规则 1–4、6，零 LLM）；Sensing Worker：CloudTrail 游标拉取（服务端 `ReadOnly=false`）+ K8s events 拉取 + 单资源增量刷新 + 防抖 rule-only 图刷新（`change-event` 触发，$0）+ 预算计数 + 状态；`GET /api/sensing/status`、`GET /api/resources/{id}/changes`、`PUT /api/resources/{id}/sensitivity`；CLI `aiops sensing status|set`；Settings 感知卡、ResourceDetail 徽标与变更时间线、IssueDetail 窗口内变更；RCA 证据包 `change_event` + `_promote` 回填 `related_changes` | 3–4 | v2.7.0 S1（单进程 + 调度器 flock 即 Worker 宿主） | 实验室 K8s 变更 ≤ 2 min 可见；账本有真实 actor（CloudTrail `Username`）；AC@1 不退；全量测试绿 |
| A2 live 级 | live 探针 + 预算降级（规则 7）+ `request_sensitivity` agent 工具 + 两种端点采集（目标健康、EndpointSlice）+ `VOLATILE_KEYS` 补齐 + live 默认清单 | 2 | A1 | live 资源 ≤ 60 s 可见；Galaxy 每小时 LLM 成本 $0 |
| A3 覆盖面 | 锚定缺口重测（按 ARN 资源段）+ 九种解析器 + ALB → 目标组关系 | 2–3 | A1 | 锚定率 ≥ 95%，或如实报告长尾 |
| A4 评测门禁 | 每夜 $0 指标（`SensingMetrics` 调度 + `sensing_metrics` 表）+ chaos-lab 三个感知场景 + `location_eval.py --assert` + 判定回填；再议 `sensing_enabled` 默认值 | 1.5–2 | A1–A3 | 一次完整评测通过阈值 |

每个 A 阶段可独立发布、独立回退（`sensing_enabled=false` 兜底）。每阶段统一门禁：后端全量 pytest ≥ 当期基线；前端 `npx tsc --noEmit` 0 错误、vitest 全过（含 locale 中英成对）、`npm run build` 成功；六个可达面逐行；文档同阶段更新（README 双语同提交）；交主人逐条可复现的验收清单。A4 的 chaos-lab 评测有费用、要实验室凭证，开跑前问主人。

**以 v2.7.0 的代码为准写计划**（spec 写于 10-06，之后 S3–S7 改动了它要碰的地方）：`ResourceResponse` 已有 `open_issues` / `health`；`/app/issues` 是 Cases 双栏布局，IssueDetail 有 `embedded` 模式（「窗口内变更」放在 `components/issue/DiagnoseCard.tsx`，两种布局都显示）；`_ADD_COLUMNS_2_7_0` 已被 S5 / S6 扩展（A1 的列用独立命名的迁移）；`providers/base.get_provider()` 在 RunContext 已绑定其它账户时抛 `AccountResolutionError`（Worker 逐账户轮询，不能残留别的账户的绑定）；lifespan 已有 S5 / S6 的启动清扫（Worker 启停写在调度器块内）。

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

---

## 2.7.0 的跟进项

### 1. 受保护值按表格行比较（主人 10-08 决定）

2.7.0 的报告翻译把受保护值（资源 id、数字、时间等）当**多重集**比较（`services/content_protect.protected_hash`）：任何值被改、丢、增、重复或合并都会被拒，但两个值可以互换位置——`Restart i-0aaa111, keep i-0bbb222` 换成两个 id 对调、`from 3 to 2` 换成 `from 2 to 3` 都能通过（`docs/MVP-2.7.0-E2E-REPORT.md`「Observations」第 9 条）。主人 10-08：2.7.0 保留这个语义，**2.7.1 按 markdown 表格行收窄**——表格每一行内的受保护值单独比较，跨行互换不再通过。届时收紧 `tests/test_content_protect.py::test_a_swapped_pair_of_values_passes_by_design`（表格行内对调应被拒；正文段落的语序自由保留与否随计划定）。**已做（10-09），见下文「已做：受保护值在表格里逐行、逐单元格比较」。**

### 2. 2.7.0 E2E 观察（第 1–5 条已修，10-09）

出自 `docs/MVP-2.7.0-E2E-REPORT.md`「Observations (not fixed in this release)」：

1. **SRE 的修复方案越界**：针对「副本数为 0」的两份修复方案都加了集群级 add-on 安装、HPA 和注解，定为 L2；策略里没有任何东西把修复方案限制在问题本身的资源上。人工审查拦住了，执行角色的 IAM 拒绝了那一次 AWS 写入。**已修（10-09），见下文「已修：修复方案只做恢复，回滚不复现故障」。**
2. **回滚可能把故障带回来**：方案 #1 针对「恢复失败一半」的回滚是「把两者都缩回 0」。**已修（同上）。**
3. **命令分类器判错**：`kubectl rollout status`（只读）被判为写操作（每次第一次尝试被拒、再重试）；`aws eks create-addon` 被判为 `unknown` 档，执行器在已批准的方案里被允许尝试它。报告的建议：未知档的写命令应按写处理。**已修（10-09），见下文「已修」节。**
4. **`RCAResult.model_id` 为空**（API 里那次 RCA 运行）。**已修（10-09），见下文「已修：代码知道的事实由代码记录」。**
5. **两次执行的 `duration_ms` 都是 45000**：像是上报的，不是测的。**已修（同上）。**

---

## 已修：命令分类与自动批准下限（2.7.0 E2E 观察第 3 条，2026-10-09）

**之前**：
- 执行闸门（`run_aws_cli` / `run_on_host` / `run_kubectl` / provider 层 `guarded_run`）本来就把 `unknown` 当写处理：要确认、变更评审期间拒绝、命中 `change_required` 时要已批准的方案、写命令账本。E2E 里 `create-addon` 在已批准方案里被尝试，与一条普通写命令待遇相同。
- 真正的缺口是**自动批准不看命令**：`policies.yaml` 的 `auto-approve-low-risk` 只看方案自己标的风险等级（L0/L1，由 SRE 给出），一份带着代码判不出的命令、却被标成 L1 的方案，会在没有任何人看过的情况下被批准并执行。E2E 那份方案标的是 L2，所以没撞上。
- 标签本身也错：`kubectl rollout status` / `rollout history` 是读，却因为整个 `rollout` 被列为写而先被拒一次；AWS 写前缀表只有 25 条、没有一条 EKS，`create-addon` 落到 `unknown`。

**现在**：
- **kubectl**：`rollout status`、`rollout history` 判为只读（先于写表检查）；`rollout restart` / `undo` / `pause` / `resume` 仍是写。
- **AWS**：前缀表没命中的命令按操作动词兜底——`create` / `delete` / `update` / `put` / `modify` / `attach` / `detach` / `associate` / `start` / `stop` / `reboot` / `tag` / `untag` / `enable` / `disable` / `invoke` / `publish` / `send` / `run` / … 判为写，`batch-` 看第二个词（`batch-write-item` 写、`batch-get-item` 不变）。取操作名时跳过全局选项及其值（`aws --region r eks create-addon` 是写，`aws --region create-1 eks list-clusters` 不会把选项值当动词）。**只升不降**：表里漏掉的读动词仍是 `unknown`，blocked 规则仍最先判。
- **自动批准下限**：方案的步骤或回滚里，只要有一步的命令档位是 `unknown`，或者一步根本没写命令（执行器只能临场决定跑什么），就**不自动批准**，交人审，时间线记一条 `policy_decision`（规则 `unclassified_command`、动作 `require_human`，原因列出前 5 条命令）。修复方案在 `pipeline_service.trigger_auto_approve` 里于策略判定之后、Trust-Kernel 上限检查之前生效（策略启用与否都生效）；变更方案在 `change_service.evaluate_policy` 里把 `auto_approve` 改为 `require_human`，于是成为需要人审批的 normal 变更。判定是一个函数 `change_steps.unclassified_commands`（复用 `command_tier`）。

**口径裁定**（实现时定，代价写明）：
- 回滚方案格式不固定：只读其中实际带着的步骤（`steps` / `commands` 列表或裸列表）；纯文字描述（`{"description": …}`）不是步骤、不计——若也算，几乎所有 L1 方案都会被拦到人审，超出本次修复。
- 没写命令的步骤计为「判不出」（save_fix_plan 的约定是每步都有 `command`）。代价：仍按旧习惯只写文字步骤的方案会改由人审。
- `pre_checks` / `post_checks` 不在下限里（它们应是只读检查；本次范围是步骤与回滚）。

**可达面**：CLI — 非目标（`/approve` 本来就是人）；Web API — 非目标（接口形状不变）；Web UI — 非目标、无 UI 改动：没自动批准的原因已经在时间线的 `policy_decision` 事件里（动作 `require_human` 有现成文案），方案照常出现在「需要你处理」与待审批通知里；Agent tool — 做：`run_kubectl rollout status` 不再要求确认，`run_aws_cli` 对兜底判为写的命令照写处理；Schedule — 非目标；Notification — 非目标（沿用现有待审批通知）。

**测试**：`tests/test_unclassified_command_floor.py`（判定函数、回滚读取、修复方案三种路径、变更方案两种路径）；分类器用例补进 `tests/test_skills_security.py`、`tests/test_aws_cli_tool.py`。两处旧夹具改为可判档的命令：`tests/test_pipeline_service.py` 的 mock 方案原本没有真实的 `steps` 列；`tests/test_plan_content.py` 自动批准用例的 `echo a` 现在会被下限拦下（没有把 `echo` 加进只读表——`echo x > file` 是写）。

**门禁**（2026-10-09，`.worktrees/mvp-2.7.1`，一次性库 `/tmp/aiops-271-test.db`）：后端全量 **6955 passed / 85 skipped / 1 failed**——失败的是 `test_session_manager_props.py::TestTTLExpirationCleanup::test_active_agents_are_kept`，时序型 Hypothesis 抖动，单独重跑 3 次均通过，且不引用本次改动的任何模块。本 worktree 不带主人未提交的 `settings.yaml` / `reporter_agent.py` 改动，所以主检出上那 2 个环境性失败不出现。前端未改动。

**非目标**：L0 方案里带写命令时不拦（L0 本应只读，E2E 没撞到，待主人定）；观察第 1、2、4 条；推送。

---

## 已修：代码知道的事实由代码记录（2.7.0 E2E 观察第 4、5 条，2026-10-09）

**之前**：`save_rca_result` 的 `model_id` 只是 RCA agent 调工具时自己填的参数，agent 从来不知道自己跑在哪个模型上，于是 `RCAResult.model_id` 为空；`save_execution_result` 的 `duration_ms` 同样是 executor 自报的数（E2E 两次都是 45000），没有任何地方测量；没有排队单的执行（自动执行、chat 里直接调用）新建的记录 `started_at = completed_at = 结束时刻`。

**现在**：`RunContext` 多两个由代码填写的字段——`model_id`（`rca_agent` 用构建 agent 的那个模型 id 包住整次调用）和 `run_started_at`（`executor_agent` 在调用开始时写入）。`save_rca_result` 存 `RunContext.model_id`，agent 的参数只在代码没给时兜底；`save_execution_result` 从 `run_started_at` 量时长，否则用排队单认领时的 `started_at`，两者都没有才保留 agent 上报的数，新建的执行记录 `started_at` 也是真实开始时刻。三条执行路径（自动执行、ExecutorService 排队执行、chat 里直接调用）都经过 `executor_agent`，所以都被测量。

**可达面**：CLI / Web API / Web UI / Schedule / Notification — 非目标（字段与接口形状不变，只是值变真；Issue 页的执行卡与 `GET /api/rca` 照常展示这两个字段）；Agent tool — 做：两个工具的参数仍收，但不再是唯一来源。

**测试**：`tests/test_run_measured_facts.py`（模型 id：代码值、代码值优先于参数、无上下文时用参数、`rca_agent` 在调用期间写入并在结束后复原；时长：从执行开始量、从排队单认领量、都不知道时保留上报值、`executor_agent` 在调用期间写入并复原）。

**门禁**（2026-10-09，`.worktrees/mvp-2.7.1`，一次性库）：后端全量 **6964 passed / 85 skipped / 0 failed**。

---

## 已修：修复方案只做恢复，回滚不复现故障（2.7.0 E2E 观察第 1、2 条，2026-10-09）

主人 10-09：两条都做；回滚闸门遇到会让服务下线的回滚，**拒绝保存**（不是「保存 + 强制人审 + 警告」）。

**之前**：
- 针对「副本数为 0」的两份修复方案，都在恢复副本之外加了集群级 add-on、HPA 和注解，定为 L2；没有任何规则把修复方案限定在恢复问题本身。
- 方案 #1 的回滚是「把两个 Deployment 都缩回 0」，也就是这个 issue 本身的故障；执行在第 4 步失败后，回滚真的把服务又缩回了 0。

**现在**：
- **SRE 提示词（Mode A 第 6 步）**：
  - `SCOPE`：修复方案只让出问题的资源回到上一个正常状态，每一步都作用于问题的资源或 RCA 定位到的根因；改进项（新组件，例如集群插件、自动扩缩、监控 agent；注解或标签；重构）一律不进修复方案，写进摘要，作为另开变更单的后续建议。
  - `ROLLBACK`：只把本方案自己的步骤撤回到上一个正常状态，绝不重现 issue 描述的故障；修复前的状态就是故障时（例如副本为 0、服务已停），回滚保留已恢复的部分并停在那里。
  - 措辞按概念类别写，保持云中立，服务名只作示例。SRE 提示词 13,424 字符，在预算 12,600 ±25% 之内。
- **代码闸门（只对修复方案）**：`save_fix_plan` 读回滚里实际带着的步骤（`change_steps.rollback_steps`；纯文字描述不计），只要有一条会让服务下线的命令（`change_steps.outage_commands`：`kubectl scale … --replicas=0`、`kubectl delete` 工作负载或 Service、ECS `--desired-count 0`、Auto Scaling `--desired-capacity 0` / `--max-size 0`、EKS 节点组 `desiredSize=0`、停 EC2 实例、停 RDS 实例或集群、Lambda 并发设为 0、`systemctl stop`、`service … stop`），就返回 `INVALID`，并点名前三条命令，什么都不写，SRE 当场改写。变更方案不检查（「把 0 扩到 2」的变更，回滚到 0 就是正当的撤销）；人工通过 `PUT /api/fix-plans/{id}` 编辑也不检查（那是人的决定）。

**口径**：第 1 条只改提示词、不加代码闸门——「超出恢复范围」没有可靠的确定性判据。兜底仍是第 3 条的自动批准下限，以及 S3 审批对话框的核对勾选；SRE 实际会不会照做，要下一次 live E2E 才能验证。

**可达面**：
- CLI / Web API / Web UI / Schedule / Notification — 非目标：接口形状不变；被拒的方案根本不会出现，Issue 页照常显示 SRE 改写后保存的方案。
- Agent tool — 做：SRE 提示词两条规则；`save_fix_plan` 对会让服务下线的回滚返回 `INVALID`。

**测试**：`tests/test_fix_plan_scope_and_rollback.py`：17 条会下线的命令逐条命中、10 条不会下线的不误报、字符串与 dict 形式的步骤都读、纯文字描述不计；修复方案被拒且不写库、不触发自动批准；保留已恢复部分的回滚照常保存；变更方案可以回滚到 0；提示词两条规则的关键句（空白折叠后比对）。

**门禁**（2026-10-09，`.worktrees/mvp-2.7.1`，一次性库）：后端全量 **6996 passed / 85 skipped / 0 failed**。

---

## 已做：受保护值在表格里逐行、逐单元格比较（2.7.0 E2E 观察第 9 条，主人 10-08 决定，2026-10-09）

**之前**：报告翻译恢复受保护值后，按**多重集**比较（`services/content_protect.protected_hash`）：值被改、丢、增、重复或合并会被拒，但两个值可以互换位置。正文段落里这是有意保留的（zh 会把日期写在时间前面；S7 用真实模型证实了按顺序比较会误拒真实报告）。可在表格里，这就意味着某一行的副本数可以和另一行对调、同一行的 Replicas 可以和 Max 对调，而翻译照样「通过」。

**现在**：哈希在全文多重集之外，再加上每张 markdown 表格的结构——**逐行、行内逐单元格**，每个单元格是它所含受保护值的多重集。表格按 GFM 识别（表头行 + 分隔行 `|---|`，首尾 `|` 可有可无，正文行到空行或不含 `|` 的行为止），并且是在**遮罩后的文本**上识别，所以代码块、行内代码里的 `|` 不会成为表格或单元格。于是：值挪到另一个单元格（同行或别行）、挪出表格进正文、两行合并成一行，译文都会被拒（`failed` / `protected_values_changed`）；表头翻译、对齐符号、首尾 `|`、单元格里的空格都不影响；同一单元格里的值仍可重排（zh 在一个单元格里把日期写在时间前面）。

**口径裁定**：你 10-08 的原话是「按 markdown 表格行比较」，并要求把「两个值互换」那条用例在表格里收紧。只按行比较的话，同一行的两列对调（副本数和上限互换）仍会通过，所以我在行内再细到单元格。**仍然留着的缺口**：同一个单元格里的两个值互换（`2 / 6` → `6 / 2`）还会通过，因为要让 zh 能在单元格里重排日期和时间，单元格内只能按多重集比较。这一条已经写成明示的测试 `test_two_values_of_one_cell_may_still_trade_places_by_design`。存库的 `protected_value_hash` 只在 API 里原样返回、不参与任何比较，所以哈希定义变了，已有的译文也不会被误判为过期。

**风险**：模型翻译时若改动表格结构（拆行、合并单元格、把表格改写成列表），译文会被拒，于是读者看到的是原文。这是有意的保守取向，但会抬高翻译失败率。这次没有用真实模型验证，要在下一次 live E2E 里确认。

**可达面**：CLI / Web API / Web UI / Agent tool / Schedule / Notification — 非目标：接口与页面不变。被拒的译文和以前一样显示为 `failed` 并可重试，报告页照常显示原文。

**测试**：`tests/test_content_protect.py` 新增 10 条（跨行挪动被拒、翻译过的表格照常通过、单元格内可重排、同行两值换单元格被拒、单元格内互换是明示缺口、无首尾 `|` 的表格也能识别、对齐与空格无关、挪进正文被拒、合并行被拒、代码里的 `|` 不算表格）；`tests/test_content_rendering_api.py` 新增 2 条（模型把两行的值对调 → `failed`；保留行的翻译 → `ready`）。

**门禁**（2026-10-09，`.worktrees/mvp-2.7.1`，一次性库）：后端全量 **7008 passed / 85 skipped / 0 failed**。

---

## ChatGPT 风格的 Web Chat（2026-11-07）

设计：`docs/superpowers/specs/2026-11-07-chatgpt-style-chat-design.md`（主人在浏览器草图上确认）· 计划：`docs/superpowers/plans/2026-11-07-chatgpt-style-chat.md` · E2E：[`MVP-2.7.1-CHAT-E2E-REPORT.md`](MVP-2.7.1-CHAT-E2E-REPORT.md)

### 做了什么

- **页面**：
  - Chat 页上，全局导航收成 56 px 的图标栏，「展开导航」后以浮层显示完整侧栏。
  - 对话列表默认展开（标题单独一行），手机上是抽屉。
  - 居中单栏：用户消息是右侧的灰色气泡，回答平铺显示。
  - 空对话时输入框居中。
- **工作过程**：每个回答上方有一个 Codex 式的步骤块。
  - 运行中实时追加步骤，完成后收成一行「已处理 N 步 · T」。
  - 每一步显示：工具（常用的显示中文名）、输入摘要（已脱敏）、耗时、可展开的结果预览（已脱敏）。
  - 模型在步骤之间写的话放进块里，正文不再以「我先查一下……」开头。
  - 子 agent 和 `enhanced_task` 各算一步。
- **回答渲染**：
  - 统计用 ```` ```chart ```` JSON 块（recharts：柱状图、折线图、面积图、饼图，放大后附数据表）。
  - 流程用 ```` ```mermaid ```` 块。mermaid 只在出现流程图时才加载，用 `strict` 模式，并去掉 `%%{init}%%`。
  - 代码块可以复制。
  - 回答下面：复制、重新生成（只在最后一条；原问题带附件时不可用）、⋯（存为报告、复制为纯文本）、token 用量、「下一步」建议。
- **输入框**：
  - 附件在框里面：图片是方形缩略图带圆形进度；文档是按类型着色的卡片；被拒的文件是红色卡片并写明原因；有计数。
  - 「＋」菜单：上传文件、上传图片；触屏上还有拍照。
  - 按键：Enter 发送，Shift+Enter 换行；输入法候选期间不发送；触屏上 Enter 换行。
  - 整个对话区都能拖入文件，只给一层淡色提示。
- **滚动**：只有用户自己翻动才会停止吸底（行高测量引起的位置变化不算）；有「↓ 回到底部」。
- **手机**：`100dvh`、safe-area；主要按钮的点击区域 44 px；大图预览左右滑动切换。

### 后端

- **SSE 帧**：
  - `tool_start` 增加 `text_offset`；
  - 新帧 `tool_input {call_id, summary}`：模型写完这次调用的输入后才发；
  - `tool_end` 增加 `duration_ms`、`result_preview`、`text_end`、`started_ms`。
- **持久化**：上面这些都写进 `chat_messages.tool_calls`。旧消息没有偏移量，整段当正文，步骤照常列出。
- **计时**：一步的耗时从它开始执行时算起（输入完整的那一刻），不是从模型开始写这次调用算起；总计是实际时间跨度（E2E 中发现并修复，见报告）。
- **`chat/tool_steps.py`**：
  - 摘要：优先取 `command`，否则取唯一的文本字段，否则拼 `k=v`；单行，最长 160 字。
  - 结果预览：最长 200 字，先截到 4000 字再跑正则。
  - 显示层脱敏：先过 `redact_secrets`，再盖掉 `--password` 一类参数的值、`aws_secret_access_key <值>`、`Bearer` token、URL 的 `user:pass@`；ARN 不受影响。
  - 共用的 `redact_secrets` 不变。
- **提示词**：`create_main_agent(rich_output=True)` 只由 `web/session_manager` 传入，完整版和只读版都有。它会追加 `RICH_OUTPUT_PROMPT`（英文、云中立：统计用 chart，流程用 mermaid，不画 ASCII）。CLI、IM、定时任务、报告都不变。
- **`enhanced_task`**：内部的工具事件不再算步骤；它输出的文字照常流式显示，并归到这一步下面。

### 可达面

| 面 | 本次 |
|---|---|
| CLI | 非目标：CLI 的主 agent 不加输出规则，回答照旧（E2E 已确认没有 chart / mermaid 块） |
| Web API | 做：SSE 新增 `tool_input` 帧；`tool_start` / `tool_end` 新增字段；`tool_calls` 持久化这些字段。不新增端点 |
| Web UI | 做：Chat 页骨架、工作过程、富渲染、操作栏、「下一步」、输入框、吸底、移动端（见上） |
| Agent tool | 非目标：没有新工具；只有 Web Chat 的主 agent 提示词增加输出规则 |
| Schedule | 非目标 |
| Notification | 非目标 |

### 升级注意

- **前端新增依赖 `mermaid@^11`。** 需要 `npm ci`，然后重新构建前端（`npm run build`）。
- **需要重启服务**，后端的 SSE 帧和提示词才会生效。
- **CLI、IM、报告不受影响。**

### 闸门

- 后端全量（含评审修复）：7363 passed · 99 skipped · 4 failed（4 个都与本改动无关：2 个是本机未提交的 `settings.yaml`，1 个是本机未提交的 `reporter_agent.py` 中文行，1 个是 DNS 误报；前 3 个在干净的 HEAD 上通过）。
- 前端：vitest 70 个文件 / 773 个测试；`tsc` 0。
- 在 `/tmp` 空目录里 `npm ci && npm run build && vitest`：通过。
- 真实模型 E2E：桌面、移动、性能、纯文本渠道全部通过，见报告。
- 全分支评审：没有 Critical；5 个 Important 已修复（`ac1779f`）：
  - emoji 导致分界错位；
  - 只有一个字段的密钥原样显示；
  - 正则平方级耗时；
  - 流程图加载外站图片；
  - 生成中拖入文件导致离开页面。
- 10 个 Minor 记录在案，见报告。

## 模型流读超时与思考摘要（2026-11-08）

### 起因

一个会话（Fable 5.1，effort max）分析一份 39 KB 的 HTML 时，一连三轮都报 `ReadTimeoutError`，界面只显示「回复失败」。

### 实测

真实模型，约 3.3 美元：

| 实测 | 结果 |
|---|---|
| 原样重放第 1 轮（读超时放宽到 900 s） | 首字节在 **271.9 s** 才到；停止原因 **`max_tokens`，正文 0 字** |
| 同一会话重放「hi」 | 22 s 出首字节，32 s 完成 |
| ConverseStream 加 `thinking.display: "summarized"` | Opus 5.5、Sonnet 5.5、Fable 5.1 都接受，并流回思考摘要 |
| Fable 5.1 + effort max + summarized | 5.9 s 起持续流回摘要（1613 段），**最大间隔 7.3 s**，用掉 14845 / 16000 输出 token |

三个缺陷叠在一起：

1. **读超时太短。** 所有 agent 的 Bedrock 连接都用 Strands 默认的 120 s 读超时，而 4.7 及以后的模型思考时默认不返回内容，连接上一个字节都没有。
2. **effort max 下输出上限不够。** 选 effort max 时，Main 的 16384 输出 token 被思考用完了。
3. **失败原因看不出来。** 两种失败都归为 `internal`。

### 修复

- **思考摘要（`preamble.thinking_fields_for_budget`）：**
  - Claude ≥ 4.7 的自适应思考请求带上 `"display": "summarized"`，思考期间持续有数据流回；计费不变。
  - 4.6 默认就是 summarized，不改。
  - 每个开着思考的 agent（Main、RCA）都受益。
- **读超时进 DB 配置：**
  - `settings.yaml` 新增 `model_runtime.stream_read_timeout_seconds`，默认 600，范围 60–3600。
  - 管理员的覆盖值存在 `runtime_settings` 的 key `model_runtime` 下（`agents/model_runtime`，做法和 `chat_upload` 一样）。
  - `bedrock_model_kwargs` 给每个模型都带上 `boto_client_config`；报告 agent 原来单独设的 300 s 去掉了。
  - 接口：`GET` / `PATCH` / `DELETE /api/settings/model-runtime`，只有管理员能改，留审计；修改后清空聊天 agent 缓存，下一轮按新值。
  - 界面：Settings → 通用 →「模型连接」卡片。
- **两个新错误码（`chat/stream_errors`）：**
  - `timeout`：读超时。界面提示降低 effort 或换模型，管理员也可以在 Settings → 通用 → 模型连接 调高等待上限。
  - `max_tokens`：Strands 的 `MaxTokensReachedException`。界面提示到 Settings → 通用 → Agent 模型 调高 Main 的 Max tokens，或降低 effort。
  - 存库的失败消息也按这两个码显示对应文案。
- **思考摘要实时显示（主人决定：不存库）：**
  - SSE 新帧 `thinking {text}`。
  - 生成中，「思考中…」后面和工作过程块的最后一行显示「正在思考 · <最新一句>」。
  - 回答完成后不保留。
- **历史重建（`_load_history_messages(known_tools=)`）：**
  - 只重建 agent 自己有的工具调用。
  - 11-07 之前存下的 Claude Code 内部步骤（`Read File`、`Terminal`）不再被重建成 toolUse；以前它们会被 Strands 改名为 `INVALID_TOOL_NAME` 并打警告。

### 可达面

| 面 | 本次 |
|---|---|
| CLI | 做（无界面）：同一个构建入口，CLI 的 agent 也拿到读超时和思考摘要 |
| Web API | 做：`/api/settings/model-runtime`；SSE `thinking` 帧；`error` 帧的 `timeout`、`max_tokens` 两个码 |
| Web UI | 做：「模型连接」卡片；两条错误文案；实时的思考摘要行 |
| Agent tool | 非目标 |
| Schedule | 非目标（定时任务跑的 agent 经同一个构建入口拿到新超时；无界面） |
| Notification | 非目标 |

### 验证

- 后端全量 7390 passed（失败的只有已知的环境用例，以及一个单独跑能通过的偶发测试）；前端 780 个测试通过。
- 真实 E2E 全部通过，见 [`MVP-2.7.1-CHAT-E2E-REPORT.md`](MVP-2.7.1-CHAT-E2E-REPORT.md)「追加：模型流读超时与思考摘要」：
  - 思考期间帧与帧之间最大间隔 5.9 s；
  - 输出上限用完时，界面给出新的提示；
  - Max tokens 调到 64000 后，同样重的请求 139 s 完成；
  - 历史重建不再出现 INVALID_TOOL_NAME。

### 配置方向（主人 11-08 决定）

`settings.yaml` 逐步交给 DB 接管：非核心或限额类配置逐步迁进 DB 配置表；yaml 只保留默认值和启动配置。这次只迁了新增的读超时；各 agent 的 model / max tokens / 窗口留到之后单独迁。

## OpenAI 模型的推理参数、被拒请求的原因、SQLite 锁（2026-11-08）

### 起因

主人在开发机上用 GPT-6 Astra 加任意一个 effort 对话，每一轮都只显示「The reply failed.」。同一天开发机上还有一轮对话以 `database is locked` 失败（14:31 UTC）。

### 实测

错误原文存在失败消息的 `token_usage.error` 里（开发机，只读查询）：

- GPT-6 Astra 那两轮：`ValidationException … Unknown parameter: 'reasoning_effort'.`
- 14:31 那一轮：`(sqlite3.OperationalError) database is locked`，发生在服务重启后、Signal Gate 删除 5706 条过期信号的 0.6 秒后。

直接调 Bedrock ConverseStream（开发机和本机都调了；本机现在能直连这些模型），每次调用不到几美分。逐个型号、逐个档位都发了一遍：

| 型号 | `reasoning_effort`（原来发的） | `reasoning: {effort}` | 支持到的最高档位 |
|---|---|---|---|
| GPT-6 Astra / Sol / Luna，GPT-6.1 Terra / Sol | **400 `Unknown parameter: 'reasoning_effort'`** | 正常 | max |
| GPT-5.6 Terra / Luna / Sol | **同样 400** | 正常 | max |
| GPT 5.5、GPT 5.4 | 被接受但无效（连 "bogus" 也照收） | 正常，档位生效（GPT 5.4：6 → 42 token） | xhigh（max 返回 "'max' is not supported"） |
| gpt-oss-120b / 20b、gpt-oss-safeguard-120b / 20b | 正常，档位生效（如 120b：76 → 169 token） | 被接受，但几乎不改变输出 | high（minimal、xhigh、max 都报错） |

### 原因

1. **推理参数的格式写错了。**
   - `preamble.bedrock_model_kwargs` 给所有非 Anthropic 模型都发 `reasoning_effort`，而这只在 gpt-oss 上实测过。
   - GPT-5.6 接入时本机被地域限制，没法实测；单元测试照这个假设，把错误的格式固定成了预期结果。
   - 结果是，GPT-5.6 和 GPT-6 上选任何一个 effort（low 到 max）都会让整个请求失败。
2. **档位映射不分型号。** 原来所有 OpenAI 模型都最高给 high：GPT-5.6 / GPT-6.x 的 xhigh、max 从未发出，GPT 5.4 / 5.5 的 xhigh 也没有。
3. **被拒的请求说不清原因。** `ValidationException` 被归为 `internal`。11-07 附件文件名不合法那次也是这样。
4. **SQLite 锁住了读。**
   - 过期信号是在 Signal Gate 自己的事务里、持着 `_gate_lock` 一次删完的。
   - SQLite 用回滚日志，大事务一旦溢出到文件就挡住所有读者；Python 默认只等锁 5 秒。

### 修复

- **按模型家族发推理参数（`preamble._openai_reasoning_fields`）：**
  - 一张实测出来的表 `_OPENAI_REASONING`（型号、请求字段、最高档位）：gpt-oss → `reasoning_effort`，最高 high；GPT 5.4 / 5.5 → `reasoning: {effort}`，最高 xhigh；GPT-5.6 / GPT-6.x → `reasoning: {effort}`，最高 max。
  - 档位先按 Claude 的 `_effort_tier` 五档映射（2048 → low，4096 → medium，8192 → high，12288 → xhigh，更高 → max），再截到该型号的最高档位。
  - 表里没有的型号不发这个字段，只记一次 warning。不带这个字段的请求总是合法的。
- **被拒的请求单独一类（`chat/stream_errors`）：**
  - 不是上下文超长的 `ValidationException` 归为 `request_rejected`。
  - `rejection_detail` 取 Bedrock 给的原因：去掉 "The model returned the following errors: " 前缀、脱敏、最多 300 字。
  - 原因写进 SSE `error` 帧的 `detail`，并存进 `token_usage.error_detail`。
  - 界面在「模型拒绝了这次请求。」下面显示「原因：…」，生成时和重新打开会话时都显示。
- **SQLite：**
  - `init_db` 把库切到 WAL（`models._use_wal`，记在库文件里），读者不再等写者。
  - 每个连接等锁 30 秒（`models._SQLITE_BUSY_TIMEOUT_S`）。
  - 过期信号每批删 500 行，每批一个事务，在拿 gate 锁之前做；每个进程每天一次（`_prune_lock`）。
  - 所有用 SQLite 的部署都在本地盘、EBS 或 emptyDir 上：WAL 不能放在 NFS / EFS 上。
  - **备份：** 只拷 `.db` 文件已不是完整备份；部署流程用的在线备份 API 会把 WAL 里的内容一起拷进去。

### 可达面

| 面 | 本次 |
|---|---|
| CLI | 做（无界面）：CLI 的 agent 走同一个 `bedrock_model_kwargs`；两项数据库改动对 CLI 进程同样生效。CLI 的错误输出不改（非目标） |
| Web API | 做：SSE `error` 帧新增码 `request_rejected` 和 `detail` 字段；失败消息的 `token_usage` 多了 `error_detail` |
| Web UI | 做：被拒的请求显示「模型拒绝了这次请求。」和「原因：…」 |
| Agent tool | 非目标 |
| Schedule | 做（无界面）：定时任务的 agent 同样拿到修正；安全轮询里的过期信号清理改为分批 |
| Notification | 非目标 |

### 验证

- **后端全量**：7478 passed、99 skipped、4 failed。4 个失败都是本机环境造成的：
  - 本机 `settings.yaml` 的本地模型配置，影响 2 个用例；其中一个还受本机 `.env` 影响，它仍钉着 `AIOPS_BEDROCK_MODEL_ID=…claude-opus-4-6-v1`；
  - reporter 提示词里一行未提交的中文；
  - DNS 误报。
- **前端**：vitest 71 个文件、783 条全部通过；`tsc --noEmit` 0 错误；在 `/tmp` 空目录里 `npm ci && npm run build` 通过。
- **真实 E2E（本机）**：结果全部通过，见 [`MVP-2.7.1-CHAT-E2E-REPORT.md`](MVP-2.7.1-CHAT-E2E-REPORT.md)「追加：OpenAI 模型的推理参数、被拒请求的原因、SQLite 锁」：
  - 被拒请求的原因，在生成时和重新打开会话时都显示；
  - GPT-6 Astra + 极限两轮对话（含工具调用）完成；
  - 选择器里 14 个 OpenAI 型号 × 4 个档位，56 / 56 成功。
- **E2E 中发现并修正**：第一版按「OpenAI 都到 max」映射，gpt-oss + 极限被拒（"'reasoning_effort' value 'max' is not supported"）。之后逐档实测所有型号，改成按型号截断的表。

## 编辑账户不再丢掉已保存的密钥；账户的增删改写审计（2026-11-09）

### 起因

11-09 02:3x（UTC），主人在 Settings → 账户 里给 Agenticops-Global 加了区域并保存。从 02:38:46 起，这个账户 34 个区域的扫描和安全轮询全部报 AccessDenied（共 216 次），对话里也用不了这个账户。

### 实测

- **开发机（只读查询）：**
  - 账户的 `credentials` 只剩 `role_arn` 和 `external_id`，加密存放的访问密钥对（`_encrypted`）没了；
  - `audit_logs` 里没有任何账户修改的记录；
  - 部署前的备份里，这个账户还有 `_encrypted`。
- **本机复现（旧代码）：**新建一个停用的测试账户，填 Role ARN 和假的 AK/SK；只改区域就保存，`_encrypted` 没了，也没有审计行。见 [`MVP-2.7.1-CHAT-E2E-REPORT.md`](MVP-2.7.1-CHAT-E2E-REPORT.md)「追加：编辑账户不再丢掉已保存的密钥」。

### 原因

1. **表单看不到已存的密钥。**API 把它们显示成 `***REDACTED***`，表单不填进输入框；不重新输入，提交的 `credentials` 里就只有 `role_arn` / `external_id`。
2. **`PUT /api/accounts/{id}` 把整份凭证换成提交的内容**，原来的 `_encrypted` 就此丢失。
3. **没了访问密钥，AWS provider 改用默认凭证链**（开发机的实例角色）去 AssumeRole；实例角色没有这个权限，于是全部 AccessDenied。
4. **账户的增删改不写 `audit_logs`**，所以没有留下记录。

同一个整体替换还会：
- 每次编辑删掉表单没有输入框的 `account_id`（身份校验用）和 `kubeconfigs`；
- 收到 `credentials: {}` 或 `null` 时清空全部凭证；
- 把 GET 的返回原样 PUT 回去时，把 `***REDACTED***` 当成密文存下。

agent 工具 `update_cloud_account` 也是整体替换。而且它在返回「Invalid source type」之前已经换掉了凭证，会话照样提交。`aiops init` 重新登记一个已有名字的账户时，同样把凭证整体换成 `account_id` / `role_arn` / `external_id`，丢掉已存的密钥和 `kubeconfigs`。

### 修复

- **编辑 = 合并（`credentials/store.merge_credentials`，经 `CredentialStore.merge_update`）。**Web API 和 agent 工具共用：
  - 密钥字段（`is_sensitive_key`，和加密用同一条规则）只被新的非空值替换；留空、不传、回传 `***REDACTED***`，或回传 `list_cloud_accounts` 打印的 `****xxxx` 掩码，都保持不变；
  - 非密钥字段：`""` 或 `null` 表示删除，有值就设置；
  - 没传的字段一律保留（`account_id`、`kubeconfigs`）；
  - 删除已存的密钥只有一种方式：`clear_secrets`；
  - 密钥没变时保留原来的密文。凭证指纹（会话缓存 key、私有 kubeconfig 路径）按存储形态计算，重新加密会让它变，只改区域的编辑因此不会让会话和 kubeconfig 重建。
- **切换凭证方式时，去掉旧方式自己的字段。**AWS provider 只看字段在不在，不看 `credential_source_type`：有 `role_arn` 就 AssumeRole，有 `profile_name` 就压过密钥。所以 `credential_source_type` 一变，就去掉 assume_role 的 `role_arn` / `external_id`，或 profile 的 `profile_name`。已存的密钥不随切换删除。
- **审计（`services/account_audit`）：**
  - 账户的新建、修改、删除各写一条 `audit_logs`，和改动在同一个事务里；
  - 记录前后两份快照：非密钥字段，加上是否存有密钥；
  - `details.secrets` 记密钥的去向（kept / replaced / added / removed / none），`details.via` 记来源（web / agent_tool / cli）；
  - 从不记录密钥值或密文；
  - actor 是会话里的用户；agent 工具用当前运行的 actor，没有运行上下文时记 `agent:unattributed`。
- **CLI 的账户写入也写审计（`via: cli`，actor 为 `cli:<系统用户>`）：**`aiops create|update|delete account`、CLI 对话里的 `/account activate|deactivate|delete`；`aiops init` 重新登记已有账户时改为合并，已存的密钥和 `kubeconfigs` 保留。`aiops update account` 原本就是在原凭证上改字段，不会丢密钥，这次只加审计。
- **账户的三个写接口改为普通 `def`。**编辑要解密、再加密，KMS 后端下这是网络调用。
- **agent 工具 `update_cloud_account`：**
  - 先校验所有参数，再改任何东西；
  - 新参数 `clear_secrets='true'`；
  - docstring 写明合并规则。
- **表单（Settings → 账户，`lib/accountForm.buildAccountCredentials`）：**
  - 编辑时只发这种方式有输入框的字段：清空的非密钥字段发 `""`；密钥只在输入了新值时才发；「Access Keys Only」方式还会发 `role_arn: ""` 和 `external_id: ""`；
  - 账户存有密钥时，在密钥输入框下方显示「Stored keys are kept — leave empty to keep them」，并给一个「Remove the stored keys」勾选项（Assume Role 方式下的说明是「Use the platform identity instead」）；
  - 切换凭证方式不再清空表单：原来那样会把已存的 `account_id` 清空，保存时就删掉了。
- **已处理的数据（主人同意）：**
  - 从部署前的备份恢复了 Global 账户的密钥，AssumeRole 恢复；
  - 去掉了 17 个这个 AWS 账户没开通的区域（34 → 17）；
  - 之后的资源扫描（03:37–03:44 UTC）`errors: 0`，Global 账户 1526 个资源。

### 可达面

| 面 | 本次 |
|---|---|
| CLI | 做：`aiops create|update|delete account`、对话里的 `/account activate|deactivate|delete` 写审计；`aiops init` 重新登记已有账户时合并、写审计（计划里写成「非目标：没有修改账户的 CLI 命令」，实现时发现写错了，按主人「增删改都写审计」的决定补上） |
| Web API | 做：`PUT /api/accounts/{id}` 改为合并，新增 `clear_secrets`；新建、修改、删除各写一条 `audit_logs` |
| Web UI | 做：编辑账户时显示「Stored keys are kept」和「Remove the stored keys」；只发送这种方式有输入框的字段。审计行出现在 Settings → 审计日志（无需改动，那一页读 `GET /api/audit`） |
| Agent tool | 做：`update_cloud_account` 同样合并，新增 `clear_secrets`；`add_cloud_account` / `update_cloud_account` / `remove_cloud_account` 都写审计 |
| Schedule | 非目标 |
| Notification | 非目标 |

### 验证

- **后端全量**：7524 passed、99 skipped、3 failed。3 个失败和上一轮一样，都是本机环境造成的：本机 `settings.yaml` 的模型配置（2 个用例），reporter 提示词里一行未提交的中文（1 个）；DNS 误报这次通过了。新增的测试：凭证合并 23 条、账户接口 10 条、agent 工具 7 条、CLI 5 条，外加 vitest `accountForm` 8 条。
- **前端**：vitest 72 个文件、791 条全部通过；`tsc --noEmit` 0 错误；在 `/tmp` 空目录里 `npm ci && npm run build` 通过。
- **真实 E2E（本机）**：全部通过，见 [`MVP-2.7.1-CHAT-E2E-REPORT.md`](MVP-2.7.1-CHAT-E2E-REPORT.md)「追加：编辑账户不再丢掉已保存的密钥」：
  - 先在旧代码上复现：只改区域，`_encrypted` 就没了；
  - 新代码上只改区域：密文不变（sha1 相同），`account_id`、`kubeconfigs` 保留；
  - agent 工具、「Remove the stored keys」、切到 Access Keys Only、删除，以及真实的 `aiops update|delete account` 都按规则执行，各写一条审计；
  - Settings → 审计日志 列出这些行，没有一行含密钥值。
- **实现中发现并补上**：计划里 CLI 写成「非目标」，实现时发现 CLI 有五处写账户，`aiops init` 也会整体替换凭证，已补上（见上文「修复」）。

### 观察到但不在这次改

- **开发机没有配置凭证加密的密钥**（没有 `AIOPS_MASTER_KEY` / `AIOPS_KMS_KEY_ID`），`_encrypted` 实际上只是 base64 编码。
- **「Assume Role 不填密钥 = 用平台身份」与凭证铁律第 2 条的措辞冲突**：铁律写的是只有 `environment` 类型可以用默认凭证链。是否改成一个显式的选项，由主人决定。
- **账户表单不校验区域是否已在 AWS 账户里开通**：这次的 17 个区域就是这样加进去的。

## 随 rebase 带入的 main 交付（2026-11-07）

11-07 本分支 rebase 到 `main` = `bb01e5f`。v2.7.0（`a953e6b`）之后直接在 main 上交付的工作因此都在 2.7.1 里，版本串仍是 2.7.0。它们各自的设计、可达面与证据在下表所指的文档里，这里不重复。

| 交付 | PR / 合并提交 | 一句话 | 文档 |
|---|---|---|---|
| 只读 viewer / editor 账户，删除自助注册 | PR #28 `93d7fcb`；PR #29（`ae62cd2`，经 PR #33 合入） | 自身权限不含 write 的用户只能浏览、对话、改自己的密码和偏好，其余写请求 403 `read_only`；对话跑只读主 agent；`settings_read` 可只读看 Settings；账户只能由 `aiops users create` 建立 | `MVP-2.7.0-RELEASE.md`「发布后追加」 |
| RAW 想法文档只留本地 | PR #30 `4dfd0c5` | `RAW-Idea-latest-v3.md`、`RAW-Creative-Idea.md` 不再进 git（在 `.gitignore`），本地副本保留 | 同上 |
| 两份研究 | PR #31 `e257321` | AgentCore 中国区、Strands 升级 | `superpowers/specs/2026-11-06-*-study.md` |
| Strands 1.45 → 1.64 保持行为升级 + 可行性报告 | PR #33 `603046d`；报告 PR #34 `9119cfb` | 不传 `context_manager`（1.56 起它会丢弃各 agent 的 `conversation_manager`）；`ContextOffloader` 作插件并保留 1.45 只取头的预览 | `STRANDS-1.64-UPGRADE-REPORT.md` |
| 模型配置一致性 | PR #35 `f115743` | 所有直连模型调用走 `preamble.converse_text`（只对接受的模型发 `temperature`，跳过推理块，空回答报错）；技能生成 / 案例提炼 / SOP / 旧 RCAEngine 跟随 Main；`agent_logs` 记实际运行的模型；价格表来自 AWS Price List；提交的默认模型 = 开发机实际在用的（Opus 5.5 / Sonnet 5.5 / GPT-6 Astra） | `superpowers/plans/2026-11-07-model-config-fixes.md` |
| 聊天附件 | PR #36 `7893547` | 对话里粘贴 / 拖入 / 选择任何常见文件，立即上传；按模型交付（Claude 原生读图片与 PDF / Word / Excel，GPT-6 只看图，gpt-oss 只读文本），每次请求守 Bedrock 上限；历史附件预算钩子；上传配置存数据库，管理员在 Settings 或 `/api/settings/chat-upload` 修改并留审计 | `superpowers/plans/2026-11-07-chat-attachments.md`（含证据） |
| 开发机 Node 22 | PR #37 `bb01e5f` | deploy-sg 装 Node 22：ACP Claude Code 适配器 0.50+ 需要 Node ≥ 22，Node 20 上只能装到不认识 Opus 5.5 的 0.49 | `iac/deploy-sg/` |

### 从 v2.7.0 升到本分支的注意

1. **依赖要重装**：`requirements.txt` 钉 `strands-agents==1.64.0`，并新增 openpyxl、python-pptx、pillow-heif、defusedxml（`files` 扩展）。`uv pip install -r requirements.txt && uv pip install -e ".[im,files,reports]" --no-deps`。
2. **前端要重建**：`cd src/agenticops/web/frontend && npm install && npm run build`。11-07 本地实测：没重建时服务端用的是 10-08 的旧前端包，它发消息不带 `client_message_id`，每次发送都是 422「client_message_id (a UUID) is required」。git 跟踪的 `dist/` 已经很旧，不能当作当前前端。
3. **先停服务再切换代码**：运行中的旧进程会在切换后懒加载磁盘上的新模块（Strands 版本不一致时报 `ImportError: StorageError`）；切换、装依赖、重建之后再启动。
4. **`settings.yaml` 新键**：`chat_upload:`（上传限额，管理员可在运行时覆盖）、`chat_attachments_dir`、价格表的 Claude 5.5 / GPT-6 行；提交的默认模型改了（见 PR #35）。本地或机器上有自己的 `settings.yaml` 时，三方合并：自己选过的值保留，其它取新版本。
5. **新表**：`chat_attachments`、`runtime_settings`，启动时 `create_all` 自动建。
6. **不要在环境变量里钉模型**：`AIOPS_*` 压过 `settings.yaml`；开发机的 `AIOPS_BEDROCK_MODEL_ID` 已删。
7. **ACP 需要 Node ≥ 22**（PR #37）。

### rebase 的冲突处理

| 文件 | 处理 |
|---|---|
| `CLAUDE.md`、`docs/README.md`、`docs/MVP-2.7.0-RELEASE.md` | 两边都保留：main 的「发布后追加」与 2.7.1 的版本行 / 指引并存 |
| `README.md` / `README_CN.md` 设计原则 | 第 2 条取 2.7.1（自动批准以命令可判档为前提），第 3 条取 main（模型分层改为 5.5） |
| `run_context.py` | 并集：main 的 `read_only` + 2.7.1 的 `model_id` / `run_started_at` |
| `agents/executor_agent.py` | 并集：2.7.1 的 `run_context(run_started_at=…)` 包裹 + main 的 `track_agent(model_id=…)`（按实际运行的模型计价） |

**门禁**（2026-11-07，rebase 后的 `MVP-2.7.1` = `cd4f0d2`，一次性库）：后端全量 **7339 passed / 99 skipped / 1 failed**——失败的是已知的 DNS 误报 `test_web_tools.py::TestWebFetchErrors::test_invalid_headers_json`（本机 DNS 把 example.com 解析到私网段，SSRF 守卫先触发）；前端 vitest 61 个文件 / 725 条，`tsc --noEmit` 0 错误。本地主检出切到本分支后重启服务，发送一条消息得到 `accepted` → 回复 → `done`。

---

## 六个可达面（本版本合计）

A1 的逐行见上文；A2–A4 与跟进项的可达面在各自计划里逐行列出（CLI / Web API / Web UI / Agent tool / Schedule / Notification，Web API 与 Web UI 两行）。随 rebase 带入的 main 交付，可达面在各自文档里（见上表「文档」列）。
