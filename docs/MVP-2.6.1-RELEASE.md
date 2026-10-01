# MVP-2.6.1 Release Notes — 图驱动的 RCA 定位闭环 + Issue / Change 逻辑与界面整理

> Version: 2.6.1 · Branch: `MVP-2.6.1` · Date: 2026-09-29（草稿日期；push 时按主人确认日期回填） · 主题：问题锚到图上的资源，RCA 在图上定位根因、由人评判；审批绑定内容、执行后有验收；界面拆成 问题 / 变更 / 审计
>
> **状态：计划 A–E 已全部实现，作为 `MVP-2.6.1` 分支上的本地提交存在（未 push）；全量 pytest 与前端 `tsc` / `vitest` / `vite build` / locale-parity 四道门的结果由控制器在执行时据实填入；联合 live E2E（含 26 次定位评测）尚待与主人一起跑。** 依主人铁律，只有联合 E2E 通过且当面确认后才 `git push --no-verify`。测量数字（测试计数、锚定率、查询 p95、评测指标）由控制器据实填入或引用实测文件 —— 本文不预填未验证的数字。
>
> 设计：`docs/superpowers/specs/2026-09-28-mvp-2.6.1-graph-rca-loop-and-issue-change-design.md`
> 计划：`docs/superpowers/plans/2026-09-28-mvp-2.6.1-plan-{a,b,c,d,e}-*.md`
> 图事实实测：`docs/MVP-2.6.1-GRAPH-FACTS-MEASUREMENT.md`（`scripts/measure_graph_facts.py`，在本地库只读副本上生成）
> 定位评测证据（待产出）：`docs/MVP-2.6.1-LOCATION-EVAL-REPORT.md`

## 一句话

2.6.0 之前，一个 Issue 指向哪个资源靠模糊匹配取第一条，RCA 拿到的拓扑是提示词里的一段文字，说不清「根因在哪个资源」，也没人能判它对不对；审批批的是「某个方案 id」而不是方案内容，执行完没有统一的验证，Issue 状态散落在二十多处直接赋值。MVP-2.6.1 把这几件事接成一个闭环：**Issue 锚定到规范资源 → 一张有版本的规范关系表 → RCA 用工具取有边界的局部图证据、输出经 fail-closed 校验的结构化定位 → 人对定位下判定、有统计**；修复与变更两条流都改成**审批绑定内容哈希 → 执行 → 确定性验证 → 人工验收**，Issue 状态只有一个写入口；界面按 **问题 / 变更 / 审计** 重排，并在 IssueDetail / ChangeDetail / ResourceDetail 上画出局部关系图。

## 定位（为什么做、做给谁）

- **给值班的人**：看到一个问题，一眼知道它落在哪个资源、周围连着什么、RCA 认为根因在哪、证据是什么；执行完的修复有人签字验收，而不是「跑完即关单」。
- **给平台自己**：定位是结构化、可校验、可统计的（Top-1、判定数、锚定率），为后续的评测和策略（爆炸半径参与风险升级）提供可信的地基。
- **只观测，不驱动**：定位结果和图上的潜在影响**不驱动修复**。潜在影响进入策略默认是**影子模式**（`policy_graph_impact_enforce=false`），看过 E2E 统计再由主人决定何时打开（spec §10.2）。

## 六个可达面（逐行 —— 每个面显式写「做」或「非目标」）

> 规则：**Web API 与 Web UI 永远是两行**，绝不合并成「Web」。

- **CLI** — 做。`aiops connectors list` / `aiops connectors run <name> [--account A]`；REPL `/approve` 先显示方案版本 + 内容哈希再确认，提交时带上哈希；新增 `/accept <I<id>|C<id>> yes|no <理由>`（actor 固定 `cli:<os user>`）。**非目标**：定位判定、拓扑查看（走 Web）；自带步骤由 Chat 自然语言经 agent 映射，不另开 CLI 参数。
- **Web API** — 做。
  - `GET /api/connectors`、`POST /api/connectors/{name}/run`（202 / 404 / 409）；
  - `GET /api/graph/focus?issue_id|resource_id|change_request_id&depth&node_cap`（含合并信号 `merged`、相邻问题 `candidates`，上限 50，边带 `observed_at`）；
  - `GET /api/rca/location-stats?days=`；`POST /api/health-issues/{id}/rca-feedback` 加 `location_verdict`（判定人取会话 actor，不取请求体）；
  - `POST /api/fix-executions/{id}/accept`（`decision` accepted|rejected + 必填 `reason`）；
  - `PUT /api/fix-plans/{id}/approve`、`POST /api/changes/{id}/approve` 必须带审过的 `content_hash`（缺 422，方案已变 409）；
  - `POST /api/changes` 与详情加 `proposed_steps` / `external_ref` / `steps_diff`；`POST /api/changes/intake`（HMAC 签名，见下）；
  - `GET /api/issues`、`GET /api/anomalies` 带 `scope=ops|security|all`（服务端按 `security_` 前缀过滤）；Issue 详情返回锚点字段；`GET /api/settings` 只读暴露 `policy_graph_impact_enforce`（PATCH 拒绝，400）；
  - 告警 webhook `POST /api/webhooks/alert[/{source}]` 配置 `webhook_secret` 后校验令牌或 HMAC。
  - `/api/changes/intake` **无 UI，这是有意的**：它给外部 ITSM 系统调用，创建的变更单在现有变更页面里可见。其余新端点都有对应 UI（下一行）。
- **Web UI** — 做。
  - 侧栏改为 **问题 / 变更 / 审计** 三个入口；`/app/audit` 独立成页；`/app/plans` 重定向到 `/app/changes`（`?tab=fix` → `/app/issues`，`?tab=audit` → `/app/audit`）；删除 `pages/PlansAndChanges.tsx` 与 `components/plans/FixPlansTab.tsx`。
  - 问题列表三个视图：运维事件（默认）/ 安全发现 / 全部，写进 URL（`?scope=`），原有阶段筛选保留。
  - IssueDetail 重排：顶部 业务 / 执行 / 验证 三个状态标签 + 锚点徽标（资源链接 / 未定位 / 歧义 N 个候选 / 账户级）+ 待验收横幅（接受 / 拒绝，理由必填）；五个 tab 写进 `?tab=`：调查（RCA + 定位卡 + 局部图 + 定位判定）、修复方案（版本 + 哈希）、执行记录（step / pre / post / rollback 证据）、验证、时间线（长值可展开，不再截断）。
  - ChangeDetail 重排：首屏一句话（状态 · 原因 · 待办 · 主操作）；申请（自带步骤 + 外部工单链接）、实施方案 vN（步骤、`steps_diff`、哈希）、审批（「策略建议」与「实际审批」分开；影子模式下潜在影响的数字和图标注「仅供参考」）、执行证据、验收卡；NewChangeDialog 加可选的步骤编辑和外部引用。
  - 局部关系图 `components/graph/LocalGraph.tsx`：用于 IssueDetail、ResourceDetail（新「局部关系图」tab）和 ChangeDetail 审批卡；四种关系（结构关系 / RCA 定位路径 / 合并信号 / 相邻问题）、三层爆炸半径（数字直接取 API）、下方附键盘可达的列表视图、截断时写明原因；节点详情可「在全景图中查看」（Open in Galaxy，跳到 Galaxy 的 `?focus=`）。
  - Galaxy：`?focus=<资源 id>` 深链（`cloud_resources` 的 id，写作 `12`、`R12`、`R%2312` 或 `res:12`；选中 + 居中；不在最新构建里时给提示）；有新构建落地就刷新；删除没人用的 overview / expand hooks（端点保留）。
  - Chat：`C#` 引用也打开 ContextPanel（问题 + 变更两种）；FixPlanCard 标题形如「I#12 修复方案 v2」「C#3 实施方案 v1」+ 短哈希。
  - Settings → 常规：连接器卡片（开关状态、调度、运行中徽标、立即运行、最近几次运行的状态和计数）。AgentMetrics：RCA 定位卡片（7 / 30 / 90 天，Top-1、已判定数、锚定率，定位状态与锚点分布）。
  - 命名与中英文案统一：问题 / Issues，变更 / Changes，审计 / Audit，修复方案 / Fix plan，实施方案 / Implementation plan，执行记录 / Execution，验收 / Acceptance；locale-parity 通过。
