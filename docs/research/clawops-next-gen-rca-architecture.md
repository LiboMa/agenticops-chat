# ClawOps 下一代 RCA 架构：Agent-First 探索方向

> **日期**: 2026-03-15
> **作者**: ClawOps Team (Orchestrator Lead)
> **版本**: v1.0

---

## 1. 核心理念：Alert-Driven Agent-First RCA

不依赖预构建的全局服务拓扑图，而是像资深 SRE 一样：**只看到告警，凭经验和推理能力，自主规划调查路径，逐步收集证据，最终定位根因。**

### 感知-规划-决策闭环 (Perceive-Plan-Act)

```
告警 → 感知(Perceive) → 规划(Plan) → 执行(Act) → 验证(Verify) → 沉淀(Learn)
         │                  │              │              │              │
    "发生了什么？"       "该查什么？"     "收集证据"     "结论对吗？"    "记住经验"
         │                  │              │              │              │
    告警解读 +          自主规划        调用 Tools      Devil's        知识库
    历史经验匹配       Action 序列     收集证据链       Advocate       更新
```

### 与传统路线的本质区别

| 维度 | Graph-First (传统) | Agent-First (ClawOps) |
|------|-------------------|----------------------|
| 输入 | 完整服务拓扑 + 全量监控 | 只需告警 + 基础信息源 |
| 前提 | 必须先维护好 CMDB/服务图 | 零前置依赖 |
| 推理 | 图遍历 + 规则关联 | LLM 自主规划 + 经验引导 |
| 类比 | 拿着地图找路 | 像资深 SRE 凭经验排查 |
| 落地门槛 | 高 | 低（有告警就能用） |

---

## 2. 五大探索方向

### 2.1 Prompting 优化

**核心洞察**: eARCO (Microsoft, arXiv:2504.11505) 证明 Prompt 优化 > RAG > Fine-tuning，在 180K 真实事故上准确率提升 21%。

**方案**:
- 自动 Prompt 搜索：参考 PromptWizard/DSPy，从历史 RCA 案例中自动提炼最优 prompt 模板
- Few-shot 历史案例注入：遇到新告警时，自动检索最相似的历史事故作为 context 注入
- 动态 Prompt 组装：根据告警类型（ALB/ECS/RDS/Lambda）选择对应的调查路径模板

**关键点**: Prompt 不是告诉 Agent "答案是什么"，而是告诉它 "最有效的调查路径是什么"。

**论文支撑**:
- eARCO (arXiv:2504.11505, Microsoft 2025) — Prompt 优化在 RCA 中的效果
- GPT-4 In-Context RCA (arXiv:2401.13810, 2024) — 10 万事故 ICL 方法

---

### 2.2 Skills 自动更新与习得

**核心理念**: 每次成功的 RCA 都是一个新的 "调查路径模板"，系统应该自动将其转化为可复用的 Skill。

**方案**:
- Skill Gap Detection：RCA 过程中发现"我没有对应的工具/知识"→ 自动标记缺口
- Skill Auto-Generation：基于成功 RCA 的调查路径，自动生成新的 Skill 定义
- Skill 质量验证：新 Skill 通过 Chaos Lab 场景验证后才入库
- Skill 过期淘汰：基础设施变化后，旧 Skill 自动标记为 deprecated

**演进路径**:
```
手写 Skill → 半自动生成(人工审核) → 全自动生成(AI 审核) → 自我演进
```

**论文支撑**:
- OpsAgent (arXiv:2510.24145, 2025) — 自进化多 Agent 运维
- RCACopilot (arXiv:2305.15778, Microsoft 2023) — 4 年生产系统经验积累

---

### 2.3 知识与经验沉淀

**核心理念**: 组织的运维知识不应该只存在于 SRE 的脑子里，而应该成为 Agent 可检索、可推理的结构化知识。

