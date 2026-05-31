# ② 记忆系统质变 — 设计文档 (Memory System Qualitative Upgrade)

- **日期**: 2026-05-31
- **周期**: ② of 3（①核心审查加固 ✅ → **②记忆系统质变** → ③Skills自主化）
- **目标分支**: 待创建（建议 `cycle2-memory-quantum`，从 main 开)
- **范围**: 把文件制 Agent 记忆升级为 Hermes 式 **self-optimizing** 记忆系统（永续 + 增强 + 自主优化）；冻结/移除已死的 DB 跨会话记忆层
- **不含**: Skills 自主化（→③）；情景语义召回 Tier 2 的实现（推迟，仅保留 seam）

---

## 1. 背景与目标

用户诉求（2026-05-29）：「对所有 Agents 的记忆功能、永续记忆(persistent)、增强记忆(enhanced)、自主优化记忆(self-optimizing) 做一个质的升级和全面的优化，就如 Hermes 一样。」

经三方并行审查（文件制记忆 / DB 记忆 / 用户意图）+ S3 Vectors 架构研究，确认现状与方向。本文档只包含**已验证**的现状与**已拍板**的决策。

### 1.1 现状（审查确认）
- **A. 文件制 Agent 记忆**（`memory/agent_memory.py` + `agent-memory/*.md`）：行为约束层，per-agent + shared，YAML frontmatter，confidence 1-5，构建时注入 top-10。**核心问题：write-once-read-forever** —— 无合并、无去重、无 size cap、confidence 永不变、无 staleness/归档自动化。23 文件已现碎片化（`sre_query.md` ×4 目录、`cpu_spike.md` + `auto_cpu_spike.md` 近重复）。
- **B. DB 跨会话记忆**（`web/memory_service.py` + `AgentMemory`/`AgentMemoryFact`）：**已死代码** —— `session_manager.py:516` 用空 query 调 `build_memory_context`，`memory_service.py` `if initial_context:` 门控 → 向量搜索**从未被调用**，语义召回贡献 = 0。另有全局 scope 泄漏、O(N) 全表内存扫描等 bug。

### 1.2 验收成功标准（可量化）
1. 文件制记忆成为唯一核心，具备完整生命周期（size-cap 合并 + stale→archive + reactivate-on-use），不再 write-once-read-forever。
2. Agent 可经 `memory_manage` 工具自主 create/patch/merge 记忆，带 `created_by` provenance，人工可审。
3. 死的 DB 语义路径冻结/移除：停止 `build_memory_context` 注入、删除 O(N) `search_experiences` 扫描。
4. 每 agent 注入记忆封顶（cap=15），token 可控；全程 `py_compile` + 现有 pytest 全绿 + 新增回归测试每项配套。
5. 严守用户铁律：文件制（非 DB）、保持简约、不加没用的功能、先测完再提交。

---

## 2. 架构决策（已拍板）

| # | 决策 | 理由 |
|---|------|------|
| D1 | **文件制 = 唯一核心；DB 层冻结/移除** | 用户「搞到DB岂不是很土」；DB 语义层从未生效，贡献为 0 |
| D2 | **Hermes 式 Curator 自优化** | size-cap 倒逼写入时合并 + 后台 stale→archive，近零 LLM，符合简约 |
| D3 | **Agent 自主 create/patch，带 provenance** | 真正的 self-optimizing；`created_by: agent` 标记，人工可审 |
| D4 | **Tier 1 文件（无向量）/ Tier 2 情景召回推迟** | 行为记忆全量注入，向量召回对它无意义且有静默漏触发风险 |
| D5 | **阈值 cap=15/agent, stale=30天, archive=+60天**（settings.yaml 可调） | Hermes 同量级；~15 条 ≈ 5-7K token；低频写入场景合适 |
| D6 | **scope = per-agent + shared** | 已验证可用；L3 跨 agent 传播经 shared/ 实现 |
| D7 | **Frozen-snapshot 注入纪律** | 会话开始加载一次、本会话不变、写入下会话生效；保护 Bedrock prompt-cache 命中率 |
| D8 | **S3 Vectors = 未来云端冷层 flag，现在不建** | GA 但中国区未验证、现实现是 O(n) 非原生 API；情景召回无消费者（YAGNI） |

---

## 3. 数据模型（Tier 1 文件制，增强版）

### 3.1 目录布局（保持现状 + 新增 .archive/）
```
agent-memory/
  <agent>/                 # detect/ rca/ sre/ executor/ reporter/ scan/
    MEMORY.md              # 索引（仅列 active）
    <slug>.md              # 单条 active 记忆
    .archive/              # 【新增】归档记忆（不注入、不检索，可恢复）
      <slug>.md
  shared/                  # 跨 agent 共享（同结构）
    .archive/
```

