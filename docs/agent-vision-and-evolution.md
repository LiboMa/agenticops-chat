# AgenticOps: Agent 架构愿景与自我进化路线图

> 内部讨论总结 | 日期: 2026-02-13
> 背景: Phase 0+1 实施后，对 Agent 架构的价值、LLM 升级路径、自我进化能力的深度讨论

---

## 1. 架构对比：Legacy 路径 vs Agent 路径

### Legacy 路径（`aiops run scan/detect`）

固定管线，确定性执行：

```
用户输入命令 → 固定代码路径 → 固定输出
```

能力边界：只能做代码预定义的事。检测逻辑写死了，输出格式写死了，流程写死了。

### Agent 路径（`aiops chat` → Strands Multi-Agent）

LLM 驱动的动态工作流：

```
用户自然语言 → LLM 推理 → 动态选择工具 → 动态决定下一步 → 综合分析输出
```

---

## 2. Agent 路径的六大核心优势

### 2.1 动态工作流编排

Legacy 的 detect 对每个资源做完全相同的事。Agent 可以按情况调整策略：

```
用户: "我的订单服务好像有问题"

Agent 推理过程:
  → get_managed_resources(resource_type="Lambda") — 先找相关资源
  → list_alarms(region="us-east-1", state="ALARM") — 被动检查
  → 发现 Lambda order-processor 有 ALARM
  → get_metrics("order-processor", "Lambda", "us-east-1", hours=6) — 拉详细数据
  → query_logs("/aws/lambda/order-processor", "us-east-1") — 查错误日志
  → lookup_cloudtrail_events("order-processor", "us-east-1") — 查最近变更
  → 发现 2 小时前有代码部署
  → create_health_issue(..., related_changes=[部署事件])
  → 综合分析: "order-processor Lambda 在 2 小时前部署后错误率飙升..."
```

Legacy 做不到：不会因为发现部署事件而去拉 CloudTrail，也不会把日志和 metric 关联分析。

### 2.2 跨 Agent 协作

Main Agent 可以编排多步工作流：

```
用户: "全面检查一下我的环境"

Main Agent:
  → scan_agent(services="all", regions="all")    — 先更新资源清单
  → detect_agent(scope="all", deep=False)         — 再做健康检查
  → 综合两者结果: "发现 47 个资源，其中 3 个有告警，2 个缺少监控..."
```

Legacy 需要用户手动跑多个命令并自己关联结果。

### 2.3 自然语言理解 + 模糊意图处理

```
Legacy:  用户必须知道 aiops run detect --type EC2 --region us-east-1
Agent:   "检查一下东京区域的数据库有没有问题"
         → LLM 理解 "东京" = ap-northeast-1, "数据库" = RDS
```

### 2.4 错误恢复和自适应

```
Agent 调用 describe_ec2("ap-south-2") → 返回 "Error: region not enabled"
  → LLM 理解这不是程序崩溃，而是该区域未开通
  → 跳过该区域，继续扫描其他区域
  → 最终报告: "扫描了 5 个区域，ap-south-2 未开通已跳过"

Legacy: 抛异常或静默跳过，不会解释原因
```

### 2.5 知识库集成

```
detect_agent 发现 RDS connections 告警
  → rca_agent:
      search_sops("RDS", "connection exhausted") → 找到 SOP
      按 SOP 步骤逐一验证:
        1. 检查 max_connections 参数
        2. 检查连接池配置
        3. 检查 CloudTrail 是否有参数组变更
      → 生成结构化 RCA 报告 + 修复建议

Legacy: 只能说 "DatabaseConnections > 100, severity=MEDIUM"
```

### 2.6 可扩展性

添加新能力 = 添加一个 `@tool`，不需要改管线逻辑：

```python
@tool
def check_cost_anomaly(resource_id: str, region: str) -> str:
    """Check if a resource has unusual cost spikes."""
    ...

# 用户: "我的 RDS 成本是不是涨了？" → Agent 自动选择 check_cost_anomaly
```

Legacy 需要写新的 pipeline、新的 CLI 命令、新的调用链。

---

## 3. LLM 模型升级 → Agent 输出质量自动提升

Agent 架构本质上是 **推理层（LLM）+ 执行层（Tools）** 的分离：

```
用户请求 → LLM 推理（选工具、定策略、理解上下文）→ Tool 执行（确定性代码）→ LLM 综合（分析、总结）
              ↑ 随模型升级而提升                          ↑ 不变
```

### 随 LLM 升级自动提升的维度

| 能力维度 | 提升？ | 具体表现 |
|---------|:---:|---|
| 工具选择准确性 | Yes | 更强的模型更少选错工具、更少遗漏步骤 |
| 多步推理规划 | Yes | 能编排更长、更复杂的工作流 |
| 错误理解与恢复 | Yes | 看到 "AccessDenied" 能判断是权限问题而非资源不存在 |
| 结果综合分析 | Yes | 从 metrics + logs + CloudTrail 中提炼更准确的根因判断 |
| 大上下文处理 | Yes | 不会截断或丢失大 JSON 数据 |
| 模糊意图理解 | Yes | "数据库最近不太对" → 准确映射到 RDS + 正确的检测策略 |