**方案**:
- Case Study 自动生成：每次 RCA 完成后，自动生成结构化案例（告警 → 调查路径 → 证据链 → 根因 → 修复方案）
- 经验优先级排序：成功率高的调查路径自动提权，失败的降权
- CloudTrail 因果分析：利用 AWS CloudTrail 变更事件作为天然的因果干预数据
- 知识图谱构建：从历史案例中提取 "告警类型 → 最可能根因 → 最优调查路径" 的关联

**ClawOps 现有基础**:
- Memory Fast Path — 已实现经验快速召回
- RCA Learner — 已实现模式提取和周期性反思
- Evidence Hierarchy — 8 级证据权重体系

**论文支撑**:
- Pearl's Causal Framework — 三级因果阶梯（关联 → 干预 → 反事实）
- Causal Reasoning Survey (arXiv:2408.17183, 2024) — 86 篇因果推理综述

---

### 2.4 Agent-First 重规划 + RAC (Reason-Act-Critique)

**核心理念**: Agent 在调查过程中不是线性执行，而是不断 "推理 → 行动 → 自我批评" 的循环，遇到新信息随时调整规划。

**RAC 架构**:
```
┌─────────────────────────────────────────┐
│              RAC 循环                    │
│                                         │
│  Reason(推理)  → Act(执行)  → Critique  │
│     │               │          │        │
│  "基于当前证据    "调用工具     "结论      │
│   我该查什么？"   收集证据"    可靠吗？"   │
│     │               │          │        │
│     └───────────────┘──────────┘        │
│              ↕ 重规划                    │
│  "新证据改变了判断，调整调查方向"           │
└─────────────────────────────────────────┘
```

**与传统 ReAct 的区别**:
- ReAct: Reason → Act → Observe (线性)
- RAC: Reason → Act → **Critique** → **Re-plan** (带自我批评和重规划)

**Critique 环节的关键创新**:
- 独立 Devil's Advocate Agent（不同 prompt 策略，不是同模型自我质疑）
- 推理质量监测器：检测 Stalled/Biased/Confused 信号（来自 arXiv:2601.22208 的 16 类失败分类）
- 置信度校准：每个结论附证据链 + 校准后的置信度分数

**论文支撑**:
- Why Do AI Agents Fail at Cloud RCA (arXiv:2602.09937, 2026) — 架构 > 模型
- 16 类 RCA 推理失败 (arXiv:2601.22208, FORGE 2026) — 失败可预测
- mABC Multi-Agent RCA (arXiv:2404.12135, 2024) — 多 Agent 共识投票

---

### 2.5 结果验证与知识沉淀

**核心理念**: RCA 不以"输出结论"结束，而是以"验证结论 + 沉淀知识"结束。

**验证机制**:
- Evidence Grounding：每个结论必须引用具体的 CloudWatch 数据点
- Counterfactual Check："如果根因没发生，告警还会触发吗？"
- Human-in-the-Loop：置信度 < 阈值时，自动请求人工确认
- 修复验证：执行修复后，监控告警是否消除

**知识沉淀流程**:
```
RCA 完成 → 结果验证 → Case Study 生成 → Skill 更新 → Prompt 模板优化
    │                                                    │
    └──────────────── 下次遇到类似告警直接用 ──────────────┘
```

**论文支撑**:
- CCAR (arXiv:2603.08736, 2026) — 形式化安全修复边界 + 置信度校准
- AIOpsLab (arXiv:2501.06706, Microsoft 2025) — 端到端 Agent 评估框架

---

## 3. 完整架构图

