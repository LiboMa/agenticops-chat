# ClawOps 下一代 RCA 架构：Agent-First 探索方向

## 核心理念：像 SRE 一样思考

- **告警驱动**：不依赖预构建的服务拓扑图
- **自主规划**：凭经验和推理能力，规划调查路径
- **逐步排查**：收集证据 → 推理 → 验证 → 沉淀
- **类比**：资深 SRE 看到告警后的思维过程

## 感知-规划-决策闭环

- **感知 (Perceive)**：告警解读 + 历史经验匹配 (Memory Fast Path)
- **规划 (Plan)**：自主规划调查路径 + Prompt 优化引导 + Skills 调度
- **执行 (Act)**：调用 Tools 收集证据 (CloudWatch/CloudTrail/X-Ray)
- **验证 (Verify)**：Devil's Advocate + 置信度校准 + Evidence Grounding
- **沉淀 (Learn)**：Case Study 生成 + Skill 更新 + Prompt 模板优化

## 与传统路线的区别

| 维度 | Graph-First (传统) | Agent-First (ClawOps) |
|------|-------------------|----------------------|
| 输入 | 完整服务拓扑 + 全量监控 | 只需告警 + 基础信息源 |
| 前提 | 必须维护 CMDB/服务图 | 零前置依赖 |
| 推理 | 图遍历 + 规则关联 | LLM 自主规划 + 经验引导 |
| 落地门槛 | 高 | 低（有告警就能用） |

## 方向 1：Prompting 优化

- **eARCO (Microsoft)**: Prompt 优化 > RAG > Fine-tuning，准确率 +21%
- 自动 Prompt 搜索：从历史案例中提炼最优调查路径模板
- Few-shot 注入：遇到新告警，自动检索最相似历史事故作为 context
- 动态组装：根据告警类型选择对应调查路径模板
- **关键**: Prompt 不是告诉 Agent 答案，而是告诉它最有效的调查路径

## 方向 2：Skills 自动更新与习得

- Skill Gap Detection：RCA 中发现"没有对应工具/知识"→ 自动标记缺口
- Skill Auto-Generation：基于成功 RCA 自动生成新 Skill
- Skill 质量验证：新 Skill 通过 Chaos Lab 验证后才入库
- Skill 过期淘汰：基础设施变化后自动标记 deprecated
- **演进**: 手写 → 半自动(人审核) → 全自动(AI审核) → 自我演进

## 方向 3：知识与经验沉淀

- Case Study 自动生成：告警 → 调查路径 → 证据链 → 根因 → 修复方案
- 经验优先级排序：成功率高的调查路径提权，失败的降权
- CloudTrail 因果分析：AWS 变更事件 = 天然因果干预数据 (Pearl 框架)
- **现有基础**: Memory Fast Path + RCA Learner + 8 级 Evidence Hierarchy

## 方向 4：RAC 架构 (Reason-Act-Critique)

- **Reason (推理)**: 基于当前证据，决定下一步查什么
- **Act (执行)**: 调用工具收集证据
- **Critique (批评)**: 结论可靠吗？有没有遗漏？
- **Re-plan (重规划)**: 新证据改变判断，调整调查方向
- **vs ReAct**: 增加了自我批评 + 动态重规划
- **支撑**: 推理质量监测器检测 Stalled/Biased/Confused 信号

## 方向 5：结果验证 + 知识沉淀

- Evidence Grounding：每个结论必须引用具体 CloudWatch 数据点
- Counterfactual Check："如果根因没发生，告警还会触发吗？"
- Human-in-the-Loop：置信度 < 阈值时请求人工确认
- **完整闭环**: RCA → 验证 → Case Study → Skill 更新 → Prompt 优化 → 下次更快

## 差异化竞争优势

| 维度 | HolmesGPT | Keep | PagerDuty | ClawOps |
|------|-----------|------|-----------|---------|
| RCA 方式 | 单 Agent | 规则引擎 | 统计关联 | Agent-First RAC |
| 前置依赖 | K8s 拓扑 | 130+ 集成 | 服务图 | 只需告警 |
| 学习能力 | 无 | 无 | 有限 | 自动 Skill 生成 |
| 验证机制 | 无 | 无 | 无 | Devil's Advocate |
| Prompt 优化 | 无 | 无 | 无 | 自动优化+Few-shot |

## 实施路线图

| Phase | 时间 | 内容 | 收益 |
|-------|------|------|------|
| Phase 1 | 2 周 | Prompt 优化 + Few-shot | 准确率 +21% |
| Phase 2 | 4 周 | RAC 循环 + 推理监测 | 拦截错误 RCA |
| Phase 3 | 6 周 | Devil's Advocate + Skills 自动生成 | 减少幻觉 |
| Phase 4 | 8 周 | 完整闭环 + Benchmark | 端到端评估 |

## 核心参考论文

| 论文 | ID | 关键贡献 |
|------|------|---------|
| eARCO (Microsoft 2025) | arXiv:2504.11505 | Prompt优化>RAG>Fine-tuning |
| 16 RCA Failure Types (2026) | arXiv:2601.22208 | 48K场景, 推理失败可预测 |
| AI Agents Fail at RCA (2026) | arXiv:2602.09937 | 架构>模型, 12种失败类型 |
| AIOpsLab (Microsoft 2025) | arXiv:2501.06706 | Agent评估框架 |
| mABC Multi-Agent RCA (2024) | arXiv:2404.12135 | 多Agent共识投票 |
| CCAR (2026) | arXiv:2603.08736 | 置信度校准+安全修复边界 |
| OpsAgent (2025) | arXiv:2510.24145 | 自进化多Agent运维 |
| Pearl Causality (2009) | - | 因果推断理论基础 |