### 不随 LLM 变化的维度

| 能力维度 | 提升？ | 原因 |
|---------|:---:|---|
| AWS API 返回数据 | No | describe_ec2 返回什么就是什么，跟模型无关 |
| 统计检测精度 | No | z-score 算法是确定性代码 |
| 规则引擎判断 | No | CPU>90%=CRITICAL 是硬编码规则 |

### 关键设计原则

只需改一行 config 就能升级模型，所有 agent 的 system prompt、tool 定义、工作流结构都不需要改：

```python
# config.py — 换模型，整个系统推理能力立刻升级
bedrock_model_id: str = "global.anthropic.claude-opus-4-6-v1"
```

**这是 Agent 架构的核心投资价值 — 架构工作不会过时，只会随模型进步而增值。**

---

## 4. 自我进化能力路线图

### 层次 1：知识积累（Phase 2-3）— Knowledge Flywheel

```
检测问题 → RCA 分析 → 解决问题 → Reporter 生成案例 → 写入 KB
    ↑                                                      ↓
    ← ← ← ← RCA Agent 查询 KB 找到类似案例 ← ← ← ← ← ←
```

具体演进：

```
第 1 次: RDS 连接耗尽
  → RCA Agent 查 KB → 没有历史案例
  → LLM 从零推理 → 置信度 0.6
  → 解决后 Reporter 生成案例 → 写入 cases/rds-conn-exhaust-001.md

第 2 次: 另一个 RDS 连接耗尽
  → RCA Agent 查 KB → 找到上次的案例
  → LLM 参考历史案例 + 当前数据 → 置信度 0.9
  → 诊断速度更快，建议更准确

第 N 次:
  → KB 里有 N-1 个案例 + 成熟的 SOP
  → 几乎可以直接按 SOP 执行
```

这不是 LLM 自身在进化，而是系统的知识上下文在增长。LLM 的能力是固定的，但给它的参考资料越来越丰富。

### 层次 2：反馈学习（Phase 4-5）

基于 `RCAResult.user_feedback: thumbs_up/thumbs_down` 建立反馈回路：

```
RCA 输出建议 → 用户标记好/坏
  → 好评案例权重更高，差评案例被标注为低质量
  → 下次类似问题，优先参考好评案例
```

更进一步：
- **SOP 自动演化**：多次解决同类问题后，自动生成或更新 SOP
- **模式抽象**：从具体案例中提取通用 failure pattern（patterns/ 目录）
- **Agent 行为调优**：分析 AgentLog 表中的 tool_calls 和 duration，识别低效的推理路径

### 层次 3：真正的自主进化（远期探索）

| 方向 | 可行性 | 说明 |
|------|--------|------|
| Prompt 自动优化 | 中期可行 | 根据 AgentLog 中成功/失败的 pattern，自动调整 system prompt |
| 工具自动生成 | 远期探索 | LLM 生成新的 @tool 函数（代码生成 + sandbox 执行） |
| 模型微调/蒸馏 | 远期 | 用历史案例数据 fine-tune 一个专用运维模型 |
| 主动学习 | 远期 | Agent 主动识别知识盲区，请求人类输入 SOP |

---

## 5. 质量增长曲线

```
        质量
         ↑
         │         Agent 路径 (LLM 升级 + KB 积累)
         │              ╱
         │           ╱
         │        ╱
         │     ╱  ← 每次模型升级、每次案例积累，都在这里拐一次
         │  ╱
         │╱ ─ ─ ─ ─ ─ ─ ─ ─  Legacy 路径 (固定上限)
         │
         └──────────────────→ 时间
```

---

## 6. 前提条件

Agent 路径实现上述愿景的前提是：**Agent 路径的基础能力不能弱于 Legacy**。

Phase 0+1 审查发现的关键能力差距：
- Detect Agent 缺少统计检测 tool（Legacy 有 z-score/规则引擎）
- 缺少 `managed` 字段和 opt-in 机制
- HealthIssue 去重逻辑缺失
- 两套检测系统（anomalies vs health_issues）完全断裂

这些必须在 Phase 1 补完后，才能在 Phase 2+ 有效启动 Knowledge Flywheel。

---

## 7. Phase 路线图回顾

| Phase | 目标 | 进化层次 |
|-------|------|---------|
| 0+1 (当前) | Multi-Agent 骨架，Scan + Detect + CLI | 基础架构 |
| 1 补完 | 统计检测 tool、managed 字段、去重、测试 | 能力基线对齐 |
| 2 | RCA Agent + Reporter Agent + 完整 KB | 知识飞轮启动 |
| 3 | 动态 pipeline、审批门、SRE Agent (只读) | 自动化升级 |
| 4 | SRE Agent 执行、向量搜索、反馈学习 | 反馈回路建立 |
| 5 | 生产加固、Session 持久化、全面测试 | 生产就绪 |

---

*本文档是架构愿景讨论的总结，用于指导后续 Phase 的设计决策和优先级排序。*
