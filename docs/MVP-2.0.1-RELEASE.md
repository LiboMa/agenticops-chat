# MVP-2.0.1 Release Notes

> Version: 2.0.1 · Branch: `MVP-2.0.1` · Started: 2026-07-03 · Completed: 2026-07-04

一次以**前端体验重做**为主、外加**后端 SDK 现代化**的迭代版本。在 2.0.0「治理型自治」的骨架上，把日常最高频的 Chat / Dashboard / 导航三处交互全部翻新，并把 agent 运行时升级到 Strands 1.45、启用 SDK 原生的上下文治理与可选人审门。

| 子项 | 一句话 | 日期 |
|------|--------|------|
| **A** Chat Composer 2.0 | 每会话模型切换 pill；移除 detail-level 旋钮（全链路） | 2026-07-04 |
| **B** Rich Chat 切片 1 | 建议 chips（模型生成、点击即发）；I# 问题原地定位面板 | 2026-07-04 |
| **C** Nav Sidebar 2.0 | 可展开/收起侧栏；拖拽排序（自愈序）；hover 实时预览卡 | 2026-07-04 |
| **D** Dashboard 2.0 | 运维优先的 5 区实时统计页（10s 轮询）；Cost/Token 合并一行 | 2026-07-04 |
| **E** Strands 1.45 增强 | `context_manager="auto"`（省 token + 大结果 offload）；executor 可选 HITL 安全网 | 2026-07-04 |

---

## Sub-project A — Chat Composer 2.0 (2026-07-04)

### Per-session model switch

- New composer bottom-left **model pill** (replaces the detail-level select): shows `Auto · <global model>` or the session's chosen model; click opens a Radix Popover listing **Auto (follow global)** + all model presets with the full model id as a mono sub-line.
- **Per-session persistence**: `chat_sessions.model_id` nullable column (NULL = Auto). Set via existing `PATCH /api/chat/sessions/{id}` with a `""`-sentinel for Auto; omitted field = don't change.
- **Validation**: PATCH accepts only ids from the cached model presets ∪ `MODEL_ALIASES` values (400 otherwise). While the session is streaming, model PATCH returns **409** (new `_streaming_sessions` in-flight registry); the pill is also disabled client-side during streaming.
- On change, **only this session's** cached agent is evicted (`session_manager.remove`) — context/history preserved, agent rebuilds with the new model on the next message. Sub-agents are unaffected (Settings per-agent config remains their mechanism).
- **Cost attribution** now uses the session's effective model (override or global) in both the assistant-persist block and `log_agent_call` — per-token pricing stays correct for switched sessions.

### Detail-level removal (full chain)

- The concise/medium/detailed knob is **gone end-to-end**: composer select, `ChatMessageCreate.detail_level`, `set_detail_level`/`get_detail_level`/`VALID_DETAIL_LEVELS` ContextVar machinery in config.py, `agent_output_detail` setting, CLI `/detail` command + `--detail/-d` flag, session save/restore field.
- Output rules are fixed to the former **medium** template (`preamble.OUTPUT_RULES` single constant + RCA/SRE addenda); `get_output_rules(agent_type)` keeps its signature so all 7 agents' call sites are untouched.

### Docs / specs

- Design spec: `docs/superpowers/specs/2026-07-03-chat-composer-model-switch-design.md`
- Visual mockup: `docs/superpowers/specs/2026-07-04-chat-composer-model-selector-mockup.md`
- Plan: `docs/superpowers/plans/2026-07-04-chat-composer-model-switch.md`

## Sub-project B — Rich Chat 切片 1：建议 Chips + 问题原地定位 (2026-07-04)

### 建议 Chips（模型生成，点击即发）