```
                    ┌───────────┐
                    │   告警输入  │
                    └─────┬─────┘
                          │
                ┌─────────▼──────────┐
                │  感知 (Perceive)    │
                │  告警解读 + 经验匹配 │
                │  Memory Fast Path  │
                └─────────┬──────────┘
                          │
                ┌─────────▼──────────┐
                │  规划 (Plan)        │
                │  自主规划调查路径    │
                │  Prompt 优化引导    │
                │  Skills 调度       │
                └─────────┬──────────┘
                          │
              ┌───────────▼───────────┐
              │    RAC 循环            │
              │  ┌──────────────────┐ │
              │  │ Reason → Act →   │ │
              │  │ Critique →       │ │
              │  │ Re-plan          │ │
              │  └──────────────────┘ │
              │  证据收集 + 推理质量监测 │
              └───────────┬───────────┘
                          │
                ┌─────────▼──────────┐
                │  验证 (Verify)      │
                │  Devil's Advocate  │
                │  置信度校准         │
                │  Evidence Grounding│
                └─────────┬──────────┘
                          │
                ┌─────────▼──────────┐
                │  沉淀 (Learn)       │
                │  Case Study 生成   │
                │  Skill 更新        │
                │  Prompt 模板优化   │
                │  知识库更新         │
                └────────────────────┘
```

---

## 4. 实施路线图

| Phase | 时间 | 内容 | 收益 |
|-------|------|------|------|
| **Phase 1** | 2 周 | Prompt 优化 + Few-shot 案例注入 | RCA 准确率 +21% |
| **Phase 2** | 4 周 | RAC 循环 + 推理质量监测器 | 提前拦截错误 RCA |
| **Phase 3** | 6 周 | Devil's Advocate + Skills 自动生成 | 减少幻觉 + 知识积累 |
| **Phase 4** | 8 周 | 完整闭环 + Benchmark 建设 | 端到端评估能力 |

---

## 5. 差异化竞争优势

| 维度 | HolmesGPT | Keep | PagerDuty | ClawOps |
|------|-----------|------|-----------|---------|
| RCA 方式 | 单 Agent + K8s 工具 | 规则引擎 | 统计关联 | **Agent-First RAC** |
| 前置依赖 | K8s 拓扑 | 130+ 集成配置 | 服务图 | **只需告警** |
| 学习能力 | 无 | 无 | 有限 | **自动 Skill 生成** |
| 验证机制 | 无 | 无 | 无 | **Devil's Advocate** |
| Prompt 优化 | 无 | 无 | 无 | **自动优化 + Few-shot** |
| 知识沉淀 | 无 | 无 | 有限 | **Case Study + Memory** |

---

## 6. 参考论文

| # | 论文 | ArXiv ID | 年份 | 关键贡献 |
|---|------|----------|------|---------|
| 1 | eARCO: Prompt Optimization for RCA | 2504.11505 | 2025 | Prompt 优化 > RAG > Fine-tuning, 180K 事故 |
| 2 | Stalled, Biased, and Confused: 16 RCA Failure Types | 2601.22208 | 2026 | 48K 场景, 推理失败可预测 |
| 3 | Why Do AI Agents Fail at Cloud RCA | 2602.09937 | 2026 | 12 种 Agent 失败类型, 架构 > 模型 |
| 4 | AIOpsLab: Agent Evaluation Framework | 2501.06706 | 2025 | 端到端 Agent 评估框架 |
| 5 | mABC: Multi-Agent Blockchain-Inspired RCA | 2404.12135 | 2024 | 多 Agent 共识投票 |
| 6 | RCACopilot (Microsoft) | 2305.15778 | 2023 | 4 年生产 RCA 系统 |
| 7 | GPT-4 In-Context RCA | 2401.13810 | 2024 | 10 万事故, 准确率 +43.5% |
| 8 | OpsAgent: Self-Evolving Multi-Agent | 2510.24145 | 2025 | 自进化多 Agent 运维 |
| 9 | CCAR: Confidence-Calibrated Resolution | 2603.08736 | 2026 | 形式化安全修复边界 |
| 10 | Causal Reasoning in Software QA | 2408.17183 | 2024 | 86 篇因果推理综述 |
| 11 | AIDR (Walmart) | 2404.16887 | 2024 | 3000+ 模型生产级告警 |
| 12 | Pearl, J. — Causality (2009) | - | 2009 | 因果推断理论基础 |

---

*ClawOps Team — Orchestrator (Lead), Architect, Researcher, Developer, Tester*
