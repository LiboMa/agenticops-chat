# 研究报告：Strands Agents 升级点与收益（1.45 → 1.64 / Strands harness / Strands Evals）

日期：2026-11-06 · 状态：**研究结论，待主人决策**（不是实施计划）· 只读研究，未改代码、未安装（新包只下载 wheel 当文本读）
姊妹篇：[`2026-11-06-agentcore-china-region-study.md`](2026-11-06-agentcore-china-region-study.md)（中国区 AgentCore，独立成文）

出处约定：`docs:` = https://strandsagents.com/docs/user-guide/ ；changelog = https://strandsagents.com/changelog/ ；
发布 tag 已迁到 monorepo `github.com/strands-agents/harness-sdk/releases/tag/python/vX.Y.Z`。

## 0. 结论

1. **版本差距**：我们在 `strands-agents` **1.45.0**；最新 **1.64.0**（2026-11-04）。同期新包：`strands-harness` 0.3.4、
   `strands-agents-evals` 1.9.0、`strands-agents-tools` 0.9.0。
2. **不把应用换成 Strands harness**：它是一个把 SDK 能力组装成**普通 `strands.Agent`** 的工厂，默认带 shell / 文件工具、
   本地 `./.agent` 目录和一个通用子 agent —— 与我们的凭证铁律、单进程 / DB 状态设计冲突；官方文档也把「自有工具集、
   多 agent 编排」的场景指回 SDK。**把它当零件库。**
3. **升级有一个静默破坏性变更**：1.56 起 `context_manager="auto"` 会**丢弃**我们传入的 `conversation_manager`，
   detect（8000）、scan（1000）、executor / reporter（1800）等滑动窗口全部失效，现有测试抓不到。升级必须用保持
   1.45 行为的配置。
4. **收益最大的三件事**：① 升级本身（带保持行为配置）；② **Strands Evals** 试点（1.9 已兼容 1.45，可把 13 例 RCA 定位
   评测变成可重复、可对比的实验，并做红队测试）；③ Harness 计划阶段 0 的零件：RCA 结构化输出、`ContextInjector`、
   OTEL、deny-only 干预、`cancel_signal`。
5. **KB、Agent 记忆、Skills 不替换**：我们的实现有生命周期、来源追溯、安全闸门和混合重排，SDK 版本没有；SDK 记忆的
   自动抽取会写入未验证事实（正是 Harness 计划要防的「学到假成功」）。

## 1. Strands harness 是什么

- 包：Python `strands-harness`（0.3.4）、TS `@strands-agents/harness`；SDK 本身已并入同一 monorepo，文档称「Strands Harness SDK」。
  0.x 版本：minor 即可能破坏兼容（docs: harness/versioning）。0.3.4 需要 `strands-agents[otel]>=1.57.2`，钉死 `pydantic-monty==0.0.23`。
- 关系：`create_harness()` 把选项解析成 SDK 对象，加上内置工具、插件、子 agent，**返回普通 `strands.Agent`**；没点名的参数原样传给
  `Agent`（docs: harness/composing-with-sdk）。可复用的导出：`HARNESS_CONTRACT`、`build_system_prompt`、`resolve_memory`、`resolve_interventions`。
- 默认值（`strands_harness/defaults.py`）：模型 `bedrock/global.anthropic.claude-opus-5`；`context_manager="auto"`、缓存 auto；
  工具 `shell / read / write / edit / web_fetch / web_search / programmatic_tool_caller`（模型写的代码在 Monty 沙箱里跑）/
  `subagent`（通用、深度 2）；插件 `todos`、`environment`；会话 `SnapshotSessionManager`（`./.agent/sessions`）；记忆
  `MemoryManager` + `FileMemoryStore`（`./.agent/memory`，每轮注入，后台小模型抽取）；Skills `AgentSkills`（`./.agent/skills`）；
  干预默认无（可选 `ask` / `smart` 风险分类 / 自然语言策略 / Cedar）；OTEL 只在设了 exporter 时导出。
- `HARNESS_CONTRACT`：模型中立的行为契约 —— 先探索再改动、不可逆操作先确认、宣称完成前先验证、如实报告结果。
- 生产指引（docs: harness/production）：按 SDK agent 部署 / 观测 / 加固；会话和记忆目录指向持久存储；沙箱化或去掉
  programmatic tool caller；shell / 编辑用干预 + 沙箱把门；同一会话 id 并发写是后写覆盖、无锁。
- 官方数据（都是厂商自测，基准不是运维 / SRE 任务）：

