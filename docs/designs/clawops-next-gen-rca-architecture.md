# ClawOps Next-Gen RCA Architecture
## Agent-First 感知-规划-决策 + 知识自进化闭环

> **日期**: 2026-03-15 | **团队**: ClawOps Research Team | **版本**: v1.0

---

## Executive Summary

基于团队深度调研（16+ 篇前沿论文）和 ClawOps 实战经验（3500+ tests, 93% coverage），我们提出 **Agent-First RCA** 架构——从传统的 Graph-Driven pipeline 转向告警驱动的自主探索模式，结合 Prompt 自动优化、Skills 自动习得、知识闭环验证，构建 L5 Self-Improving Ops Platform。

---

## 1. 核心架构：Agent-First 感知-规划-决策

### 设计哲学

**不要让 SRE 知道所有服务的状态和拓扑图。只给告警和基础信息源，让 Agent 自己规划调查路径。**

这与 arXiv:2602.09937 的核心发现一致：**架构设计 > 模型能力 > Prompt 工程**。

### 架构对比

- **传统 Graph-Driven RCA**: 预构建拓扑图 → 告警 → 图上关联 → RCA（重、脆弱、维护成本高）
- **Agent-First RCA**: 告警 → 感知 → 规划 → 执行 → 决策（轻、灵活、像真人 SRE）

### RAC 循环（Reason-Act-Confirm）

- **Reason（推理）**: Agent 基于告警 + 历史经验 + LLM 推理，规划调查路径
- **Act（行动）**: Agent 主动调用工具（CloudWatch/CloudTrail/X-Ray API）采集证据
- **Confirm（验证）**: 独立验证器检查推理质量 + 证据完整性 + 结论可靠性
- 循环迭代直到置信度达标或触发人工介入

### 差异化优势

- 零前置依赖：不需要预建拓扑图
- 按需探索：Agent 自主决定查什么
- 经验驱动：历史案例直接加速下次调查
- AWS 原生：CloudWatch + CloudTrail + X-Ray 数据充足

---

## 2. Prompt 自动优化

### 核心论据

**eARCO (arXiv:2504.11505, Microsoft Research, 2025)**:
- 在 180,000+ 微软真实事故上验证
- **Prompt 优化 > RAG (+21%) > Fine-tuning (+13%)**
- 使用 PromptWizard 自动搜索最优 prompt

### 在 Agent-First 中的角色

Prompt 优化直接决定 **"规划"环节的质量**：

- 手写 prompt: "分析这个告警" → Agent 漫无目的
- 优化 prompt: "ALB 5xx 告警，历史 85% 根因在 target group。先查 TG → ECS task → 网络" → Agent 有方向

### 落地方案

- **Phase 1**: 基于历史 RCA 案例，自动提取最优调查路径模板
- **Phase 2**: 实现 few-shot 动态注入——每次 RCA 自动检索最相似历史案例作为 prompt context
- **Phase 3**: 自动化 prompt A/B testing——同一告警用不同 prompt 策略，比较 RCA 质量

---

## 3. Skills 自动习得与更新

### 设计理念

每一次成功的 RCA 都是一个新的 Skill。系统应自动将调查路径固化为可复用的 Skill，并在新证据出现时自动更新。

### Skill 生命周期

- **发现**: SkillGapDetector 检测 Agent 在某类告警上的能力缺口
- **创建**: 从成功 RCA 的调查路径自动生成 Skill 模板（SOPAutoWriter）
- **验证**: 新 Skill 在历史案例上回测，确认有效性
- **应用**: Agent 在规划阶段自动匹配最相关 Skill
- **更新**: 基于新案例的结果反馈，自动修正 Skill（revision-first learning）
- **淘汰**: 长期未使用或验证失败的 Skill 自动降权/归档

### 与 Memory 的协同

