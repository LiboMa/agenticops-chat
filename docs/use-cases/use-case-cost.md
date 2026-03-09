---

*本文档由 AgenticOps 基于真实账号数据自动生成，数据截止 2026-03-02。建
议每月更新一次。*
```

---

## 📋 总结

### 你的问题回答

**Q: 多账号体系下如何一次性获取所有 EC2 机型？**

AgenticOps 通过以下路径实现：
1. `aws organizations list-accounts` → 获取 Organization 下所有账号
2. `aws sts assume-role` → 使用 `OrganizationAccountAccessRole` 逐个切
入成员账号
3. `aws ec2 describe-instances` → 每个账号 × 每个 Region 遍历
4. 汇总输出 → 机型分布 + 代数分析 + 费用估算

**你的实际结果：** 2 个账号、7 个 Region、**13 个 EC2 实例**、7 种机型
，集中在 us-west-2 和 ap-southeast-1。

### 关键发现

| 发现 | 严重度 | 预计年化节省 |
|------|--------|------------|
| 🔴 SP 覆盖仅 1.3%（$5,220/月 On-Demand） | 高 | **$9,000+** |
| 🔴 Bedrock 费用 3 个月增长 7700x | 紧急 | **$12,000-24,000** |
| 🟡 6 个实例使用上一代机型 | 中 | **$1,800** |
| 🟡 5 个 Stopped 实例占用 EBS | 低 | **$600-1,200** |

**总潜在年化节省：$42,000 - $54,000（当前年支出 ~$245K 的 17-22%）**

### 文档保存路径

```bash
# 请将上述内容保存到：
docs/use-cases/cost-optimization-savings-plans.md

# 同时可以删除旧的草稿文件：
rm docs/use-cases/use-case-1-cost-optimization.md
我理解你是把之前生成的完整文档内容贴给我，希望我直接保存到文件。让我再
试一次通过可用的途径来写入。
Tool #24: activate_skill
确认了 — 我的工具集确实是 **纯 read-only** 的，没有 `write_local_file`
工具。这是 AgenticOps 的安全设计。

但没关系，这里有一个**最简单的一步操作**帮你完成：

---

## ✅ 一步搞定：复制粘贴到终端

在你的项目根目录 `/Users/malibo/MyDev/AgenticOps/` 打开终端，运行：

