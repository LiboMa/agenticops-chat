# 可行性报告：Strands 1.64 之后，下个版本重点做哪些功能

日期：2026-11-06（2026-11-07 更新：§5.3、§8、§9）· 状态：**主人已选组合 A**（2026-11-07；不是实施计划，每项另起 Plan Mode）·
前提：Strands 1.45 → 1.64 保持行为升级（已验收，2026-11-07 经 PR #33 合入 main，见 §8 与 `docs/STRANDS-1.64-UPGRADE-REPORT.md`）
姊妹篇：[`2026-11-06-strands-upgrade-study.md`](2026-11-06-strands-upgrade-study.md)（升级点总览）、
[`2026-11-06-agentcore-china-region-study.md`](2026-11-06-agentcore-china-region-study.md)（中国区）

方法：读 1.64.0 的包源码（`S/` = `.worktrees/strands-164/.venv/lib/python3.12/site-packages/strands/`）、
strands-agents-tools 0.9.0 的 wheel（`T/`，只当文本读）、AWS 文档，以及我们自己的代码；另外在 1.64 本地实例上做了
测量（chat 三轮、3 例 chaos-lab 定位评测两轮 + 1 例重跑、topology evidence 体积）。「实测」= 本次跑过；「读码」= 只读了代码；
「未确认」= 没核实。

评级：**收益** 高 / 中 / 低；**工作量** S ≤ 2 天、M 3–7 天、L > 2 周；**中国区** = 在没有 Bedrock 的部署里能否用。

## 0. 一页结论

1. **记忆、KB 不应换成 SDK 的实现**，但我们自己的实现有 4 个可以小成本修掉的实缺陷（§2、§3）。
   SDK 记忆的价值只在「按轮临时注入」，适合以后的事件 / 事实层，不适合我们每次调用都必须可见的行为规则。
2. **S3 Vectors 现在不值得做**：KB 只有 297 个案例、677 个向量（本机库实测），pgvector 已覆盖多进程场景。
   **中国区 KB 真正的阻碍是嵌入模型，不是向量库**：没有 Bedrock 时 KB 会静默降级成纯关键词检索（§3）。
3. **子 agent 最值得的不是换成 `as_tool`，而是在手写的 `@tool` 包装里透传 `invocation_context` 和 `cancel_signal`**：
   整棵 agent 树的用量、预算、取消一次接通，同时保住按调用升级 effort 和账户绑定（§5.1）。
4. **本次测量新发现两个影响大、改动小的问题**（§5）：
   - **RCA 的拓扑证据包每次都被截成预览**：约 2.3 万 token，远超 1500 token 的卸载阈值，模型看到的只有约 3000 字符，
     而它写因果路径要用的边几乎都在预览之外。1.64 的预览改成「头 60% + 尾 40%」后一条边都看不到，模型写错的那条边正是
     预览里露出的第一条边的片段（§5.3）。升级已恢复 1.45 的预览；根治是 X1。
   - **成本记账有两个相反方向的缺口**（实测）：`/api/cost/summary` 里 main chat 的成本少记约 93%（chat 路径写 AgentLog 时
     没传缓存 token）；而每条 chat 消息上显示的成本又不含子 agent（这次 sre 子 agent 的 $0.51 没算进去）。
5. **建议下个版本的重点（6 项，按顺序）**：升级收尾 → 成本记账修正 → 子 agent 透传 → 拓扑证据适配上下文 →
   记忆检索 / 老化 / 归属修正 → 嵌入 Provider 化（并入模型 Provider 层），外加 Evals 试点作为尺子（§7）。

## 1. 功能清单（给主人勾选用；编号在 §7 引用）

