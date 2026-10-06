# 变更感知的系统模型（Change-aware System Model）设计

> **日期**：2026-10-06 · **分支**：`MVP-2.6.1`（实现落在哪个分支由主人在计划阶段定）· **状态**：待主人评审
> **来源**：2026-10-05/06 的架构讨论（brainstorm）。主人提出"系统性加强 RCA、资源构图精确性、实时性、易用性"，讨论收敛为三个子项目：**A' 变更感知的系统模型**（本 spec）→ B RCA 调查运行时 + 评测（已批准的 Harness 计划阶段 1–2）→ C 易用性作为 A/B 的验收要求。本 spec 只覆盖 A'。
> **参考**：`RAW-Idea-latest-v3.md`（两条流水线一个闭环；Scan/Detect 作为后台数据飞轮；L3–L4 甜蜜点）、`docs/AGENTIC-SRE-READINESS-AUDIT-2026-08-29.md` §3.6（"当前 Graph 是资源图，不是运维知识图"）、`docs/MVP-2.6.1-GRAPH-FACTS-MEASUREMENT.md`、`docs/MVP-2.6.1-LOCATION-EVAL-REPORT.md`。

## 0 主人已定的决策（本 spec 的约束）

| # | 决策 | 日期 |
|---|---|---|
| D1 | 三分法：A' 系统模型 → B RCA 运行时 → C 易用性并入验收；第一个 spec 做 A' | 2026-10-05 |
| D2 | **变更事件只拉取，不在客户账户部署任何东西**；推送（EventBridge）只留数据契约 | 2026-10-05 |
| D3 | **感知度是每个资源的属性**，不是系统开关：EC2 这类少变的小时级够，Focus 的服务分钟级，端点秒到分钟级 | 2026-10-05 |
| D4 | 感知度由**系统自己维护**（确定性规则，零 LLM），人少参与；**SRE 手设的值单独留存、钉住**；颗粒度在资源创建时就赋予 | 2026-10-05 |
| D5 | Service 作为完整实体放 spec 2；本期"服务"只是感知度的选择器（标签 / 命名空间 / 账户） | 2026-10-05 |
| D6 | 路线 1：常驻感知工作线程 + 变更账本（否掉：调度器原生多条小调度；只做探针差异；走 Signal Gate） | 2026-10-05 |
| D7 | 三节设计（数据模型与感知度 / 工作线程与数据流 / 覆盖面·RCA·评测·可达面·分期）逐节通过 | 2026-10-06 |

一处**反转**要明说：2026-09-30 主人曾裁定"CloudTrail 增量只加快可见性，先不做；全量对账保证正确性"。按 D3 的需求，增量现在要做——但**正确性仍由对账扫描保证**，增量只负责新鲜度，这一点不变。

## 1 问题与目标

**问题（实测，2.6.1）**
- 图只按小时轮询（`resource-scan` 60 min、`galaxy-auto-build` 60 min、`k8s-discovery` 10 min）。RCA 看不到"告警前谁动了什么"：`content_changed_at` 记的是**采集注意到变化的时刻**（粒度 10 分钟，且只有 K8s 连接器写，AWS 行永远为空）；没有任何变更账本；CloudTrail 只被 agent 临时查、结果不落库。
- 锚定率 66.1%（(562+25)/888）。297 条未锚定里 291 条是"库存里没有这个资源"——扫描器只列 17 种类型，告警指向的 CloudFormation 栈、ELB 目标组、IAM 实体等不在库存。
- 13 场景定位评测 AC@1 0.77、图召回 13/13；3 个未命中都是数据/层级问题（被删对象只剩缺席行；节点级答案落到集群级），不是推理问题。
- 图查询不是瓶颈：2 跳 p95 6.1 ms、SQL ≤ 4。

**目标**：图按资源的"感知度"保持新鲜，RCA 的证据包里有真实的变更时间线（谁、何时、改了什么），锚定缺口按实测分布补齐，并且每一步都在评测上量出来。