| 来源 | 说法 | 依据与注意 |
|---|---|---|
| 发布博客 2026-09-21 | 同模型下比其他 harness 便宜 28%；Fable 5 上比 Claude Code 便宜 77%、Terminal-Bench 2.1 更高 | 主要归功于上下文默认值（工具结果 >~1500 token 截断、85% 时压缩、循环内溢出恢复） |
| 后续博客 2026-10-13 | 实际约 34%；不同 harness 每题成本 $0.74–$1.57 | 约 94,000 次试验、8 个基准、12 个模型；**美元是按 token 估算**；作者说聚合数据「不能分离各因素的贡献」 |
| Harness Optimizer 2026-07-10 | AppWorld 72.6 → 95.8，WebShop 56.5 → 67.5 | 只优化 system prompt；skill / memory / tool 的优化「仍在开发」；需要奖励信号 |
| 红队博客 2026-10-26（Evals 1.7+） | `RedTeamExperiment` | 风险类：提示注入、越权、敏感数据、数据外泄、提权、违反业务规则、社工；建议看工具调用而不只看分数、多次运行 |

- **结论：组合使用，不替换。** 它的价值在 SDK 能力上，我们可以一个个接；其中 AgentSkills、MemoryManager、ContextInjector、
  GoalLoop、steering、Cedar、HITL、`structured_output_model` **在我们装的 1.45 里已经有**。

## 2. 1.45 → 1.64 的变化

### 2.1 会碰到我们代码的破坏性变更 / 弃用

1. **1.56.0（PR #4282）`context_manager` 覆盖 `conversation_manager`**（未标为 breaking）：1.45 时显式的会话管理器会保留，
   "auto" 只加 `ContextOffloader(1500/750)`（与 `config.py:1330–1345` 的注释一致）；1.64 时只发一个
   `UserWarning("context_manager is set, ignoring co-provided conversation_manager")` 并改用 `NullConversationManager`，
   "auto" 变成一组策略（工具结果 >1500 token 截断留 750 预览、到模型窗口 85% 时摘要、紧急截断、新工具 `retrieve_context`）。
   → 8 个 agent 构建点的滑动窗口全部失效；工具列表变了，缓存前缀也变了；model info 把 Claude 4.6 / 5 记为 1M 窗口，
   摘要可能几乎不触发（Bedrock 实际窗口 1M 还是 200k：未确认）。`tests/test_strands_context_manager.py` 只断言字符串 `"auto"`。
2. **1.55.0（PR #3985）`cache_tools` 弃用**：`preamble.py:317` 会发 DeprecationWarning → 改 `CacheConfig(strategy="auto", tools_ttl=True)`。
3. **1.53（PR #3681）auto 缓存也缓存 system prompt**（`system_prompt_ttl` 默认开）：大概率是收益（我们的记忆块在最后），命中率要重测。
4. **1.63** `context_manager` + `RepositorySessionManager`（File / S3）会抛 `ValueError`：只在将来采用 SDK 会话时相关，改用 `SnapshotSessionManager`。
5. **1.63** 空 prompt 被拒（需确认我们没有这种路径）；Bedrock `maxTokens` 默认取 model info 上限（我们总是显式传，不受影响）。

### 2.2 已核实不变（或只增不改）

`Agent.__init__` 只新增关键字参数 `aux_model`、`storage`、`background_tasks`、`baggage_attributes`；`stream_async` 新增
`cancel_signal`、`invocation_context`，`limits={"turns": …}` 仍可用；`ToolStreamEvent` 形状不变（`acp/mapping.py` 安全）；
`additional_request_fields` 原样透传（自适应 thinking 与 `reasoning_effort` 的形状仍有效）；`HumanInTheLoop` 新增 `classifier`；
`ToolRegistry.registry` / `process_tools` 仍在（`skills/tools.py:124–128` 依赖这个私有 API）；与 `pyproject.toml` 无依赖冲突，
`requirements.txt:303`（`==1.45.0`）需重新生成。

### 2.3 值得用的新能力