| 编号 | 功能 | 来源 | 收益 | 工作量 | 风险 | 中国区 | 建议 |
|---|---|---|---|---|---|---|---|
| U0 | 1.64 升级收尾（保持行为） | 升级研究 §5 | 高（后面所有项的基础） | S（剩验收） | 预览差异见 §8 | 是 | **已完成**（2026-11-07 合入 main） |
| **M1** | 记忆检索改分词打分（含中文二元组） | 自研 | 中 | S | 低 | 是 | **下个版本** |
| **M2** | 「注入即用过」改为「命中或被引用才算用过」 | 自研 | 中 | S | 低 | 是 | **下个版本**（与 M1 一起） |
| **M3** | 记忆写入记录 owner / 会话；私有会话写的记忆先待审 | 自研 | 中（隐私） | S | 低 | 是 | **下个版本**（与 M1 一起） |
| M4 | 结果加权记忆 v0（运行结论 → `adjust_confidence`） | 自研（审计 §10、Harness 阶段 4） | 高 | M | 中（归因有噪声） | 是 | 第二波（先有 X4 基线） |
| M5 | `MemoryManager` + 自写只读 `MemoryStore`（按轮注入事件记忆） | SDK 1.54+ | 低–中 | M | 中 | 是 | 以后 |
| M6 | SDK `FileMemoryStore` / 自动抽取 / BM25 / AgentCore Memory | SDK / AWS | — | — | 高 | 部分否 | **不做** |
| **K1** | 嵌入 Provider 化：OpenAI 兼容嵌入、向量记录模型 id + 维度、Titan 改走 `get_bedrock_session()`、重嵌入 CLI | 自研 | 高（中国区前提） | S–M | 换模型要全量重嵌入（677 条） | **是** | **下个版本**（并入模型 Provider 层 P1） |
| K2 | 真 Amazon S3 Vectors 后端（`VectorStore` 接口后面） | AWS GA 2025-12-02 | 低（现规模） | M | 查询延迟 100 ms–1 s | 很可能（未确认） | 以后 |
| K3 | Bedrock KB / Strands `BedrockKnowledgeBaseStore` / tools 包 `retrieve` | AWS / SDK | — | M–L | 默认凭证链、失去混合重排 | 否 | **不做** |
| **S1** | 子 agent 包装透传 `invocation_context`（整棵树的用量 / limits） | SDK 1.63 | 高 | S | 父请求 `turns` 上限要重算 | 是 | **下个版本** |
| **S2** | 透传 `cancel_signal`（chat 断开、RCA 看门狗协作式停下） | SDK 1.54 / 1.58 | 中 | S | 正在跑的工具会先跑完 | 是 | **下个版本**（与 S1 一起） |
| S3 | 子 agent 的工具进度流到 chat | 自研 + 异步生成器工具 | 中（体验） | M | 只能转发工具事件 | 是 | 第二波 |
| S4 | 专家 agent 换成 `Agent.as_tool` / 内置 `subagent` 工具 | SDK 1.59 | — | M | 丢 effort 升级、并发锁、继承全部工具 | 是 | **不做** |
| S5 | Graph / Swarm / A2A | SDK | — | L | 与代码驱动的 Trust Kernel 冲突 | 是 | **不做** |
| **X1** | 拓扑证据适配上下文（证据包紧凑化，必要时用 1.64 `should_offload` 豁免） | 自研 + SDK 1.64 | 高（RCA 定位） | S–M | 豁免会多 ~2 万 token / 次（大多走缓存） | 是 | **下个版本** |
| **X2** | 成本记账修正：main 的缓存 token 写进 AgentLog；chat 回合显示整棵树用量 | 自研（S1 顺带） | 高（成本可观测） | S | 低 | 是 | **下个版本** |
| X3 | RCA 结构化输出（flag + `structured_output_attempts`） | SDK 1.63 | 中–高 | S–M | 强制重试时 thinking 被关 | 是 | 第二波 |
| **X4** | Strands Evals 试点（13 例定位评测可复现 + 红队） | strands-agents-evals 1.9 | 高（尺子） | M | 需要 rich 15（独立 venv） | 是 | **下个版本，并行做** |
| X5 | 工具边界 Deny 干预 / middleware（viewer、绑定账户、批准哈希） | SDK 1.45 / 1.62 | 中（纵深防御） | M | 包装层太宽 | 是 | 第二波（Harness 阶段 1） |
| X6 | OTEL + baggage（flag） | SDK 1.60 | 中 | S | exporter 配置 | 是 | 以后 |
| X7 | system prompt 进缓存（`system_prompt_ttl=True`） | SDK 1.53 | 中（成本） | S | 命中率需 A/B | 不适用（Anthropic 特性） | 第二波 |
| X8 | `ModelRouter` 限流回退 | SDK 1.52 | 中 | S–M | `AgentLog` 模型 id / 成本记错 | 是 | 以后 |
| X9 | `DecisionModel`（Signal Gate L2、critic 改「封闭问题 + Uncertain」） | SDK 1.63 | 低–中 | S–M | 强制工具关 thinking | 是 | 以后（`DecisionsAPIDecisionModel` 会外发数据 → 不做） |
| X10 | `SnapshotSessionManager` 无损恢复会话 | SDK 1.51 | 低–中 | M | 与 `chat_messages` 双真源 | 是 | 以后（先 IM 试点） |
| X11 | strands-agents-tools 0.9.0（`use_aws` / `retrieve` / `memory`） | tools 包 | — | — | `use_aws` 用模型给的 `profile_name`，违反凭证铁律 | — | **不做** |