### 3.2 Frontmatter schema（扩展现有字段）
```yaml
agent: detect              # 归属 agent（或 shared）
type: feedback|pattern|preference|baseline|umbrella   # 【新增 umbrella】合并产物
status: active|stale|archived                          # 【扩展】新增 stale 中间态
confidence: 1-5
source: user|chat|auto|agent                           # 【新增 agent】自主写入
created_by: user|agent                                 # 【新增】provenance
created_at: YYYY-MM-DD
last_confirmed: YYYY-MM-DD
last_used: YYYY-MM-DD                                   # 【新增】Curator 用于 staleness
absorbed_into: <slug>|""                               # 【新增】归档去向（合并/纯剪枝）
absorbed_from: [<slug>, ...]                            # 【新增】umbrella 记录其来源
resource_pattern: <regex>
related_issue_id: <int>
```
- **向后兼容**：旧文件缺新字段时，`last_used` 默认取 `last_confirmed`/`created_at`，`created_by` 默认 `user`，`status` 缺省 `active`。一次性 backfill 迁移补齐。

---

## 4. 核心机制（Hermes 式 Curator）

### 4.1 机制一：硬 size-cap → 写入时自我合并
- 每 agent 目录 active 记忆上限 `memory_max_active`（默认 **15**，settings.yaml）。
- 写入第 16 条时：**不静默截断**，`save_memory_file` 返回结构化错误给调用方（agent）：当前满，附 active 清单，提示先 merge 腾空间。
- Agent 用 `memory_manage(action="merge", ...)` 把相关窄记忆合并成 umbrella（`type: umbrella`，记 `absorbed_from`），源记忆移 `.archive/` 标 `absorbed_into`。腾空后新记忆写入。
- **唯一可能的 LLM 成本点**，且由正在工作的 agent 顺手完成（摊销，非独立后台扫描）。

### 4.2 机制二：Curator 后台生命周期（纯文件元数据，零 LLM）
状态机：`active --(stale_days 没用)--> stale --(archive_days 又没用)--> archived`
- **active**：注入提示词 + 参与检索。
- **stale**（默认 `last_used` > 30 天）：**不注入**但保留、仍可被检索命中。
- **archived**（stale 后再 > 60 天）：移 `.archive/`，不注入不检索，可 `restore`。
- **三铁律**（抄 Hermes）：①永不删除只归档（可恢复）；②**reactivate-on-use**：被检索/注入命中 → `last_used=today` → 拉回 active；③归档必声明 `absorbed_into`（合并去向）或 `""`（纯剪枝）。
- **触发点**：每次 agent 构建时顺带跑一次轻量扫描（比日期、改 status），或独立周期任务。**禁止递归工具**（遵 `feedback_no_recursive_tools`）。

### 4.3 confidence 演化
- `last_confirmed` 启用：同一记忆被再次确认 → `last_confirmed=today`；被用户标 false-positive 矛盾 → confidence -1（下限 1）。
- 注入排序：confidence 降序 + 同分按 `last_used` 新→旧。

---

## 5. Agent 自主写入（`memory_manage` 工具）

参照 Hermes `skill_manage`，新增一个 agent-facing 工具（替代/增强现有 `record_agent_feedback`）：

| action | 语义 | provenance |
|--------|------|-----------|
| `add` | 新增一条记忆（含 size-cap 检查） | `created_by=agent`, `source=agent` |
| `patch` | 增量改某条记忆 body（token-cheap，优先） | 更新 `last_confirmed` |
| `merge` | 多条窄记忆 → 1 条 umbrella | 源归档标 `absorbed_into` |
| `remove` | 归档（非删除） | 标 `absorbed_into=""` |
| `search` | 跨 agent 检索（保留现有 `search_agent_memory`） | reactivate-on-use |

- **Prompt 引导**：agent 在「完成复杂任务（≥5 工具调用）成功 / 被用户纠正 / 发现可复用工作流」时被提示考虑 `add`；优先 `patch` 而非整篇重写。
- **人工可审**：`created_by=agent` 的记忆在 WebUI 可筛选、审阅、降级、归档。
- **安全**：bundled/手写记忆（`created_by=user`）不被自动化生命周期归档（pinned 概念）。

---

## 6. 注入纪律（Frozen-snapshot，D7）

- 记忆在 **agent 构建时加载一次并快照**，本会话/任务期间不变（即使 agent 中途 `memory_manage` 写入）。
- 写入**立即落盘**（下次会话生效），但**不**热patch当前 system prompt。
- 理由：保护 `bedrock_cache_enabled` 的 prompt-cache 命中率（中途改 prompt 前缀会使缓存失效、增加成本）。
- 这是对现有「hot-reload」设计的**有意收敛**（原设计会破坏缓存）。

---

## 7. DB 层冻结/移除（D1）