- **Episodic Memory**: 记录每次 RCA 的完整调查路径
- **Procedural Memory**: Skills 就是固化的 Procedural Memory
- **Semantic Memory**: 故障模式的抽象知识（"ALB 5xx 通常与 target group 相关"）
- **Reflection Memory**: 定期反思哪些 Skills 有效、哪些需要更新

### 论文支撑

- **OpsAgent (arXiv:2510.24145)**: 双重自进化机制（内部模型更新 + 外部经验积累）
- **16类推理失败 (arXiv:2601.22208)**: Skills 可以编码"避免某类推理失败"的规则

---

## 4. 知识经验沉淀体系

### 三层知识架构

- **L1 即时知识 (Hot)**: 当前 RCA session 中采集的证据和推理链——Evidence Chain
- **L2 经验知识 (Warm)**: 历史 RCA 案例库——Memory Fast Path + RCA Learner patterns
- **L3 结构化知识 (Cold)**: 故障模式知识图谱——因果关系 + 修复方案 + 验证标准

### 知识质量保证

- **写入前验证**: RCA 结论必须附带证据链，无证据不入库
- **事后验证**: PostActionValidator 检查修复结果，反向更新知识置信度
- **交叉验证**: 多个 Agent 独立 RCA，共识结论才写入知识库
- **衰减机制**: decayed_confidence 时间衰减 + 使用频率加权

### 论文支撑

- **GPT-4 ICL (arXiv:2401.13810)**: 10 万事故数据的 few-shot learning，+24.8% 准确率
- **RCACopilot (arXiv:2305.15778)**: Microsoft 4 年生产 RCA 系统的知识积累经验
- **Pearl 因果框架**: CloudTrail 变更事件 = 天然的因果干预数据

---

## 5. 结果验证 + 知识闭环

### PostActionValidator 架构

- **输入**: 修复动作 + VerificationSpec（目标指标 + 阈值）
- **判定四态**: SUCCESS / PARTIAL_SUCCESS / FAILED / UNCERTAIN
- **观察窗口**: T0=30s, T1=2min, T2=5min, T3=15min

### 闭环流程

- 1. RCA 完成 → 生成修复建议 + VerificationSpec
- 2. 修复执行（按 L0-L3 安全分级）
- 3. PostActionValidator 在观察窗口内验证结果
- 4. SUCCESS → reinforce 知识（+confidence）
- 5. FAILED → penalize 知识（-confidence）+ 自动回滚
- 6. PARTIAL_SUCCESS → 保留知识但标记需 review

### 修复安全分级（L0-L3）

| 级别 | 操作范围 | 审批要求 | 示例 |
|------|---------|---------|------|
| L0 | 只输出建议 | 无 | "建议重启服务 X" |
| L1 | 只读诊断 | 无 | describe-instances, get-metrics |
| L2 | 预批准安全操作 | 自动 | 重启服务、增加实例 |
| L3 | 配置变更 | 沙箱+人工 | Security Group 修改 |

### 论文支撑

- **CCAR (arXiv:2603.08736)**: 首个形式化安全修复边界框架，78% 自主修复率
- **AIOpsLab (arXiv:2501.06706)**: 端到端 Agent 评估，含修复验证环节

---

## 6. 整体架构图

### Agent-First RCA + 知识自进化闭环