- **Agent tool** — 做。RCA：`get_topology_evidence(issue_id, depth, window_minutes)`（有边界的局部图证据包；没有已发布构建或锚点缺失时返回 `available:false` + 原因，不当作「没发现问题」）、`save_rca_result(location=…)`。Main：`get_plan`、`get_execution_result`、完整版 `get_change_request`；`request_change` 支持 `proposed_steps` / `external_ref`。**非目标**：触发连接器的工具（连接器是确定性采集，不给 agent）；审批 / 验收仍然**不是** agent 能做的动作。
- **Schedule** — 做。`k8s-discovery`（lifespan 里种子化，间隔 `k8s_discovery_interval_minutes`），采集后结构有变化就触发 rule-only 刷新；`resource-scan`（`ResourceScan` 管道，即 `POST /api/scan` 的 W2 扫描定时跑，启动时种子化一次、间隔 `resource_scan_interval_minutes`；已有的行不动，可在 Schedules 里改或停用）；重新锚定挂在每次构建完成之后，不另开调度。
- **Notification** — 做。新通知点 `execution_pending_acceptance`（fix 与 change 共用，带原因和深链）；`change_result` 在 `needs_review` 时附带原因。**非目标**：连接器失败通知（只记在 `connector_runs`，Settings 卡片可见）。
- **Webhook**（第七面，明确列出）— 做：告警 webhook 的令牌 / HMAC 校验与字段补全（6 个解析器取 `observed_at`）；变更 intake（HMAC）。**非目标**：ServiceNow / GitHub 专用适配器、外部状态回写。

## 架构与数据流

```
 推送：webhook 告警（令牌 / HMAC + 字段补全）            拉取：K8s 连接器（kubectl，账户寻址）
                   │                                                 │
                   ▼                                                 ▼
   process_signal（Signal Gate，唯一的 Issue 入口）    ingest()：实体 → cloud_resources（provider=kubernetes）
                   │                                          运行记录 → connector_runs
                   ▼                                                 │
   IdentityResolver → HealthIssue.resource_ref / anchor_status       │
                   ▲                                                 ▼
                   └── 每次构建完成后重新锚定 ◄─ Galaxy build：derive_rule_graph（账户化 + AWS/K8s 规则）
                                                   │ ① 规则关系写入 resource_relations，设置 rules_published_at
                                                   │ ② LLM 阶段（可失败，不影响 ①）；llm=False 时跳过
                                                   ▼
                                      GraphQueryService（有方向、有上限、按 build 版本）
             ┌──────────────────────────┬───────────────┴────────────┬──────────────────────────────┐
     /api/graph/focus → LocalGraph   get_topology_evidence（RCA）   estimate_blast_radius（影子模式）  评测：图召回率
                                           │
                     save_rca_result(location) → fail-closed 校验 → RCAResult.location_status
                                           │
                        人工 location_verdict → /api/rca/location-stats → AgentMetrics 定位卡片

 修复 / 变更：plan_version + content_hash → approve(content_hash) → 执行前比对批准哈希 → Executor
              → verification.evaluate() → passed / failed / pending_acceptance → transition_issue / on_execution_result
              → 人工验收 POST /api/fix-executions/{id}/accept（IssueDetail 横幅 / ChangeDetail 验收卡 / CLI /accept）
```

三条不变量：**锚定不上就明说（`unanchored` / `ambiguous` / `account_level`），绝不取第一条**；**缺验证结果永远不算 passed**；**HealthIssue 状态只由 `transition_issue` 写**（grep 测试守住）。

## 计划 A — 图事实层

- **IdentityResolver**（`services/identity_resolver.py`）：spec 的 7 条确定性规则在代码里按顺序是 `resource_id`（含 ARN ↔ 短 id）/ `elb_arn` / `name` / `account_level` / `k8s_hints` / `alarm_name`（告警名模式），第一条有命中的规则说了算；同一规则命中多个物理资源 → `ambiguous` 并把候选记进 `anchor_candidates`；跨账户同 id 不串号，输入不带账户时每条规则在所有启用账户里跑、只有唯一物理命中才锚定并回填账户。锚定不上时 `anchor_candidates.rule` 写明原因：`none`（库存里没有）、`unknown_account`（信号指向本平台未管理的账户）、`account_conflict`（ARN 里的账号与声明的账户矛盾）、`account_unknown`（不知道账户且不允许跨账户搜）。`HealthIssue` 新增 `resource_ref`（FK）、`anchor_status`（anchored / account_level / ambiguous / unanchored）、`anchor_candidates`、`observed_at`。
- **账户声明 `issue_account_claim`**：重新锚定（`reanchor_open_issues`）与 2.6.1 锚点回填都先用它找回「这个 Issue 当初声明的是哪个账户」，再只在那个账户里重试，可信度从高到低：Issue 自己的 `account_id` → 锚点审计里记下的声明（`anchor_candidates` 第一个候选的 `account`）→ 该 Issue 最早一条 `promoted` 的 Signal 行（`alert_events`）上的账户。Signal 行的账户为空 = 信号本来就没说账户，按 spec 搜所有启用账户；连 Signal 行都没有（过了 `signal_retention_days` 被清理，或从未写入）= 不知道账户，**不跨账户去猜**，结果是 `unanchored`（`account_unknown`）。
- **规范关系表** `resource_relations` + 关系注册表（`graph/relations.py`）：关系方向按类型定义（`contains` 正向，`secured_by` / `routes_to` 反向…），UI、RCA、策略读同一份。
- **Galaxy 构建**：规则关系在 LLM 阶段**之前**发布（`rules_published_at`），LLM 失败不再遮住规则层；`build_graph(trigger, llm=False)` 是 rule-only 刷新（仅 `k8s-discovery` / `rca-recollect`），带过最新 LLM 构建的边、不写 `galaxy_resource_state`；每次构建完成都重新锚定未关闭的 Issue。Galaxy 健康叠加改为四值（`unknown` / `notice` / `warning` / `critical`，没有未关闭 Issue = `unknown`，从不显示「健康」；缺席资源置灰划线）。
- **GraphQueryService**（`graph/query_service.py`）：有方向、有上限（`graph_query_node_cap` / `graph_query_edge_cap` / `graph_query_max_depth`）、按 build 版本的查询；2 跳邻域 SQL 条数 ≤ 5（测试用 SQLAlchemy 事件计数）。退役 `graph/context.py`，调用方全部迁移。
- **实测**：`scripts/measure_graph_facts.py --db <只读副本>` 产出锚定率与原因分布、跨账户重复 id、查询 SQL 条数与 p50 / p95（见 `docs/MVP-2.6.1-GRAPH-FACTS-MEASUREMENT.md`）。

