# MVP-2.7.1 Release Notes — 变更感知的系统模型（核心能力轨 A1–A4）+ 2.7.0 的跟进项

> Version: 2.7.1（进行中）· Branch: `MVP-2.7.1`（从 `v2.7.0` = `a953e6b` 切出，工作树 `.worktrees/mvp-2.7.1`）· 起始日期：2026-10-09
>
> **状态：尚未开始实现。** 主人 10-08 把核心能力轨 A1–A4 从 v2.7.0 移到本版本（「complete the A1–A4's implementation within MVP-2.7.1」）。spec 已批准；A1 的详细实施计划待出，写好后交主人批准、选执行方式，批准前不动代码；A2–A4 各自开工前再出计划。依主人铁律，只有 E2E 通过且当面确认后才 `git push --no-verify`。
>
> 设计输入：`docs/superpowers/specs/2026-10-06-change-aware-system-model-design.md`（A1–A4 = 其 §12 的 P1–P4）；来历：`docs/MVP-2.7.0-RELEASE.md` 与 `docs/superpowers/plans/2026-10-05-mvp-2.7.0-roadmap.md` 的「核心能力轨」节（10-06 并入 2.7.0、10-08 移出，正文已搬到本文件）。

## 本版本范围

| 项 | 内容 | 状态 |
|---|---|---|
| **A1 账本与分钟级** | `change_events` 账本 + 感知度（资源属性）+ Sensing Worker（CloudTrail / K8s events 拉取、增量刷新）+ RCA 接入 + 三端点 / CLI / Settings 感知卡 / 资源与问题页 | **计划待出**（预定路径 `docs/superpowers/plans/2026-10-06-change-aware-a1-ledger-minute.md`） |
| A2 live 级 | live 探针、预算降级、`request_sensitivity`、两种端点采集、`VOLATILE_KEYS` 补齐 | 未开始 |
| A3 覆盖面 | 锚定缺口重测、九种解析器、ALB → 目标组 | 未开始 |
| A4 评测门禁 | 每夜 $0 指标、三个感知场景、`--assert`、再议 `sensing_enabled` 默认值 | 未开始 |
| 受保护值按表格行比较 | 主人 10-08 决定（见下文「2.7.0 的跟进项」第 1 条） | 未开始 |
| 2.7.0 E2E 观察 | 四条未修的观察（见下文第 2 条）；**是否在本版本修、修哪几条，待主人定** | 待定 |

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

2.7.0 的报告翻译把受保护值（资源 id、数字、时间等）当**多重集**比较（`services/content_protect.protected_hash`）：任何值被改、丢、增、重复或合并都会被拒，但两个值可以互换位置——`Restart i-0aaa111, keep i-0bbb222` 换成两个 id 对调、`from 3 to 2` 换成 `from 2 to 3` 都能通过（`docs/MVP-2.7.0-E2E-REPORT.md`「Observations」第 9 条）。主人 10-08：2.7.0 保留这个语义，**2.7.1 按 markdown 表格行收窄**——表格每一行内的受保护值单独比较，跨行互换不再通过。届时收紧 `tests/test_content_protect.py::test_a_swapped_pair_of_values_passes_by_design`（表格行内对调应被拒；正文段落的语序自由保留与否随计划定）。

### 2. 2.7.0 E2E 观察（未修；修不修、修哪几条待主人定）

出自 `docs/MVP-2.7.0-E2E-REPORT.md`「Observations (not fixed in this release)」：

1. **SRE 的修复方案越界**：针对「副本数为 0」的两份修复方案都加了集群级 add-on 安装、HPA 和注解，定为 L2；策略里没有任何东西把修复方案限制在问题本身的资源上。人工审查拦住了，执行角色的 IAM 拒绝了那一次 AWS 写入。
2. **回滚可能把故障带回来**：方案 #1 针对「恢复失败一半」的回滚是「把两者都缩回 0」。
3. **命令分类器判错**：`kubectl rollout status`（只读）被判为写操作（每次第一次尝试被拒、再重试）；`aws eks create-addon` 被判为 `unknown` 档，执行器在已批准的方案里被允许尝试它。报告的建议：未知档的写命令应按写处理。**这一条是执行面的安全缺口，建议优先。**
4. **`RCAResult.model_id` 为空**（API 里那次 RCA 运行）。

---

## 六个可达面（本版本合计）

A1 的逐行见上文；A2–A4 与跟进项的可达面在各自计划里逐行列出（CLI / Web API / Web UI / Agent tool / Schedule / Notification，Web API 与 Web UI 两行）。