**可测的成功标准**
1. 锚定率 ≥ 95%；达不到则按原因分布如实报告（例如长尾是无扫描器的 agent 写入 ARN 行），不放宽规则。
2. 新鲜度（chaos-lab 实测，三个感知场景）：`live` 资源变更后 ≤ 60 s 可见；`minute` 级 K8s 变更 ≤ 2 min；`minute` 级 AWS 变更在 **CloudTrail 可查后** ≤ 3 min（CloudTrail 自身延迟 2–15 min 不替它承诺）；`hourly` 不变。
3. RCA 证据包在窗口内含 `change_event`，带 `actor` 与 `event_name`；AC@1 / 图召回在扩大后的评测集上不低于基线 − 0.1 / 12/13。
4. 每账户每分钟只读调用数有上限，可在 Settings 看到；Galaxy 每小时的 LLM 重算降为 $0（易变字段补齐）。
5. `sensing_enabled=false` 时系统行为与 2.6.1 分毫不差。
6. 门禁：全量 pytest 不低于基线（2.6.1 收尾时 6378 passed / 85 skipped）；前端 `tsc` / vitest / build / locale parity。

## 2 范围

**做**：变更账本与游标；感知度（资源属性）与 Curator；Sensing Worker（CloudTrail 游标拉取、K8s events 拉取、live 探针）；单资源增量刷新 + 防抖 rule-only 图刷新 + 重锚定；RCA 证据包接入；覆盖面重测与解析器补齐；"端点"两种新采集；评测门禁（每夜 $0 指标 + 每周 chaos-lab 三个感知场景 + 阈值断言）；六个可达面（§8）。

**不做**：推送接入（EventBridge/SNS/SQS，只留 `source` 枚举位与"一条事件一行"的契约）；K8s watch（分钟级用拉取够，秒级靠探针）；Service 实体（spec 2）；Neo4j / PostgreSQL 迁移；通知（预算触顶、凭证失败只记日志与状态卡）；在 CI 里跑 chaos 评测（需要实验室凭证）；L5；复活 `services/graph_sync_service.py`（死代码，非账户寻址）。

## 3 核心概念：感知度（sensitivity）

每个 `cloud_resources` 行有一个感知度，三级：

| 级 | 含义 | 机制 |
|---|---|---|
| `hourly` | 地板；就是今天的对账扫描。没有"关掉"这一级 | `resource-scan` / `k8s-discovery`（不变） |
| `minute` | 分钟级变更可见 | CloudTrail 游标拉取 + K8s events 拉取触发的单资源增量刷新 |
| `live` | 秒到分钟级 | 对该资源的定向只读探针 + 内容哈希比对 |

**进入库存即赋值**：扫描器 `scanner/engine._save_resources`、连接器 `connectors/ingest.ingest`、agent `tools/metadata_tools.save_resources` 三条写入路径都经同一个 `services/inventory.assign_sensitivity(row)`，按类型默认表给初值。

**钉住规则**：`sensitivity_set_by="user"` 的值系统永不覆盖；SRE 设回 `null` = 交还系统。

## 4 数据模型

### 4.1 `change_events`（新表）—— 证据，不驱动 Issue，不驱动执行

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | PK | |
| `account_id` | FK `aws_accounts` | 账户寻址：事件属于哪个被管账户 |
| `provider` | `aws` / `kubernetes` | |
| `resource_id` | String(500) | 事件源看到的资源标识（原样：ARN、短 id、`<cluster>/<Kind>/<ns>/<name>`） |
| `resource_ref` | FK `cloud_resources.id`，可空 | 经 `services/identity_resolver.resolve` 锚定；锚不上留空，**不猜** |
| `event_time` | datetime（UTC） | **真实发生时间**（CloudTrail `EventTime`、K8s `lastTimestamp`/`eventTime`；探针/对账差异用观察时间） |
| `observed_at` | datetime（UTC） | 我们看到它的时间；`observed_at − event_time` 是新鲜度滞后 |
| `source` | `cloudtrail` / `k8s_event` / `probe` / `scan_diff` | 枚举留位给未来的 `push` |
| `event_name` | String(120) | 如 `ModifyDBInstance`、`ScalingReplicaSet`、`content_changed` |
| `actor` | String(200)，可空 | CloudTrail `Username` / `userIdentity.arn`；K8s `source.component`；探针与对账为 `agenticops:sensing` |
| `summary` | String(500) | 一句话 |
| `detail` | JSON | **有界**：只存按来源白名单挑出的键（§6 配置 `change_events_detail_keys`）；CloudTrail 的 `requestParameters` / `responseElements` 默认不存 |
| `fingerprint` | String(64)，唯一索引 | `sha256(source|account_id|event_id)`；无 event_id 的来源用 `source|account_id|resource_id|event_time|event_name`。重复拉取幂等 |
| `created_at` | datetime | |

