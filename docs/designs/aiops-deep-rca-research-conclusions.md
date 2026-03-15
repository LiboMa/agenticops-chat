# ClawOps Deep RCA Engine — 前沿架构调研结论

> **日期**: 2026-03-15
> **参与**: Ma Ronnie, Orchestrator, Architect, Developer, Researcher, Tester
> **状态**: 团队共识 + 待 Ma Ronnie 定方向

---

## 1. 项目定位

Ma Ronnie 确认：ClawOps 之前的项目思路与 **AIOpsLab**（Microsoft Research, arXiv:2501.06706）一致 —— 构建 AI-first 的自主云运维平台，覆盖完整事故生命周期（检测 → 诊断 → 修复 → 验证 → 学习）。

---

## 2. AIOps 核心难题排序（团队 5/5 一致）

| 排名 | 核心难题 | 性质 | ClawOps 现状 |
|------|---------|------|-------------|
| **#1** | **自动修复安全边界** | 信任问题，无 benchmark，行业零共识 | `@secure_tool` T0-T3 分级（手工定义，缺自动化 blast radius 评估） |
| **#2** | **因果推断准确性** | 技术问题，可渐进改善 | Deep RCA 7-step + evidence chain，但无因果图（causal DAG） |
| **#3** | **知识闭环 + 评估标准** | 工程问题，需时间积累 | RCALearner + SOPAutoWriter + SkillGapDetector，缺验证机制 |

**关键纠正**（Ma Ronnie）：数据源不是瓶颈。AWS CloudWatch/CloudTrail/X-Ray 数据充足，API 直接拿。

---

## 3. 当前代码库分析（Orchestrator Claude Code Brainstorming）

### 3.1 现有能力（analyze/ 目录，1,428 LOC）

| 文件 | 行数 | 功能 |
|------|------|------|
| `rca.py` | 344 | Base RCA — 单次 LLM prompt + 异常/指标上下文 |
| `deep_rca.py` | 609 | Deep RCA — 7-step: 记忆召回 → 图enrichment → KB搜索 → 迭代LLM(max 3轮) → 自验证(CriticAgent) → WAL写入 → CaseStudy |
| `rca_learner.py` | 227 | Post-RCA 学习 — 模式提取 + 技能缺口检测 + 定期反思 |
| `evidence.py` | 248 | 证据采集器 + 来源加权置信度（CloudTrail: 0.95, Trace: 0.9, CW: 0.85 等） |

### 3.2 优势（已领先 HolmesGPT/Keep）

- 7-step Deep RCA + Memory + Graph + KB + 迭代调查
- Self-verification（Voyager CriticAgent 模式）— AIOps 领域独特
- Evidence chain + 加权置信度 — 定量推理
- Learning loop（RCALearner）+ Skill Gap Detection
- Graph topology context（blast radius, 依赖关系）

### 3.3 关键 Gap

| Gap | 描述 | 影响 |
|-----|------|------|
| **Trace/Logs gatherer 是 TODO stub** | `evidence.py` 中 trace 和 logs 采集器未实现 | 证据链不完整 |
| **无因果图（Causal DAG）** | topology graph 只有结构，没有因果方向 | 无法区分因果 vs 相关 |
| **自验证用同一模型** | CriticAgent 用同一个 LLM 自我挑战（弱对抗性） | 幻觉检测不可靠 |
| **Pattern matching 硬编码** | `_categorize_root_cause` 8 个硬编码类别 | 扩展性差 |
| **无反事实推理** | 不能回答"如果 X 没发生，还会出问题吗？" | 因果推断不完整 |
| **Reproducibility 未测试** | 同输入跑 5 次可能结论不同 | 不敢基于结果自动修复 |

---

## 4. 关键论文及对 ClawOps 的指导

### 4.1 优先级排序（Researcher 分析）

