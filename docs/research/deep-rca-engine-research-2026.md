# ClawOps Deep RCA Engine — 前沿架构调研报告

> **日期**: 2026-03-15
> **参与者**: Orchestrator (Lead), Architect, Researcher, Developer, Tester
> **状态**: 团队共识已达成，待 Ma Ronnie 确认方向

---

## 1. 背景

Ma Ronnie 要求对 ClawOps Deep RCA Engine 做深度调研，要求：
- ✅ 可落地（基于现有代码 + AWS Bedrock）
- ✅ 有商业前景（客户愿意买单）
- ✅ 差异化（不重复 HolmesGPT/Keep/PagerDuty/Datadog）
- ✅ 轻量级（快速 MVP）

Ma Ronnie 确认：ClawOps 之前的项目就是按照 AIOpsLab 的思路进行的。

---

## 2. 现有代码分析

### 2.1 RCA 引擎现状 (src/agenticops/analyze/, 1,428 行)

| 文件 | 行数 | 功能 |
|------|------|------|
| rca.py | 344 | 基础 RCA — 单次 LLM prompt + 异常/指标上下文 |
| deep_rca.py | 609 | Deep RCA — 7 步流程：记忆召回 → 图增强 → KB 搜索 → 迭代 LLM (最多 3 轮) → 自验证 (Voyager CriticAgent) → WAL 写入 → CaseStudy 捕获 |
| rca_learner.py | 227 | 事后学习 — 模式提取、技能缺口检测、周期性反思 |
| evidence.py | 248 | 证据收集器，带源加权置信度 (CloudTrail: 0.95, Trace: 0.9, CW: 0.85) |

### 2.2 现有优势（已领先 HolmesGPT/Keep）

- 7 步 Deep RCA + 记忆 + 图 + KB + 迭代调查
- 自验证 (Voyager CriticAgent 模式) — AIOps 领域独特
- 证据链 + 加权置信度 — 量化推理
- 学习闭环 (RCALearner) + 技能缺口检测
- 图拓扑上下文（爆炸半径、依赖关系）
- `@secure_tool` + T0-T3 安全分级体系
- 3,503 tests / 93% 覆盖率 — 测试基础设施成熟

### 2.3 当前缺口

- `trace` 和 `logs` 证据收集器是占位符 (TODO stubs)
- 无因果图 — 拓扑图捕获结构但非因果
- 自验证用同一模型挑战自己（弱对抗）
- 模式匹配基于关键词 (`_categorize_root_cause` — 8 个硬编码类别)
- 无反事实推理（"如果 X 没变，还会故障吗？"）

---

## 3. 竞品分析

### 3.1 HolmesGPT
- **优势**: YAML 定义工具集 + 三层上下文管理 + LLM 压缩 + K8s 深度集成
- **劣势**: 单 Agent 推理，无学习闭环，K8s 专精（不通用）
- **启发**: per-tool output transformer、重复调用检测、公平分配截断

### 3.2 Keep
- **优势**: 130+ 集成 Provider Factory、告警管道工作流引擎
- **劣势**: LLM 仅用于摘要/关联（非核心），RCA 能力弱
- **启发**: Provider 自动发现模式、告警去重指纹

### 3.3 PagerDuty / Datadog
- **优势**: 企业级、大规模、丰富的集成
- **劣势**: RCA 依赖规则引擎 + 简单关联，非因果推断
- **我们的差异化**: LLM Agent 因果推理 + 证据链 + 学习闭环

---

## 4. AIOps 核心难题排序（团队共识）

| 排名 | 难题 | 本质 | ClawOps 现状 |
|------|------|------|-------------|
| **#1** | 自动修复安全边界 | 信任问题，行业无标准 | `@secure_tool` + T0-T3 已在构建 |
| **#2** | 因果推断准确性 | 从相关性→因果链是数学难题 | 已有 Bedrock RCA，需提升因果能力 |
| **#3** | 知识闭环演化 | 学习容易，遗忘和纠错难 | RCA Learner + SOPAutoWriter 在做 |
| **#4** | 评估标准缺失 | 不知道自己做得好不好 | Chaos Lab + 5 scenario 可建 benchmark |