索引：`(resource_ref, event_time)`、`(account_id, event_time)`、`fingerprint` 唯一。保留期 `change_events_retention_days`（默认 90），每日清理，与 `audit_logs` / `alert_events` 同一套清理调度。

### 4.2 `change_cursors`（新表）—— 形状照抄 `SecurityPollCursor`，**不复用那张表**

`(account_id, source, scope)` 唯一（AWS 的 scope = region；K8s 的 scope = cluster），`cursor`（ISO 时间或 resourceVersion）、`updated_at`、`last_error`、`last_error_at`。不复用 `security_poll_cursors` 的原因：安全轮询的语义是"高危事件 → Issue"，耦合会让一边的改动破坏另一边。

### 4.3 `cloud_resources` 新增 5 列

| 列 | 取值 |
|---|---|
| `sensitivity` | `hourly` / `minute` / `live`，默认由类型表决定 |
| `sensitivity_set_by` | `system` / `user` |
| `sensitivity_reason` | `type_default` / `focus_selector` / `open_issue` / `critical_issue` / `recent_changes` / `budget` / `agent_request` / `user` |
| `sensitivity_updated_at` | datetime |
| `next_check_at` | datetime，可空；Sensing Worker 优先队列的键，`hourly` 行为空 |

迁移：沿用 `_migrate_2_6_x` 的写法——幂等 `ALTER TABLE ADD COLUMN`，新表 `create_all`；随后一次 fail-soft 回填：所有现有行按类型默认表赋 `sensitivity`，`set_by=system`，`reason=type_default`。

### 4.4 Service 留位

本期不建 Service 表。为 spec 2 留位的只有一条约定：`change_events` 与感知度都挂在资源上，Service 层到来时通过 `cloud_resources.service_ref`（未来列）聚合，**不需要改本期任何表**。

## 5 感知度 Curator：确定性规则，零 LLM

在 Sensing Worker 的每个周期跑一遍（`services/sensitivity.py`，纯函数 + 一次事务），对每个在场资源按序判定，命中即止：

1. `set_by == "user"` → 不动。
2. 命中 **Focus 选择器**（配置 `sensitivity_focus_selectors`：按标签键值、K8s 命名空间通配、账户名）→ 选择器指定的级（默认 `live`），reason `focus_selector`。
3. 资源上有**未关闭 Issue**（`OPEN_ISSUE_STATUSES`，按 `resource_ref`）→ 至少 `minute`，reason `open_issue`；是 **critical** Issue 的锚点 → `live`，reason `critical_issue`。Issue 关闭后下一周期回落。
4. **近期变更密度**：`sensitivity_recent_change_window_minutes` 内该资源的 `change_events` ≥ `sensitivity_recent_change_threshold` → 升一级，reason `recent_changes`，静默 `sensitivity_decay_minutes` 后回落。
5. **agent 临时请求**（§7.3）：在有效期内 → 至少请求的级，reason `agent_request`；到期回落。
6. 否则 → 类型默认，reason `type_default`。
7. **预算降级**（在以上之后、作为上限）：该账户上一分钟的调用数超过 `sensing_max_calls_per_minute_per_account` → 本周期把该账户的 `live` 行按 `next_check_at` 最晚者优先降到 `minute`，reason `budget`；预算恢复后下一周期按规则重算。宁可慢，不打爆客户账户的 API 限速。