| 优先级 | 论文 | 行动 | 难度 | 预期收益 |
|--------|------|------|------|---------|
| 🥇 #1 | **eARCO** (arXiv:2504.11505, Microsoft) | Prompt 自动优化 + few-shot 历史案例注入 | **低** | RCA 准确率 **+21%** |
| 🥈 #2 | **16类推理失败** (arXiv:2601.22208) | 迭代循环中增加推理质量监测器 | 中 | 提前拦截错误 RCA |
| 🥉 #3 | **Agent系统性失败** (arXiv:2602.09937) | 独立 verification agent（不同模型） | 中 | 减少幻觉和探索不完整 |
| 4 | **Pearl因果框架** | CloudTrail 变更事件因果分析 | 高 | 差异化竞争优势 |
| 5 | **AIOpsLab** (arXiv:2501.06706) | 参考框架建 benchmark | 中 | 长期评估基础 |

### 4.2 论文详解

#### eARCO (arXiv:2504.11505) — Prompt 优化 > RAG > Fine-tuning

- **来源**: Microsoft Research, 2025
- **数据**: 180K+ 微软真实事故
- **核心发现**: Prompt 优化比 RAG 高 21%，比 fine-tuned 小模型高 13%
- **方法**: PromptWizard 自动搜索最优 prompt instruction + 语义相似历史案例作 few-shot
- **对 ClawOps**: 最直接可落地。现有 `rca.py` 和 `deep_rca.py` 都是手写 prompt，可以大幅改进

#### 16类推理失败 (arXiv:2601.22208) — LLM RCA 的失败分类法

- **来源**: FORGE 2026
- **数据**: 6 个 LLM × 48,000 故障场景，累计 228 天执行
- **核心发现**: 16 类推理失败（Stalled/Biased/Confused），多跳传播最难
- **关键价值**: 推理失败可预测 → 可以在 RCA 过程中实时监测质量
- **对 ClawOps**: 在 `deep_rca.py` 迭代循环中增加 reasoning quality monitor

#### Agent 系统性失败 (arXiv:2602.09937) — 架构 > 模型

- **来源**: 韩国团队, 2026
- **数据**: 5 个 LLM × 1,675 次 Agent RCA
- **核心发现**: 12 种失败类型，最常见的"幻觉数据解读"和"探索不完整"在所有模型上出现
- **关键结论**: 问题在架构不在模型，改进 Agent 间通信协议减少失败 15%
- **对 ClawOps**: 引入独立 verification agent（不同模型），而不是同模型自验证

#### AIOpsLab (arXiv:2501.06706) — Agent 评估框架

- **来源**: Microsoft Research, SoCC'24 + MLSys'25
- **提出 "AgentOps" 范式**: AI Agent 自主管理完整事故生命周期
- **对 ClawOps**: 参考框架，先用自有 Chaos Lab + 5 scenario 建 benchmark

#### Pearl 因果框架 — 因果推断理论基础

- **三级因果阶梯**: 关联（Seeing）→ 干预（Doing）→ 反事实（Imagining）
- **对 ClawOps**: CloudTrail 是 Pearl 因果框架在 AWS 场景的天然数据源（API 调用 = do 操作）
- **行动**: evidence.py 中增加 CloudTrail 变更事件与指标异常的因果关联分析

---

## 5. Architect 调研报告要点（10 大未解决难题）

完整报告: `~/.openclaw/workspace-architect/aiops-unsolved-problems-2026.md`（524 行，16 篇核心论文）

### 多 Agent RCA 架构（Architect 提案）

```
┌─────────────┐  ┌──────────────┐  ┌──────────────┐
│ Metrics Agent│  │  Logs Agent  │  │ Traces Agent │
│ (CloudWatch) │  │ (CloudWatch  │  │  (X-Ray)     │
│              │  │   Logs)      │  │              │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                  │
       └────────┬────────┘──────────────────┘
                │
       ┌────────▼────────┐
       │  RCA Synthesizer │ ← 共识投票 + 证据链合并
       └────────┬────────┘
                │
       ┌────────▼────────┐
       │  Confidence      │ ← 置信度校准 + Grounding 检查
       │  Calibrator      │
       └────────┬────────┘
                │
       ┌────────▼────────┐
       │  Remediation     │ ← L0-L3: 建议 → 确认 → 执行
       │  Advisor         │
       └─────────────────┘
```