## 计划 B — 拉取式连接器与告警入口鉴权

- 契约 `connectors/base.py` + 唯一写入口 `connectors/ingest.py`（确定性）：实体写进 `cloud_resources`（`provider=kubernetes`），每次运行一行 `connector_runs`（状态 complete / partial / failed + 计数）。**部分采集不做缺席判定**；缺席的资源记 `absent_since` 而不删除；Secret 行里没有 `data` / `stringData`；AWS 扫描不动 kubernetes 行。
- **K8s 连接器**（`connectors/k8s.py`）：只读 `kubectl get`，经 `kubectl_env_for_cluster` 取**目标账户**凭证（先 strip 所有 `AWS_*`）+ 私有 kubeconfig（`k8s_kubeconfig_max_age_seconds` 内复用），**不碰 `~/.kube/config`**；`run_kubectl` 共用同一入口。单次输出超过 `k8s_connector_max_output_bytes` → 该 kind 记为部分。
- **墓碑规则**（父 → 子的存在规则，spec §3.B.2 修订 2026-10-01）：W2 扫描证明一个集群不在了，下一次发现运行就把它下面的 K8s 行标上 `absent_since` —— 永不删除，集群回来时恢复。这个墓碑目标不调 kubectl、不取凭证。
- **AWS 缺席判定 + `resource-scan` 调度**（spec §3.B.2 修订 2026-09-30）：W2 扫描（`scanner/engine`）在某个种类完整列出之后，把这次没看到的 `provider="aws"` 行标上 `absent_since`；`resource-scan` 调度定时跑这次扫描。资源计数和列表统一用同一个「存在」定义（`absent_since IS NULL`）。
- **告警 webhook**：配置 `webhook_secret` 后，令牌（`Authorization: Bearer` / `X-AIOps-Token` / `?token=`）或 HMAC（`X-AIOps-Signature` over `X-AIOps-Timestamp + "." + body`，时间窗 `intake_signature_window_seconds`）必带，否则 401；未配置 = 不校验（行为不变）。6 个解析器补全 `observed_at`。

## 计划 C — RCA 定位闭环与评测

- **证据**：`get_topology_evidence` 按 Issue 类别取有方向的局部图 + 时间窗（`rca_topology_window_before_minutes` / `…_after_minutes`）内的变化；K8s 锚点可触发一次定向重采（`rca_k8s_recollect_min_age_seconds` / `…_timeout_seconds`），失败则 `freshness: stale` + 原因、用已有数据继续。`rca_topology_context_enabled` 的语义改为「注入这个工具」。证据包的决策字段（anchor、freshness、truncated、candidates）排在 JSON 最前面，保证经过 Strands 上下文卸载器的预览后仍然可见。
- **定位**：`save_rca_result(location=…)` 接收 ≤ 3 个排序的候选资源 + 因果路径；`services/rca_location.validate_location` 对照库存与已发布关系图 **fail-closed** 校验，丢弃不合法的部分，`location_status` 取 valid / partial / invalid / absent（历史 RCA 回填为 `absent`）。无效引用绝不会被记成 valid。**存下来的路径是一组逐条校验过的边，不是一条验证过的因果链**：每条边单独核对（构建、来源、账户、两端），不核对它们是否连通、是否触到锚点或候选。agent 反向给出的边也接受，按图自己的方向存。
- **判定与统计**：人对定位下 correct / partial / incorrect（仅当最新 RCA 的定位为 valid / partial 时可判，否则 409），统计走 `GET /api/rca/location-stats`（Top-1、已判定数、锚定率、分布）。
- **策略影子模式**：`estimate_blast_radius`（下游、rule 关系、≤ 3 跳、不含自身；变更取最宽的目标）记在决策的 `shadow_blast_radius` 上，`policy_graph_impact_enforce=false` 时 `blast_radius_gte` 规则看不到它。
- **证据门变严**：RCA 证据检查不再拿 `save_rca_result` 自己的输入 / 回复当依据，证据门从此真正起作用（见「已知偏差与限制」C-M6）。
- **评测**：`infra/eks-chaos-lab/e2e/ground_truth.yaml`（13 个场景的真值）+ `location_eval.py`（纯函数：AC@1 / AC@3 / MRR、图召回率）+ `LOCATION_BATCH=off|on bash run-e2e.sh --location-only`；结果写进 `docs/MVP-2.6.1-LOCATION-EVAL-REPORT.md`（模板已就位，联合 E2E 时填）。

## 计划 D — Issue / Change 逻辑

- **方案版本与内容哈希**：`fix_plans` 加 `plan_version`、`content_hash`、`approved_hash`、`approved_version`；审批必须带审过的哈希（方案已变 → 409）；执行前哈希 ≠ 批准哈希 → 拒绝执行，执行记为 aborted + 原因，Issue 回到 `root_cause_identified`。`services/plan_content.plan_label` 统一命名（「I#12 fix plan v2」/「C#3 implementation plan v1」），CLI、通知、元数据工具共用。
- **变更单自带步骤与外部引用**：`proposed_steps`（≤ 50 步）、`external_ref`（system / ticket / url），SRE 的实施方案与申请步骤的差异存为 `steps_diff`；`needs_review_reason` 与执行记录的 `verification_reason` 是同一条原因（IssueDetail 与 ChangeDetail 顶部显示同一句）。
- **外部入口** `POST /api/changes/intake`：`change_intake_secret` 为空时 404；签名错误或过期 401；同一外部工单重复提交返回仍在进行中的同一张变更单（201 新建 / 200 已有）；`webhook:*` actor 尝试 approve / execute / accept 一律 403，**影子模式下也是**。
- **统一的执行后验证**（`services/verification.py`）：`evaluate()` 给出 passed / failed / `pending_acceptance`；缺少 post_checks 或结果不全、有 warning、某步未报告成功 → `pending_acceptance`，**永远不算 passed**。`accept_execution` 由会话 actor 做人工验收，按方案种类的审批权限鉴权。
- **`transition_issue()`**（`services/issue_state.py`）：唯一的状态写入口 —— 校验边、`UPDATE … WHERE status=:expected`（0 行 → 409）、同事务写 `status_changed` 时间线事件；`tests/test_issue_status_writes.py` 扫描 `src/`，任何别处的写入都会失败。回退边：`fix_approved` / `fix_executing` / `fix_executed` → `root_cause_identified`。
- **dismissed 语义统一**：`dismissed` 抑制同指纹的重复，但不算「未关闭」；`dismissed → open` 可重开。HealthIssue 状态机因此是 10 态（主线 9 态 + `dismissed`）。