## 2. Agent 记忆

### 2.1 现状（实测 / 读码）

| 问题 | 证据 | 后果 |
|---|---|---|
| 检索是整串子串匹配 | `memory/agent_memory.py:541–552`：`if query_lower in searchable` | 多词查询、中文查询基本命不中；`memory_manage search` 形同虚设 |
| 注入就算「用过」 | `agent_memory.py:225–230`：每个被注入的记忆都 `touch_last_used` | Curator 的「按使用老化」实际变成「按置信度排名老化」：排进前 15 的永远活着，其余慢慢被归档；每次 agent 构建都改写最多 15 个文件（本 worktree `git status` 就有 7 个只改了 `last_used` 的记忆文件） |
| `adjust_confidence` 从没被调用 | `agent_memory.py:398` 定义，`grep` 无调用方 | 置信度只由写入时决定，「学到假成功」无法被纠正（审计 §10.1） |
| 记忆没有归属 | frontmatter 无 owner / session 字段 | 私有 chat 里写下的记忆会注入给所有用户的 agent（读码，2.7.0 S1 的会话归属没覆盖到记忆） |

### 2.2 SDK 1.64 的记忆能做什么（读源码）

- `MemoryManager` 是插件：注册 `search_memory`（`add_memory` 需显式开），默认每次 user 回合前检索，把 `<memory>` 块拼到
  **最近一条 user 消息末尾**，不进历史、不碰缓存前缀（`S/injection/_message_injection.py:95,148`）。
- 默认只在 `userTurn` 注入：一次 RCA 最多 40 轮，记忆只在**第一次**模型调用可见（`:130`）。我们的记忆主要是行为规则
  （如「日期必须用工具取」），必须每次调用都在 → **system prompt 冻结快照才是对的位置**。
- `FileMemoryStore` 没有生命周期 / 来源；自动抽取（`ModelExtractor`）写入未经验证的事实；BM25 分词 `\W+` 切不开中文
  （40 个记忆文件里 20 个含中文）；AgentCore Memory 中国区没有。→ 都不采用。

### 2.3 建议

- **M1 + M2 + M3 一起做（S，约 2 天）**：分词打分（英文词 + 中文字二元组）；只在检索命中或模型回复引用 `[file: …]` 时
  touch；写入时记录 owner / session，私有会话写的记忆进待审。顺带消除「每次构建改脏 `agent-memory/`」，也符合
  peer 会话「别 checkout agent-memory」的红线。
- **M4 结果加权 v0（M，第二波）**：注入块已带文件名（`agent_memory.py:241`），把每次运行的注入集记到 `AgentLog` / RCA 结果；
  `verification.evaluate` 出结论或 RCA 被判对 / 判错后调 `adjust_confidence`（+1 / −1）。需要 X4 先给出基线，否则无法
  证明它让 RCA 变好。
