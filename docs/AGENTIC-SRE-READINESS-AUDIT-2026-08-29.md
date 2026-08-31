# AgenticOps 迈向“自主调查型 SRE”完整差距审计

> 日期：2026-08-29  
> 审计对象：`MVP-2.2.0`，HEAD `f66a623`  
> 目标体验：SRE 只描述一个可疑现象，系统即可自主识别环境与对象、穷尽关键证据、排除竞争假设、定位根因、给出安全修复方案、验证恢复，并在后续同类事件中更快、更准、更省。

## 0. 精度声明

不存在诚实的“绝对无误差”架构评估。本文通过以下方式尽量逼近可验证结论：

1. 只把代码中已经存在并进入实际调用链的能力标为“已具备”。
2. 设计文档存在、代码不存在的能力标为“仅设计”。
3. Prompt 中声明、但没有确定性代码或持久化状态保证的能力标为“软约束”。
4. 时间估算明确写出团队和范围假设。
5. 所有评分都以本文定义的目标状态为分母，而不是以普通 MVP 为分母。

这也解释了为什么项目作为 MVP 可以得到约 `7.0/10`，但相对“可信自主调查型 SRE”目标只有 `47/100`：两个分数的比较基准不同。

---

## 1. 最终结论

### 1.1 一句话判断

**AgenticOps 已经拥有一套罕见且有价值的 Agentic SRE 骨架，但目前仍是“由多个 Agent 串成的自动化流水线”，尚未成为“有持久调查状态、竞争假设、证据账本、独立验证和结果学习的自主调查系统”。**

### 1.2 当前距离

| 目标层级 | 当前完成度 | 判断 |
|---|---:|---|
| 可展示的 AWS/EKS AgenticOps Demo | 72% | 已能形成很强的演示 |
| 可供设计合作客户试用的调查助手 | 55% | 需要 Trust Kernel 和 Investigation Runtime |
| 限定 AWS/EKS 场景的可信生产助手 | 47% | 最大缺口是验证、运行隔离、评测和 Graph 完整性 |
| 可受控自动修复的生产 Autonomous SRE | 35% | 还不能证明“执行成功”和“事故恢复” |
| 真正随使用越来越快、准、省的学习系统 | 32% | 有 Memory/RAG 外形，但缺少结果加权和因果归因 |
| 跨云、跨应用、跨组织的通用自主 SRE | 22% | 不应作为当前主攻范围 |

### 1.3 时间判断

在**锁定 AWS/EKS、2 名强工程师全职、1 名 SRE 兼职提供故障与验收样本**的前提下：

| 里程碑 | 日历时间 | 累计人周 |
|---|---:|---:|
| 可信演示版：不会把未知当成功 | 6-8 周 | 12-16 |
| 设计合作客户版：Chat 自动创建并完成结构化调查 | 3-4 个月 | 24-32 |
| 限定 AWS/EKS 场景可靠生产使用 | 6-9 个月 | 44-64 |
| 学习飞轮有统计证据，而非主观感觉 | 9-12 个月 | 68-88 |
| 跨域高级 SRE 助手 | 12-18 个月 | 96-140 |

若主要由 1 人承担研发、测试、产品和客户交付，日历时间应乘以 `1.5-2.0`。  
若同时推进多云、Security Review、eBPF、GNN 和大规模 Galaxy 重构，时间至少再增加 `40%-70%`，且核心可信闭环会被稀释。

### 1.4 是否值得继续

**值得，而且方向正确。** 但下一阶段不能继续按“增加功能数量”来衡量进展。必须切换为：

> 以“每个结论能否被证明、每个动作能否被验证、每次学习能否被结果支持”为唯一主线。

---

## 2. 已经真正成立的能力

这些不是概念，而是项目目前的真实资产。

### 2.1 Agent 与工具层

- Main、Scan、Detect、RCA、SRE、Executor、Reporter 已形成 agents-as-tools 分工。
- RCA 已接入 CloudWatch、CloudTrail、日志、Jaeger、Datadog/Prometheus、AWS CLI、SSM/SSH、kubectl、KB、Skills 和 Graph。
- SRE 与 Executor 已分离，FixPlan 有风险级别、步骤、回滚、pre-check 和 post-check。
- 多账户凭证解析比多数开源 Agent 项目更认真，核心路径有 fail-closed 设计。
- 模型、thinking budget、成本和调用日志已经具备可观测性基础。

### 2.2 信号与 RCA 质量层

- Signal Gate 已统一多条 Issue 创建路径，具有指纹、归并、flapping 降噪和 Signal 台账。
- RCAResult 已有 evidence、Critic、human verdict 和 execution dispute 字段。
- RCA 有最大轮次、thinking 升档和历史事件注入。
- 修复失败会反驳对应 RCA，而不是继续把它当作正确知识。

### 2.3 Graph 层