## 计划 E — 界面、文档与联合 E2E

见上文「Web UI」一行。另：`useFixExecutions` 改为请求已有的 `GET /api/fix-executions?fix_plan_id=`（原来请求的是不存在的端点）；顶栏标题补齐 agent-metrics / skills / galaxy / security 四个路由。

## 数据模型

| 表 | 变更 |
|---|---|
| `health_issues` | + `resource_ref`（FK，索引）、`anchor_status`、`anchor_candidates`（JSON）、`observed_at` |
| `cloud_resources` | + `absent_since`、`content_changed_at`（连接器写入时内容哈希变化的时间，RCA 证据读取） |
| `galaxy_builds` | + `rules_published_at`；rule-only 刷新用现有 `trigger` 列区分（`k8s-discovery` / `rca-recollect`，token 记 0） |
| `resource_relations` | 新表：规范关系 |
| `connector_runs` | 新表：连接器运行记录 |
| `rca_results` | + `location`（JSON）、`location_status`、`location_build_id`、`location_verdict`、`location_verdict_by`、`location_verdict_at` |
| `fix_plans` | + `plan_version`、`content_hash`、`approved_hash`、`approved_version` |
| `change_requests` | + `proposed_steps`、`external_ref`（JSON）、`external_system` + `external_ticket_id`（联合索引）、`steps_diff`、`needs_review_reason` |
| `fix_executions` | + `verification_status`、`verification_reason`、`accepted_by`、`accepted_at`、`acceptance_note` |

## 配置（`config/settings.yaml`；`config.py` 只定义 schema）

| 键 | 默认 | 说明 |
|---|---|---|
| `identity_alarm_name_patterns` | `['^EKS-(?P<cluster>.+)-[A-Za-z0-9]+-[A-Za-z0-9]+$']` | 告警名 → 集群 / 命名空间 |
| `identity_type_families` | `{EKS: [EKS, EKS_Cluster]}` | 视为同一物理资源的类型族 |
| `graph_query_node_cap` / `graph_query_edge_cap` | `200` / `500` | GraphQueryService 默认上限 |
| `graph_query_max_depth` | `2` | 邻域最大深度（潜在影响固定 3 跳） |
| `k8s_connector_enabled` | `true` | K8s 连接器总开关 |
| `k8s_discovery_interval_minutes` | `10` | `k8s-discovery` 调度间隔 |
| `k8s_connector_max_output_bytes` | `20000000` | 单次 kubectl 输出字节上限，超出则该 kind 为部分 |
| `k8s_kubeconfig_max_age_seconds` | `3600` | 私有 kubeconfig 复用时长 |
| `resource_scan_interval_minutes` | `60` | `resource-scan` 调度间隔（只在首次种子化时生效；已有的行在 Schedules 里改） |
| `rca_topology_context_enabled` | `true`（已有） | 语义改为「注入 `get_topology_evidence` 工具」 |
| `rca_topology_window_before_minutes` / `…_after_minutes` | `30` / `10` | 证据包时间窗 |
| `rca_k8s_recollect_min_age_seconds` / `…_timeout_seconds` | `120` / `60` | RCA 定向重采的最小间隔与超时 |
| `policy_graph_impact_enforce` | `false` | 潜在影响是否真正参与策略规则（false = 影子模式）；GET /api/settings 只读可见 |
| `webhook_secret` | `''` | 告警 webhook 共享令牌 / HMAC 密钥；为空 = 不校验。**真实密钥绝不提交** |
| `change_intake_secret` | `''` | 变更 intake 的 HMAC 密钥；为空时接口 404。**真实密钥绝不提交** |
| `intake_signature_window_seconds` | `300` | 两处 HMAC 的时间窗 |
| `galaxy_llm_exclude_types` | 追加 13 个 `K8s_*` 类型（含 `K8s_Pod`） | K8s 关系走确定性规则，不送 LLM |

## 迁移

`models._migrate_2_6_1(engine)` 沿用 `_migrate_2_6_0` 的写法：新表 `create_all`，新列幂等 `ALTER TABLE … ADD COLUMN`，SQLite 与 PostgreSQL 都能跑；进程内按 DB URL 幂等一次（带锁），DDL 失败即抛出、进程不启动。随后是三项幂等回填，每项 **fail-soft**（失败只记日志，不阻止启动）：

1. 还没锚定过的 `health_issues`（`anchor_status` 为空）跑一次 `resolve()`，写入 `anchor_status` / `resource_ref` / `anchor_candidates`；失败的留空，由构建后的重新锚定补上。账户先经 `issue_account_claim` 找回（见计划 A），只在声明的账户里锚定；Issue 原本没有 `account_id`、而锚定得到了账户时，同时回填 `account_id` —— 账户是方案内容的一部分，所以该 Issue 下已有哈希、仍未终结的方案会重算哈希并升一个版本（已批准的方案因此需要重新批准）；
2. 历史 `rca_results.location_status` 置为 `absent`；
3. 还没有哈希的 `fix_plans` 计算 `content_hash`，已批准或执行中的方案同时回填 `approved_hash` / `approved_version`，让它们还能执行；回填失败的方案没有批准哈希，会在执行门被拒（fail-closed），需要重新批准。

`resource_relations` 由下一次构建填充，迁移不代写。

**升级提示（每个部署都会受影响）**：升级后启动时会种子化一个 `resource-scan` 调度（默认每小时一次，`resource_scan_interval_minutes`），每个部署从此**每小时对所有启用的 AWS 账户发一轮只读 AWS API 调用**，并把完整列出的种类里这次没看到的资源**标为缺席**（`absent_since`，不删除）。不想要这份流量，在 Schedules 里改间隔或停用这一行（已存在的行不会被重新种子化覆盖）。

**升级提示（证据门）**：RCA 证据门变严之后，部署后预期 `needs_review` 上升、自动修复下降（见 C-M6）。

## spec 修订