变级只更新 5 列；`user` 的设置与交还另写 `audit_logs`（action `sensitivity.set` / `sensitivity.release`，actor 为会话身份）。系统变级不写审计（reason + updated_at 已可解释）。

## 6 配置（全在 `config/settings.yaml`；`config.py` 只定义 schema）

| 键 | 默认 | 说明 |
|---|---|---|
| `sensing_enabled` | `false` | 总开关；默认关，P4 评测通过后再议默认开。关 = 2.6.1 行为 |
| `sensitivity_type_defaults` | `{hourly: [EC2, VPC, Subnet, SecurityGroup, NATGateway, IAMRole, KMS, S3, EBS, EFS, Route53, K8s_Namespace, K8s_Node, K8s_ConfigMap, K8s_Secret, K8s_PersistentVolumeClaim], minute: [EKS, ECS, RDS, DynamoDB, ElastiCache, OpenSearch, ELB, AutoScaling, Lambda, K8s_Deployment, K8s_StatefulSet, K8s_DaemonSet, K8s_Service, K8s_Ingress, K8s_NetworkPolicy, K8s_PodDisruptionBudget, K8s_Pod], live: []}` | `live` 默认清单在 P2 的两种端点采集（`TargetGroup`、`K8s_EndpointSlice`）落地后填入；未列类型 = `hourly` |
| `sensitivity_focus_selectors` | `[]` | 形如 `[{tags: {Service: payment}, tier: live}, {k8s_namespace: "prod-*"}, {account: prod-a, tier: minute}]` |
| `sensitivity_open_issue_tier` / `sensitivity_critical_issue_tier` | `minute` / `live` | 规则 3 |
| `sensitivity_recent_change_window_minutes` / `_threshold` / `sensitivity_decay_minutes` | `60` / `3` / `180` | 规则 4 |
| `sensitivity_agent_request_max_hours` | `24` | §7.3 |
| `sensing_cloudtrail_interval_seconds` | `120` | 每账户 × 区域 |
| `sensing_cloudtrail_page_cap` | `500` | 每轮每账户-区域最多处理的事件数；超了记"本轮截断"，游标只推进到已处理的最后一条 |
| `sensing_cloudtrail_overlap_minutes` | `5` | 游标回退重叠，幂等靠 fingerprint |
| `sensing_cloudtrail_ignore_prefixes` | `[Describe, List, Get, Head, BatchGet, LookupEvents]` | 跳过只读事件名 |
| `sensing_k8s_events_interval_seconds` | `60` | 每集群 |
| `sensing_k8s_event_ignore_reasons` | `[Pulled, Pulling]` | 纯噪音；`Killing` / `ScalingReplicaSet` / `FailedScheduling` / `BackOff` / `Unhealthy` 等保留 |
| `sensing_live_probe_interval_seconds` | `30` | 每个 `live` 资源 |
| `sensing_debounce_seconds` | `30` | 变更 → 图刷新的合并窗口 |
| `sensing_max_calls_per_minute_per_account` | `60` | 三类任务共用的预算 |
| `change_events_retention_days` | `90` | |
| `change_events_detail_keys` | `{cloudtrail: [eventSource, eventName, awsRegion, sourceIPAddress, userIdentity.type, userIdentity.arn, errorCode, errorMessage, resources], k8s_event: [reason, type, count, source.component, involvedObject, message], probe: [changed_keys], scan_diff: [changed_keys]}` | `detail` 白名单；`message` 截 500 字符 |

YAML 里 `hourly/minute/live` 等键名不会被解析成布尔值；但沿用项目规则：所有键加引号。

## 7 Sensing Worker 与数据流

### 7.1 宿主

一个 daemon 线程，**只在调度器选出的那个 worker 里启动**（复用 `web/app.py` 的 `fcntl` 文件锁选举 / `AIOPS_SCHEDULER_WORKER`），启动方式照 `im/feishu_ws.start_feishu_ws`：崩溃自动重启、指数退避、`sensing_enabled=false` 则不启动。它是**变更触发刷新的唯一写入者**（`change_events` 写入、单资源增量 ingest、`change-event` 触发的图刷新都只从它发出）——4 个 uvicorn worker 各持线程锁的已知问题对这条路径不存在；其他 worker 的手动 / API / RCA 路径不变。