- `graph/` 已有有向基础设施图、邻居、可达性、路径、SPOF、容量和 impact analysis。
- Graph 上下文可直接注入 RCA。
- `galaxy/` 具备确定性规则边、LLM 建议边、provenance、证据接地和增量构建。
- Graph 与 Policy 已发生连接：blast radius 和 simulation 可参与审批。

### 2.4 治理与执行层

- 声明式 Policy Engine、freeze window、风险升级、ITSM action 已有基础。
- Executor 有 approval gate、pre-check、执行、post-check、rollback 和审计记录。
- EKS Chaos 场景证明了系统在受控实验环境中能走通感知、分析和执行链。

### 2.5 记忆与知识层

- 每个 Agent 有独立 Memory，支持置信度、生命周期、归档和人工固定。
- Skills 有草稿、审核、安全扫描、发布与恢复机制。
- resolved 事件可蒸馏 Case、SOP，并进入向量检索。
- Incident Memory 已能把相同指纹或资源的历史结论注入 RCA。

### 2.6 产品层

- Chat、Issue、Plan、Signal、RCA 反馈、成本、Skills、Reports、Galaxy 已形成可用界面。
- 飞书、钉钉、企业微信、Slack 等入口使产品更接近真实 SRE 工作流，而不是单纯 Web Demo。

---

## 3. 六个必须直面的事实

### 3.1 现在是“自动流水线”，不是“调查运行时”

当前 Chat 的 Main Agent 根据 Prompt 做路由；“check/status”通常进入 Detect，“RCA”通常要求已有 Issue ID。RCA 内部是一次 Strands Agent 循环，结束后只留下 RCAResult。

当前不存在：

- `InvestigationRun`
- 持久化调查计划
- 竞争假设列表
- 调查任务 DAG
- 数据源覆盖率
- 证据支持/反驳关系
- 预算与停止原因
- 运行 lease
- 可恢复、可暂停、可重放的调查状态

因此 SRE 输入“支付服务偶尔变慢”时，系统可以聪明地调用工具，但它没有一个确定性运行时保证：

1. 正确解析了“支付服务、生产环境、相关账户和区域”。
2. 检查了所有必要数据源。
3. 对比了至少两个替代解释。
4. 在信息不足时选择 abstain，而不是生成最像答案的结论。

### 3.2 现在有“证据字段”，没有“证据账本”

RCA evidence 是 Agent 最后提交的一组自由 JSON。校验方式主要是检查 `ref` 是否能在工具 trace 文本里找到。

它缺少：

- 证据唯一 ID
- 来源系统与查询参数
- 工具调用 ID
- 目标资源与时间窗口
- observed_at / valid_at / freshness
- 原始结果摘要与不可变 digest
- supports / refutes 哪个 Hypothesis
- source reliability
- 是否直接证据、间接证据或历史先验
- 权限不足、采集失败和数据空洞的显式表示

字符串命中可以防住一部分引用幻觉，但不能证明证据与根因之间的逻辑关系。

### 3.3 RCA 的“fail-closed”目前并未成立

`services/rca_quality.py` 的实际行为是：

- evidence 为空时，`verified=None`，不会直接阻断。
- evidence 校验异常时，记录日志后跳过。
- Critic 异常时，记录日志后跳过。
- 只要 Agent 自报 confidence 超过阈值且 Critic 没有明确返回 `refuted`，即可触发 Auto-SRE。

这在代码语义上是 fail-soft，不是 fail-closed。

必须改成：

| 条件 | 自动修复资格 |
|---|---|
| 无有效 evidence | 禁止 |
| evidence verifier 异常 | 禁止 |
| Critic 被策略要求但不可用 | 禁止 |
| 关键数据源权限不足 | 禁止，或降级到 Recommend |
| 存在未排除的高概率替代根因 | 禁止 |
| Graph 相关结论依赖陈旧/不完整图 | 禁止 |

### 3.4 Executor 自己不能证明自己成功

当前同一个生成式 Executor：

1. 执行步骤。
2. 运行 post-check。
3. 自己决定 status。
4. 调用 `save_execution_result(status="succeeded")`。
5. 代码据此把 Issue 直接改为 `resolved`。

这是整个项目最大的生产风险。

“命令返回 0”“Pod Running”“Agent 认为 post-check passed”都不等于：

- 用户请求成功率恢复。
- 错误率在稳定窗口持续下降。
- 上游和下游恢复。
- 告警不会在 5 分钟后重新触发。
- 修复没有引入新问题。
- 根因判断正确，而不是恰好症状短暂消失。

### 3.5 当前 Memory 可能学习到错误成功

`resolved` 会触发 RAG、Case、SOP 和 Skill 改进。由于 `resolved` 目前可以来自 Executor 自报 success，错误的 RCA 与修复可能被写成“成功经验”。

这是比单次误修更危险的系统性问题：

> 单次误修伤害一个事故；错误经验进入记忆后，会系统性污染后续所有相似事故。

所以学习链必须满足：

```text
executed != resolved
resolved != verified episode
verified episode 才有资格进入高权重记忆
```

### 3.6 当前 Graph 是“资源图”，不是“运维知识图”