### 修复安全分级（L0-L3）

| 级别 | 操作 | 审批 |
|------|------|------|
| L0 | 只输出修复建议 | 无需 |
| L1 | 只读诊断操作（describe-instances） | 无需 |
| L2 | 预批准安全操作（重启服务、增加实例） | 自动 |
| L3 | 配置变更 | 沙箱验证 + 人工确认 |

---

## 6. 闭环验证路线图（L4.5 → L5）

团队已识别 3 个 Gap:

| Gap | 描述 | 架构方案 |
|-----|------|---------|
| Gap 1 | Execution Outcome Verification（执行结果自动判定） | PostActionValidator ~200-300 LOC |
| Gap 2 | Outcome-based Knowledge Revision（基于结果的知识纠错） | validation_state + revise/reinforce/penalize |
| Gap 3 | Auto-rollback on Failure（失败自动回滚） | 可逆性判断框架 |

**Verdict 四态**: SUCCESS / PARTIAL_SUCCESS / FAILED / UNCERTAIN

**观察窗口按 Tier**: T0=30s, T1=2min, T2=5min, T3=15min

---

## 7. 待讨论：Prompt 优化 + Skills 迭代

**Ma Ronnie 下一步要求**: 深入讨论 prompt 优化和 skills 迭代方向。

### Prompt 优化（基于 eARCO）

- 当前: 手写 prompt（rca.py + deep_rca.py）
- 方向: 自动化 prompt 优化 + few-shot 历史案例注入
- 预期: RCA 准确率 +21%（eARCO 数据）
- **待讨论**: 具体实现方案

### Skills 迭代

- 当前: SkillGapDetector 检测能力缺口
- 方向: 自动创建/更新 Skills，闭环验证
- **待讨论**: Skills 质量保证机制

---

## 参考文献

| # | 论文 | ArXiv ID | 关键贡献 |
|---|------|----------|---------|
| 1 | eARCO: Prompt Optimization for RCA | 2504.11505 | Prompt优化 > RAG > Fine-tuning，+21% |
| 2 | 16 RCA Reasoning Failure Types | 2601.22208 | 48K场景，推理失败可预测 |
| 3 | AI Agents Systematically Fail at Cloud RCA | 2602.09937 | 架构 > 模型，通信协议 -15% 失败 |
| 4 | AIOpsLab: Evaluating AI Agents for Autonomous Cloud | 2501.06706 | Agent评估框架 |
| 5 | Building AI Agents for Autonomous Clouds | 2407.12165 | 设计原则 |
| 6 | AIOps Survey (CSUR 2025) | 2507.12472 | 183篇综述 |
| 7 | mABC: Multi-Agent Blockchain RCA | 2404.12135 | 多Agent投票共识 |
| 8 | RCACopilot (Microsoft) | 2305.15778 | 4年生产RCA |
| 9 | GPT-4 ICL for RCA (10万事故) | 2401.13810 | +24.8% 准确率 |
| 10 | OCEAN: Online Multi-modal RCA | 2410.10021 | 多模态因果 |
| 11 | OpsAgent: Self-evolving | 2510.24145 | 自进化Agent |
| 12 | CCAR: Autonomous Resolution | 2603.08736 | 形式化安全修复边界 |
| 13 | AIDR (Walmart) | 2404.16887 | 3000+模型生产级 |
| 14 | Causal Reasoning Survey | 2408.17183 | Pearl因果86篇综述 |
| 15 | Triage Survey | 2511.08607 | 告警分诊234篇综述 |
| 16 | LogEval Benchmark | 2407.01896 | LLM日志分析评测 |