**排除项**: 数据源/可观测性 — AWS CloudWatch 生态下不是瓶颈。

**核心洞察**: 因果推理可以渐进改善，但自动修复信任没有渐进路径 — 这是 L4→L5 的真正鸿沟。

---

## 5. 关键论文解读（5 篇）

### 5.1 eARCO — Prompt 优化做 RCA (arXiv:2504.11505, Microsoft, 2025)

**核心发现**: Prompt 优化 > RAG > Fine-tuning，在 180K+ 微软真实事故上验证，准确率提升 21%。

**对 ClawOps 的意义**: 
- 最直接可落地！不需要 fine-tuning，只需要做 prompt 优化 + few-shot 历史案例注入
- 结合 Memory Fast Path + RCA Learner 逻辑一致
- **投入产出比最高的改进**

### 5.2 16 类 RCA 推理失败 (arXiv:2601.22208, FORGE 2026)

**核心发现**: 6 个 LLM × 48,000 故障场景，建立 16 类推理失败分类法（Stalled/Biased/Confused）。某些早期推理模式可以预测最终结果是否正确。

**对 ClawOps 的意义**:
- 16 类失败分类可直接作为 RCA quality checklist
- "推理失败可预测" = 可以在 RCA 过程中实时监测推理质量
- 在 `deep_rca.py` 迭代循环中增加 reasoning quality monitor

### 5.3 AI Agent 系统性 RCA 失败 (arXiv:2602.09937, 2026)

**核心发现**: 12 种失败类型，最常见的两种（幻觉数据解读 + 探索不完整）在所有模型上都出现。问题在架构，不在模型。改进 Agent 间通信协议能减少通信类失败 15%。

**对 ClawOps 的意义**:
- 自验证用同一模型是"弱对抗" — 需引入独立 verification agent
- 架构改进比换模型更有效

### 5.4 AIOpsLab — Agent 评估框架 (arXiv:2501.06706, Microsoft, 2025)

**核心发现**: 第一个完整 AIOps Agent 评估框架，提出 AgentOps 概念。当前 Agent 能处理简单故障，复杂多步骤故障表现差。

**对 ClawOps 的意义**:
- Ma Ronnie 确认 ClawOps 之前就按 AIOpsLab 思路做的
- 先用自有 Chaos Lab + 5 scenario 建 benchmark，不等外部框架

### 5.5 Pearl 因果推断框架

**核心概念**: 三级因果阶梯 — 关联(Seeing) → 干预(Doing) → 反事实(Imagining)。

**对 ClawOps 的意义**:
- 当前 Deep RCA 做的是第 1 级（指标关联 + LLM 推理）
- CloudTrail 变更事件 = 天然的因果干预数据（API 调用 = do 操作）
- 下一步：CloudTrail 变更 + 指标异常的因果关联分析 — **差异化竞争优势**

---

## 6. 差异化方案：Evidence-First Causal RCA

### 6.1 核心理念

**不是先推理再找证据，而是先收集证据再构建因果链 — "法庭审判模式"**

| 维度 | 方案 |
|------|------|
| **创新点** | Multi-Agent 证据对质 + 共识投票 + CloudTrail 因果分析 |
| **轻量级** | 基于现有 evidence.py + deep_rca.py 扩展，不重写 |
| **差异化** | HolmesGPT = 单 Agent；我们 = 证据优先 + 双 Agent 对质 + 因果 |
| **商业价值** | MTTR 25min → 5min，每个结论附证据链（可审计 = 企业买单）|

### 6.2 技术架构

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
       │  (Claude Bedrock)│
       └────────┬────────┘
                │
       ┌────────▼────────┐
       │  Devil's Advocate│ ← 独立验证 Agent（不同 prompt 策略）
       │  (质疑 + 反事实) │
       └────────┬────────┘
                │
       ┌────────▼────────┐
       │  Confidence      │ ← 置信度校准 + Grounding 检查
       │  Calibrator      │
       └────────┬────────┘
                │
       ┌────────▼────────┐
       │  Remediation     │ ← L0-L2: 建议 → 确认 → 执行
       │  Advisor         │
       └─────────────────┘
