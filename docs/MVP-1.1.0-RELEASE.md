# AgenticOps v1.1.0 Release — 自主记忆 + 自主技能

> **版本**: 1.1.0 | **日期**: 2026-05-31 | **分支**: `cycle2-memory-quantum` + `cycle3-skills-autonomy` → `main`

---

## 一、版本概述

v1.1.0 是 v1.0.0-MVP 之后的第一个功能性大版本，聚焦于让 Agent 系统从**被动工具执行者**进化为**自主学习的运维伙伴**。两个核心升级：

1. **Cycle ② — 自主记忆系统**：Agent 拥有 Hermes 式自优化记忆，能从每次运维中学习并永久保留经验
2. **Cycle ③ — 自主技能系统**：Agent 能自主创建、改进、合并技能包，并通过安全门控发布

> **设计理念**: 镜像 Hermes Agent（NousResearch）的自治模式，在安全边界内最大化 Agent 自主权

---

## 二、Cycle ② — 自主记忆系统 (Self-Optimizing Agent Memory)

### 2.1 核心能力

| 能力 | 说明 |
|------|------|
| **`memory_manage` 工具** | Agent 自主 add/patch/merge/remove/search 记忆 |
| **Hermes-style Curator** | 零 LLM 的后台生命周期：active→stale(30d)→archived(60d) |
| **Size-cap 自合并** | 达上限(15)时返回 MemoryFullError + 当前列表，引导 Agent merge |
| **Provenance 溯源** | `created_by=agent/user`，人写记忆优先级更高 |
| **Frozen-snapshot 注入** | 构建时一次加载，会话内不变（护 Bedrock prompt-cache） |
| **Never-delete** | 归档 ≠ 删除，`restore_memory` 随时恢复 |
| **Reactivate-on-use** | 被注入时自动复活 stale → active |
| **Confidence 演化** | 每次确认 +1、过期/失败 -1，排序注入 |

### 2.2 文件结构

```
agent-memory/
├── detect/*.md       # Detect Agent 专属记忆
├── rca/*.md          # RCA Agent
├── sre/*.md          # SRE Agent
├── executor/*.md     # Executor Agent
├── shared/*.md       # 跨 Agent 共享记忆
└── <agent>/.archive/ # 归档区（可恢复）
```

### 2.3 配置

| Key | Default | 说明 |
|-----|---------|------|
| `memory_max_active` | `15` | 每 agent 活跃记忆上限（超过需 merge） |
| `memory_stale_days` | `30` | 未使用多少天 → stale |
| `memory_archive_days` | `60` | stale 后多少天 → archived |
| `memory_autonomous_write` | `true` | 允许 Agent 自主写入记忆 |
| `memory_curator_enabled` | `true` | 启用 Curator 后台生命周期 |

---

## 三、Cycle ③ — 自主技能系统 (Autonomous Skill Management)

### 3.1 核心能力

| 能力 | 说明 |
|------|------|
| **`skill_manage` 工具** | Agent 自主 add/improve/merge/deprecate/restore/search 技能 |
| **Skills Curator** | 零 LLM 生命周期：agent draft active→stale(30d)→archived(60d) |
| **人类技能永久 Pinned** | 14 个手写 skill 永不被 Curator 触碰 |
| **安全门控发布** | `promote_skill` 扫描 bash 代码块，blocked-tier 命令 → 拒绝发布 |
| **多代本可恢复备份** | promote 归档到 `.archive/<name>__<timestamp>/`，支持 rollback |
| **Provenance 溯源** | `created_by`, `created_at`, `skill_version`, `improved_from` |
| **改进审计闭环** | 所有 improve 路径接线 `improvement_store`（genealogy） |
| **Frozen-snapshot 注入** | Skills XML 构建时加载一次，~460 tokens |
| **路径遍历防护** | `_safe_skill_name` 校验，拒绝 `../../etc` 等恶意 name |
| **XML 注入防护 (P0.5)** | `build_available_skills_xml` 使用 `xml.sax.saxutils.escape` 转义 `<>&"` |
| **YAML 容错解析 (P0.5)** | colon-fallback — `description: Use when: foo` 不再静默丢失 |
| **严格 name 格式校验 (P0.5)** | kebab-case + 1-64 字符 + 必须等于父目录名（agentskills.io 规范） |
| **资源自动枚举 (P0.5)** | `activate_skill` 返回 scripts/references/assets 文件列表（上限 20） |
| **索引召回率提升 (P0.5)** | XML 描述截断从 80 → 200 字符，去掉首句切分 |

### 3.2 安全分级 (Defense-in-Depth)

```
Layer 1: skill_manage 写入 → 只能落 draft（永不直接发布）
Layer 2: promote_skill → scan_skill_safety 扫描所有 bash fence
         检测: rm -rf /path, dd of=/dev/, curl|bash, mkfs, fork bomb, shutdown...
Layer 3: runtime execution → classify_shell_command 逐命令分级
         blocked → 拒绝执行 | write → 需确认 | readonly → 自动执行
```