- **语义召回层不放在 agent 记忆上**：40 个文件不需要向量；我们已有按指纹的 incident memory（`rca_agent.py:233`）和 KB
  案例向量两层事件记忆。

## 3. KB 管理

### 3.1 现状

- 三个后端（`kb/vector_store.py`）：`SQLiteVectorStore`、`PostgresVectorStore`（pgvector）、以及**名不副实的**
  `S3VectorStore`（`:301`）—— 在普通 S3 桶里存 numpy `.npy` + 一个 JSON 索引，每次查询对每条向量发一次 `GetObject`（`:385`），
  每次写入读改写整个索引（`:339`）。它不在任何部署配置里，只有测试用到。
- 嵌入：Titan v2 1024 维（`kb/embeddings.py`）。两个缺陷（读码）：
  1. `_get_client()` 用裸 `boto3.client("bedrock-runtime")`（`:63`），走进程默认凭证链，而凭证铁律的例外只允许 Bedrock 控制面
     经 `get_bedrock_session()`；
  2. Bedrock 不可达时 `get_embedding_client()` 静默退回 `NullEmbeddingClient`（`:96–126`）→ **中国区部署的 KB 会悄悄
     变成纯关键词检索**，没人会发现。
- 向量记录不带嵌入模型 id / 维度（`case_vectors` 表）：换嵌入模型会把两种向量空间混在一起比较。

### 3.2 建议

- **K1（S–M，下个版本，并入模型 Provider 层）**：`EmbeddingClient` 增加 OpenAI 兼容子类（DashScope `text-embedding-v4` 等
  1024 维可选、或自建 bge-m3）；每条向量记录模型 id + 维度，不一致的拒绝参与检索；Titan 改走 `get_bedrock_session()`；
  一个 `aiops kb reembed` CLI；嵌入不可用时在 Settings / 健康检查里**明说**「KB 已降级为关键词检索」，不再静默。
- 假 `S3VectorStore` 改名为 `S3BlobVectorStore` 并标 deprecated（或直接删，它无部署使用），避免和真 S3 Vectors 混淆。
- 可达面（规则 9，K1 若入选）：CLI 做（`aiops kb reembed`）；Web API 做（嵌入 provider 归入模型 Provider 的 API）；
  Web UI 做（Settings → Model providers 里的嵌入分配 + KB 降级提示）；Agent tool 非目标；Schedule 非目标；
  Notification 做（嵌入不可用时通知一次）。

## 4. S3 Vectors

| 项 | 事实 | 出处 |
|---|---|---|
| 状态 | 2025-12-02 GA，每索引最多 20 亿向量 | aws.amazon.com what's-new 2025-12 |
| API | `CreateVectorBucket` / `CreateIndex` / `PutVectors`（≤ 500 条/次）/ `QueryVectors`（`filter`、`returnMetadata`、`returnDistance`）/ `GetVectors` / `ListVectors` / `DeleteVectors` | botocore 1.42.49 `s3vectors` 服务模型 |
| 规格 | 维度 1–4096、float32、cosine / euclidean；元数据 ≤ 40 KB（可过滤 ≤ 2 KB、≤ 50 键）；Top-K ≤ 10,000 | S3 userguide s3-vectors-limitations |
| 过滤 | `$eq/$ne/$gt…/$in/$nin/$exists/$and/$or/$startsWith`；2026-09-30 起新建桶为 `ENHANCED`（先过滤再搜），更早的 `CLASSIC` 可能返回少于 K 条 | s3-vectors-metadata-filtering |
| 延迟 | 低频 < 1 s，高频「低至 100 ms」 | s3-vectors 概述 |
| 价格 | us-east-1 存储 $0.06/GB·月、查询 $2.5/百万次；我们约 2.8 MB 向量 ≈ $0.0002/月 | aws.amazon.com/s3/pricing |
| 中国区 | amazonaws.cn 价格页列有宁夏 / 北京的 S3 Vectors 人民币价格；docs.amazonaws.cn 写「与 Bedrock / OpenSearch 的集成」不可用 → 服务本身**很可能可用，未确认** | amazonaws.cn S3 价格页、docs.amazonaws.cn |
| Strands 的 S3 Vectors 策略（1.64） | 只给 `S3Storage` 的对象建索引；向量只有 key、无元数据；`topK` 之后才在客户端按前缀过滤；默认 Titan 嵌入；未注入 session 时回退默认凭证链 | `S/storage/search/s3_vector.py:101,136–153,184` |