- **FR-3（spec §3.A.4 修订，2026-10-01，Plan C 终审 I-3）**：网络类与计算类 Issue 的默认关系集都加上 K8s 规则关系 `restricts`（NetworkPolicy / PDB → 工作负载）与 `uses`（工作负载 → ConfigMap / Secret / PVC）。原表按 AWS 写成，这两种 K8s 关系从计算类、网络类 Issue 都走不到，而它们正是配置类和网络策略类故障的根因所在。数据库类与「其他」不变。`/api/graph/focus` 用的是同一份 `default_relations`，所以这两类 Issue 的局部关系图也随之变宽。
- **spec §3.B.2 修订（2026-09-30）**：AWS W2 扫描标缺席 + `resource-scan` 调度 + 统一的「存在」定义（见计划 B）。
- **spec §3.B.2 修订（2026-10-01，P-1）**：父 → 子的存在规则（墓碑，见计划 B）。
- **spec §3.C.1 修订（2026-10-01，Plan C 终审 M-2）**：锚点是容器（集群 / 命名空间 / 网络）时，在证据包里排在所有候选之后；本 Issue 自己不算佐证。

## 验收标准（对照设计 §8）

| # | 标准 | 状态 |
|---|---|---|
| 1 | 锚定率 `(anchored + account_level) / 总数` ≥ 95%（达不到则报告原因分布，不放宽规则）；36 组跨账户重复 id 一次都不错配 | 实测见 `MVP-2.6.1-GRAPH-FACTS-MEASUREMENT.md`；控制器据实填入 |
| 2 | 2 跳邻域 SQL ≤ 5；本地库 p95 < 200 ms | 同上 |
| 3 | 图召回率 ≥ 12/13（硬门槛） | 联合 E2E（`MVP-2.6.1-LOCATION-EVAL-REPORT.md`） |
| 4 | on 批次 `location_status ∈ {valid, partial}` ≥ 90%；无效引用绝不记成 valid | 校验分支有单测；比例待联合 E2E |
| 5 | AC@1 / AC@3 / MRR 的 off / on 对照如实报告，不设门槛 | 联合 E2E |
| 6 | 连接器安全：Secret 无 data；部分采集不产生 absent；kubectl env 无非目标账户的 `AWS_*` | 单测覆盖；联合 E2E 在真实集群复核 |
| 7 | 配置令牌后不带令牌的 webhook 401；6 个解析器都取到 `observed_at` | 单测覆盖 |
| 8 | 过期哈希审批 409；执行器遇到哈希不一致拒绝执行；状态写入只在 `transition_issue`（grep 测试） | 单测覆盖 |
| 9 | dismissed / resolved 不给节点上色；没有 Issue 的节点 `unknown`；UI 三层爆炸半径与 API 一致 | 单测 + 前端 vitest 覆盖 |
| 10 | 规则关系行数 = rule_graph 资源到资源的边数；方向测试通过，锁反向的旧测试已删 | 单测覆盖 |
| 11 | `pending_acceptance` 时 IssueDetail 与 ChangeDetail 顶部显示同一条原因 | 前端 vitest 覆盖；联合 E2E 走查 |
| 12 | intake：签名错 401、未配置 404、同一工单重复提交得到同一张变更单；`webhook:*` 批准在影子模式下也 403 | 单测覆盖；联合 E2E 复核 |
| 13 | 全量测试 + 前端四道门通过；联合 live E2E 跑完并经主人确认后才 push | 门禁结果由控制器填入；E2E 待跑 |

## 联合 live E2E 清单（设计 §7，和主人一起跑 —— 尚未执行）

部署方式与环境当场与主人确认（定位评测在 chaos-lab 集群内按 `infra/eks-chaos-lab/e2e/README.md`「Root-cause location eval」跑；其余流程在 dev）。任何 push 之前先征得确认。

1. **定位评测 26 次**：`LOCATION_BATCH=off` 与 `on` 各跑 13 个场景 → `python location_eval.py <off> <on>` → 填 `MVP-2.6.1-LOCATION-EVAL-REPORT.md`（验收 3–5）。注意：`--location-only` 会带评测环境变量重启集群内的应用，**重启会清空 pod 的数据库**，onboarding 夹具的 Galaxy 重建会跑廉价模型（Haiku）的 LLM 增强（有费用）；cleanup 恢复所有故障并撤掉评测环境变量。顺带核对一次被卸载的证据包里 candidates 仍能到达 agent（C-FR1）。
2. **一次 fix 流**：IssueDetail 看锚点与局部图 → 修复方案 tab 批准（对话框显示哈希）→ 执行 → `pending_acceptance` 横幅 → 接受（理由必填）→ Issue resolved；再验一次「批准后改方案 → 执行被拒 → 回到 `root_cause_identified`」。`?tab=verification` 直接打开时选中该 tab；接受后横幅消失；拒绝后 Issue 回到 `root_cause_identified`。`infra/eks-lab/scenarios/case-6-unhealthy-targets/verify.sh` 的批准段（现在走得到，只做过语法检查）在这里真跑一次。
3. **一次 change 流**：NewChangeDialog 自带步骤 + 外部工单 → SRE 审核 → ChangeDetail 看 `steps_diff` 与影子模式的潜在影响 → 批准 → 执行 → 验收卡验收。
4. **intake**：未配置 404 → 配置后错签 401 → 正确签名 201 → 同一工单再提交 200 同一张单 → 以 `webhook:*` 身份批准 403。
5. **告警 webhook 令牌**：配置 `webhook_secret` 后不带令牌 401、带令牌 200。
6. **连接器**：Settings 连接器卡片「立即运行」→ 卡片先显示运行中、再出现一行新运行和计数；运行中再点一次 → 409 提示，运行结束后清掉；库里 Secret 行无 data；采集后 Galaxy 出现 K8s 节点、`?focus=` 可深链。
7. **UI 走查**：问题三视图、IssueDetail 五个 tab、ChangeDetail、审计页、Chat 的 `I#` / `C#` 面板、AgentMetrics 定位卡片（7 天的比率）、中英切换；LocalGraph 在 IssueDetail、ChangeDetail、ResourceDetail 三处都渲染；从 LocalGraph 的「在全景图中查看」（Open in Galaxy）走一次 `?focus=<id>`，参数还在 URL 时等一次构建落地；顶栏四个标题（agent-metrics、skills、galaxy、security）；浏览器控制台无报错。

## 已知偏差与限制

每条前面的短 ID 指向它的来源（A–E = 计划 A–E）。

**界面（计划 E）**