`graph/` 主要覆盖 VPC/网络/基础设施；`galaxy/` 主要覆盖 inventory、显式引用、tag grouping 和 LLM advisory edge。

目标系统还需要这些一等节点：

- Service / Application / Environment
- Deployment / ReplicaSet / Pod / Container
- API / Endpoint / Queue / Topic
- Database / Cache / DNS / Config
- Alert / Signal / Change / Incident
- Owner / Team / SLO
- Investigation / Hypothesis / Evidence / Action / Outcome

还需要这些时间化关系：

- `CALLS`
- `DEPENDS_ON`
- `RUNS_ON`
- `ROUTES_TO`
- `READS_FROM` / `WRITES_TO`
- `SHARES`
- `CHANGED_BY`
- `OBSERVED_BY`
- `AFFECTED`
- `SUPPORTS` / `REFUTES`

“可能导致”不能直接成为事实边；它应该先是带有效期和证据的 Hypothesis edge。

---

## 4. 代码级关键证据

| 结论 | 代码证据 |
|---|---|
| Chat 主要是 Prompt 路由，而非持久 Investigation | `agents/main_agent.py:116-195` |
| RCA 是固定协议的一次 Agent loop | `agents/rca_agent.py:75-186`, `:394-529` |
| evidence 为空不会 fail-closed | `services/rca_quality.py:65-83` |
| Critic 异常会跳过 | `services/rca_quality.py:85-95` |
| confidence 足够即可触发 Auto-SRE | `services/rca_quality.py:121-130` |
| RCA timeout 无法停止后台线程 | `services/rca_service.py:80-101` |
| Auto-SRE/Execute 使用 daemon thread，缺少 durable run | `services/pipeline_service.py:38-89`, `:257-315` |
| Graph/Simulation 不可用时策略规则不匹配 | `services/policy_engine.py:333-386` |
| Graph 增量替换只删除旧出边 | `graph/store.py:165-180` |
| Graph sync 只取默认 AWS 账户和单个 region | `services/graph_sync_service.py:69-95` |
| Executor 同时执行和 post-check | `agents/executor_agent.py:62-109` |
| succeeded 可直接 resolved | `tools/metadata_tools.py:1207-1235` |
| resolved 后立即蒸馏 SOP/Case/Skill | `services/resolution_service.py:61-126` |
| 现有状态机没有 verifying/needs_review | `models.py:359-378` |
| 默认启用 auto-fix/executor/auto-resolve | `config/settings.yaml:60-70`, `config.py:849-857` |
| 默认管理员密码仍为固定值 | `config.py:542-550` |

---

## 5. 目标能力评分

### 5.1 加权总分

| 能力 | 权重 | 当前分 | 核心判断 |
|---|---:|---:|---|
| Chat intake 与实体解析 | 7% | 58 | 自然语言和引用体验较好，缺 Service Identity |
| 数据源与工具覆盖 | 9% | 68 | AWS/EKS 强，CI/CD、应用日志和 ownership 仍碎片化 |
| Operational Graph | 10% | 48 | 资源/网络图可用，时序、应用、完整性不足 |
| Investigation Orchestration | 12% | 32 | 有 Agent loop，无 durable investigation |
| Hypothesis 与 Evidence | 12% | 38 | 有 evidence/critic，缺 typed ledger 和 coverage gate |
| RCA 决策质量 | 8% | 45 | 有质量机制，但 confidence 未校准且 fail-closed 不成立 |
| 修复计划 | 7% | 72 | 当前最成熟的环节之一 |
| Policy 与自治治理 | 8% | 58 | 规则清晰，缺自治等级、scope、预算和最严格合并 |
| 执行安全 | 7% | 52 | 有审批/回滚，但执行与验证未隔离 |
| 独立 VerifyGate | 8% | 15 | 实质缺失 |
| Outcome-weighted Learning | 7% | 42 | 记忆丰富，但结果真值不足 |
| Eval 与生产工程 | 5% | 43 | 测试和 Chaos 较强，缺 replay、校准和生产 SLO |
| **总分** | **100%** | **47/100** | **骨架领先，可信闭环不足** |

### 5.2 当前最成熟的三个环节

1. FixPlan 结构与 SRE/Executor 分工。
2. Signal Gate 和 Issue 生命周期可审计性。
3. AWS/EKS 工具、凭证、Graph、Policy 的组合。

### 5.3 当前最薄弱的三个环节

1. 独立、确定性的结果验证。
2. 持久调查运行时与竞争假设。
3. 经过结果真值加权的学习飞轮。

---

## 6. 目标架构

```text
Chat / Alert / IM
  -> Intent + Entity Resolver
  -> InvestigationRun
  -> Scope Resolver + Graph Snapshot + Data Coverage
  -> Hypothesis Planner
  -> Typed Investigation Tasks
  -> Specialist Agents / Deterministic Tools
  -> Shared Evidence Ledger
  -> Hypothesis Evaluator + Coverage Gate + Critic
  -> RCAQualityDecision
  -> Remediation Options + VerificationSpec
  -> AutonomyDecision
  -> Executor
  -> VerifyGate
       -> passed -> resolved -> Verified Episode Memory
       -> failed -> rollback / re-investigate
       -> uncertain -> human review
```