**结论**：不用 Strands 的策略；真要用 S3 Vectors 就在 `VectorStore` 接口后面自写 `S3VectorsStore`（每个「嵌入模型 + 维度」
一个索引、key `{case_id}#{field}`、`resource_type` / `verified` 作可过滤元数据），并需要主人对凭证铁律例外清单加一条
「平台自有资源用平台 session」。**按现在 677 个向量的规模，价值低于延迟代价**（本地暴力检索是毫秒级），等出现
「无 RDS 的云 profile」或 AgentCore 拆分需要共享 KB 时再做（K2）。

## 5. 子 agent，以及本次测量发现的两个问题

### 5.1 子 agent

- 现状：main 的 6 个专家是手写 `@tool` 包装，每次调用新建 `Agent`、返回 `str(result)`；1.64 默认 `ConcurrentToolExecutor`
  （`S/agent/agent.py:610`），main 已能在一轮里并行调多个子 agent，不需要改。
- **S1 + S2（S，约 1–2 天）**：包装加 `@tool(context=True)`，把 `tool_context.invocation_context` 和 `cancel_signal` 透传给
  `invoke_with_retry`。这正是 `as_tool` 内部做的事（`S/agent/_agent_as_tool.py:249`），但能保住类型化参数、按调用升级
  effort、`RunContext` 账户绑定（`asyncio.to_thread` 会复制 contextvars）、post-RCA 质量流水线和 `track_agent`。
  收益：整棵树共享 `total_tokens` 预算（Harness 阶段 1/2 的「每次运行 token 预算」）；chat 断开 / RCA 看门狗能让子 agent
  协作式停下（`web/app.py` 现在断开时只是 `break`）。
- `as_tool` / 内置 `subagent` 不适合专家：`as_tool` 只接一个 `input` 字符串、同实例并发直接报错（`_agent_as_tool.py:203`）、
  模型构建时定死；`subagent` 默认继承父 agent 的全部工具并带 `context_manager="auto"`（`S/multiagent/spec.py:346,360`）。
- **必须守住**：viewer 白名单 `read_only_main_tools()`（`main_agent.py:290`）—— 任何插件带进来的工具（offloader 的
  `retrieve_offloaded_content`、`MemoryManager` 的 `search_memory` / `add_memory`）都要逐个核对；任何 `model=` /
  `aux_model=` 都不能传字符串（会变成默认凭证链的 `BedrockModel`，`S/agent/agent.py:202`）。

### 5.2 新发现 ①：成本记账两个相反方向的缺口（实测，1.64 本地实例，3 轮 chat）

| 回合 | chat 消息上记的成本（只算 main） | AgentLog（`/api/cost/summary` 的数据源）里 main 的成本 | 子 agent |
|---|---|---|---|
| 普通回答 | $0.519 | $0.009 | — |
| 子 agent 只读查询 | $0.667 | $0.057 | sre $0.511（只在 AgentLog） |
| 技能激活 | $0.813 | $0.081 | — |

- **缺口 A**：`web/app.py` chat 路径调 `log_agent_call(agent_name="main", …)` 时**没传** `cache_read_tokens` /
  `cache_write_tokens`，而 Opus 5 的 main 几乎全部输入都走缓存 → `/api/cost/summary` 和 Agent metrics 页上 main chat 的成本
  少记约 93%（这三轮：$0.147 对 $2.00）。这是 main 分支上已有的缺陷，与升级无关。