```
告警输入
  │
  ▼
┌────────────────────────────┐
│  感知层 (Perceive)          │
│  告警解析 + 上下文提取        │
│  Memory Fast Path 快速匹配   │
└────────────┬───────────────┘
             │
             ▼
┌────────────────────────────┐
│  规划层 (Plan)              │
│  Prompt 自动优化             │  ◄── Skills 库
│  历史案例 few-shot 注入       │  ◄── Episodic Memory
│  调查路径规划                 │
└────────────┬───────────────┘
             │
             ▼
┌────────────────────────────┐
│  执行层 (Act)               │
│  CloudWatch Metrics/Logs    │
│  CloudTrail 变更事件         │
│  X-Ray Traces              │
│  Evidence 采集 + 加权        │
└────────────┬───────────────┘
             │
             ▼
┌────────────────────────────┐
│  决策层 (Decide)            │
│  RCA 结论 + 证据链           │
│  推理质量监测器               │  ◄── 16类失败检测
│  修复建议 + L0-L3 分级        │
└────────────┬───────────────┘
             │
             ▼
┌────────────────────────────┐
│  验证层 (Verify)            │
│  PostActionValidator        │
│  SUCCESS/FAILED/PARTIAL     │
└────────────┬───────────────┘
             │
             ▼
┌────────────────────────────┐
│  知识沉淀 (Learn)           │
│  reinforce / penalize       │
│  Skill 创建/更新/淘汰         │
│  Knowledge Graph 更新        │
└─────────────────────────────┘
```

---

## 7. 路线图

### Phase 1: Agent-First MVP (4 weeks)

- 重构 deep_rca.py: pipeline → ReAct loop
- Evidence gatherers 补齐 trace + logs
- 基于历史案例的 few-shot prompt 注入
- 推理质量监测器 v1

### Phase 2: Skills 自动习得 (4 weeks)

- Skill 自动生成（从成功 RCA 提取）
- Skill 验证（历史案例回测）
- Skill 匹配（规划阶段自动选择）

### Phase 3: 闭环验证 (3 weeks)

- PostActionValidator 实现
- L0-L2 安全修复
- 知识 reinforce/penalize 机制

### Phase 4: Prompt 自动优化 (3 weeks)

- Prompt A/B testing 框架
- 自动化 prompt 搜索（参考 PromptWizard/DSPy）
- 持续优化 pipeline

---

## 参考论文

| # | 论文 | ArXiv ID | 年份 | 关键贡献 |
|---|------|----------|------|---------|
| 1 | eARCO: Prompt Optimization for Cloud RCA | 2504.11505 | 2025 | Prompt优化 > RAG > Fine-tuning, +21% |
| 2 | Stalled, Biased, Confused: 16 RCA Reasoning Failures | 2601.22208 | 2026 | 48K场景推理失败分类，失败可预测 |
| 3 | Why AI Agents Systematically Fail at Cloud RCA | 2602.09937 | 2026 | 架构 > 模型，通信协议 -15% 失败 |
| 4 | AIOpsLab: Evaluating AI Agents for Autonomous Cloud | 2501.06706 | 2025 | 端到端Agent评估框架 |
| 5 | OpsAgent: Self-Evolving Diagnosis | 2510.24145 | 2025 | 双重自进化多Agent运维 |
| 6 | CCAR: Confidence-Calibrated Autonomous Resolution | 2603.08736 | 2026 | 形式化安全修复边界 |
| 7 | GPT-4 In-Context Learning for RCA | 2401.13810 | 2024 | 10万事故ICL, +24.8% |
| 8 | RCACopilot (Microsoft) | 2305.15778 | 2023 | 4年生产RCA系统 |
| 9 | mABC: Multi-Agent Blockchain RCA | 2404.12135 | 2024 | 多Agent投票共识 |
| 10 | OCEAN: Online Multi-Modal RCA | 2410.10021 | 2024 | 跨模态因果建模 |
| 11 | AIOps Survey (CSUR 2025) | 2507.12472 | 2025 | 183篇综述 |
| 12 | Building AI Agents for Autonomous Clouds | 2407.12165 | 2024 | Agent设计原则 |
| 13 | Causal Reasoning in Software QA | 2408.17183 | 2024 | Pearl因果86篇综述 |
| 14 | AIDR (Walmart Production) | 2404.16887 | 2024 | 3000+模型生产级告警 |
| 15 | LogEval: LLM Log Analysis Benchmark | 2407.01896 | 2024 | LLM日志分析评测 |
| 16 | Triage in Software Engineering | 2511.08607 | 2025 | 告警分诊234篇综述 |