| 版本 | 能力 |
|---|---|
| 1.51 | `SnapshotSessionManager`；HITL 的 LLM 风险分类器 |
| 1.52 | `ModelRouter`（回退策略） |
| 1.54 | `FileMemoryStore`；外部 `cancel_signal`；`cache_key` |
| 1.56 | 上下文策略 presets；BM25 检索 |
| 1.58 | `aux_model`（摘要 / 分类 / steering 的旁路调用用小模型）；`agent.cancel()` |
| 1.59 | 内置 subagent 工具；嵌套 agent-as-tool 的中断可在重建后恢复 |
| 1.60 | OTEL baggage 传播 |
| 1.61.1 | 跨模型家族时丢弃 reasoning 块（我们的 Claude ↔ GPT `/model` 切换会用到） |
| 1.62 | 公开 middleware；**历史被编辑导致 thinking 签名失效时自动 `drop_block` 重试**（2026-08-31 后新建的 Bedrock 账户强制 thinking 块绑定，docs: model-providers/amazon-bedrock §5.4） |
| 1.63 | `DecisionModel`；`Model.model_info`；结构化输出重试上限；limits 与 usage 在整个 agent 树上生效 |
| 1.64 | S3 Vectors 检索策略 |

配套包：**strands-agents-evals 1.9.0** 只要求 `strands-agents>=1.45.0`（今天就能用），但要求 `rich>=15,<16`（我们 14.3.2，
typer / CLI 在 rich 15 下是否正常：未确认 → 先在独立 venv 里试）；**strands-harness 0.3.4** 要求 SDK ≥ 1.57.2。

## 3. 逐组件：能不能升级、收益是什么

评级：工作量 S / M / L；建议 = 采用 / 试点 / 以后 / 不做。