- **E-1** detect agent 产出的安全类来源（`threat_detection`、`vuln_scan` 等）不以 `security_` 开头，所以列在「运维事件」下 —— spec 的视图规则按前缀，本版保持不变。
- **E-2** `/app/plans?tab=fix` 重定向到 `/app/issues`：修复方案现在挂在所属 Issue 下，没有独立列表。
- **E-3** 审计页账本行仍显示 `plan #<id>`：审计行只带方案 id，不带其所属的 I# / C#。
- **E-4** 验收只在 Issue 最新一次执行上提供，且仅当 Issue 在 `fix_executed`；较早的 `pending_acceptance` 执行 API 也拒绝（409）。
- **E-5** 显式 markdown 链接 `[I#1](/app/issues/1)` 在 Chat 里新开标签页（`renderMarkdown` 的既有行为），只有裸引用 `I#1` / `C#1` 打开 ContextPanel。
- **E-6**（E-T1 M-3）IssueDetail 的返回链接不带列表的 `?scope=`，返回后是默认视图。
- **E-7**（E-T1 M-5）导航里「问题」旁的圆点统计的是所有视图的未关闭问题，不只是列表当前显示的那个视图。
- **E-8**（E-T3）局部关系图上，一个被合并过两次的节点，两条合并信号的连线会叠在一起画（仅视觉）；关掉 LLM 开关时，如果「关」那一次的查询缓存已被回收（5 分钟），LLM 才有的节点会闪现一次（瞬时）。
- **E-9**（E-T4 M-6）执行状态原样显示 `succeeded` / `failed`；`rollback_results` 标为「回滚计划」/ "Rollback Plan"，其实装的是一次回滚运行的结果。
- **E-10**（E-T4）执行记录里单元素数组的显示只在元素是字典时与 Python 一致（嵌套列表 `String(["ok"])` 与 `str(["ok"])` 不同）—— 仅影响显示，判定由服务端给出。
- **E-11**（E-T7）Galaxy `?focus=`：在空白处双击会清掉焦点标签，但 `?focus=` 还留在 URL 里；参数还在时，新构建落地（现在会自动刷新）会再应用一次 —— 重新打开面板并重新居中；「不在最新构建里」的提示没有关闭按钮，离开页面才消失。
- **E-12**（E-T8）Settings 连接器卡片：点「立即运行」之后，刷新可能赶在后台运行拿到锁之前，卡片于是显示「未运行」、按 30 秒继续轮询并保留「已启动」那一行，直到后面某次轮询看到这次运行（运行本身不受影响）。
- **E-13** 局部关系图图例写的是「RCA 因果链」，定位卡写的是「因果链」；按 C-1，这条路径应读作「一组逐条校验过的边」。

**图事实层（计划 A）**

- **A-1** 锚定率可能达不到 95%（spec §10.1），实测数字与原因分布见 `docs/MVP-2.6.1-GRAPH-FACTS-MEASUREMENT.md`；按 spec 如实报告原因分布，**不为达标放宽规则**。
- **A-2** 规则写入的串行锁在进程内；多个 uvicorn worker 会各有一把，多 worker 部署需要换成 DB 级锁（spec §10.3）。
- **A-3**（A M-5）Galaxy 页面与 GraphQueryService 对「当前构建」的定义不同（前者按 `finished_at`，后者按 `rules_published_at`）：普通构建还在 LLM 阶段时落地的一次 rule-only 刷新，会让查询层读刷新的规则，而页面仍显示那次普通构建。
- **A-4**（A M-7）某账户没配 `credentials.account_id` 时，跳过 `account_conflict` 检查；ARN 里的账号如果没有任何账户声明过，结果是 `unknown_account`，即使库存里有这个资源 —— 拉低锚定率，不影响安全。

**连接器与告警入口（计划 B）**

- **B-1**（PARK-S2）凭证指纹看不到行以外的身份变化（`environment` 源没有 `account_id`；某个 profile 在 `~/.aws/config` 里的目标被改了），暴露窗口以 `k8s_kubeconfig_max_age_seconds` 为界。
- **B-2**（PARK-S3 / F9）K8s `raw_data` 里键名像密钥的 label 入库时被打码，前后哈希每次都不同：没有真实变化，`content_changed_at` 也每次采集都会移动，该集群每次都触发一次 rule-only 刷新（无 LLM 费用），RCA 证据里的「有变化」候选因此偏多。
- **B-3**（PARK-S4）设了 `webhook_secret` 之后，eks-lab 的 Alertmanager receiver 需要加 `http_config.authorization`（WORKFLOW 有示例）；`infra/eks-lab/monitoring/prometheus-values.yaml` 没改，实验室操作员设了密钥会先看到 401。
- **B-4**（PARK-S6）告警 webhook 的 HMAC 没有 nonce（时间窗内可重放），请求体大小不设上限。
- **B-5**（PARK-S8）PostgreSQL 部署的会话 TimeZone 必须是 UTC，否则缺席判定的截止时间会按时区偏移错开。
- **B-6**（Plan B Task 13）调度器串行执行：`resource-scan` 与 `galaxy-auto-build` 都在整点，一个排在另一个后面跑。
- **B-7** HMAC 时间戳头用宽松的 `int()` 解析（首尾空白、正号、下划线分隔这类写法也能通过）。
- **B-8** chaos-lab `deploy-app.sh` 的 `--webhook-secret` 参数在 `ps` 里可见；用 `AIOPS_WEBHOOK_SECRET` 环境变量更稳妥。
- **B-9** AWS 缺席判定的已知缺口：没有扫描器列出的类型里由 agent 写入的 ARN 行永远不会被标缺席；旧的 FullScan（W3）可能把 W2 写的 ELB / ECS 短 id 行改成 ARN，之后 W2 就不再标它；W3 写的带真实区域的 S3 行不会被标（W2 把 S3 当作 `global` 区域列出）；从扫描里去掉的区域和被截断的单元不会被标；唯一键不含区域；Galaxy 总览的 `resource_count` 来自构建快照、包含缺席行；`get_managed_resources` 只看受管资源、最多 50 条。
- **B-10**（Plan B 修复轮 concern 1）一条仍在场的、agent 写入的 `EKS_Cluster` ARN 行会让一个已经不在的集群一直算「在场」，墓碑不会触发；常规目标在 kubectl 处失败，记为 failed。
- **B-11** 墓碑规则本身（5cbf521）：W2 证明集群不在了，它的 K8s 行在下一次发现运行时标缺席，永不删除，集群回来时恢复 —— 所以集群消失后 K8s 行的缺席会晚一个发现周期。
- **B-12** 大集群上 `kubectl get -A` 可能超出字节上限而被判为部分采集 —— 这是安全的方向，代价是缺席判定延后。

**RCA 定位（计划 C）**

- **C-1**（C T3 C1）存下来的定位 `path` 是**一组逐条校验过的边，不是一条验证过的因果链**：每条边单独核对（构建、来源、账户、两端），从不核对连通性，也不核对是否触到锚点或候选。统计和界面都应按这个意思读。
- **C-2**（C T3 C6）定位候选只对照库存与 Issue 的账户校验，不要求在图构建里 —— 根因可能在图外。
- **C-M6**（C T3 Minor-6）证据检查不再拿 `save_rca_result` 自己的输入 / 回复当依据，证据门从此真正起作用：部署后预期 `needs_review` 明显上升、自动修复下降（一条未匹配的引用 ×0.6，0.9 的置信度就变成 0.54，低于 0.6 的门槛）。这是门变诚实，不是定位带来的副作用。
- **C-3**（C T6）打开 `policy_graph_impact_enforce` 后：由实时 describe 挂上的变更目标永远不计入（`attach_target` 总是存 `db_id: None`，库存里有这个资源也一样）；缺席的下游资源**会**计入（宁可多升级）。
- **C-4**（C T7）联合 E2E 的定位评测会重启集群内的应用、清空 pod 的数据库，onboarding 夹具的 Galaxy 重建会跑 Haiku 增强（有费用，F19）。service-deleted 场景的召回率有结构性上限：被删的 Service 只以缺席行进入图（评测读 `/api/resources?…&include_absent=true` 才能给它对上真值）。结果写在 `infra/eks-chaos-lab/e2e/results/location-<ts>.json`（永不提交）。
- **C-5**（C FR-6）Issue 带资源引用但**没有账户**时，证据包照样完整，但 `validate_location` 对没有账户的 Issue 会丢掉所有候选和路径，所以它存下的定位总是 `invalid` —— fail-closed，且少见。
- **C-6**（C FR-1）证据包的决策字段排在最前，能经过上下文卸载器约 3,000 字符的预览；预览之后的 edges / neighbors 只能通过卸载器的取回工具拿到，而提示词没有提到这个工具。
- **C-7**（C FR-2）agent 反向给出的路径边也被接受，按图自己的方向存。
- **C-8** 评测样本只有 13 个场景 × 1 遍，AC@k 只作参考，不设门槛。