- **缺口 B**：chat 消息上显示的 token / 成本只取 main 自己的 `accumulated_usage`，不含子 agent（这次少了 sre 的 $0.51，
  占该回合真实成本的 43%）；`agents/metrics.py:3–5` 的注释「覆盖所有子 agent」与事实不符。
- **X2（S，约 1 天）**：A 是两行修正；B 在 S1 之后用 `result.invocation_context.usage` 显示整棵树（AgentLog 仍按 agent 各记
  一行，不会重复计）。建议 X2 与 S1 同一批做。

### 5.3 新发现 ②：RCA 的拓扑证据包每次都被截成预览（实测）

**现象**
- `get_topology_evidence` 在 chaos-lab 上的输出：**8.2 万–9.4 万字符（约 2.0 万–2.3 万 token）**，5 个候选、184 条边、
  152 个邻居（issue 97：`candidates` 1.2 千字符、`edges` 5.2 万、`neighbors` 4.0 万；`edges` 从第 1724 个字符开始）。
  告警锚在集群上，集群是容器类型，所以按两跳取邻域 = 把整个集群装进来；其中只有 4 个邻居真有异常 / 变更 / 信号，
  其余是正常的 ConfigMap（58）、Service（30）、Secret（18）……；184 条边里 149 条是 `contains`。
- `ContextOffloader` 的阈值是 1500 token，所以**每次**都被卸载，模型只看到 750 token（3000 字符）的预览，要看边必须调
  `retrieve_offloaded_content`。`evidence.py` 早已按这一点把小字段放在前面（代码注释「the RCA agent's context offloader
  keeps only the head of a large result (~3,000 chars)」），但包太大，头部装不下边：
  - 1.45 的预览 = 前 3000 字符 → 候选 + 前四五条边；
  - 1.64 的预览 = 前 1800 字符 + 后 1200 字符 → 候选 + 第一条边的片段 + 邻居列表的尾巴。

**证据**
- 1.64 原生预览下 l2-payment-svc 两次 `partial`，rank-1 候选都对，被丢的都是路径：
  - 第一次写「命名空间 agenticops(52) → payment-svc」，而 52 正是预览里露出的那条边（集群 48 → 52）的终点；
  - 第二次写「集群(48) → payment-svc」一跳；
  - 图里真实的是「集群(48) → 命名空间 chaos-lab(54) → payment-svc(200)」，校验器 fail-closed 丢掉了整条路径。
- 恢复 1.45 的预览后重跑同 3 例：**3/3 valid**（bad-image、netpol-block、l2-payment-svc）。2.6.1 的 bad-image partial
  （报告发现 7）是同一模式。样本只有 3 例，所以「看不到边 → 猜路径」仍是强推断，不是定论（RCA 日志只记工具调用次数）。

**X1 解法（S–M，约 2–3 天 + 一次 13 例评测）**
1. **代码算好每个候选到锚点的路径**：每个候选加 `path_to_anchor`（在本次返回的边上 BFS，每条边带 `src_ref` / `dst_ref` /
   `relation_type` / `evidence_ref`，与校验器查的是同一份 build，抄过去就有效）；提示词改为「location.path 直接复制候选的
   `path_to_anchor`，不要自己拼边」。`save_rca_result` 的参数不变，fail-closed 校验不放松。
2. **默认返回紧凑包，压到卸载阈值以下**：邻居只给有异常 / 变更 / 信号的，其余按类型计数；边只给候选路径上的和异常节点之间的，
   其余只报数量；`detail="full"` 仍能取完整版（有上限）。用这次的真实数据模拟：

   | issue | 现在 | 紧凑版 | 边 | 邻居 |
   |---|---|---|---|---|
   | 97（l2-payment-svc） | 9.4 万字符 ≈ 2.3 万 token | 5.8 千字符 ≈ 1.46 千 token | 184 → 6 | 152 → 4 |
   | 1（bad-image） | 9.4 万字符 ≈ 2.3 万 token | 5.7 千字符 ≈ 1.44 千 token | 184 → 6 | 152 → 4 |
   | 2（netpol-block） | 8.2 万字符 ≈ 2.0 万 token | 4.4 千字符 ≈ 1.09 千 token | 149 → 4 | 149 → 3 |

   离阈值余量不大，实现时去掉每条边上的重复字段（两端名字、规则说明文字）。