- **停止注入**：`session_manager.py` `get_or_create` 中删除 `MemoryService().build_memory_context` 调用（注入的是空/已冻结内容）。
- **删除死扫描**：移除 `memory_service.py` 的 O(N) `search_experiences`（从未被有效调用）。
- **模型处置**：`AgentMemory`/`AgentMemoryFact` 模型与 `/api/memory/*` 端点（cycle① 已抽到 `routers/memory.py`）—— 保留模型定义与表（避免破坏性迁移），但在模型 docstring + 端点 docstring 标注 `DEPRECATED (frozen cycle②)`。端点**保持现有只读行为**（GET facts/experiences 仍查表返回已有数据，不再有新数据写入因为提取被停）；**不**新增删除/截断逻辑。遵「不碰无关代码」「不加没用的功能」。
- **保留 `kb/vector_store.py` seam**：KB case search（`search_similar_cases`/`search_sops`）仍用它，不动。

---

## 8. 存储分层（D4 + D8，前瞻但不实现）

```
Tier 1 行为记忆【本周期实现】  → git markdown，无向量无DB，全量注入，Curator 管理
Tier 2 情景召回【推迟，仅保留 seam】
  · local / cloud单节点 → SQLiteVectorStore（已实现）
  · cloud 多副本        → S3 Vectors（未来 flag，需重写为原生 QueryVectors API）
  · 中国区              → fallback sqlite/pgvector（S3 Vectors 中国区未验证）
```
- **本周期不写 Tier 2 代码**。仅在设计文档记录 profile→backend 映射，留作未来。
- **铁律**：任何向量库永不触碰 Tier 1。

---

## 9. 已确认的 Bug 修复（顺带，来自审查）

| Bug | 位置 | 修复 |
|-----|------|------|
| 非原子写入 | `agent_memory.py:223` | temp + `os.replace`（复用 cycle① `_atomic_write_text` 模式） |
| slug 文件名碰撞静默覆盖 | `app.py`/`helpers.py`/`memory_tools.py` | 写入前查重；碰撞则 suffix 或 merge 提示 |
| MEMORY.md 索引漂移 | `agent_memory.py:249` | 索引含文件 hash；不匹配则重建 |
| frontmatter 解析静默失败 | `agent_memory.py:45-63` | 校验 + error 级日志（非 warning） |
| substring 搜索假阳性 | `memory_tools.py` | 词边界匹配 + 可选 confidence 阈值 |
| confidence 永不更新 | `agent_memory.py` | §4.3 演化逻辑 |

---

## 10. 配置（settings.yaml，遵「config.py 不硬编码」）

```yaml
memory_max_active: 15          # 每 agent active 记忆上限（size-cap）
memory_stale_days: 30          # 多久没用 → stale（不注入）
memory_archive_days: 60        # stale 后多久 → archived（移 .archive/）
memory_autonomous_write: true  # 是否允许 agent 自主 memory_manage add/patch
memory_curator_enabled: true   # Curator 后台生命周期开关
```

---

## 11. 执行阶段总览（待 writing-plans 细化）

| 阶段 | 内容 | 验收 |
|------|------|------|
| P0 | 新分支 + frontmatter schema 扩展 + 向后兼容 backfill 迁移 | 旧文件正常加载 |
| P1 | Curator 生命周期（stale/archive/reactivate，纯文件） | 时间推进单测（mock 日期） |
| P2 | size-cap + `memory_manage` merge（写满触发合并） | 满→拒绝→合并→腾空 单测 |
| P3 | `memory_manage` 工具（add/patch/remove/search）+ provenance | agent 自主写入 e2e 测试 |
| P4 | Frozen-snapshot 注入 + confidence 演化 | 缓存命中不破坏 / confidence 升降单测 |
| P5 | DB 层冻结（停注入、删死扫描、标 deprecated） | 现有测试全绿、无回归 |
| P6 | 顺带 bug 修复（§9）+ WebUI 记忆审阅（created_by=agent 筛选） | 每项配回归测试 |

每阶段先测完再提交；每修配最小回归测试。

---

## 12. 风险与缓解

| 风险 | 缓解 |
|------|------|
| Curator 误归档有用记忆 | reactivate-on-use + 永不删除（可 restore）+ `created_by=user` 不自动归档 |
| Agent 自主写入产生垃圾记忆 | size-cap 倒逼合并 + provenance 可审 + confidence 演化淘汰 |
| frozen-snapshot 让反馈"慢一会话生效" | 文档明确；紧急场景可手动重建 agent（重新快照） |
| 移除 DB 注入破坏现有行为 | DB 注入本就是空/死路径，移除是净化；保留模型不删表 |
| 向后兼容（旧 frontmatter 缺字段） | backfill 迁移 + 加载时默认值兜底 |
| 中途触及 cycle③ Skills | 本周期只动记忆；`memory_manage` 不碰 `skill_manage`（③再做） |

---

## 13. 明确不做（YAGNI）

- Tier 2 情景语义召回的**实现**（无消费者；仅留 seam + 文档）
- S3 Vectors 管线 / vector-bucket IaC / 原生 API 重写（未来 flag）
- 删除 `AgentMemory`/`AgentMemoryFact` 表（破坏性迁移，仅标 deprecated）
- per-account/环境 scope 维度（保持 per-agent + shared）
- 记忆热重载（被 frozen-snapshot 有意取代）
- Skills 自主化（→ cycle ③）