```

### 6.3 MVP 路线图

| Phase | 时间 | 内容 | 基于现有代码 |
|-------|------|------|-------------|
| **Phase 1** | 2 周 | Prompt 优化 + Few-shot 历史案例注入 | 修改 rca.py / deep_rca.py 的 prompt |
| **Phase 2** | 4 周 | 证据链强制输出 + 推理质量监测器 | 扩展 evidence.py + deep_rca.py |
| **Phase 3** | 6 周 | Devil's Advocate Agent + CloudTrail 因果分析 | 新增 verification agent |
| **Phase 4** | 8 周 | 渐进自治 L0→L2 + Benchmark 建设 | 扩展 @secure_tool |

---

## 7. 优先级行动清单

| 优先级 | 来源 | 行动 | 难度 | 预期收益 |
|--------|------|------|------|---------|
| 🥇 #1 | eARCO | Prompt 自动优化 + few-shot 历史案例注入 | 低 | RCA 准确率 +21% |
| 🥈 #2 | 16类推理失败 | 在迭代循环中增加推理质量监测器 | 中 | 提前拦截错误 RCA |
| 🥉 #3 | Agent系统性失败 | 独立 verification agent（不同模型/prompt） | 中 | 减少幻觉和探索不完整 |
| 4 | Pearl因果框架 | CloudTrail 变更事件因果分析 | 高 | 差异化竞争优势 |
| 5 | AIOpsLab | 自有 Chaos Lab 建 benchmark | 中 | 长期评估基础 |

---

## 8. 待讨论事项

1. **客户场景选择**: AWS-native (A) / K8s (B) / Multi-cloud (C) / MVP 先 A 后扩展 (D)？
2. **Prompt 优化策略**: 参考 PromptWizard 还是 DSPy？
3. **Skills 迭代方向**: 如何结合 RCA Learner 的 skill gap detection 做自动化 skill 演进？

---

## 参考文献

| # | 论文 | ArXiv ID | 年份 | 关键贡献 |
|---|------|----------|------|---------|
| 1 | eARCO: Prompt Optimization for RCA | 2504.11505 | 2025 | Prompt优化>RAG>Fine-tuning |
| 2 | Stalled, Biased, and Confused | 2601.22208 | 2026 | 16类RCA推理失败分类 |
| 3 | Why Do AI Agents Fail at Cloud RCA | 2602.09937 | 2026 | 12种Agent失败类型 |
| 4 | AIOpsLab | 2501.06706 | 2025 | Agent评估框架 |
| 5 | mABC: Multi-Agent RCA | 2404.12135 | 2024 | 多Agent+投票共识 |
| 6 | RCACopilot (Microsoft) | 2305.15778 | 2023 | 4年生产RCA系统 |
| 7 | GPT-4 In-Context RCA | 2401.13810 | 2024 | 10万事故ICL RCA |
| 8 | OCEAN: Online Multi-modal RCA | 2410.10021 | 2024 | 多模态在线RCA |
| 9 | OpsAgent | 2510.24145 | 2025 | 自进化多Agent运维 |
| 10 | CCAR: Confidence-Calibrated Resolution | 2603.08736 | 2026 | 形式化安全修复边界 |
| 11 | AIDR (Walmart) | 2404.16887 | 2024 | 生产级告警系统 |
| 12 | Causal Reasoning Survey | 2408.17183 | 2024 | 86篇因果推理综述 |
| 13 | Building AI Agents for Clouds | 2407.12165 | 2024 | Agent设计原则 |
| 14 | AIOps LLM Survey | 2507.12472 | 2025 | 183篇论文综述 |
| 15 | AIOps Failure Management Survey | 2406.11213 | 2024 | LLM时代AIOps综述 |
| 16 | Autonomous Cloud Security | 2601.03303 | 2026 | 自主威胁响应 |

---

*报告由 ClawOps 团队协作完成：Orchestrator (Lead), Architect (调研报告), Researcher (论文解读), Tester (评审), Developer (代码分析)*