### 6.1 必须新增的核心数据契约

#### InvestigationRun

```text
id, trigger, user_query, status
organization/account/environment/service/resource scope
graph_snapshot_id
started_at, deadline_at, completed_at
lease_owner, lease_expires_at, generation
tool_call_budget, token_budget, time_budget, cost_budget
coverage_required, coverage_observed
stop_reason, failure_reason_code
```

#### Hypothesis

```text
id, investigation_run_id
statement, suspected_entity, mechanism
prior_probability, current_confidence
status: active|supported|refuted|unresolved
evidence_for_ids, evidence_against_ids
missing_discriminating_tests
```

#### EvidenceRecord

```text
id, investigation_run_id, hypothesis_id
source_type, source_system, tool_call_id
query_spec, target_entity, time_window
observed_at, valid_until, freshness_state
result_summary, raw_digest, storage_ref
role: supports|refutes|neutral
strength, directness, reliability
collection_status, error_reason
```

#### RCAQualityDecision

```text
decision: accept|abstain|needs_review
reason_codes[]
accepted_hypothesis_id
raw_confidence, calibrated_confidence
alternative_hypotheses[]
missing_evidence[]
coverage_score
```

#### VerificationSpec

```text
target_outcomes[]
probes[]
baseline_window
success_thresholds
stability_window
side_effect_invariants[]
timeout
rollback_trigger
rollback_verification[]
```

#### AutonomyDecision

```text
level: A0|A1|A2|A3|A4
effective_scope
matched_policies[]
reason_codes[]
action_budget, blast_radius_limit, concurrency_limit
actuation_enabled
```

#### VerifiedEpisode

```text
environment_fingerprint
symptom_pattern, graph_pattern
investigation_path
accepted_rca
action
verification_outcome
time_to_rca, time_to_recover
tool_calls, tokens, cost
transferability_scope
```

### 6.2 必须使用的状态机

```text
Investigation:
created -> scoping -> planning -> collecting -> evaluating
  -> concluded
  -> insufficient_data
  -> needs_input
  -> cancelled
  -> expired

Remediation:
approved -> executing -> executed -> verifying
  -> passed -> resolved
  -> failed -> rollback -> verifying_rollback
  -> timeout -> needs_review
  -> uncertain -> needs_review
```

`resolved` 必须只有 VerifyGate 能写。Executor 无权直接写。

### 6.3 必须统一的 Reason Codes

至少包括：

```text
ENTITY_AMBIGUOUS
DATA_SOURCE_UNAVAILABLE
DATA_SOURCE_FORBIDDEN
INVESTIGATION_BUDGET_EXHAUSTED
RCA_NO_EVIDENCE
RCA_EVIDENCE_UNGROUNDED
RCA_CRITIC_UNAVAILABLE
RCA_ALTERNATIVE_UNRESOLVED
GRAPH_STALE
GRAPH_SCOPE_INCOMPLETE
GRAPH_ENTITY_MISSING
POLICY_SCOPE_DENIED
AUTONOMY_BUDGET_EXCEEDED
RUN_LEASE_EXPIRED
LATE_RESULT_IGNORED
VERIFY_SPEC_MISSING
VERIFY_PROBE_FAILED
VERIFY_UNSTABLE
VERIFY_SIDE_EFFECT_DETECTED
ROLLBACK_VERIFY_FAILED
```

---

## 7. Trust Kernel：绝对 P0

### 7.1 RCA fail-closed

建立纯数据决策对象，不能再由散落的 `if confidence >= 0.6` 决定。

自动进入 SRE 至少同时满足：

1. RCAResult 属于当前有效 `RcaRun`。
2. 至少有一条直接证据和一条独立支持证据。
3. 所有证据都通过 provenance 校验。
4. Critic 完成且不为 refuted。
5. 必要数据源覆盖达标。
6. 高概率替代假设已被排除，或明确不影响修复安全性。
7. calibrated confidence 达到策略阈值。
8. Graph 相关判断使用了合格快照。

### 7.2 RcaRun lease 与晚到隔离

线程不能强杀不是阻塞条件。使用逻辑取消：

- 每次 RCA 创建 `run_id + generation + lease_expires_at`。
- 所有保存工具必须带 `run_id`。
- 写入前检查 run 仍是 active 且 lease 有效。
- timeout 后标记 expired，并增加 generation。
- 晚到的 tool/save/result 一律记录为 `LATE_RESULT_IGNORED`，不得触发 SRE、通知或 Memory。
- 所有 side effect 必须幂等。

### 7.3 Graph Integrity Gate

修复入边遗留后，再增加：

- `GraphSnapshot`
- scope/account/region
- collector coverage
- node/edge observed_at
- source/provenance
- TTL/freshness
- completeness score
- failed collectors
- unknown boundaries