### 7.2 循环：按 `next_check_at` 的优先队列，周期约 5 s，三类任务

**(a) CloudTrail 游标拉取**（每账户 × 区域每 `sensing_cloudtrail_interval_seconds`）
- 账户寻址客户端（照 `security/incremental_poll._get_client` 的写法，经 provider 层）；`lookup_events(StartTime=游标 − overlap)` 分页，到 `page_cap` 为止。
- 跳过 `sensing_cloudtrail_ignore_prefixes` 开头的事件名；其余每条 → `change_events`（fingerprint = EventId，`event_time` = EventTime，`actor` = Username / userIdentity.arn，`detail` 按白名单）。`Resources[]` 里每个 `ResourceName` 都尝试锚定（`identity_resolver.resolve` 规则 ①–④：ARN ↔ 短 id、ELB ARN 名段、name）；一条事件涉及多个资源就写多行（fingerprint 加 `|resource_id`）。
- 游标推进到本轮处理的最后一条 `EventTime`；错误 → `last_error`，退避，下一轮续。

**(b) K8s events 拉取**（每集群每 `sensing_k8s_events_interval_seconds`）
- `kubectl get events -A -o json`，经 `credentials/kube.kubectl_env_for_cluster`，沿用连接器的 byte cap 与超时；去重键 `metadata.uid + count`（K8s 事件会聚合计数，count 变化 = 新一次发生）；忽略清单滤噪音。
- 按 `involvedObject`（kind/namespace/name）构造 `<cluster>/<Kind>/<ns>/<name>` 锚定；`event_time` 取 `eventTime` 或 `lastTimestamp`；`actor` = `source.component`。

**(c) live 探针**（每个 `live` 资源每 `sensing_live_probe_interval_seconds`）
- AWS：对应类型的单资源只读 describe（经 `run_aws_cli` 的只读路径 / provider 会话，账户寻址）；K8s：`kubectl get <kind> <name> -n <ns> -o json`。
- 与上次 `raw_data` 的内容哈希比对（`galaxy/hashing.content_hash`，剥易变字段）；变了 → `change_events`（source `probe`，`detail.changed_keys` 列出变化的顶层键）+ 单资源增量 ingest。
- **顺手修一处已知缺陷**：`galaxy/hashing.VOLATILE_KEYS` 补 `LatestRestorableTime`、`CertificateDetails.ValidTill` 等（RDS）与 AutoScaling 的对应字段，止住 Galaxy 每小时对同 3 个资源的 LLM 重算（实测约 $0.033/h）。

### 7.3 变更 → 图

能锚定的 `change_event` → 对**那一个资源**定向 describe → `connectors/ingest.ingest(..., completeness={})`（永不标缺席；AWS 资源走等价的单行 `save/mark_seen` 路径，并**在此设置 `content_changed_at`**，补上 AWS 行永远为空的缺口）→ 防抖 `sensing_debounce_seconds` 合并 → `galaxy.builder.build_graph("change-event", llm=False)`（`RULE_ONLY_TRIGGERS` 加 `change-event`，$0）→ `_reanchor()`。
**删除不走这条路**：仍由对账扫描 / 发现运行判缺席；但 `Delete*` / `Terminate*` / K8s `Killing` 事件把该资源的 `next_check_at` 提前到"立即"，让缺席更快被探针或下一次对账确认。

**agent 工具 `request_sensitivity(resource, hours)`**（Main / RCA 可见）：只能**临时升级**到 `live`（≤ `sensitivity_agent_request_max_hours`），不能降级、不能钉住；写 `audit_logs`（action `sensitivity.agent_request`，actor `agent:<name>`）；到期由 Curator 回落。这就是 D4 里"agent 自己维护感知系统"的全部开口。

### 7.4 预算与退让