| 组件（路径） | 现状 | 可用的 Strands 能力 | 收益 | 工作量 | 风险 | 建议 |
|---|---|---|---|---|---|---|
| **上下文管理**（`config.py:1314–1345`，8 个构建点） | SlidingWindow / Null + "auto"（1.45 含义：只加 offloader） | `context_manager=False` + `ContextOffloader` 插件（完全保持行为）；之后 presets、`aux_model` | 升级不静默退化；以后可以摘要代替硬截断 | S | 摘要会改历史 → 缓存未命中、thinking 绑定重试 | **随升级采用保持行为配置**，之后 A/B 试 presets |
| **提示缓存**（`preamble.py:316–317`） | `CacheConfig(strategy="auto")` + `cache_tools` | `CacheConfig(tools_ttl, system_prompt_ttl, messages_ttl, ttl="1h")` | 去掉弃用；system prompt 进缓存；长 RCA 用 1h TTL | S | 工具列表变化导致前缀变化 | **随升级采用** |
| **RCA 质量**（`services/rca_quality.py`、`rca_agent.py`、`save_rca_result`） | 证据检查读拍平的消息文本；critic 走裸 `converse`、用量丢失；置信度闸门 | `structured_output_model`（1.45 已有，1.63 加重试上限）；steering `LedgerProvider`（工具账本）；critic 改成小模型 / `aux_model` 上的 `Agent` | 类型化结论代替 JSON 字符串参数；可用于取证的结构化轨迹；critic 成本被记账 | S–M | GoalLoop / after-model Guide 默认不限重试；LLM steering 不能变成闸门 | **结构化输出 flag 后采用（阶段 0）**；critic 改 Agent 现在就做；账本试点 |
| **评测**（`infra/eks-chaos-lab/e2e/` 的 13 例定位评测、`tests/test_prompt_budget.py`） | 手写 13 例、真集群、每批 $14.5–19.2、约 40–47 min | Strands Evals：`Experiment` / `Case` / `@eval_task(TracedHandler())`、自定义确定性评估器、轨迹 / 工具选择评估器、结果缓存、ChaosPlugin、红队、trace provider | 可重复的报告和回归对比；工具 / 凭证故障的混沌测试；对备注 / 上下文块 / IM 的提示注入与对执行器的越权做红队 | M | **不要用 ToolSimulator 评 RCA 准确率**（它让 LLM 编造工具输出）—— 用录制的真实输出；rich 15 | **现在就试点**（不依赖升级） |
| **HITL / 审批**（`executor_hitl_enabled`、`executor_agent.py`、`get_approved_fix_plan` + `content_hash`） | HITL 白名单默认关、无恢复路径；真正的闸门是 DB | `InterventionHandler.before_tool_call → Deny/Guide/Confirm`；Cedar；middleware | 工具边界上的类型化、fail-closed 拒绝（上下文里没有已批准哈希 → 拒绝写工具），纵深防御 | M | `Confirm` 会让没有 UI 的后台执行器挂起；LLM 分类器不确定 | **试点 deny-only**；Cedar 以后；LLM / DecisionModel 分类器不做 |
| **中止与预算**（RCA 看门狗 `rca_service.py:48`、chat 中断） | 线程看门狗、`limits={"turns"}` | `cancel_signal`、`agent.cancel()`、`limits.total_tokens` | 协作式取消；每次运行的 token 预算（Harness 阶段 1/2） | S | 工具要轮询信号 | **升级后采用** |
| **可观测性 / 成本**（`agents/metrics.py`、`agent_log_service.py`、`cost_service`） | `accumulated_usage` → `AgentLog`；无 OTEL；critic、Signal Gate L2、摘要的用量丢失 | `StrandsTelemetry` OTLP（gen_ai 语义约定、缓存 token 属性、baggage） | span 级延迟；生产评测的数据源 | S | exporter 配置；手写子 agent 的 span 是否嵌套在主 trace 下：未确认 | **flag 后试点**；`cost_service` 仍是计费真源 |
| **会话 / 聊天历史**（`web/session_manager.py`、`im/session_manager.py`） | 进程内缓存；从 `ChatMessage` 重建历史（合成工具对、截到 4000 字符）；IM 会话不恢复 | `SnapshotSessionManager`（消息、`agent.state`、`interrupt_state`）+ 自定义 `Storage`（4 个异步方法） | 无损恢复，含工具结果和 HITL 中断状态 | M | 与 `chat_messages` 形成两个真源；没有官方 PostgreSQL / SQLite 后端 | **以后**：先在 IM 试点，`chat_messages` 仍为权威 |
| **多 agent**（`main_agent.py` 手写的子 agent `@tool`） | 每次调用新建 `Agent`、`str(result)` | `Agent.as_tool(preserve_context, delegate)`；整棵 agent 树的 limits / usage | 子 agent 在 chat 里流式输出；用量和上限汇总；`delegate=True` 省掉主 agent 复述的一轮 | M | 必须保留每次调用的模型 / effort 升档和 `RunContext` 账户绑定 | **以后**（先试 sre_query / reporter）；Graph / Swarm / A2A **不做**（代码驱动的流水线就是 Trust Kernel） |
| **模型调用**（`preamble.py`） | 只有 `BedrockModel`；自写 `invoke_with_retry`（2 次） | `ModelRouter`（回退）、`retry_strategy`、`model_info`、`drop_block`、`OpenAIResponsesModel` | 限流回退；Claude ↔ GPT 安全切换 | S–M | 双重重试；Mantle 默认凭证链（需显式传 `boto_session`） | **升级即得 `drop_block` / `model_info`；`ModelRouter` 以后** |
| **Agent 记忆**（`memory/agent_memory.py`、`curator.py`、`tools/memory_tools.py`） | 文件；冻结的 top-15 注入 system prompt；策展器 | `MemoryManager` + 自定义只读 `MemoryStore`，每轮临时注入 + `search_memory` | 按轮召回相关记忆，不动缓存的 system prompt | M | SDK 记忆没有生命周期 / 来源；**自动抽取写入未验证事实** | **不替换**；可选：只读 store 试点、不开自动抽取 |
| **KB**（`kb/vector_store.py`、`embeddings.py`、`kb/search.py`） | SQLite / pgvector / S3 向量 + 混合重排 | `BedrockKnowledgeBaseStore`、S3 Vectors / BM25 策略 | 云 profile 的托管摄取 | M–L | 失去混合重排和本地 profile；store 默认用默认凭证链（违反凭证铁律，需注入 `get_bedrock_session()` 的 client） | **不做**（以后可选：把 `hybrid_search` 包成只读 store） |
| **Skills**（`skills/loader.py`、`tools.py`） | 三层渐进披露、草稿 / 来源 / 策展、安全闸门、动态注册工具 | `AgentSkills` 插件（agentskills.io 规范，**每次调用前刷新 XML**） | 规范一致 | M | 没有草稿 / 策展 / 按 frontmatter 注册工具；每次刷新与我们冻结的缓存快照冲突 | **不替换**；用 Evals 的技能评估器衡量 |
| **Harness Optimizer** | 手调提示词 | Formula / Trainer 循环 | 自动调提示词 | M | 13 例会过拟合；真实回放每例 ~$1+；会改写提示词，与 L0 评审和云中立规则冲突 | **以后**（先有 ≥ 50 个可离线回放的用例） |
| **`create_harness()` 整体** | — | 整个 harness | — | — | shell / 文件默认、`./.agent` 目录 | **不做** |

## 4. 与 Harness Engineering 计划（`docs/superpowers/plans/2026-09-09-harness-engineering-architecture-update.md`）的对应