策略必须采用：

```text
涉及拓扑/爆炸半径的自动动作：
graph fresh AND graph complete -> 正常评估
graph stale OR incomplete -> require_human
graph unavailable -> require_human
```

不能再让 Graph 规则“因为拿不到数据而不匹配”，随后落入 L0/L1 自动批准。

### 7.4 独立 VerifyGate

Verifier 必须满足：

- 不复用 Executor 的自然语言结论。
- 读取持久化 `VerificationSpec`。
- 使用只读、确定性 probe adapter。
- 与 Executor 使用不同的代码路径。
- 验证用户影响、目标资源、下游恢复和副作用。
- 支持稳定窗口，而非单点 snapshot。
- 验证失败时可触发回滚，回滚后再次验证。
- 不可验证等于 uncertain，不等于 success。

首批 Probe Adapter：

1. CloudWatch alarm state + metric window。
2. Prometheus/Datadog query。
3. HTTP/SLO endpoint。
4. Kubernetes rollout、ready、restart、events。
5. EC2/RDS/ELB resource state。
6. Log error-rate delta。
7. Jaeger trace error/latency delta。
8. Graph reachability/invariant。

### 7.5 Trust Invariants

这些规则应写成测试，而不仅是文档：

1. Agent 无法直接把 Issue 写成 resolved。
2. 无 VerificationSpec 无法进入 verifying。
3. 无有效 evidence 无法自动生成可执行计划。
4. Critic 或 Graph 被策略要求但不可用时，自动化只降级、不放宽。
5. expired run 的任何结果不能产生业务副作用。
6. 未验证事件不能进入 active SOP/高置信 Memory。
7. 系统不能自行提升生产自治等级。

---

## 8. Investigation Runtime：从“会查”到“会侦探”

### 8.1 Chatbox 首句处理

对于“支付接口最近偶尔慢”：

1. 提取 symptom、时间、环境、服务名候选。
2. 从 Service Catalog、Graph、资源清单、历史 Chat 中解析实体。
3. 若唯一匹配，自动创建 InvestigationRun。
4. 若存在多个生产对象，只问一个最有信息价值的问题。
5. 默认进入 A1 Investigate，不要求用户先创建 Issue ID。

### 8.2 竞争假设

首轮必须生成 3-7 个可证伪假设，例如：

- 最近部署导致应用回归。
- 下游 Redis 延迟造成级联。
- Pod CPU throttling。
- DNS/CoreDNS 抖动。
- ALB target 健康异常。
- 跨 AZ 网络/NAT 问题。

每个假设要记录“最小区分实验”。调查器优先执行信息增益高、成本低、风险低的检查。

### 8.3 Typed Tasks

不要让 Agent 只在一个超长上下文里自由游走。任务至少分为：

```text
ResolveEntity
FetchMetricWindow
SearchLogs
InspectChange
QueryTrace
InspectKubernetes
TraverseGraph
CheckDependency
CompareBaseline
TestHypothesis
```

每个 Task 有输入 schema、超时、重试、预算、结果 schema 和幂等键。

### 8.4 停止条件

允许结束调查的条件：

- 一个假设有足够直接证据。
- 主要替代假设已被证据反驳。
- 所需数据源覆盖达到场景模板要求。
- 结论能够解释全部主要症状和时间顺序。

必须 abstain 的条件：

- 身份仍歧义。
- 关键数据源不可用。
- 两个竞争假设概率接近。
- 证据只来自历史相似案例。
- 已耗尽预算但未达到 coverage gate。

---

## 9. Operational Knowledge Graph

### 9.1 统一 `graph/` 与 `galaxy/` 的语义，不急于物理合并

推荐：

- `graph/` 继续承担确定性实时运维推理。
- `galaxy/` 继续承担全局浏览和 advisory relationship。
- 两者共享统一的 Node ID、Edge Type、Provenance、Snapshot 和 Freshness 契约。
- LLM edge 永远不能直接进入 blast radius、policy 或 execution。
- 只有经确定性验证或人工确认后，LLM edge 才能晋升为 trusted edge。

### 9.2 Graph 分三层

1. **Observed Graph**：来自 API、trace、eBPF、配置和清单的事实。
2. **Derived Graph**：确定性规则和图算法产生的边。
3. **Hypothesis Graph**：Agent 推断的因果/隐式依赖，带证据和有效期。

### 9.3 完整性不是一个全局百分比

Graph 完整性必须按调查 scope 计算：

```text
coverage(account, region, environment, service, node_type, edge_type)
```

例如“EC2/VPC 95%”不能掩盖“payment-service 的 Redis dependency 0%”。

### 9.4 隐式依赖优先级

按 ROI：

1. Trace service dependency。
2. Kubernetes Service/Ingress/Endpoint。
3. RDS/ElastiCache/Queue connection metadata。
4. DNS 查询和配置中心。
5. CloudTrail/Deployment change edges。
6. eBPF 网络边。
7. 最后才考虑 GNN。

