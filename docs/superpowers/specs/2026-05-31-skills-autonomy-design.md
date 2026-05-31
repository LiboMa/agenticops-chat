# ③ Skills 自主化 — 设计文档 (Skills Autonomy Upgrade)

- **日期**: 2026-05-31
- **周期**: ③ of 3（①核心审查加固 ✅ → ②记忆系统质变 ✅ → **③Skills自主化**）
- **分支**: `cycle3-skills-autonomy`（已创建）
- **范围**: 把 Skills 系统升级为 Hermes 式自主管理（agent 自主创建/改进 + Curator 生命周期 + provenance + 多代本备份），**镜像已验证的 cycle② 记忆模式**
- **不含**: 重建已有的进度披露/draft-publish/LLM生成/安全分级（这些已工作，只增强）

---

## 1. 背景与目标

用户诉求（RAW-Idea）：「在管理以及创建 Skills 层面，要做得更加的灵活和自主，就如 Hermes 一样」+「如果 SRE 或其它 Agent 发现自己的工具不能匹配...可以交由 Main Agents 自主研发，或更新迭代 Skills，采用 Self-improving 的方式」。

经三方并行审查（核心 loader/tools/security + 自改进 evolution/review/improvement + 用户意图）确认现状与方向。**核心策略：镜像 cycle② 已验证的记忆架构**（`skill_manage`≈`memory_manage`、Curator stale→archive、provenance、frozen-snapshot），但处理 skills 的三个特有差异。

### 1.1 现状（审查确认）
**已有且良好（保留，不重建）**：
- **3 层进度披露**（比记忆更好）：system-prompt XML（~100 tok/skill）→ `activate_skill`（全文）→ `read_skill_reference`（深入）。
- **draft→publish 管线**：`create_draft_skill`/`create_published_skill`/`promote_skill`/`reject_draft_skill`。
- **LLM 生成**：`generate_skill_from_description`；**post-resolution gap 分析**：`skill_improvement_service`（已调 `add_improvement` + `auto_improve_skill`）。
- **3 层安全分级**：readonly/write/blocked 门控 `run_on_host`/`run_kubectl`。
- **原子写 + YAML 安全**（cycle① 已修）；15 published + draft/。

**关键缺口（审查发现）**：
- **无 Curator 生命周期**：skills 静态、无 staleness/archive、无 usage 追踪、draft 无限堆积。
- **无 provenance**：skill frontmatter 零 `created_by`（记忆有）。
- **无统一 `skill_manage` 工具**：`create_skill`/`improve_skill` 散乱、只生 draft。
- **有损 rollback**：`promote_skill` 单一 `.bak`（promote v2→v3→v4 丢 v2）。
- **改进闭环断裂**：`improve_skill` 工具**未接** `improvement_store`（service 路径接了，工具路径没接）；改进只生 draft 从不自动生效。
- **token bloat**：全部 15 skills XML 注入**每个** agent（含从不用的 reporter）≈ 1700 tok/agent。
- **LLM 输出校验弱**：`generate_skill_from_description` 只查 3 个 key 存在。

### 1.2 验收成功标准（可量化）
1. Agent 可经统一 `skill_manage` 工具自主 create/improve/merge/deprecate/restore/search，全部带 `created_by=agent` provenance。
2. Agent 自主写入只落 **draft**；提升到 published 需**安全扫描通过**（无危险 run_on_host）+ 可选人工确认。
3. Curator 只对 `created_by=agent` 的陈旧 draft 归档（never-delete，移 `skills/.archive/`）；**人写的 published skill 是 pinned，永不自动动**。
4. `promote_skill` 改为多代本可恢复备份（取代有损单 `.bak`）。
5. `improve_skill` 工具接线 `improvement_store`（genealogy/审计）；改进生 draft + 通知人工。
6. 全程 `py_compile` + 现有 pytest 全绿 + 每项配回归测试；保留进度披露（不注入全文）。

---

## 2. 架构决策（已拍板）

| # | 决策 | 理由 |
|---|------|------|
| D1 | **镜像 cycle② 记忆模式** | `skill_manage`≈`memory_manage` + Curator + provenance + frozen-snapshot；复用已验证架构 |
| D2 | **Agent 写 draft；安全扫描/人工 gate publish** | skills 可执行（run_on_host/kubectl）→ 安全优先；与记忆（无执行风险可直写 active）的关键差异 |
| D3 | **Curator 只归档 agent/draft 产物；人写 skill pinned 永不动** | skills 是手写资产，不能像 auto-memory 随意沉底 |
| D4 | **接线 improvement_store + draft 待审** | 改进闭环但人工把关（符合 D2）；improvement_store 已建但 `improve_skill` 工具未接 |
| D5 | **多代本可恢复备份**（取代单 `.bak`） | 镜像记忆 never-delete；现 `promote_skill` 有损 |
| D6 | **保留 3 层进度披露**（不注入全文）+ token bloat 修复 | skills 大；agent-created skill 进 `list_skills` 带 `[AGENT]` 标，全文按需 `activate_skill` |
| D7 | **Frozen-snapshot 注入纪律** | skills XML 会话开始加载一次；agent 写入下会话生效（护 prompt-cache，与记忆一致） |