- 主 agent 在回复末尾输出一个结构化 `<<SUGGEST>>[...]` 标记块（`main_agent` 提示词新增规则）；有反问时 chips = 反问的答案选项，无反问时 = 建议的下一步动作。
- **零额外 LLM 调用**：走提示词标记 + `done` SSE 事件携带（方案 A）——否决了「Haiku 后置生成」方案（多一次调用 + 1–2s 延迟，违背简约经济铁律）。
- `extract_suggestions` 标记解析器把 chips 从流中剥离并持久化；CLI 流式与 IM 出口统一 `strip <<SUGGEST>>` 标记，终端/机器人侧不泄漏原始标记。
- 前端：chips 只挂**最后一条** assistant 消息，流式中隐藏，点击**直接发送**作为下一轮输入。

### I# 问题原地定位

- 聊天里扫描出的问题引用 `I#N` 点击后**在右侧面板原地打开**（复用现有 `ContextPanel`，不离开聊天上下文）；`R#`（报告）保持跳转行为。
- 面板内可「让 agent 直接检查该问题」，形成 定位 → 检查 的闭环。

### Docs / specs

- Design spec: `docs/superpowers/specs/2026-07-04-rich-chat-quick-actions-design.md`
- Plan: `docs/superpowers/plans/`（rich chat slice 1，7 tasks，TDD）
- 注：B 的其余部分（图表、图片渲染）另行 spec。

## Sub-project C — Nav Sidebar 2.0：可展开 + 拖拽排序 + hover 预览 (2026-07-04)

### 可展开/收起侧栏

- `IconSidebar` 从固定 52px 纯图标，升级为**可切换**：收起 52px（默认，熟手省空间）↔ 展开 200px 图标 + 文字（新手要文字）；底部折叠按钮切换。
- `AppShell` 接管 nav-expanded 状态，内容区左内边距随之联动（52↔200px，带 transition），不再硬编码。

### 拖拽排序（自愈序）

- 7 个导航项支持 **原生 HTML5 DnD** 拖拽重排（不引入 dnd-kit——项目「不加依赖」铁律；ChatInput 已有同款原生 DnD 先例）。
- 顺序持久化到 `localStorage`（`aiops-nav-order`，跨标签页同步）；**自愈**纯函数处理新增/删除项，坏序自动修正。

### hover 实时预览卡

- tooltip 升级为小卡片：页面名 + 一行**实时摘要**（Issues → "53 open · 14 critical"；Chat → "N sessions"；Schedules → 下次执行时间）。
- 数据全部来自已有 `useStats`/`useChatSessions` 缓存，**零新后端**。

### Docs / specs

- Design spec: `docs/superpowers/specs/2026-07-04-nav-sidebar-design.md`
- Plan: `docs/superpowers/plans/`（nav sidebar 2.0，4 tasks）

## Sub-project D — Dashboard 2.0：运维优先的实时统计页 (2026-07-04)

### 5 区实时布局（运维优先）

Dashboard 即统计页（AgentMetrics 页不动）。v2 布局按用户验收反馈定为运维统计为主：

- **ServiceStatusBar** — DB/AWS/Disk 健康点 + Executor 开关状态 + 版本号
- **KPI 行** — Resources / Open Issues / Critical / Accounts
- **Fix Plans**（恢复）+ **Cost/Token 合并为一行**（不再各占一块）
- **InteractionStats** — 交互统计
- **AgentActivityFeed** — 最近 10 条 agent 日志，一行一条，点击跳 AgentMetrics trace 详情

### 统一 10s 轮询

- 四个数据源统一 `refetchInterval: 10_000`；`useHealth` 10s 轮询 hook；页面不可见时自动暂停。
- **不做 SSE**（YAGNI）；`agentShare` 为纯函数便于测试。
- 修复：cost hooks 的 `/api` 双前缀导致 cost dashboard 404。

### Docs / specs

- Design spec: `docs/superpowers/specs/2026-07-04-dashboard-2.0-*.md`（含 self-review 修订）
- Plan: `docs/superpowers/plans/`（dashboard 2.0，4 tasks + E2E）

## Sub-project E — Strands 1.45 升级 + 上下文治理 + 可选 HITL (2026-07-04)