当前不应优先做 GNN。数据质量、时间语义和 Ground Truth 尚不足，GNN 只会把不完整图包装成更难解释的结论。

---

## 10. Outcome-weighted Memory

### 10.1 只允许三种事件提高记忆权重

1. VerifyGate 持续通过。
2. 人工确认 RCA 正确。
3. 同一策略在多个相似环境重复成功。

以下事件必须降低权重：

- fix failed
- rollback
- verification failed
- incident reopened
- human incorrect
- Graph/schema 已变化
- 仅症状消失但用户影响未恢复

### 10.2 记忆分层

| 层 | 内容 | 晋升条件 |
|---|---|---|
| Episode | 单次事件、路径、动作、结果 | 每次调查产生 |
| Procedure | 某类问题的调查策略 | 多次 verified episode |
| Pattern | 跨服务可迁移规律 | 多环境重复成立 |
| Skill/SOP | 可执行标准流程 | replay + human approval |

### 10.3 检索排序

不能再只按 memory confidence 和 last_used 注入。建议：

```text
score =
  0.28 * symptom_similarity +
  0.22 * entity_similarity +
  0.18 * graph_pattern_similarity +
  0.15 * verified_success_rate +
  0.10 * recency +
  0.07 * environment_transferability
  - failure_penalty
  - staleness_penalty
```

### 10.4 “越来越快、准、省”的可测定义

同类重复事故相对首次事故：

- TT-RCA 中位数下降至少 40%。
- 工具调用数下降至少 30%。
- token/cost 下降至少 25%。
- RCA accuracy 不下降。
- VerifyGate failure rate 不上升。
- 历史先验被错误复用的比例低于 2%。

没有这些指标，不能宣称“系统正在进化”。

---

## 11. Autonomy Control Plane

### 11.1 风险等级与自治等级必须分离

风险仍使用 L0-L4。自治使用：

| 等级 | 能力 |
|---|---|
| A0 Observe | 只展示环境事实 |
| A1 Investigate | 自动调查，不生成执行承诺 |
| A2 Recommend | 输出 RCA、修复选项和 VerifySpec |
| A3 Human Execute | 人工批准后执行 |
| A4 Bounded Auto | 在明确 scope 和预算内自动执行 |

### 11.2 Scope

至少支持：

```text
organization
account
environment
service
resource
action_type
time_window
```

冲突采用 `most-restrictive-wins`。

### 11.3 Shadow Mode

Shadow 与 Live 必须走同一套：

- Entity Resolver
- Investigation Runtime
- Evidence Ledger
- RCA Quality
- Graph
- Policy
- Verification

唯一差异是：

```text
actuation_enabled = false
```

Shadow 不能只记录“Agent 建议了什么”，还要记录：

- 如果执行，会选择哪个动作。
- 预期 VerificationSpec。
- 人类实际做了什么。
- 最终结果。
- Agent 决策与人类决策的差异。

### 11.4 A4 开放门槛

按 action template，而不是按全局系统：

- 至少 30 个 shadow case。
- 至少 20 个 human-executed verified case。
- 最近 100 个 verified case 的成功率 95% 置信下界高于 95%。
- severe adverse event 为 0。
- rollback 成功率达到 100% 或该动作不允许自动执行。
- Graph 和 Verification coverage 达标。
- 人工批准自治 scope。

系统只能建议升级，不能自己升级。

---

## 12. 产品体验

### 12.1 用户应该看到什么

Chat 首句后不要只显示“正在调用工具”。应该形成一个可折叠的 Investigation Workspace：

```text
对象：prod/payment-service
范围：AWS account A / EKS cluster prod
当前阶段：验证竞争假设
已检查：Metrics, Logs, Traces, K8s, Deployments, Graph
缺失：CloudTrail permission denied
领先假设：Redis latency cascade (0.74 calibrated)
替代假设：recent deployment regression (0.21)
预算：12/25 tool calls, $0.38/$1.00
```

### 12.2 最终答案结构

1. 根因。
2. 关键证据。
3. 被排除的替代解释。
4. 未知和盲区。
5. 修复选项：止血、永久修复、不操作。
6. 风险和 blast radius。
7. VerificationSpec。
8. 为什么可以/不可以自动执行。

### 12.3 最大化产品感知价值

用户不最在意 Agent 调用了多少工具，而在意：

- 它是否理解了我的服务。
- 它有没有遗漏明显方向。
- 为什么相信这个结论。
- 如果执行失败会怎样。
- 它是否真的证明系统恢复。
- 同样的问题下次是否明显更快。

因此产品首页不应继续强化“Agent 数量”，而应强化：

- Investigation coverage
- Verified resolution
- MTTR saved
- Repeated-incident acceleration
- Autonomy readiness
- Prevented unsafe actions

---

## 13. 实施路线

### Phase 0：立即止血，1-2 周