**Issue / Change（计划 D）**

- **D-1**（D T2-C2）取消或崩溃的运行会把 Issue 留在 `fix_executing`（以前是 `fix_approved`）；恢复走 `fix_executing → root_cause_identified` 回退边，只能由人操作（agent 的状态工具不进出任何 `fix_*` 状态）。
- **D-2**（D FR-D11）从 `fix_executed` 走验收以外的人工出口（PUT status、CLI `/resolve`、误报 dismiss、`aiops issue update --resolve`）会让那次运行的 `pending_acceptance` 留在原处，而且这些出口不做鉴权检查（既有问题）。有待验收的运行时，IssueDetail 会引导到验收按钮。
- **D-3**（D FR-D3）只能验收 Issue 最新一次执行，而且所有执行都算在内：一次更新的 aborted / failed 执行会挡住较早那次待验收执行的验收，409 里点名的是那次更新的执行。
- **D-4**（D FR-D13 R-1）Web / API 的修复与变更批准、以及验收，都按 404 → 403 → 409 的顺序判；CLI `/approve` 与 agent 工具 `approve_fix_plan` 仍先查状态再鉴权。
- **D-5**（D M-2）「Issue 已关闭则拒绝批准」是加载时读一次：在这次读和提交之间被关闭的 Issue，它的方案仍可能被批准。
- **D-6**（D T7-M3）CLI `/accept C<id>` 会完成任何处于 `needs_review` 的变更单；API 则拒绝不在 `pending_acceptance` 的执行。
- **D-7**（D T7-M8）可重试的 abort 也带 `failed` 判定；开始执行前就 abort 的运行，RCA 仍被标为 disputed（2.2.0 的行为）。
- **D-8**（D T9）格式不对的 `step_results` 归一成 `[]`，不会挡住 `passed` 判定。
- **D-9**（D T6 / T9 变更 intake）未签名的请求体读入不设上限（与告警 webhook 相同）；±300 秒重放窗口，没有 nonce；共享密钥允许调用方自称任何外部系统名；如果两个端点复用同一个密钥，一个端点的 MAC 在另一个端点也成立；`needs_clarification` 状态的 webhook 变更单没有往前走的路；去重只看进行中的单 + 进程内锁、没有唯一索引，多 worker 部署可能竞争（假定单 worker uvicorn）。
- **D-10**（D FR-D10）`change_auto_approve_standard=true`（默认 false）时，策略判为 standard 的 intake 变更会由 `agent:auto-pipeline` 批准并执行，全程无人（WORKFLOW 已写明）。

## 明确不做（本版边界）

Datadog / 观测云 / ServiceNow CMDB 连接器与 MCP 声明式连接器；Chat 声明关系（`declared`）；外部变更事件表；patrol 拉回的外部告警接入 Signal Gate；迁移到 PostgreSQL / Neo4j；LATS 树搜索与并行多分支调查；Chat 输入区与多模态；Galaxy 的 token 优化；新增 AWS 采集（TargetGroup / RouteTable / NACL / ENI）；安全可达性改接 GraphQueryService、攻击路径画成图；`simulate_fix_impact` 改造（继续读 GraphStore，保持休眠）；ServiceNow / GitHub 专用适配器与状态回写。

## 加固清单（后续，不在 2.6.1 修）