- **阶段 0（提示词 L0–L4、hooks、结构化输出、eval v0）—— 采用**：L0 措辞参考 `HARNESS_CONTRACT`；按轮块（拓扑、事件记忆、
  `chat/context_block.py`）用 `ContextInjector` 临时注入，system prompt 字节稳定；RCA 结论用 `structured_output_model`；eval v0 用
  Strands Evals。**计划第 95 行的 hook 名写错了**：`BeforeToolInvocation` / `AfterToolInvocation` 应为 `BeforeToolCallEvent` /
  `AfterToolCallEvent`；做类型化拒绝时 interventions 比裸 hook 更合适。
- **阶段 1（Trust Kernel）—— 试点**：工具边界的 deny-only 干预 / middleware + `cancel_signal` + `limits`；不变量本身仍在代码和 DB 里。
- **阶段 2（Investigation Runtime）—— 0/1 之后试点**：EvidenceRecord 由 `AfterToolCallEvent` hook 或 steering `LedgerProvider` 产生；
  每次运行 `limits.total_tokens`；planner / evaluator 用 `aux_model`；检查点用 snapshot。
- **阶段 3（Skills 能力包）—— 保留自研**：用 Evals 技能评估器衡量；Optimizer 的 skill Formula 尚未发布。
- **阶段 4（结果加权记忆）—— 自研**：SDK 记忆没有结果加权；以后可通过自定义 `MemoryStore` 暴露检索。

## 5. 升级路径（建议顺序）

1. **准备**：新分支；重新生成 `requirements.txt`；写一个**真实 Bedrock 冒烟脚本**（单元测试几乎都 mock 了 `Agent` / `BedrockModel`，
   只有 `tests/test_executor_hitl.py` 真 import strands）。对每个 agent、每个模型家族（Opus 5、Fable 5.1、Sonnet 4.6 自适应 thinking；
   Haiku 4.5 `budget_tokens`；gpt-oss / gpt-5.6 `reasoning_effort`）检查：第二次调用 `cacheReadInputTokens > 0`；thinking 请求被接受；
   流式事件键 `data` / `current_tool_use` / `toolResult` / `result` / `tool_stream` 都在（`web/app.py:4580–4640`）；`limits={"turns": N}`
   的停止原因符合预期；`activate_skill` 动态注册正常且 `agent` 参数被注入。
2. **1.45 → 1.64，保持行为**：`context_manager=False` + `plugins=[ContextOffloader(storage=InMemoryStorage(), max_result_tokens=1500,
   preview_tokens=750)]`；`CacheConfig(strategy="auto", tools_ttl=True)`；加强 `test_strands_context_manager.py`，并把
   「ignoring co-provided conversation_manager」warning 当错误。全量测试（临时 DB）→ chaos-lab 真实运行（13 例定位评测或子集），
   与 2.6.1 的准确率和成本对比 → 主人验收后再推送。
3. **重调上下文**：主 chat 与 RCA 上 A/B「保持行为」vs「auto / presets」；盯缓存命中率和「retrying with drop_block」日志。
4. **Evals 试点**（可与 2 并行，独立 venv）：把 `location_eval.py` 包成基于录制工具输出的确定性评估器；再加 chat / IM 的红队用例。
5. **阶段 0 零件**：RCA 结构化输出（flag）、`ContextInjector`、OTEL（flag）、critic 改成 `Agent`。
6. **阶段 1 零件**：deny-only 干预；`cancel_signal` 代替 RCA 线程看门狗。
7. **以后**：IM 用 `SnapshotSessionManager`；`ModelRouter` 回退；有 ≥ 50 个可回放用例后再试 Harness Optimizer。

## 6. 需要主人决定

1. ~~是否按 §5 先做「1.45 → 1.64 保持行为升级」~~ —— **主人 2026-11-06 已定：先做**（Plan Mode 起步）。
2. Strands Evals 试点是否与升级并行？用哪批用例（现有 13 例 + 录制的工具输出）？
3. Harness 计划阶段 0 的哪些零件先做（结构化 RCA、ContextInjector、OTEL、critic 记账）？
4. 是否接受 rich 升到 15（Evals 依赖），还是 Evals 一直放独立 venv？

## 7. 未确认项

Bedrock 上 Claude 4.6 / 5 的真实上下文窗口（决定 auto 摘要是否会触发）；「85% 时摘要」在开启 thinking 的 RCA 上的表现，以及我们
从 DB 重建的历史（纯文本、合成工具对）在新账户上是否触发 thinking 绑定错误；手写子 agent 的 OTEL span 是否嵌套在主 trace 下；
rich 15 与 CLI 是否兼容；是否有路径会发送空 prompt（1.63 起被拒）；所有基准数字都是厂商自测，harness 的美元数字是按 token 估算，
且没有运维 / SRE 类基准。