agent 运行时的 SDK 现代化。7 项候选增强经评估收紧为 **4 做 3 缓**（符合「不加没用功能」铁律）。

### context_manager="auto"（省 token + 大结果 offload）

- 全部 **8 处 Agent 构造**（main / scan / detect×2 / rca / sre / executor / reporter）启用 `context_manager="auto"`：SDK 自动组合 `SummarizingConversationManager` + `ContextOffloader`。
- **与现有 per-agent `conversation_manager` 共存**：SDK 保留我们的窗口策略（Null 全上下文 / SlidingWindow），只额外挂 ContextOffloader——per-agent 窗口不变。
- 效果实证：大 inventory / 全量 scan 结果被自动 offload + 截断预览，agent 需要精度时自调 `retrieve_offloaded_content` 取回全量（冒烟中准确答出「24 open issues」）。直击 executor 的「tool_result too large」老痛点。
- config 开关 `strands_context_manager_auto`（默认 True），一键回退。

### executor 可选 HITL 安全网

- config `executor_hitl_enabled`（**默认 False**，先安全上线）+ `get_executor_interventions()` helper：关 → `[]`（行为完全不变），开 → 一个 `HumanInTheLoop`（allow-list 11 个只读/校验工具放行，mutating 工具触发 interrupt）。
- **并行第二道 SDK 级审批门**，不拆旧逻辑：现有 `get_approved_fix_plan` gate + 9 态 DB 状态机 + L0/L1 分级仍是主门。

### 升级本身

- `strands-agents` 1.26 → **1.45**（`sdk-python` 在 v1.42 收敛为 `harness-sdk` 单仓，pip 包名不变，纯升级非迁移）。1.27→1.45 唯一 breaking 是 MistralAI 2.x（本项目只用 Bedrock，零影响）。
- 缓做（无当前收益，留待真实触发点）：`structured_output`（RCA 真遇解析失败时）、OTLP 可观测性（接了 tracing 后端时）、Evals 回归测试（发现 agent 路由退化时）。

### 验证

- 全量 pytest **3539 passed / 66 skipped / 3 failed**（3 failed 全为 pre-existing、与本次无关，零新增回归）。
- 真实 Bedrock 冒烟：offloader 生效、HITL 关/开两态构造均正常。

### Docs / specs

- Design spec: `docs/superpowers/specs/2026-07-04-strands-1.45-upgrade-design.md`
- Plan: `docs/superpowers/plans/2026-07-04-strands-1.45-upgrade.md`
- 调研报告（HTML 演示）: `docs/strands-sdk-2026-enhancement-report.html`

### 新增 config 开关一览

| 开关 | 默认 | 作用 |
|------|------|------|
| `strands_context_manager_auto` | `true` | 全 agent 启用 SDK 自动上下文治理 + ContextOffloader |
| `executor_hitl_enabled` | `false` | executor 叠加一层 Strands HumanInTheLoop 审批门（主门仍是现有 gate） |

---

## Sub-project F — Galaxy 全景资源关系图（LLM 混合构图，Experimental）(2026-07-08)

`/galaxy` — 把整个多账号资源清单渲染成一张可交互的**星云图**，同时是未来"一键托管自主运营"模式的世界模型基础。核心是一套**三层混合构图 + 产线级信任模型**。

### 三层混合构图（机械关系=代码，语义关系=LLM）

- **L1 代码规则**（`rules.py`，零幻觉）：从 `raw_data` 确定性推导包含边、ID 引用边、安全组边、标签归组边，全部 `provenance=rule`。
- **L2 全局索引**（代码生成）：每资源一行 ~40 tok 摘要，作为只读上下文注入每个 L3 批次，解决分批盲区。
- **L3 LLM 语义增强**（`builder.py`，Haiku temp=0）：仅对脏批次推断语义边（如 `inferred_group`），每批 ≤`galaxy_batch_size`。

### 产线级信任模型（不容纰漏）