3. **先补测量**：RCA 的 AgentLog 现在只记工具调用次数，加上工具名序列（能看到有没有调 `retrieve_offloaded_content`）；
   验收用完整 13 例定位评测（约 $15–19、45 分钟）：partial 变少（2.6.1 on #1 为 11 valid / 2 partial，on #2 为 12 valid /
   1 partial）、AC@1 不降、每例 token 下降。

不选：用 1.64 的 `should_offload` 豁免这个工具（每次 RCA 多塞约 2 万 token，绝大多数是无关噪声，只作兜底）；放宽校验器自动补
少写的那一跳（削弱 fail-closed）。可达面（规则 9）：Agent tool 做（`get_topology_evidence` + RCA 提示词）；CLI / Web API /
Web UI / Schedule / Notification 非目标（`GET /api/graph/focus` 不受影响）。`tests/test_topology_evidence.py` 约 45 处依赖
边 / 邻居列表的断言要随之调整。

## 6. 其他高影响特性（简述）

- **X4 Strands Evals 试点（M）**：把 `location_eval.py` 包成确定性评估器，基于**录制的真实工具输出**（不要用 ToolSimulator
  评 RCA 准确率，它让 LLM 编造工具输出）；再加 chat / IM / issue 备注的提示注入红队。它是 M1–M4、X1、X3 的尺子。
  每批 13 例真实评测约 $14.5–19.2、40–47 分钟（2.6.1 实测），录制回放能把回归测试成本降下来。
- **X3 RCA 结构化输出（第二波）**：1.63 加了 `structured_output_attempts`；强制重试时 Bedrock 只删 `thinking` 字段而
  `output_config.effort` 还在，Opus 5 是否接受未确认 —— 先在冒烟脚本里验证。
- **X5 Deny 干预 / middleware（第二波）**：工具边界上「viewer 回合 / 绑定账户不符 / 上下文里没有已批准哈希 → 拒绝写工具」，
  纵深防御；真正的闸门仍是代码和 DB。
- **X7 system prompt 缓存（第二波）**：升级时按主人裁定保持 `system_prompt_ttl=False`；单独开一个 A/B 就能量化。
- X6 OTEL、X8 `ModelRouter`、X9 `DecisionModel`、X10 `SnapshotSessionManager`：以后。X11 tools 包：不引入。

## 7. 建议的版本组合（选一个，或自由组合编号）

| 组合 | 内容（按顺序） | 规模 | 适合 |
|---|---|---|---|
| **A 推荐：稳健提升** | U0 → X2 → S1 + S2 → X1 → M1 + M2 + M3 → K1（并入模型 Provider 层）；X4 并行 | 约 2–3 周（K1 随 Provider 层另计） | 先把成本、RCA 定位、记忆这几个已证实的缺陷修掉，同时为中国区铺路 |
| B 中国区优先 | U0 → K1 + 模型 Provider 层 → S1 + S2 → X2；记忆 / X1 放后 | Provider 层 3–4 周 + 1 周 | 中国区上线日期最紧时 |
| C RCA 质量优先 | U0 → X4 → X1 → X3 → M4 | 约 3–4 周 | 定位 / 结论质量是首要目标时 |

第二波：M4、S3、X3、X5、X7。以后：M5、K2、X6、X8、X9、X10。不做：M6、K3、S4、S5、X11。

## 8. 升级（U0）当前验收状态