每账户每分钟调用数计数（内存，按 UTC 分钟桶）。超 `sensing_max_calls_per_minute_per_account` 时按序退让：先把 live 探针降到 minute（§5 规则 7）→ 再推迟本轮 CloudTrail 拉取 → **永不停对账**（对账不计入这个预算，它在调度器里）。

### 7.5 状态

不另开表。`GET /api/sensing/status`（§8）从 `change_cursors.updated_at` / `last_error` + 内存计数算出：每账户 × 来源的游标时间与滞后、每分钟调用数、预算状态、三级资源计数、worker 是否存活、最近一次图刷新。

### 7.6 故障行为

| 情形 | 行为 |
|---|---|
| Worker 线程崩溃 | 退避重启；API 不受影响；状态端点报 `alive=false` |
| 某账户凭证解析失败 | 只该账户的任务标 `last_error` 并退避；**绝不回退到 ambient 凭证**（铁律 2） |
| CloudTrail 限速 / 5xx | 退避；游标不动；下一轮续 |
| kubectl 超时 / 超 byte cap | 该集群本轮跳过，记 `last_error` |
| 进程重启 | 游标在库里；最多重拉 `overlap` 窗口，fingerprint 幂等 |
| 锚不上的事件 | 仍入账本（`resource_ref` 空），不触发刷新；每夜指标统计"未锚定事件率" |
| SQLite 写冲突 | 账本写入用短事务；单写线程是主要保护；PostgreSQL 会话必须 UTC（已知 B-5，这里又多一处依赖） |

### 7.7 与现有部件的关系

安全轮询 `security/incremental_poll` 不变（职责：高危 → Issue）；`k8s-discovery` / `resource-scan` 不变（正确性对账）；RCA 的按需重采（`graph/evidence._recollect`）不变，但 live / minute 资源上基本不会再触发；Signal Gate 不参与（变更是证据不是事件：它的 disposition 会把每个非噪音结果变成 Issue，flapping 会把一次部署风暴判成噪音）。

## 8 六个可达面（Web API 与 Web UI 永远两行）

| 面 | 本 spec |
|---|---|
| **CLI** | 做：`aiops sensing status`（照 `aiops connectors` 的 typer 子命令：每账户游标时间 / 滞后 / 预算 / 三级计数 / worker 存活）；`aiops sensing set <resource-id|R<n>> <hourly|minute|live|auto>`（`auto` = 交还系统；actor `cli:<user>`，写审计）。非目标：手动触发一轮拉取 |
| **Web API** | 做：`GET /api/sensing/status`；`GET /api/resources/{id}/changes?window_minutes=&limit=`（该资源的 change_events，按 `event_time` 倒序）；`PUT /api/resources/{id}/sensitivity` body `{"tier": "live"|"minute"|"hourly"|null}`（会话 actor；404 / 403（`authz` 新权限 `resource.sensitivity`，影子模式照旧）/ 422；写审计）；`GET /api/resources/{id}` 与列表响应多返回 5 个感知度字段。**不新增其它端点** |
| **Web UI** | 做：Settings → 常规加**感知卡片**（照 `components/settings/ConnectorsCard.tsx`：总开关只读显示、每账户滞后与预算、三级计数、每夜指标趋势、worker 状态）；`pages/ResourceDetail.tsx` 概览 tab 加**感知度徽标**（级别 + 原因 + 下次核对时间 + 手设选择器 / 交还）与一节**变更时间线**（`/changes`）；`IssueDetail` 诊断卡的局部拓扑旁列出窗口内的 change_events（RCA 看到的就是用户看到的）；所有文案 zh / en 成对 |
| **Agent tool** | 做：`request_sensitivity(resource, hours)`（§7.3）。非目标：agent 读账本的其它工具——证据包已带 |
| **Schedule** | 做：`SensingMetrics` 每日一条（§10）。Sensing Worker 本身是常驻线程，**不是**调度行；非目标：在 Schedules 页显示它（状态在 Settings 卡） |
| **Notification** | 非目标：预算触顶、凭证失败只记日志与状态卡 |
| **Webhook**（第七面，明确列出） | 非目标：推送接入。只保证 `change_events.source` 能容纳 `push`，一条事件一行的契约不变 |