1. 关闭生产默认 `executor_auto_resolve`。
2. RCA 空 evidence、Verifier/Critic 异常改为 needs_review。
3. 修复 Graph 入边残留。
4. Graph 不可用/过期时，涉及拓扑的自动审批 fail-closed。
5. 修复默认管理员密码和版本漂移。
6. 给现有 auto thread 增加最小 run ID、幂等键和重复触发锁。

验收：

- 未经验证的自动 resolved 数量为 0。
- 空 evidence 自动修复数量为 0。
- stale Graph 驱动自动批准数量为 0。

### Phase 1：Trust Kernel，4-6 周

PR 顺序：

1. Trust Contract：状态机、Reason Codes、typed decisions。
2. `RcaRun` lease、logical cancellation、late-result isolation。
3. `VerificationSpec` 和 Probe Adapter 接口。
4. VerifyGate、稳定窗口、rollback verification。
5. GraphSnapshot、freshness、coverage、policy integration。
6. Trust timeline 和 UI。
7. Chaos/replay 测试。

验收：

- 只有 VerifyGate 能 resolved。
- timeout 后晚到结果无副作用。
- 任何 safety input unknown 都降级。
- 执行、验证和学习审计链可关联到同一 trace。

### Phase 2：Investigation Runtime，6-8 周

1. InvestigationRun。
2. Entity/Scope Resolver。
3. Hypothesis 与 Evidence Ledger。
4. Typed Task runtime。
5. 并行 data collection。
6. Coverage Gate 与 abstention。
7. Chat Investigation Workspace。

验收：

- 模糊现象无需 Issue ID 即可启动调查。
- 每个 RCA 至少展示一个被排除替代假设。
- 数据源缺失显式展示。
- 调查可恢复、可取消、可重放。

### Phase 3：Operational Graph，6-10 周

1. 统一 Node/Edge/Provenance/Snapshot contract。
2. 多账户、多 region Graph sync。
3. Service/Environment/Workload identity。
4. Trace/K8s/Deployment/Change edges。
5. 隐式共享依赖。
6. Graph coverage 与 unknown boundary。

验收：

- 目标服务关键依赖覆盖率达到 90% 以上。
- 图新鲜度 p95 不超过同步周期的 2 倍。
- 所有 policy Graph 输入都可追溯到 snapshot。

### Phase 4：Learning + Eval，6-8 周

1. VerifiedEpisode。
2. outcome-weighted retrieval。
3. negative memory。
4. Procedure/Pattern 晋升。
5. Golden Incident Corpus。
6. Replay CI gate。
7. Shadow ledger 和 Autonomy Readiness。

验收：

- 重复事故 TT-RCA、tool calls 和 cost 有统计下降。
- 新模型/Prompt/Skill 不能在 replay 中静默回归。
- 未验证 Episode 不进入 active SOP。

### Phase 5：设计合作客户，持续 8-12 周

1. 选 2-3 个 AWS/EKS 客户。
2. 先开 A1/A2，积累 shadow truth。
3. 只对少数动作模板开 A3。
4. 达到统计门槛后，再对单个 action/scope 开 A4。

---

## 14. 工作量与关键路径

| 工作流 | 人周 | 依赖 |
|---|---:|---|
| Trust contracts/state/reason codes | 2-3 | 无 |
| RCA fail-closed + lease | 3-4 | Trust contracts |
| VerifyGate + probes | 5-7 | Trust contracts |
| Graph integrity/snapshot/coverage | 4-6 | 可并行 |
| Autonomy decision/shadow | 4-5 | VerifyGate |
| InvestigationRun/runtime | 6-8 | Trust contracts |
| Hypothesis/Evidence/Coverage | 5-7 | InvestigationRun |
| Service identity/Operational Graph | 7-10 | Graph snapshot |
| Verified memory/retrieval | 4-6 | VerifyGate |
| Replay/eval/chaos expansion | 5-7 | typed contracts |
| UX workspace/readiness | 4-6 | runtime APIs |
| 生产加固与合作客户 | 8-12 | 全部核心链 |
| **总计** | **57-81 人周** | 部分可并行 |

关键路径：

```text
Trust Contract
 -> RCA Lease/Fail-closed
 -> VerificationSpec
 -> VerifyGate
 -> VerifiedEpisode
 -> Learning
 -> Autonomy Expansion
```

Graph Integrity 可与前半段并行，但 Graph-based auto policy 必须等 Integrity Gate 完成后才能开放。

---

## 15. 评测体系

### 15.1 Golden Incident Corpus

首版至少 50 个事件：

- 15 个 Kubernetes。
- 10 个 AWS 网络。
- 8 个数据库/缓存。
- 7 个部署回归。
- 5 个权限/安全变更。
- 5 个无根因或数据不足事件。

每个事件至少 3 个变体：资源名变化、噪声变化、缺失一个数据源。

### 15.2 分阶段指标

