# ADR-010: ClawOps Architecture Evolution

> **Status**: DRAFT
> **Author**: Architect
> **Date**: 2026-03-10
> **Supersedes**: ADR-009 (Channel-Driven RCA — concepts merged)
> **Base**: agenticops-chat (bf07376)

---

## 1. 背景

Ma Ronnie 全权授权团队自主迭代 agenticops-chat，目标打造 **ClawOps** — 一个 Self-improving、主动式的 AIOps 平台。核心愿景：

- **L5 级自主运维** — 从告警到修复到学习，全自动闭环
- **Self-improving** — Agent 自主创建/更新 Skills 和 SOP
- **每个 Agent 独立记忆** — 参考 OpenClaw MEMORY.md 模式
- **前端如 Apple 产品** — 极简、人性化、渐进式
- **后端如 AWS/GCP** — 稳定、强大、可扩展
- **永无止境的自主演进**

---

## 2. 现有架构评估

### 2.1 agenticops-chat 资产盘点

| 模块 | 行数 | 成熟度 | 评估 |
|------|------|--------|------|
| **agents/** (7 agents) | 1,438 | ⭐⭐⭐ | Main→Sub 路由模式成熟，Strands SDK |
| **pipeline/** (orchestrator) | 1,341 | ⭐⭐⭐ | Step-based pipeline + preset workflows |
| **skills/** (6 modules) | 1,785 | ⭐⭐ | 有 evolution/review/security，但 security 弱于 MVP |
| **kb/** (4 modules) | 876 | ⭐⭐⭐ | CaseStudy + vector store + hybrid search — **核心优势** |
| **im/** (8 gateways) | 1,887 | ⭐⭐ | 多 IM 支持但 lark_oapi 问题 |
| **tools/** (14 modules) | ~2,500 | ⭐⭐⭐ | 丰富的 AWS/EKS/network tools |
| **graph/** (8 modules) | ~1,200 | ⭐⭐⭐ | Topology + SPOF + capacity — **独特优势** |
| **integrations/** (4 modules) | ~600 | ⭐⭐ | CW/Datadog parsers |
| **web/** (FastAPI) | ~300 | ⭐ | 基础，需大幅增强 |

### 2.2 从 agentic-aiops-mvp 可移植的资产

| 资产 | 行数 | 价值 | 移植复杂度 |
|------|------|------|-----------|
| **@secure_tool 4-tier** | ~300 | 极高 — 标准化安全模型 | 低 (替换现有 security.py) |
| **AlertIngress + 5 Parsers** | ~800 | 高 — Channel-Driven 入口 | 中 (适配 integrations/) |
| **SkillGapDetector + SkillSpecBuilder** | ~500 | 高 — Self-improve 核心 | 低 (补充到 skills/) |
| **SOPAutoWriter + Deduplicator** | ~400 | 高 — SOP 自更新 | 低 |
| **Watch-on-Demand** | ~740 | 中 — 对话式 Watcher | 中 |
| **103 @tool functions** (8 domains) | ~3,500 | 参考 — 已有重叠 | 选择性合并 |
| **3,398 test patterns** | ~8,000 | 高 — 测试模式可复用 | 适配 |

### 2.3 差距分析

```
现有 agenticops-chat              目标 ClawOps L5
━━━━━━━━━━━━━━━━━━━━              ━━━━━━━━━━━━━━━━
L1-L2 半自动                   →  L5 全自主闭环
Skills 生成 (LLM prompt)       →  Skills Harness 自举 (ACP/Claude Code)
无独立记忆                     →  Per-Agent Memory + 跨 Agent 知识共享
Alert webhook 被动             →  Channel-Driven 主动 + Proactive Detection
单次 RCA                      →  Deep RCA 迭代 (max 3 rounds)
Pipeline 线性                  →  Pipeline DAG + 条件分支 + 回滚
Web 基础                      →  Apple-grade UX
单体                          →  可选微服务拆分
```

---

## 3. ClawOps 目标架构

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                          ClawOps Platform                           │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    🍎 Apple-Grade Frontend                   │   │
│  │  Command Bar │ Live Feed │ Topology │ Agent Chat │ Config   │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                              │                                      │
│  ┌──────────────────────────┴──────────────────────────────────┐   │
│  │                    Gateway Layer                              │   │
│  │  FastAPI │ WebSocket │ IM Gateways │ Webhook │ Channel-Driven│   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                              │                                      │
│  ┌──────────────────────────┴──────────────────────────────────┐   │
│  │              🧠 Agent Orchestration Layer                    │   │
│  │                                                              │   │
│  │  ┌─────────────────────────────────────────────────────┐    │   │
│  │  │              Main Agent (Router)                      │    │   │
│  │  │  Intent → Dispatch → Summarize → Learn               │    │   │
│  │  └────────────────────┬──────────────────────────────────┘    │   │
│  │                       │                                       │   │
│  │  ┌────────┬──────────┼──────────┬──────────┬──────────┐     │   │
│  │  │ Scan   │ Detect   │ RCA      │ SRE      │ Executor │     │   │
│  │  │ Agent  │ Agent    │ Agent    │ Agent    │ Agent    │     │   │
│  │  │        │          │ (Deep    │ (Fix     │ (L0-L4   │     │   │
│  │  │        │          │  Iter)   │  Plan)   │  Auto)   │     │   │
│  │  └────────┴──────────┴──────────┴──────────┴──────────┘     │   │
│  │  ┌────────┐  ┌────────────┐                                  │   │
│  │  │Reporter│  │ Proactive  │  ← NEW: autonomous patrol       │   │
│  │  │ Agent  │  │ Agent      │                                  │   │
│  │  └────────┘  └────────────┘                                  │   │
│  │                                                              │   │
│  │  ┌──────────────────────────────────────────────────────┐   │   │
│  │  │         Per-Agent Memory System                       │   │   │
│  │  │  Each agent: MEMORY.md + episodic + semantic search   │   │   │
│  │  └──────────────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│  ┌──────────────────────────┴──────────────────────────────────┐   │
│  │              🔧 Self-Improvement Engine                      │   │
│  │                                                              │   │
│  │  SkillGapDetector → SkillSpecBuilder → Harness (Claude Code)│   │
│  │       ↓                                     ↓                │   │
│  │  SOPAutoWriter → Deduplicator → Review Gate → Promote       │   │
│  │       ↓                                     ↓                │   │
│  │  KnowledgeFlywheel → CaseStudy → VectorStore → Rerank      │   │
│  │       ↓                                                      │   │
│  │  ArchitectureReflector → ADR Generator → Self-Refactor      │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│  ┌──────────────────────────┴──────────────────────────────────┐   │
│  │              📚 Knowledge & Skills Layer                     │   │
│  │                                                              │   │
│  │  SkillRegistry ←→ ClawHub │ KB (Vector+SQLite) │ SOP Store  │   │
│  │  @secure_tool (4-tier)    │ Graph (NetworkX)   │ Embeddings │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│  ┌──────────────────────────┴──────────────────────────────────┐   │
│  │              ☁️  Cloud Substrate                              │   │
│  │  AWS (EC2/EKS/Lambda/RDS/S3/...) │ GCP (future) │ K8s      │   │
│  │  CloudWatch │ Bedrock │ S3 (SOP) │ Datadog │ Prometheus     │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 L5 自主运维闭环

```
    ┌─────────────┐
    │   Observe   │ ← Channel-Driven + Proactive + Webhook
    └──────┬──────┘
           ↓
    ┌─────────────┐
    │   Orient    │ ← AlertIngress → StructuredAlert → Enrichment
    └──────┬──────┘
           ↓
    ┌─────────────┐
    │   Decide    │ ← Deep RCA (iterative) + KB Search + SOP Match
    └──────┬──────┘
           ↓
    ┌─────────────┐
    │    Act      │ ← Fix Plan → Approval Gate → Executor (L0-L4)
    └──────┬──────┘
           ↓
    ┌─────────────┐
    │   Learn     │ ← Knowledge Flywheel + Skill Evolution + SOP Update
    └──────┬──────┘
           ↓
           └──────→ (back to Observe — continuous loop)
```

**L5 = OODA loop runs autonomously, with human oversight only for L2+ operations.**

---

## 4. 核心设计

### 4.1 Per-Agent Memory System

每个 Agent 拥有独立的持久化记忆，参考 OpenClaw MEMORY.md 模式：

```python
# src/agenticops/memory/agent_memory.py

class AgentMemory:
    """Per-agent persistent memory with episodic + semantic storage."""

    def __init__(self, agent_name: str, base_dir: Path):
        self.agent_name = agent_name
        self.memory_file = base_dir / f"{agent_name}_MEMORY.md"
        self.episodic_store = SQLiteVectorStore(
            db_path=base_dir / f"{agent_name}_episodic.db"
        )

    async def remember(self, event: str, context: dict) -> None:
        """Store an episodic memory entry."""
        # 1. Append to MEMORY.md (human-readable)
        # 2. Embed and store in vector DB (semantic search)
        ...

    async def recall(self, query: str, top_k: int = 5) -> list[MemoryEntry]:
        """Semantic search across agent's memories."""
        ...

    async def reflect(self) -> str:
        """End-of-day summary and consolidation."""
        ...
```

**Memory 类型**:

| 类型 | 存储 | 用途 |
|------|------|------|
| **Episodic** | Vector DB | "上次 EKS pod crash 是 OOM，解决方案是..." |
| **Semantic** | MEMORY.md | 结构化知识积累 (ADR 风格) |
| **Procedural** | Skills | "如何排查 Redis 连接泄漏" |
| **Shared** | KB (CaseStudy) | 跨 Agent 共享的案例库 |

**Cross-Agent Knowledge Sharing**:
```
Agent A (RCA) discovers pattern → CaseStudy → KB
Agent B (Detect) queries KB → finds similar pattern → faster detection
Agent C (SRE) reads CaseStudy → generates Fix Plan informed by history
```

### 4.2 Self-Improvement Engine

三层自改进机制：

#### Layer 1: Skill Evolution (已有基础 + 增强)

```
Current: evolution.py → LLM prompt → draft SKILL.md
Enhanced:
  1. SkillGapDetector — 检测 Agent 调用失败 / 能力缺口
  2. SkillSpecBuilder — 生成详细 Skill 规格
  3. Harness (Claude Code / ACP) — 自主编写 tools.py + tests
  4. SkillValidator — 5 层验证 (AST → signature → sandbox → test → review)
  5. SkillPromoter — draft → active → stable (置信度 1/3/5)
```

#### Layer 2: SOP Auto-Writer (从 MVP 移植)

```
Incident resolved → SOPAutoWriter → generate/update SOP
  → SOPDeduplicator (cosine 0.85 threshold)
  → Review Gate (human or auto based on confidence)
  → S3 publish + KB sync (StartIngestionJob)
```

#### Layer 3: Architecture Self-Reflection (NEW — ClawOps 独创)

```
ArchitectureReflector:
  - 每周分析: 错误日志 / 性能瓶颈 / 代码复杂度
  - 生成 ADR proposal (不自动执行 — human-in-loop)
  - 建议: 模块拆分 / 依赖更新 / 架构优化
  - 输出: docs/adr/auto-generated/ADR-NNN.md
```

### 4.3 Channel-Driven Alert Ingress (从 MVP 合并)

```python
# src/agenticops/integrations/alert_ingress.py (新增/替代)

class AlertIngressService:
    """Unified alert entry point — Channel-Driven + Webhook."""

    def __init__(self):
        self.parsers = [
            CloudWatchParser(),
            DatadogParser(),
            PagerDutyParser(),
            GrafanaParser(),
            GenericParser(llm=True),  # LLM fallback
        ]
        self._seen = LRUCache(maxsize=1000)  # 去重

    async def ingest(self, raw: dict, source: str) -> StructuredAlert:
        """Parse raw alert → StructuredAlert → pipeline."""
        ...
```

**与现有 `alert_pipeline.py` 的关系**:
- `alert_pipeline.py` 的 `should_handle_as_alert()` 保留为前置过滤
- `AlertIngressService` 接管后续解析和标准化
- `StructuredAlert` (Pydantic) 替代 `AlertPayload` (dataclass)

### 4.4 Deep RCA — 迭代式诊断

```python
# src/agenticops/analyze/deep_rca.py (新增)

class DeepRCAEngine:
    """Iterative RCA with evidence gathering through Skills."""

    MAX_ITERATIONS = 3
    CONFIDENCE_THRESHOLD = 0.7

    async def analyze(self, alert: StructuredAlert) -> RCAResult:
        """Multi-round RCA with increasing depth."""
        # Round 1: Fast RCA (existing rca.py)
        result = await self.fast_rca(alert)

        # Iterate if confidence < threshold
        for i in range(self.MAX_ITERATIONS):
            if result.confidence >= self.CONFIDENCE_THRESHOLD:
                break

            # Gather more evidence via Skills (T0+T1 only)
            evidence = await self.gather_evidence(result.hypothesis, alert)

            # Re-analyze with new evidence
            result = await self.analyze_with_evidence(result, evidence)

            # Memory: record what we tried
            await self.agent_memory.remember(
                f"RCA iteration {i+1}",
                {"hypothesis": result.hypothesis, "confidence": result.confidence}
            )

        return result
```

### 4.5 Pipeline DAG (从线性升级)

现有 Pipeline 是线性 step-based (orchestrator.py)，需升级为 DAG：

```python
# Enhancement to pipeline/orchestrator.py

class DAGPipeline(Pipeline):
    """Pipeline with conditional branching and parallel execution."""

    async def execute(self) -> PipelineResult:
        # 1. Topological sort steps by dependencies
        # 2. Execute independent steps in parallel (asyncio.gather)
        # 3. Support conditional steps (execute_if=lambda ctx: ...)
        # 4. Support rollback on failure (rollback_func per step)
        ...
```

### 4.6 Security Model — @secure_tool 4-tier (从 MVP 移植)

替换现有 `skills/security.py` (仅 shell/kubectl 分类) 为完整 4-tier 模型：

| Tier | 名称 | 权限 | Agent 绑定 |
|------|------|------|-----------|
| T0 | Read-Only | 自动执行 | All agents |
| T1 | Diagnostic | 自动执行 | RCA, SRE, Executor |
| T2 | Write | 需确认 | SRE, Executor |
| T3 | Dangerous | 需 HMAC approval_token | Executor only |

```python
@secure_tool(tier=SecurityTier.T2, requires_confirmation=True)
def restart_service(service_name: str) -> ToolResult:
    """Restart an ECS service — requires confirmation."""
    ...
```

---

## 5. 前端愿景 — Apple-Grade UX

### 5.1 设计原则

1. **极简** — 3 个主视图，不超过 5 个
2. **渐进式** — 默认显示摘要，点击展开详情
3. **实时** — WebSocket live feed，10s 轮询告警
4. **人性化** — 自然语言交互为主，按钮操作为辅

### 5.2 视图设计

```
┌─────────────────────────────────────────────────┐
│  ⌘ Command Bar (natural language input)          │
├────────────┬────────────────────┬────────────────┤
│  Live Feed │   Main Canvas      │  Agent Chat    │
│  ─────────  │                    │  ─────────     │
│  🔴 P1 Alert│  [Topology View]   │  🤖 "I found  │
│  🟡 P2 Alert│  or                │   3 issues..." │
│  ✅ Resolved│  [Issue Detail]    │                │
│  📊 Report  │  or                │  You: "fix it" │
│             │  [Config]          │                │
│             │                    │  🤖 "Generating│
│             │                    │   fix plan..." │
└────────────┴────────────────────┴────────────────┘
```

### 5.3 关键交互

| 交互 | 实现 |
|------|------|
| 输入 "check my EKS" | Command Bar → Main Agent → Detect → Live Feed 更新 |
| 点击 Alert card | Main Canvas → Issue Detail + RCA timeline |
| "fix this" in chat | Agent Chat → SRE → Fix Plan → Approval button |
| Topology node click | Graph visualization → resource detail drawer |

---

## 6. Multi-Agent Framework 评估

| 框架 | 优势 | 劣势 | 建议 |
|------|------|------|------|
| **Strands SDK** (当前) | 已集成, agents-as-tools 模式成熟, Bedrock 原生 | 社区较小, 文档有限 | ✅ 保持为主框架 |
| LangGraph | 状态机+图执行, 社区大 | 抽象重, 迁移成本高 | ❌ 不迁移 |
| CrewAI | 角色分工清晰 | 性能问题, 不够灵活 | ❌ 不适合 |
| AutoGen | 微软支持, conversation pattern | 架构复杂 | 📊 监控发展 |
| **OpenClaw patterns** | Memory 系统成熟, Skills 生态 | 非 SDK, 是 platform | ✅ 借鉴 Memory 模式 |

**决策: 保持 Strands SDK + 借鉴 OpenClaw Memory/Skills 模式 + 复用社区 Skills**

理由：
1. Strands 的 agents-as-tools 已经工作良好
2. 迁移框架的 ROI 不值得 — 应该投入在 Self-Improve 能力上
3. 如果未来 Strands 有瓶颈，agent 层是隔离的，可以替换

---

## 7. 实施路线图

### Phase 0: Foundation (Day 1-3)

| 任务 | 负责人 | 估时 |
|------|--------|------|
| Fork → ClawOps repo | Developer | 0.5d |
| Fix 11 test failures | Developer | 0.5d |
| 建立 CI/CD baseline | Tester | 1d |
| 本 ADR 评审通过 | Architect + Reviewer | 1d |
| Self-improve 技术调研 | Researcher | 2d |

### Phase 1: Memory + Deep RCA (Day 4-10) — Memory L3

| 任务 | 负责人 | 估时 | 状态 |
|------|--------|------|------|
| Per-Agent Memory 实现 | Developer | 3d→8min | ✅ `1306dfb` 1,011 LOC, 23 tests |
| Deep RCA Engine | Developer (Claude Code) | 2d | 🔜 Next |
| AlertIngress 合并 | Developer (Claude Code) | 1d | |
| Memory + RCA 测试 | Tester | 2d | |
| 架构评审 | Architect | 1d | |

### Phase 2: Self-Improvement + Memory L4 (Day 11-20)

| 任务 | 负责人 | 估时 |
|------|--------|------|
| `@wal_enforced` meta-decorator | Developer | 1d |
| VBR (Verify Before Report) protocol | Developer | 1d |
| Self-questioning reflection (Generative Agents) | Developer | 2d |
| SkillGapDetector + SpecBuilder | Developer | 3d |
| SOPAutoWriter + Deduplicator | Developer | 2d |
| @secure_tool 4-tier 移植 | Developer | 2d |
| ClawHub 集成 | Developer | 1d |
| Self-improve E2E 测试 | Tester | 3d |
| Voyager skill library 深挖 | Researcher | 持续 |

### Phase 3: Frontend + Memory L4.5 (Day 21-30)

| 任务 | 负责人 | 估时 |
|------|--------|------|
| Predictive Memory (pattern → prediction rules) | Developer | 2d |
| Cross-Agent publish-subscribe KB | Developer | 2d |
| Command Bar + Live Feed | Developer | 3d |
| Agent Chat panel | Developer | 2d |
| Topology visualization | Developer | 3d |
| Frontend E2E (Playwright) | Tester | 2d |

### Phase 4: L5 Autonomous Loop + Memory L5 (Day 31-45)

| 任务 | 负责人 | 估时 |
|------|--------|------|
| Memory → Skill auto-conversion (Voyager pattern) | Developer | 3d |
| Core/archival memory paging (MemGPT light) | Developer | 2d |
| Pipeline DAG upgrade | Developer | 3d |
| Architecture Reflector | Developer | 3d |
| Proactive Agent enhancement | Developer | 2d |
| Full L5 E2E integration | Tester | 3d |
| 演进方向评估 + next ADR | Researcher + Architect | 持续 |

### Phase ∞: Continuous Self-Evolution

- 团队每日 standup (UTC 05:00)
- 每周架构 review
- Researcher 持续调研新技术
- Skills 自动演进 — 平台自身不断学习和改进

---

## 8. 成功指标

| 指标 | 当前 | Phase 1 目标 | Phase 4 目标 |
|------|------|-------------|-------------|
| MTTR (告警→解决) | 手动 | < 30 min (L1-L2) | < 5 min (L3-L4) |
| RCA 准确率 | ~60% | > 75% (Deep RCA) | > 90% (with KB) |
| Skill 覆盖 | 12 skills | 15 skills | 30+ (auto-generated) |
| 测试覆盖率 | ~70% (est) | > 80% | > 90% |
| 前端 API 覆盖 | ~27% | 50% | > 80% |
| 自主 Skill 创建 | 0/month | 2/month | 10+/month |

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| Self-improve 生成低质量 Skill | 污染 KB | 5 层 SkillValidator + Review Gate + golden test |
| LLM 幻觉导致错误修复 | 生产事故 | @secure_tool 4-tier + T2+ 需人工确认 |
| ACP 并发导致 gateway drain | 服务中断 | 串行使用 ACP + Rate limiter + Task queue (Phase 2) |
| Memory 膨胀 | 性能下降 | 定期 consolidation + TTL + 向量 DB pruning |
| 框架锁定 Strands | 难迁移 | Agent 层抽象接口，tools 与 framework 解耦 |
| 团队自主可能偏离方向 | 浪费资源 | 每日 standup + 每周 review + Ma Ronnie 日报 |

---

## 10. 决策记录

| # | 决策 | 理由 |
|---|------|------|
| 1 | Fork (非新建 repo) | 保留 git 历史 + 成熟代码基础 |
| 2 | 保持 Strands SDK | 已集成，迁移 ROI 不值得 |
| 3 | Per-Agent Memory (MEMORY.md + Vector DB) | 参考 OpenClaw 验证过的模式 |
| 4 | @secure_tool 4-tier 移植 | MVP 验证过，比现有 security.py 强 |
| 5 | Deep RCA 迭代 (max 3) | 平衡准确率和延迟 |
| 6 | Pipeline DAG 升级 | 支持条件分支和并行，L5 必需 |
| 7 | 项目名 ClawOps (非 OpsClaude) | 避免商标问题 (Orchestrator 建议) |
| 8 | Developer 使用 Claude Code | Ma Ronnie 指令，提升开发效率 |
| 9 | 日报 UTC 05:00 | 覆盖亚太工作时间 |
| 10 | Architecture Reflector = human-in-loop | 自动生成 ADR 但不自动执行重构 |
| 11 | 优先复用 `arc-*` 系列 Skills 模式 | lifecycle/gitops/health-monitor/trust-verifier 覆盖 Skill 全生命周期 |
| 12 | `agent-self-governance` WAL+VBR 模式 | 自主行为可审计可回溯，L5 安全基石 |

---

*📐 Architect — ADR-010 Draft, 2026-03-10*
*Pending: Reviewer 评审 + Orchestrator 确认优先级*