- **fail-closed 机器质检**：LLM 边两端必须在库存中（无法发明资源）+ evidence 必须能在**任一端点** `raw_data/tags` 回验 + 置信度闸；未过则丢弃并计数，丢弃率超 `galaxy_drop_rate_alert` 记 WARNING。
- **provenance 分级**：`rule` 边=事实骨架（可作未来执行依据）；`llm` 边=仅辅助、前端虚线、**永不驱动执行**。
- 真实实测：1287 资源全量构建 5m11s / $1.27，175 条 LLM 边过验、361 条被 fail-closed 丢弃。

### 内容哈希增量（成本可控）

- 每小时定时任务先做内容哈希 diff（剥离易变字段）：无变化→<1s 退出、$0、不调 LLM；仅对变化资源重跑 L3，未变资源沿用上次 LLM 边。稳态 ~$1-3/月（对比纯 LLM 每小时全量 $1,100+/月）。
- build 历史剪枝到 `galaxy_builds_keep`（默认 24）以约束 DB 增长（每行存完整 rule+llm 图 blob）。

### 前端 — Canvas 星云（固定 Nebula Violet 主题）

- d3-force 力导向一次铺开全清单（~1300 节点）；warning/critical 脉冲、rule 边实线 / llm 边虚线；滚轮缩放、拖拽平移、双击星团聚焦、悬停高亮邻居。
- **交互分工（house rule）**：细节→右侧滑动面板，临时数据→Dialog。
  - 单击节点 → **右侧关键信息面板**（状态 + open issues 带 `IssueStatusBadge`）。
  - 点 issue → **居中 Dialog**（RCA/指标，ESC 关闭继续看下一个）。
  - 点「查看原始数据」→ **第二层右侧面板**：可折叠、可搜索的 `JsonTree` 渲染深层嵌套 `raw_data`（解决固定宽度显示不全）。
- 依赖：移除 `@xyflow/react` + `@dagrejs/dagre`，改用细粒度 d3 子包（Galaxy bundle 221KB→79KB）。

### Docs / specs

- Design spec: `docs/superpowers/specs/2026-07-05-galaxy-resource-graph-design.md`
- Plan: `docs/superpowers/plans/2026-07-06-galaxy-resource-graph.md`
- Workflow: `docs/WORKFLOW.md` → "Galaxy — Resource Relationship Graph" 段

### 新增 config 开关一览

| 开关 | 默认 | 作用 |
|------|------|------|
| `galaxy_enabled` | `true` | 启用 Galaxy 构图管线 + `/api/galaxy` + 每小时/扫描后触发 |
| `galaxy_build_interval_minutes` | `60` | 自动构建 cadence |
| `galaxy_model_id` | `""` | LLM 增强模型覆盖（空=`bedrock_model_id_cheap`） |
| `galaxy_batch_size` | `40` | 每个 LLM 批次最大资源数 |
| `galaxy_confidence_min` | `0.5` | LLM 边保留的最低置信度 |
| `galaxy_drop_rate_alert` | `0.05` | 丢弃率超此值记 WARNING（漂移烟雾探测） |
| `galaxy_expand_node_cap` | `200` | `/expand` 单次返回节点上限 |
| `galaxy_builds_keep` | `24` | 保留最近 N 条 build（旧的剪枝） |

---

## 修复 — Agent Memory 并发原子写 (2026-07-09)

- 多 agent 并行构建时都会 `touch_last_used` 同一 `shared/` memory（reactivate-on-use），`_atomic_write_text` 旧的**固定 tmp 名** `.{name}.tmp` 导致并发写互相覆盖 → `os.replace` 命中已消失的 tmp → `FileNotFoundError`（被 DEBUG 吞掉，但刷屏 + 偶尔 `last_used` 丢更新）。
- 修复：tmp 名按 `(pid, thread, 单调计数器)` 唯一化；`os.replace` 仍原子（last-writer-wins）；失败清理 tmp。回归测试 12 线程×25 touch 同一文件 + E2E 7 agent×15 并发 load 全绿。