| 阶段 | 指标 |
|---|---|
| Entity | entity resolution precision/recall |
| Plan | 必需数据源覆盖率、无效任务比例 |
| Evidence | grounded precision、freshness、provenance completeness |
| Hypothesis | root cause top-1/top-3、alternative elimination |
| RCA | selective accuracy、abstention quality、calibration error |
| Fix | plan correctness、rollback completeness、risk classification |
| Execute | action success、idempotency、side effect |
| Verify | false pass、false fail、time to stable |
| Learn | repeat speedup、cost reduction、negative transfer |

### 15.3 生产门槛

- Auto path evidence provenance：100%。
- Unverified auto-resolve：0。
- Verify false-pass：<1%。
- RCA selective accuracy：在系统选择“accept”的样本中 >90%。
- 低置信 abstention：允许高，不以“回答率”压低安全性。
- L1 action severe adverse event：0。
- 每个 A4 action template 独立统计。
- Graph scope coverage：>90%，关键边 >95%。
- p95 RCA 时延和成本有硬预算。

---

## 16. 现在应暂停的方向

在 Trust Kernel 和 Investigation Runtime 完成前，暂停或严格限制：

1. 新增更多 Agent。
2. 全面多云扩张。
3. eBPF 自研采集器。
4. GNN/时序 GNN。
5. 让 LLM edge 驱动执行。
6. 完整 Galaxy 视觉重构。
7. 自动升级生产自治权限。
8. 未经 replay 的 Skill 自动发布。

这些方向并非错误，只是当前边际 ROI 低于信任闭环。

---

## 17. 与 MVP-2.5 Cloud Security Review 的关系

Security Review 可以成为很好的旗舰垂直场景，但不能绕过 Trust Kernel。

建议：

- 保留官方 findings、确定性可达性、CIS scoring 的设计。
- Security Recommendation 必须复用 Evidence Ledger 和 RCAQualityDecision。
- Security 自动修复必须复用 VerificationSpec、AutonomyDecision 和 VerifyGate。
- Graph 攻击路径必须使用 snapshot/freshness/coverage。
- 在 Trust Kernel 完成前，Security 保持 Observe/Investigate/Recommend，不开放 Bounded Auto。

若资源有限，应把 Security Review 作为 Phase 2/3 的验收场景，而不是与 Trust Kernel 并列争抢 P0。

---

## 18. 商业与产品定位

最有力量的定位不是“AI AIOps 平台”，而是：

> 面向 AWS/EKS、自托管、图感知、可审计、能证明修复结果的 Trusted Autonomous SRE。

第一阶段不卖“完全自治”，卖三件可验证的东西：

1. **Investigate**：一个模糊现象，自动完成跨工具调查。
2. **Explain**：给出证据链、替代解释和盲区。
3. **Verify**：执行后证明恢复，不能证明就拒绝关闭事故。

商业壁垒最终来自：

- 客户环境的 Operational Graph。
- 经验证的 Episode。
- 每个 action template 的成功统计。
- 可审计的 Policy/Autonomy contract。
- 随重复事件下降的 MTTR 和成本。

Agent 数量、模型名称、Galaxy 动画都不是长期壁垒。

---

## 19. 最终优先级

| 优先级 | 项目 | ROI | 不做的后果 |
|---|---|---:|---|
| P0 | VerifyGate + resolved 权限收口 | 100 | phantom resolution，污染学习 |
| P0 | RCA fail-closed | 98 | 无证据结论驱动修复 |
| P0 | RcaRun lease/late isolation | 97 | timeout 后副作用失控 |
| P0 | Graph integrity/freshness/coverage | 96 | blast radius 与 policy 错判 |
| P1 | InvestigationRun | 95 | Chat 仍只是聪明路由器 |
| P1 | Hypothesis + Evidence Ledger | 94 | 无法证明“调查完整” |
| P1 | Shadow + Autonomy Control Plane | 92 | 无法安全扩大自治 |
| P1 | VerifiedEpisode Memory | 91 | 不能证明越用越好 |
| P1 | Replay Eval CI | 90 | 模型/Prompt/Skill 回归不可见 |
| P2 | Application/Temporal Graph | 84 | 隐式依赖和级联定位受限 |
| P2 | Security Review vertical | 82 | 可延后，但适合作为验收场景 |
| P3 | eBPF/GNN/多云扩展 | 55 | 当前不是核心瓶颈 |

---

## 20. 最终判词

AgenticOps 不缺“Agent”，也不缺“能调用的工具”。它缺的是一套让 Agent 的调查、结论、动作、验证和学习都成为**可持久、可证明、可拒绝、可回放**对象的运行时。

达到目标的真正转折点不是“RCA 更聪明”，而是以下三条同时成立：

1. **不知道时敢于说不知道。**
2. **执行后必须由独立 Verifier 证明恢复。**
3. **只有被结果证明的经验，才允许影响下一次决策。**

完成 Trust Kernel 后，当前项目会从“功能丰富的 AgenticOps MVP”跨入“值得 SRE 逐步交付权限的系统”。完成 Investigation Runtime、Operational Graph 和 Verified Learning 后，才会出现用户设想的体验：一句模糊现象，系统像侦探一样主动查清，并且真的越用越快、越准、越省。