---

## 3. 数据模型（SKILL.md frontmatter 扩展）

现 `SkillMetadata`：`name, description, metadata{}, tools[], is_draft`。扩展 frontmatter（向后兼容默认）：
```yaml
name: redis-admin
description: "..."
created_by: user|agent        # 【新增】provenance，缺省 user
created_at: YYYY-MM-DD         # 【新增】
last_improved_at: YYYY-MM-DD   # 【新增】改进时戳
improved_from: [<prev>, ...]   # 【新增】genealogy（merge/improve 来源）
skill_version: "1.0"           # 【新增】语义版本字符串（improve 时 bump）
status: active|deprecated|archived  # 【新增，仅 agent/draft 产物用；人写=active pinned】
tools: [...]                   # 既有
metadata: {...}                # 既有
```
- **向后兼容**：旧 SKILL.md 缺新字段 → `normalize_skill_frontmatter` backfill（`created_by=user`, `status=active`, `created_at`/`last_improved_at` 从文件 mtime 或今天）。**人写的 14 个 skill 一律 `created_by=user`（pinned）**。

---

## 4. 核心机制

### 4.1 `skill_manage` 工具（镜像 memory_manage，新建统一入口）
新增一个 agent-facing 工具（增强/替代散乱的 `create_skill`+`improve_skill`，但保留它们供兼容）：

| action | 语义 | 落点 | provenance |
|--------|------|------|-----------|
| `add` | LLM 生成新 skill | **draft**（D2：从不直接 publish） | `created_by=agent` |
| `improve` | 改进已有 skill | **draft**（保留原 published）+ 接 improvement_store | `improved_from`, `last_improved_at` bump |
| `merge` | 多窄 skill → umbrella draft | draft（umbrella）+ 源标记 | `improved_from=[sources]` |
| `deprecate` | 标记 agent skill 为 deprecated | 仅 `created_by=agent` skill | status=deprecated |
| `restore` | 从 `.archive/` 恢复 | — | status=active |
| `search` | 本地+registry 搜索（保留现有） | — | — |

- **安全门**：`add`/`improve` 生成的 draft 在**提升时**经 `security.py` 扫描——若声明了危险 `run_on_host`（blocked 模式）→ 拒绝 publish，标记需人工。
- **Prompt 引导**：agent 在「发现无 skill 覆盖当前域 / 现有 skill 决策树遗漏了案例」时被提示 `skill_manage(action="add"/"improve")`；明确「只生 draft，需人工/安全扫描后才生效」。

### 4.2 Skills Curator（镜像 memory/curator.py，纯文件零 LLM）
`skills/curator.py`：
- **只作用于 `created_by=agent` 的产物**（draft + agent-published）。**`created_by=user` 的 skill 是 pinned，完全跳过**。
- 状态机：未提升的 agent draft `active --(陈旧 N 天未 activate/improve)--> stale --(再 M 天)--> archived`（移 `skills/.archive/`）。
- **never-delete**：归档=移到 `.archive/`，可 `restore`。
- **reactivate-on-use**：draft 被 `activate_skill` 命中 → 刷新 `last_used`、拉回 active。
- 触发：main-agent build 时顺带跑（gated by `skills_curator_enabled`），与记忆 Curator 一致。
- **禁止递归工具**（遵 feedback_no_recursive_tools）。

### 4.3 多代本可恢复备份（修 `promote_skill` 有损）
`promote_skill` 现把旧 published 移到单一 `<name>.bak`（覆盖）。改为：移到 `skills/.archive/<name>__v<timestamp>/`，保留所有历史代本；新增 `rollback_skill(name)` 从最近 archive 恢复。镜像记忆 never-delete。

### 4.4 改进闭环接线（修断裂）
- `improve_skill` 工具（+ `skill_manage improve`）调用 `auto_improve_skill` 后，**接线** `improvement_store.add_improvement(...)` 记录 genealogy（现仅 `skill_improvement_service` 路径接了，工具路径漏了）。
- post-resolution 改进保持「生 draft + 通知人工审阅」（D4），不自动 publish。

---

## 5. 注入纪律（Frozen-snapshot，D7）+ token bloat 修复（D6）