1. **PARK-S5（Important，既有问题）**：`validate_api_key` 返回一个已脱离会话的 `User`，读它的列会抛错 —— 用 API key 调用的请求，在任何要解析 `current_actor` 的端点上很可能 500。需要主人知悉。
2. **C-1 / P-1（Important，主人决定）**：APIAuthMiddleware 按 `request.url.path` 判路径，而这个值受 Host 头影响，可以绕过 API 鉴权。2.6.1 已由 3cb7b6e 修复（改为读 `request.scope["path"]`，即实际路由的路径）；但 origin/main 上还是旧代码（`src/agenticops/web/app.py:4313`），是否回移到 main 由主人决定。
3. 其余：
   - **PARK-S7**（既有）：ASGI `root_path` 可绕过 APIAuthMiddleware（潜在问题，目前没有部署设置它）。
   - **A N-1**：2.6.1 之后创建、信号没写账户的 Issue，一旦它那条 promoted 的 `alert_events` 行被清理（`signal_retention_days`），就不再跨账户重试（偏安全的方向）。修法：`_promote` / 回填把声明记进 `anchor_candidates`。
   - **A M-1**：`account_conflict` / `unknown_account` 会丢掉信号声明的受管账户（Issue 在列表和筛选里失去归属；下游 fail-closed，安全）。`unknown_account` 时保留声明的受管账户；`account_conflict` 保持为空，但在界面上显示声明。
   - **A M-2**：同一个构建里，`include_llm=True` 的拓扑缓存可能过期（LLM 阶段时缓存了只有规则的拓扑）。
   - **A M-3**：`/api/graph/focus` 在取完邻域之后才读 `build_id`，中间有发布时，返回的构建号可能与数据不符。
   - **A M-4**：残留的 `running` GalaxyBuild 行（如 LLM 阶段时重新部署或 OOM）会永远挡住普通构建和 `/rebuild`（409）；需要像调度器那样在启动时或超时后清理。
   - **A M-5 / M-7**：见 A-3 / A-4。
   - **A M-6**：`account_pk` 把数字字符串当主键接受，审计里以文本存的主键在删账户后可能解析到别的账户；审计里应存账户名或 12 位账号。
   - `identity_type_families` 补上 ElastiCache 与 ECS 两族。
   - `alert_events` 加索引。
   - **PARK-T11-UI**：资源列表开「显示缺席」→ 选一个全是缺席的类型 → 再关掉，类型筛选保留一个下拉里已没有的值（取消再选即可恢复）。
   - `pages/Schedules.tsx` 硬编码了 `PIPELINE_OPTIONS`，没人读 `/api/schedules/pipeline-options`：K8sDiscovery 与 ResourceScan 能作为行显示，但在 Pipeline 下拉里选不到。这是第一项。
   - **B M-4**：`connector_runs` 没有保留期清理。
   - Plan B Task 14 小项：跨区域预热丢了（首次多区域扫描时每个账户 N 次 STS 往返）；`tests/test_aws_tools_coverage.py` 里有失效的旧格式种子；`assume_role` 手抄了 `resolver._snapshot`。
   - `tests/test_multi_cloud_api.py` 往默认数据库里漏写行。
   - `_related()` 应改用 `issue_account_claim`。
   - **B concern 4**：`account_name` 匹配不到任何目标的 K8sDiscovery 调度会以 `targets: 0` 完成，而不是报错（ResourceScan 同样情况会抛错）。
   - **B concern 5**：测试的发送守卫只覆盖 botocore，不覆盖通知器的 Feishu / Slack / webhook HTTP。
   - **B concern 6 / 7**：`tests/test_multi_cloud_api.py` 单独跑会挂 6 个测试（它 patch 的是 `web.app.get_db_session`，路由却在 `web/routers/accounts.py`）；`test_notification_operator::db_session` 漏出 `settings.database_url` / `reports_dir`，在全量里掩盖了这次失败。
   - **B re-review Minor 1**：有了发送守卫，单独 `pytest tests/integration --run-integration` 会跳过整个 live 套件，还需要 `AIOPS_TESTS_ALLOW_AWS=1`；`--run-integration` 的帮助文本和集成测试的 docstring 仍只写了一个开关。
   - **B re-review Minor 2**：ingest 抛错时，runner 的兜底把目标已有的部分采集错误换成一条「未入库」错误，而且原样存下异常文本（SQLAlchemy 的 StatementError 带 SQL 与参数）；应前置并截断。
   - **B re-review Minor 3**：`connectors/runner.py:116` 的注释（"the write rolled back whole"）只对实体阶段成立；ConnectorRun 写入失败时会留下已提交的行和一条 `failed` 运行记录（无害）。
   - **B OOS-2**：`_tombstones` 每次发现运行对每个历史上缺席的集群各跑一次前缀查询，缺席的集群行从不清理；量大了要批量化或按 `absent_since` 年龄限定。
   - **B OOS-3**：在 `pytest_configure` 里设 `AWS_EC2_METADATA_DISABLED=true`，让没有凭证的机器得到确定的错误，而不是守卫从 IMDS 抛出的 RuntimeError。
   - **C T2-R3**：RCA 的 K8s 重采失败没有限流（最小间隔按上次成功计），坏掉的集群上一场告警风暴会让每次 RCA 都耗满 `rca_k8s_recollect_timeout_seconds`。
   - **C T2-R5**：「无账户 + 最近有过运行 → stale」分支没有测试；`galaxy_enabled=False` 时，有变化的重采仍保持 `ok=True`（按设计不刷新规则）。
   - **C T3-R10**：RCA 证据检查仍把其他工具的 toolUse **输入** 算作痕迹，agent 自己传进某个工具输入里的引用也能通过（既有问题，所有证据类型都是）。更严的做法：`graph:` 引用只对照 `get_topology_evidence` 的 toolResult，或不再计 toolUse 输入。
   - **C T6**（打开 enforce 之前要做）：(a) enforce 模式下也把算出的数字记在决策上（目前只有影子模式的 `shadow_blast_radius` 带它，enforce 时审计说不清为什么升级）；(b) 没有 `db_id` 的变更目标经按账户限定的库存查找解析；(c) 单独钉住 `_expand` 的逐跳账户过滤的测试（目前被 `_assemble` 掩盖）。设计说明：估算在自己的会话里读（Ruling T6-R1），图读取失败在 PostgreSQL 上永远不会让一次批准失败 —— 代价是每个目标多一条短连接。
   - **D concern 4**：影子模式下变更验收检查两次 `change.approve`（两条 `authz.denied_shadow`）；Web 修复批准先鉴权，会为本来就会 409 的请求写影子记录。
   - **D T4-M2 / M3**：CLI 的修复批准不显示内容哈希（在门上 fail-closed）；FixPlan 的状态写入不是 CAS。
   - **D T5**：`get_change_request` 文本会被截断；`external_system` 只校验、不规范化；`steps_diff` 不在 `content_hash` 里（方案步骤在，申请步骤不可变）；`change_steps._command` 只读 `"command"`。
   - **D T7-M6 / M7**：`services/verification` 引用了 `tools`（分层问题，计划所定）；`on_execution_result` 重新计算 `evaluate`。
   - **D M-6**：`infra/eks-lab/scenarios/case-6-unhealthy-targets/verify.sh` 的批准段只做过语法检查 → 联合 E2E。
   - **E-T1 M-1 / E-T5 M2**：7 个孤儿 locale 键 `plans.planStatus.*`，下次清理 locale 时删掉。
   - **E-T1 M-4**：「安全问题」有两套定义（`security_service._SECURITY_DETECTORS` 按 `detected_by`，`app.py` 的 `SECURITY_SOURCE_PREFIX` 按 `source`），目前一致，应统一。
   - **E-T2 M-4**：图聚焦的 `related.truncated` 没考虑 `NODE_CAP_MAX` 造成的结构截断（界面可以读 `blast.truncated`）。
   - **E-T2**：Web 的修复方案批准路由从不调用 `notify_fix_approved`（既有问题；只有 agent 工具那条路会通知）。
   - **E-T3 M-7b**：LocalGraph 没有中心节点时的候选循环没有测试；`latestExecution` 按 `created_at` 排序，而后端的「最新一次」是 `max(id)`（除非两次运行时间戳相同，否则一致）。
   - **E-T4**：`IssueDetail.tsx` 太大（各 tab + 验收 + 证据），以后拆分。
   - **E-T6b**：修复方案批准对话框（ContextPanel 与 IssueDetail）实时读 `fp.content_hash`，确认时显示的就是发送的；对话框开着时哈希变了，显示的文本也会跟着变（门会再查一次，漂移会被拒）。
   - **E-T7**：ResourceDetail 的 tab 标签除了新的「局部关系图」都是硬编码英文（既有）；没有 `focus` 参数时，Galaxy 的 `exitFocus` 也会做一次无意义的 URL 替换。
   - **E-T8**：连接器卡片的轮询间隔（运行中 5 秒 / 空闲 30 秒）写死在 `useConnectors` 里，没有测试。
   - **E-13**：局部关系图图例与定位卡的「因果链」改成与 C-1 一致的说法。

## Future（后续期）

1. 2.6.2：更多连接器（Datadog APM 服务图 / 部署事件、ServiceNow CMDB）、MCP 声明式连接器、Chat 声明关系、外部变更事件表。
2. 看过联合 E2E 的统计后，由主人决定何时打开 `policy_graph_impact_enforce`（先做加固清单里的 C T6 三项）。
3. 规则写入锁换成 DB 级锁，支持多 worker。
4. 审计账本行带上所属的 I# / C#。