### 3.3 Skill 生命周期

```
Agent 发现知识空白
    ↓
skill_manage(action="add", description="...")
    ↓
LLM 生成 → draft/ (created_by=agent, status=active)
    ↓ (人工/自动审阅)
promote_skill(name)
    ↓ scan_skill_safety → safe?
    ├── No → 拒绝，需人工修改
    └── Yes → 归档旧版本 → 移到 skills/ → 生效(下次会话)

    ↓ (长期未用)
Curator: active → stale(30d) → archived(60d) → skills/.archive/
    ↓ (被 activate_skill 调用)
Reactivate: stale → active (touch last_used)
    ↓ (需要恢复)
restore_skill / rollback_skill → 回到 draft/skills
```

### 3.4 配置

| Key | Default | 说明 |
|-----|---------|------|
| `skills_autonomous_write` | `true` | 允许 Agent 自主创建/改进技能（落 draft） |
| `skills_curator_enabled` | `true` | 启用 Skills Curator 生命周期 |
| `skills_draft_stale_days` | `30` | Agent draft 多久未用 → stale |
| `skills_draft_archive_days` | `60` | Stale 后多久 → archived |
| `skills_security_scan_on_promote` | `true` | 发布前安全扫描 |

### 3.5 API 新增

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/skills/{name}/rollback` | POST | 回滚到上一个归档版本 |
| `/api/skills/{name}/restore` | POST | 从 Curator 归档恢复到 draft |

---

## 四、架构升级总览

```
v1.0.0 Agent 架构:
  Main Agent → Sub-Agents → Tools → AWS

v1.1.0 Agent 架构 (NEW):
  Main Agent → Sub-Agents → Tools → AWS
       │                       ↑
       ├── memory_manage ──→ agent-memory/*.md (自优化)
       ├── skill_manage ───→ skills/draft/ (自创建)
       │                       ↓ promote (security-gated)
       │                     skills/ (published)
       │
       └── build time: Curator(memory) + Curator(skills)
                       → inject frozen-snapshot → prompt-cache safe
```

---

## 五、技术统计

| 指标 | Cycle ② | Cycle ③ | 合计 |
|------|---------|---------|------|
| Commits | 17 | 13 | 30 |
| 新/改文件 | 12 | 17 | 29 |
| 新增行 | ~800 | ~988 | ~1,788 |
| 新测试 | 47 | 371 tests total | 418+ |
| 新配置项 | 5 | 5 | 10 |
| 新 API 端点 | 1 (restore) | 2 (rollback, restore) | 3 |
| 新 @tool | 1 (memory_manage) | 1 (skill_manage) | 2 |

---

## 六、已知限制 & 后续计划

| 项目 | 状态 | 说明 |
|------|------|------|
| 向量语义召回 (episodic memory) | Deferred | S3 Vectors 仅 cold-tier，当前 behavioral memory 足够 |
| Per-agent skill 域过滤 | YAGNI | ~460 tok 远低于阈值，不需要 |
| Security classifier 深度修复 | Follow-up | kubectl RBAC / docker arg over-match |
| CLI 大文件拆分 (main.py 4300L) | Deferred to 1.2 | 见 cycle① 计划 |
| 前端 Skills management UI | Follow-up | 端点已有，前端 wiring 下期 |
| 存量测试桩修复 (boto3 patch) | Tech-debt | 14 个测试 mock target 需 retarget |

---

## 七、升级指南

```bash
# 从 v1.0.0 升级
git pull origin main
pip install -e .

# 新配置项已有默认值，无需手动设置
# 验证：
aiops chat "list skills"     # 应显示 14+ skills
aiops chat "search memory"   # 应显示 agent 记忆
```

配置覆盖（可选）：
```yaml
# config/settings.yaml
memory_autonomous_write: true    # Agent 可自主写记忆
skills_autonomous_write: true    # Agent 可自主建技能
skills_security_scan_on_promote: true  # 发布前安全扫描
```

---

## 八、验证清单

- [x] Cycle ② Memory: 47 tests passed
- [x] Cycle ③ Skills: 371 tests passed (2.07s)
- [x] P0.5 loader hardening: 36 tests passed (1.36s), 16 新增
- [x] All agents import clean
- [x] CLI `aiops --help` works
- [x] Web app compiles + starts
- [x] 15 human skills discovered (pinned) — all pass kebab-case name validation
- [x] Prompt-cache discipline: frozen-snapshot, no mid-session mutation
- [x] Security: path-traversal guard, promote scan, non-dict tolerance

---

> **下一版本**: v1.2.0 — CLI 大文件拆分 + Skills 前端管理 + episodic memory (if needed)