- skills XML 在 agent build 时加载一次快照，会话期间不变；agent 写入下会话生效（护 prompt-cache）。
- **token bloat — 先测量再决定（YAGNI）**：审查估算全部 15 skills XML ≈ 1700 tok/agent。但核实发现**所有 agent（含 reporter）都真实使用 skills**（reporter 用 `activate_skill("local-os-operator"/"notification-operator")`），所以不能简单按 agent 关闭注入。当前 XML 已是截断描述（~100 tok/skill，非全文），进度披露本就在控制成本。**决策：先测量实际注入 token；若 <2000 tok 则不做过滤（符合「不加没用的功能」），仅把 agent-created draft 在 XML 标 `[AGENT]` 以便区分**。真正的按域过滤（agent 只见相关 skill）留作 follow-up，除非实测证明必要。

---

## 6. 已确认的 Bug 修复（顺带，来自审查）

| Bug | 位置 | 修复 |
|-----|------|------|
| `improve_skill` 工具未接 improvement_store | `tools.py:252` | 接线 add_improvement |
| promote 单 `.bak` 有损 | `review.py:99-103` | 多代本 `.archive/` + rollback |
| skills 无 provenance | SKILL.md frontmatter | created_by/created_at（§3） |
| token bloat（全 skills 注入每 agent） | `preamble.py` + `loader.py` | 先测量；<2000 tok 不过滤，仅标 [AGENT]（§5，YAGNI） |
| LLM 输出校验弱 | `evolution.py generate_skill_from_description` | 加类型/长度/name 格式校验（轻量，非 cycle① 已修的 YAML escape） |

（安全分类漏洞 kubectl RBAC/docker arg over-match → 记为 follow-up，非本周期核心）

---

## 7. 配置（settings.yaml，遵「config.py 不硬编码」）
```yaml
skills_autonomous_write: true     # 允许 agent skill_manage add/improve（落 draft）
skills_curator_enabled: true      # Curator 后台生命周期开关
skills_draft_stale_days: 30       # agent draft 多久未用 → stale
skills_draft_archive_days: 60     # stale 后多久 → archived
skills_security_scan_on_promote: true  # 提升时安全扫描门
```

---

## 8. 执行阶段总览（待 writing-plans 细化）

| 阶段 | 内容 | 验收 |
|------|------|------|
| P0 | config 旋钮 + SKILL.md frontmatter 扩展 + `normalize_skill_frontmatter` backfill（人写 skill=pinned） | 旧 skill 正常加载 |
| P1 | Skills Curator（stale/archive/reactivate，只动 agent 产物，人写 pinned） | 时间推进单测 + pinned 豁免 |
| P2 | `skill_manage` 工具（add/improve/merge/deprecate/restore/search）+ provenance + 安全扫描门 | agent 自主写 draft e2e + 危险 skill 被拦 |
| P3 | 多代本备份 + rollback（修 promote 有损）+ 改进闭环接线（improvement_store） | rollback 单测 + genealogy 记录 |
| P4 | 注册 skill_manage 到 agents + Curator at build + token bloat 修复（按 agent 过滤注入） | 注入 token 下降 + 现有测试绿 |
| P5 | LLM 输出校验加固 + WebUI（created_by=agent 筛选 + restore/rollback 端点）+ CLAUDE.md | 每项回归测试 + 最终门禁 |

每阶段先测完再提交；每修配最小回归测试。

---

## 9. 风险与缓解

| 风险 | 缓解 |
|------|------|
| Agent 生成危险 skill（run_on_host rm -rf） | D2 安全扫描门：提升时 security.py 扫描，blocked → 拒绝 publish + 需人工 |
| Curator 误归档人写 skill | D3：只动 created_by=agent；人写一律 pinned 跳过 |
| 注入过滤破坏 agent skill 感知 | 只对确定不用 skills 的 agent（reporter）关；其余保留 XML 列表 |
| 改进闭环产生垃圾 draft | Curator 归档陈旧未提升 draft；human review gate |
| 触及 cycle②/① 代码 | 本周期只动 skills/*；`skill_manage` 不碰 `memory_manage` |
| 向后兼容（旧 frontmatter 缺字段） | normalize backfill + 加载默认兜底；人写 skill 一律 pinned |

---

## 10. 明确不做（YAGNI）
- 重建 draft/publish/LLM生成/进度披露（已工作，只增强）
- size-cap 强制合并（记忆需要，但 skills 14 个手写 + agent draft 受 Curator 管够了；如未来 agent skill 爆炸再加）
- 外部 skill registry SaaS 强依赖（clawhub 仅可选只读，保持现状）
- 安全分类漏洞深修（kubectl RBAC / docker arg）→ follow-up
- 跨 skill 依赖图 / 语义去重（过度工程）
- agent 直接 patch published skill（D2 否决——安全优先）