## 9 覆盖面

**第 0 步 — 重测**：`scripts/measure_graph_facts.py` 加"按 ARN 资源段拆分"输出。现报告把 ELB / IAM / RDS / EC2 的 116 条缺失记成已扫描类型，实际是子类型（目标组、监听器、IAM 用户/策略、RDS 集群、卷/ENI）。不重测就选解析器会补错东西。

**补齐顺序**（按缺口大小；每种 = `scanner/commands.py` 命令 + `scanner/parsers.py` 解析器与 `_PARSERS` 注册 + `EXPECTED_KEY` + `PARSER_RESOURCE_TYPE` 四处；解析器输出短 id、ARN 进 `raw_data`；沿用"只有完整列举才判缺席"的门）：
1. ELBv2 目标组 + 监听器（38；同时补 ALB → 目标组 → 目标这条今天没有的关系链，`galaxy/rules.py` 加 `routes_to`）
2. CloudFormation 栈（39）
3. IAM 用户 / 策略 / 实例配置（35，global）
4. RDS 集群（25）
5. Secrets Manager（18）
6. EC2 子类型（卷 / ENI；重测后定）
7. CloudFront（15，global）
8. API Gateway（15）
9. ECR（12；agent 已写 `ECR_Repository`，沿用该名）

九种 ≈ 90%；95% 取决于 76 条长尾的构成——如实报告。

**"端点"两种新采集**（P2，专为 `live`）：ELBv2 **目标健康**（`describe-target-health`，写进目标组行的 `raw_data`，是 live 探针的比对对象）；K8s **EndpointSlice**（新 kind，`routes_to` 到 Pod；`connectors/k8s._CALLS` 加一项，`K8S_RAW_DATA_CONTRACT` 加白名单）。

## 10 RCA 接入与评测门禁

**RCA 接入**
- `graph/evidence._changes` 增加 `change_event` 种类：按 `event_time` 落在 `rca_topology_window_before_minutes` / `_after_minutes` 窗口内，`detail` 带 `actor` / `event_name` / `summary`；与 `created` / `content_changed` / `absent` / `execution` 并列，使节点成为带理由的候选（现有排序规则不变）。
- `signal_gate._promote` 在建 Issue 时把锚点窗口内的 change_events 填进 `HealthIssue.related_changes`（今天全靠 agent 自己查 CloudTrail 再填）。
- `lookup_cloudtrail_events` 工具保留；RCA 提示词改为"先读证据包里的变更，再按需查 CloudTrail"。

**评测门禁 — 两条腿**
- **每夜、$0、自动**：`scripts/measure_sensing.py`（扩展现有测量脚本，只读副本），算：锚定率按原因分布；`change_events` 各来源条数与未锚定率；新鲜度滞后 `observed_at − event_time` 的中位数 / p95 按级别；三级资源分布；预算触顶次数；Galaxy 每小时成本。调度 `SensingMetrics` 每日跑，结果写一张小表 `sensing_metrics`（日期、指标 JSON），Settings 感知卡显示趋势。
- **每周、有费用、半自动**：chaos-lab 定位评测加三个**感知场景**：`sense-k8s-scale`（minute：改 Deployment 副本数 → 账本有事件、图可见，秒数）、`sense-aws-tag`（CloudTrail：给实例打标签 → 账本有事件带 actor，秒数，并区分"CloudTrail 可查"与"我们看到"）、`sense-live-endpoint`（live：缩容让 EndpointSlice 变化 → 可见秒数）。`location_eval.py --assert`：AC@1 ≥ 基线 − 0.1、图召回 ≥ 12/13、located ≥ 0.9、三个滞后不超过 §1 承诺。评测仍由人跑（要进实验室凭证，不进 CI），**阈值由脚本判**。顺手把每个用例的定位结果以 `location_verdict` 回填，让 `GET /api/rca/location-stats` 的 Top-1 变成活数据。