| 验收标准（计划） | 结果 |
|---|---|
| 1 只有 strands 变 | `uv.lock` 只有 strands-agents 1.45.0 → 1.64.0；`requirements.txt` 同步 |
| 2 平行测试 | 7 个 agent × 开 / 关，构建零 warning，窗口大小、offloader 1500 / 750 均符合 —— 通过 |
| 3 全量 pytest | 恢复 1.45 预览后再跑：6990 passed、85 skipped、3 failed —— `test_web_tools` 是已知 DNS 假失败；`test_memory_roundtrip_props`、`test_session_manager_props` 是 hypothesis 的 FlakyFailure（「第一次失败、重跑不失败」），那次全量和本地服务、评测同时跑、用了 9 分 48 秒，两个文件单独重跑 13/13 通过 —— 通过 |
| 4 真实 Bedrock 冒烟 | 所有模型家族全部检查通过，Anthropic 第二次调用 `cacheReadInputTokens > 0` —— 通过 |
| 5 本地 chat E2E | 普通回答（5 s）、子 agent 只读查询（`sre_query`，43 s）、技能激活（`activate_skill`，7 s）全部 `completed`；服务日志里「ignoring co-provided conversation_manager」/ DeprecationWarning / `drop_block` / Traceback 都是 0 —— 通过 |
| 6 3 例定位评测 | **第一轮（1.64 原生预览）**：AC@1 = 1.0；bad-image valid、netpol-block valid、l2-payment-svc partial（重跑一次仍 partial）→ 按标准算变差，原因见 §5.3。**第二轮（恢复 1.45 预览，2026-11-07，最终版本）**：AC@1 = AC@3 = MRR = 1.0、graph recall 3/3、**3/3 valid**（bad-image 比基线的 partial 好，另两例与基线持平）—— 通过。token（只计这 3 次 RCA，按 AgentLog）：16.7 万 / 15.2 万 / 13.5 万，成本 $1.00 / $0.78 / $0.73；2.6.1 基线按整批合计约 25.3–25.8 万 / 例（口径含批内其他调用，偏高），≤ 1.2 × 达标。耗时 121–146 s / 例（基线 64–111 s；这次是本地实例、不是集群内实例，不可直接比） |

**计划之后发现、已处理的版本差异**：1.64 的 `ContextOffloader` 预览从「只取头」变成「头 60% + 尾 40%」（还新增了
`evict_after_cycles`，只作用于新的统一 Storage，我们用的旧 `InMemoryStorage` 不受影响）。按主人裁定（2026-11-07，选项 a），
`config._head_preview_offloader_class` 用一个子类覆盖 `_slice_preview` 恢复 1.45 的预览；`tests/test_strands_parity.py`
钉住预览 = 前 750 × 4 字符，并检查 SDK 仍通过 `_slice_preview` 生成预览（换掉这个私有方法的版本会让测试失败，而不是让
预览再次静默改变）。

## 9. 主人的决定与仍待决定

已定（2026-11-07）：
1. U0 的预览差异 → **(a) 恢复 1.45 预览**，已完成并重跑（§8）。
2. 下个版本 → **组合 A**：U0 → X2 → S1 + S2 → X1 → M1 + M2 + M3 → K1（并入模型 Provider 层），X4 并行。每项单独从 Plan Mode 起步。

仍待决定：
3. **K2 是否需要**：凭证铁律例外清单是否加一条「平台自有资源（KB 向量桶）用平台 session」。只有做 K2 时才需要决定。
4. **X4 Evals 的放置**：长期放独立 venv，还是接受 rich 升到 15。

## 10. 未确认项

S3 Vectors 是否已在 cn-north-1 / cn-northwest-1 上线（只有价格页为证）；`ENHANCED` 索引的参数在 botocore 1.42.49 里没有；
Opus 5 在强制结构化输出重试时是否接受不带 `thinking` 的 `output_config.effort`；手写子 agent 的 OTEL span 是否嵌套在父
span 下；DashScope / bge-m3 在我们中英混合运维文本上相对 Titan 的召回差异；§5.3 里「看不到边 → 猜路径」的因果关系
（3 例样本支持，需要工具名日志或 X1 之后的 13 例评测来证实）。