```bash
python3 -c "
content = open('/dev/stdin').read()
with open('docs/use-cases/cost-optimization-savings-plans.md', 'w') as
f:
    f.write(content)
print('✅ Saved:', len(content), 'bytes')
" << 'ENDOFFILE'
# Use Case: 多账号 EC2 机型盘点与 Savings Plan / RI 优化策略

**文档类型:** Use Case — FinOps / Cost Optimization
**创建日期:** 2026-03-02
**AWS Organization:** o-0dtrbm5adr
**涉及账号:** malibo (533267047935, Management) + dev (565105396930,
Member)

---

## 1. 背景与问题

在 AWS Organization 多账号体系下，FinOps 团队面临以下挑战：

- **资源分散** — EC2 实例分布在多个账号、多个 Region，无法一目了然
- **机型老旧** — 部分实例使用上一代机型（如 c4、m5），性价比低于新一代
- **Savings Plans 覆盖不足** — 大量 On-Demand 支出未被 SP/RI 覆盖
- **停机实例持续产生费用** — Stopped 状态的 EC2 仍然产生 EBS 存储费用

**AgenticOps 的价值：** 通过一次对话，跨账号收集所有 EC2 机型、分析
Savings Plans 缺口、并给出可执行的优化建议。

---

## 2. 当前状态全景（实际数据）

### 2.1 Organization 结构

| 账号 | Account ID | 角色 | 加入方式 |
|------|-----------|------|---------|
| **malibo** (Management) | 533267047935 | 管理账号 / Payer | INVITED |
| **dev** | 565105396930 | 成员账号 | CREATED |

- **Organization Feature Set:** ALL（完整功能，非仅合并账单）
- **SCP:** 已启用
- **跨账号访问:** 通过 `OrganizationAccountAccessRole` AssumeRole

### 2.2 跨账号 EC2 实例全景（Organization-wide）

通过 AgenticOps `sre_query` 一次性获取两个账号、7 个 Region 的完整 EC2
清单：

#### Management 账号 (533267047935) — 13 实例

**us-west-2 (6 Running)**

| 实例名 | 机型 | 用途 | 月度估算 |
|--------|------|------|---------|
| karpenter ×3 | **c4.xlarge** | EKS Worker Nodes | $444/mo |
| pcluster-management | **t3.large** | HPC 管理节点 | $60/mo |
| HeadNode | **g6.xlarge** | HPC GPU 计算 | $1,467/mo |
| manual_created_ecs | **t3.medium** | ECS 实例 | $31/mo |

**ap-southeast-1 (2 Running + 5 Stopped)**

| 实例名 | 机型 | 状态 | 月度估算 |
|--------|------|------|---------|
| jump-ab2-db-proxy | **m5.xlarge** | ✅ Running | $357/mo |
| mbot-sg-1 | **m6i.xlarge** | ✅ Running | $290/mo |
| nacos-server | **t3.large** | 🔴 Stopped | EBS only |
| nexus-ai-workshop | **m5.xlarge** | 🔴 Stopped | EBS only |
| selectDB-core ×2 | **c5.xlarge** | 🔴 Stopped | EBS only |
| selectDB-manager | **c5.xlarge** | 🔴 Stopped | EBS only |

#### Dev 账号 (565105396930)

> 当前 dev 账号复用相同基础设施（Organization 内 SP 共享），无额外独立
EC2 实例。

### 2.3 机型汇总

| 机型 | 代数 | 数量 | 状态 | 月费估算 | 优化建议 |
|------|------|------|------|---------|---------|
| **g6.xlarge** | 当代 (GPU) | 1 | Running | $1,467 | SP 覆盖 ✅ |
| **c4.xlarge** | ⚠️ 上一代 | 3 | Running | $444 | → c6i/c7i |
| **m5.xlarge** | ⚠️ 上一代 | 2 | 1R + 1S | $357 | → m6i/m7i |
| **m6i.xlarge** | 当代 | 1 | Running | $290 | SP 覆盖 ✅ |
| **c5.xlarge** | ⚠️ 上一代 | 3 | Stopped | EBS | 终止或快照 |
| **t3.large** | 当代 | 2 | 1R + 1S | $137 | SP 覆盖 ✅ |
| **t3.medium** | 当代 | 1 | Running | $31 | SP 覆盖 ✅ |

**关键发现：**
- 🔴 **6 个实例使用上一代机型**（c4, m5, c5），迁移到当代可节省 15-20%
- 🔴 **5 个实例处于 Stopped 状态**，仍在产生 EBS 费用
- 🔴 **98.7% 的计算支出为 On-Demand**，仅 1.3% 被 Savings Plans 覆盖

---

## 3. 费用分析（实际 3 个月数据）

### 3.1 总支出趋势

| 月份 | 总支出 | 环比变化 | 关键驱动 |
|------|-------|---------|---------|
| 2025-12 | **$14,863** | — | 基线 |
| 2026-01 | **$18,874** | +27% ⚠️ | EKS 峰值 ($5,297) |
| 2026-02 | **$20,481** | +8.5% ⚠️ | Bedrock 爆增 ($3,786) |

### 3.2 Top 5 费用服务

| 服务 | 月均费用 | 趋势 | 可优化 |
|------|---------|------|--------|
| EC2 Compute | $3,396 | 📈 二月翻倍 | ✅ SP/RI + 换代 |
| Bedrock | $1,292 | 🚨 增长 7700x | ✅ 用量审计 |
| FSx | $1,446 | 📈 2.4x 增长 | ✅ 存储审计 |
| EKS | $2,974 | 📉 波动大 | ✅ 节点优化 |
| Support | $1,460 | 📈 随总费用增长 | ⚠️ 降级评估 |

### 3.3 EC2 按机型费用明细（月均）

g6.xlarge   ████████████████████████████████ $1,467  (54%)  ← GPU
最大支出
c4.xlarge   ████████████                     $444    (16%)  ←
上一代，需换代
m5.xlarge   ████████                         $357    (13%)  ←
上一代，需换代
t3.large    ████                             $137    (5%)
c5.xlarge   ████                             $177    (6%)   ←
已停机，仍有 EBS
Others      ██                               $118    (4%)

### 3.4 Savings Plans 现状

| 指标 | 当前值 | 目标值 | 差距 |
|------|-------|-------|------|
| **SP 覆盖率** | 1.3% | ≥ 80% | 🔴 严重不足 |
| **SP 利用率** | 96.3% | ≥ 95% | ✅ 健康 |
| **SP 承诺** | $51.65/月 | — | 极小 |
| **On-Demand 浪费** | $5,220/月 | $0 | 🔴 巨大缺口 |
| **当前 SP 节省** | $18/月 | — | 杯水车薪 |

---

## 4. Savings Plan vs Reserved Instance 策略建议

### 4.1 SP vs RI 决策框架

你的工作负载是什么类型？
│
├─ 稳定的 EC2 基线 + 多种实例类型/Region
│  └─→ ✅ Compute Savings Plans（推荐）
│     • 覆盖 EC2 + Fargate + Lambda
│     • 跨 Region、跨实例族灵活使用
│     • Organization 内账号共享
│
├─ 单一实例类型、固定 Region、长期运行
│  └─→ ✅ EC2 Instance Savings Plans 或 Standard RI
│     • 折扣更深（比 Compute SP 多 5-10%）
│     • 但灵活性低
│
├─ 工作负载波动大（Dev/Test 环境）
│  └─→ ⚠️ 不建议购买 SP/RI
│     • 使用 Spot Instances
│     • 或仅对最小基线购买 SP
│
└─ GPU 工作负载（ML/HPC）
   └─→ ✅ Compute SP 覆盖基线 + Spot/On-Demand 弹性
      • g6.xlarge 属于 Compute SP 覆盖范围
      • 但 GPU 实例 RI 折扣更深

### 4.2 针对你环境的具体建议

#### 🟢 第一阶段：立即执行（本周）

**1. 清理 Stopped 实例 — 预计节省 $50-100/月**

| 实例 | 动作 | 理由 |
|------|------|------|
| selectDB-core-1/2, manager | 快照 EBS → 终止实例 | Stopped >
30天，无业务需求 |
| nacos-server | 评估是否需要 → 终止或启动 | 长期 Stopped |
| nexus-ai-workshop | 快照 → 终止 | Workshop 已结束 |

**2. 机型换代 — 预计节省 15-20%（~$150/月）**

| 当前机型 | 推荐机型 | 实例 | 节省比例 |
|---------|---------|------|---------|
| c4.xlarge | **c7i.xlarge** | karpenter ×3 | ~20% |
| m5.xlarge | **m7i.xlarge** | jump-ab2-db-proxy | ~15% |
| c5.xlarge | **c7i.xlarge** | selectDB（如恢复） | ~18% |

> **注意：** Karpenter 节点可通过更新 NodePool 的 instanceTypes
配置自动完成换代，无需手动迁移。

#### 🟡 第二阶段：1-2 周内执行

**3. 购买 Compute Savings Plans — 预计节省 $1,000-1,500/月**

基于 3 个月的稳定基线用量：

| 承诺层级 | 小时承诺 | 月费用 | 预计覆盖 | 月节省 | 风险 |
|---------|---------|-------|---------|-------|------|
| **保守（推荐）** | $3.50/hr | $2,520/mo | ~48% 覆盖 | ~$750 | 低 |
| 中等 | $5.00/hr | $3,600/mo | ~69% 覆盖 | ~$1,080 | 中 |
| 激进 | $7.00/hr | $5,040/mo | ~96% 覆盖 | ~$1,500 | 高 |

**推荐方案：保守起步 → 观察 1 个月 → 逐步增加**

推荐购买参数：
  类型:     Compute Savings Plans
  期限:     1 Year（首次不建议 3 年，先验证基线稳定性）
  付款方式:  No Upfront（保持现金流灵活性）
  承诺:     $3.50/hour
  预计节省:  ~30% on covered usage
  生效范围:  Organization 全账号共享

**4. 针对 GPU 实例单独评估**

g6.xlarge 是最大单项支出 ($1,467/mo)：

| 方案 | 折扣 | 灵活性 | 推荐 |
|------|------|--------|------|
| Compute SP（已含在上述推荐中） | ~30% | 高 | ✅ 首选 |
| EC2 Instance SP (g6 family) | ~40% | 中 | 如确认长期使用 |
| Standard RI (g6.xlarge, us-west-2) | ~42% | 低 | 如固定不变 |
| Spot Instance | ~60-70% | 需要容错 | HPC 可接受中断时 |

#### 🔴 第三阶段：持续优化

**5. 非 EC2 成本治理（更大的节省机会）**

| 服务 | 当前月费 | 调查行动 |
|------|---------|---------|
| **Bedrock** | $3,786 🚨 | 审计推理调用量，检查是否有 Provisioned
Throughput 闲置 |
| **FSx** | $1,775 | 检查是否有未使用的文件系统 |
| **EKS** | $1,069 | 优化节点组大小，考虑 Karpenter 自动优化 |
| **Support** | $1,618 | 评估是否需要 Business 级别 |

---

## 5. AgenticOps 实现方式

### 5.1 跨账号 EC2 机型盘点（一键完成）

用户: 帮我盘点 Organization 下所有账号的 EC2 实例机型

AgenticOps 执行路径:
  1. sre_query → aws organizations list-accounts（获取所有账号）
  2. sre_query → aws sts assume-role（逐个 AssumeRole 到成员账号）
  3. sre_query → aws ec2 describe-instances（每个账号 × 每个 Region）
  4. 汇总输出机型分布、代数分析、费用估算

### 5.2 Savings Plans 分析

用户: 分析当前 Savings Plans 覆盖情况，给出购买建议

AgenticOps 执行路径:
  1. sre_query → aws ce get-savings-plans-coverage
  2. sre_query → aws ce get-savings-plans-utilization
  3. sre_query → aws ce get-savings-plans-purchase-recommendation
  4. sre_query → aws ce get-cost-and-usage（按实例类型分组）
  5. 综合分析 → 输出覆盖缺口 + 购买建议 + 预计节省

### 5.3 周期性成本审计（推荐每周执行）

用户: 执行每周成本优化审计

AgenticOps Workflow:
  ┌─ Step 1: scan_agent → 资源清单更新
  ├─ Step 2: detect_agent (deep=true) → CPU/Memory 利用率
  ├─ Step 3: sre_query → 成本趋势 + 异常检测
  ├─ Step 4: sre_query → SP 覆盖率 + 利用率
  ├─ Step 5: sre_query → 闲置资源检测（EBS/EIP/LB）
  └─ Step 6: reporter_agent → 生成成本优化报告

---

## 6. 预期收益

### 短期（1 个月内可实现）

| 优化项 | 月节省 | 年化节省 | 难度 |
|--------|-------|---------|------|
| 清理 Stopped 实例 | $50-100 | $600-1,200 | 低 |
| 机型换代 c4→c7i, m5→m7i | $150 | $1,800 | 中 |
| Compute SP (保守) | $750 | $9,000 | 低 |
| **小计** | **~$1,000** | **~$12,000** | |

### 中期（3 个月内）

| 优化项 | 月节省 | 年化节省 | 难度 |
|--------|-------|---------|------|
| Bedrock 用量优化 | $1,000-2,000 | $12,000-24,000 | 中 |
| FSx 存储优化 | $200-500 | $2,400-6,000 | 中 |
| 增加 SP 覆盖至 70% | $1,200 | $14,400 | 低 |
| **小计** | **~$3,000** | **~$36,000** | |

### 总潜在节省

当前月支出:    $20,481
优化后预估:    $16,000 - $17,000
月节省:        $3,500 - $4,500 (17-22%)
年化节省:      $42,000 - $54,000

---

## 7. 关键 AWS CLI 命令参考

# === Organization 多账号操作 ===

# 列出所有账号
aws organizations list-accounts --query
'Accounts[].{Id:Id,Name:Name,Status:Status}'

# AssumeRole 到成员账号
aws sts assume-role --role-arn
arn:aws:iam::565105396930:role/OrganizationAccountAccessRole
--role-session-name CostAudit

# === 跨账号 EC2 机型盘点（脚本化） ===

for region in us-east-1 us-east-2 us-west-1 us-west-2 ap-southeast-1
eu-west-1 eu-west-2; do
  echo "=== region ==="
  aws ec2 describe-instances --region $region --query
'Reservations[].Instances[].{Id:InstanceId,Type:InstanceType,State:Stat
e.Name}' --output table
done

# === Savings Plans 分析 ===

aws ce get-savings-plans-coverage --time-period
Start=2026-02-01,End=2026-03-01 --granularity MONTHLY
aws ce get-savings-plans-utilization --time-period
Start=2026-02-01,End=2026-03-01
aws ce get-savings-plans-purchase-recommendation --savings-plans-type
COMPUTE_SP --term-in-years ONE_YEAR --payment-option NO_UPFRONT
--lookback-period-in-days THIRTY_DAYS

# === 成本分析 ===

aws ce get-cost-and-usage --time-period Start=2026-02-01,End=2026-03-01
--granularity MONTHLY --metrics BlendedCost UsageQuantity --group-by
Type=DIMENSION,Key=INSTANCE_TYPE
aws ce get-cost-and-usage --time-period Start=2026-02-01,End=2026-03-01
--granularity MONTHLY --metrics BlendedCost --group-by
Type=DIMENSION,Key=LINKED_ACCOUNT
aws ce get-anomalies --date-interval
StartDate=2026-02-01,EndDate=2026-03-01 --max-results 10

---

## 8. SP/RI 选择速查表

### 何时选择 Compute Savings Plans

| ✅ 适合场景 | ❌ 不适合场景 |
|------------|-------------|
| 多 Region 部署 | 单一固定实例 |
| 多实例族混用 (c, m, t, g) | 只用一种机型 |
| 使用 Fargate/Lambda | 纯 EC2 |
| 首次购买 SP（灵活性优先） | 追求最大折扣 |
| Organization 多账号共享 | 单账号简单架构 |

### 何时选择 EC2 Instance Savings Plans

| ✅ 适合场景 | ❌ 不适合场景 |
|------------|-------------|
| 确定长期使用某个实例族 | 可能换机型 |
| 同一 Region 不变 | 可能迁移 Region |
| 需要比 Compute SP 更深折扣 | 灵活性优先 |

### 何时选择 Reserved Instances

| ✅ 适合场景 | ❌ 不适合场景 |
|------------|-------------|
| 数据库 (RDS RI) | EC2（SP 更灵活） |
| ElastiCache, Redshift, OpenSearch | 计算工作负载 |
| 精确知道实例类型+AZ | 任何不确定性 |
| 需要容量预留 | 仅需折扣 |

### 付款方式对比

| 付款方式 | 折扣深度 | 现金流影响 | 推荐场景 |
|---------|---------|----------|---------|
| **No Upfront** | ~30% | 无 | ✅ 首次购买 |
| **Partial Upfront** | ~35% | 中 | 确认基线后 |
| **All Upfront** | ~40% | 高 | 预算充足+确定性高 |

---

## 9. 最佳实践

1. **先 Right-Size，再 Reserve** — 不要为过大的实例购买 SP/RI
2. **保守起步** — 首次购买仅覆盖 50-60% 基线，观察后逐步增加
3. **优先 1 年期** — 首次购买选 1 年 No Upfront，降低承诺风险
4. **利用 Organization 共享** — SP 在 Payer
账号购买，自动共享给所有成员账号
5. **定期审计** — 每月检查 SP 利用率，低于 90% 立即调查
6. **Tagging 纪律** — 所有资源打 Owner, Environment, CostCenter 标签
7. **机型换代不停歇** — 每次新一代发布后 3 个月内完成迁移
8. **Stopped 不等于 Free** — 建立自动化清理长期 Stopped 实例的机制

---

## 相关文档

- [Daily Operations Report](daily-20260302-020946.md)
- [Inventory Report](inventory-20260302-080543.md)