## 11 测试

- **纯函数**：Curator 七条规则逐条 + 钉住 + 预算降级 + 回落；fingerprint 幂等（含多资源一事件）；游标推进与重叠；K8s events 去重与忽略清单；CloudTrail 只读前缀过滤；锚定（复用 `identity_resolver` 的测试夹具）；防抖合并；`assign_sensitivity` 类型默认与未列类型。
- **集成**：`ingest(completeness={})` 永不标缺席；`change-event` 触发的 rule-only 刷新与 `_reanchor`；`_changes` 的 `change_event` 进入候选；`_promote` 回填 `related_changes`；`PUT /sensitivity` 的 404 / 403 / 422 与审计；`sensing_enabled=false` 时无线程、无新调度、行为与基线一致。
- **契约**：照 `tests/test_issue_status_writes.py` 的 grep 测试守住"`build_graph("change-event", …)` 只在 Sensing Worker 模块里出现"。
- **门禁**：全量 pytest 不低于基线；前端 `tsc` / vitest / build / locale parity。
- **Live**：chaos-lab 三个感知场景实测滞后（§10）。

## 12 分期（每期可独立发布、可独立回退，`sensing_enabled` 兜底）

| 期 | 内容 | 退出标准 |
|---|---|---|
| **P1 账本与分钟级** | §4 两表 + 5 列与迁移；§5 Curator（规则 1–4、6）；§7 Worker 的 (a)(b) + 7.3 增量与刷新 + 7.4 预算计数 + 7.5 状态；§8 的 status / changes / sensitivity 端点、CLI、Settings 卡、ResourceDetail 徽标与时间线；§10 RCA 接入 | 实验室里 K8s 变更 ≤ 2 min 可见；账本有真实 actor；AC@1 不退；全量测试绿 |
| **P2 live 级** | §7.2(c) 探针 + §5 规则 7 预算降级 + `request_sensitivity` + §9 两种端点采集 + `VOLATILE_KEYS` 补齐 + `live` 默认清单 | live 资源 ≤ 60 s 可见；Galaxy 每小时 LLM 成本 $0 |
| **P3 覆盖面** | §9 第 0 步重测 + 九种解析器 + ALB → 目标组关系 | 锚定率 ≥ 95%，或如实报告长尾 |
| **P4 评测门禁** | §10 每夜指标 + 三个感知场景 + `--assert` + 判定回填；再议 `sensing_enabled` 默认值 | 一次完整评测通过阈值 |

## 13 风险

- **CloudTrail 量**：繁忙账户 2 分钟可达上千条管理事件——`page_cap` + 只读前缀过滤；截断时游标只推进到已处理处，不丢。`requestParameters` 可能含敏感值——白名单默认不存。
- **锚定失败率**：CloudTrail 的 `ResourceName` 形态杂（ARN / 名字 / id）；规则 ①–④ 覆盖大部分，未锚定事件仍入账本并被每夜指标盯住；P3 补覆盖面后应下降。
- **时钟**：`event_time` 来自源、`observed_at` 来自本机；滞后统计只在各自一侧比较；PostgreSQL 会话 UTC。
- **4 worker**：本设计让变更触发刷新只有一个写入者，但 `runner._LOCKS` / `builder._RULE_LOCK` / `_intake_lock` 的老问题在其它路径依旧——留在 2.6.1 已知缺口。
- **成本**：预算默认 60 次/分钟/账户 ≈ CloudTrail 1 + K8s 1 + 最多 ~58 次探针 → 最多约 29 个 live 资源保持 30 s 节奏；更多 live 资源会被规则 7 降级并在状态卡上显示——这是有意的上限，不是故障。
- **误报**：K8s 事件风暴（CrashLoop）会让"近期变更密度"规则把资源抬到 live，再被预算压回；可观察，不致命。

## 14 刻意不做（重申）

推送接入、K8s watch、Service 实体、Neo4j、通知、CI 里跑 chaos 评测、复活 `graph_sync_service.py`、让 agent 降级或钉住感知度、L5。
