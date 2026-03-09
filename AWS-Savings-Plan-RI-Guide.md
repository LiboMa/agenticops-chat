# AWS EC2 和 RDS 成本优化指南
## Savings Plans 和 Reserved Instances 完整操作手册

---

## 📋 目录

1. [概述](#概述)
2. [Savings Plans vs Reserved Instances 对比](#对比分析)
3. [EC2 成本优化方案](#ec2-成本优化)
4. [RDS 成本优化方案](#rds-成本优化)
5. [购买决策流程](#购买决策)
6. [操作步骤详解](#操作步骤)
7. [最佳实践](#最佳实践)
8. [注意事项和风险](#注意事项)
9. [监控和优化](#监控优化)

---

## 📊 概述

### 什么是 Savings Plans 和 Reserved Instances？

**Savings Plans (SP)**
- 承诺在1年或3年期间使用特定金额的计算资源（$/小时）
- 自动应用于符合条件的使用量
- 提供最高72%的折扣
- 更灵活，可跨实例类型、区域、操作系统

**Reserved Instances (RI)**
- 预留特定配置的实例容量
- 提供最高75%的折扣
- 针对特定实例类型、区域、操作系统
- 更适合稳定、可预测的工作负载

### 潜在节省

| 承诺期限 | EC2 Savings Plans | Compute Savings Plans | EC2 RI | RDS RI |
|---------|-------------------|----------------------|--------|--------|
| 1年 (全预付) | 最高42% | 最高54% | 最高40% | 最高38% |
| 1年 (部分预付) | 最高40% | 最高52% | 最高38% | 最高35% |
| 1年 (无预付) | 最高38% | 最高50% | 最高36% | 最高33% |
| 3年 (全预付) | 最高66% | 最高72% | 最高62% | 最高63% |
| 3年 (部分预付) | 最高64% | 最高70% | 最高60% | 最高60% |
| 3年 (无预付) | 不可用 | 不可用 | 最高58% | 最高57% |

---

## 🔄 对比分析

### Savings Plans vs Reserved Instances

| 特性 | Compute Savings Plans | EC2 Instance Savings Plans | EC2 Reserved Instances | RDS Reserved Instances |
|------|----------------------|---------------------------|----------------------|----------------------|
| **灵活性** | ⭐⭐⭐⭐⭐ 最高 | ⭐⭐⭐⭐ 高 | ⭐⭐⭐ 中等 | ⭐⭐ 较低 |
| **折扣率** | 最高72% | 最高66% | 最高75% | 最高63% |
| **跨区域** | ✅ 支持 | ✅ 支持 | ❌ 不支持 | ❌ 不支持 |
| **跨实例族** | ✅ 支持 | ❌ 不支持 | ❌ 不支持 | ❌ 不支持 |
| **跨操作系统** | ✅ 支持 | ✅ 支持 | ❌ 不支持 | N/A |
| **适用服务** | EC2, Fargate, Lambda | 仅 EC2 | 仅 EC2 | 仅 RDS |
| **容量预留** | ❌ 不支持 | ❌ 不支持 | ✅ 可选 | ✅ 自动 |
| **可交易** | ❌ 不可 | ❌ 不可 | ✅ 可在市场交易 | ❌ 不可 |

### 推荐选择策略

```
使用场景决策树：

1. 工作负载是否稳定且可预测？
   ├─ 是 → 继续
   └─ 否 → 使用按需实例或 Spot 实例

2. 是否需要跨区域或跨实例类型的灵活性？
   ├─ 是 → Compute Savings Plans
   └─ 否 → 继续

3. 是否只使用 EC2？
   ├─ 是 → EC2 Instance Savings Plans 或 EC2 RI
   └─ 否（使用 Fargate/Lambda）→ Compute Savings Plans

4. 是否需要容量保证？
   ├─ 是 → EC2 RI (with capacity reservation)
   └─ 否 → EC2 Instance Savings Plans

5. 对于 RDS：
   └─ 使用 RDS Reserved Instances
```

---

## 💻 EC2 成本优化

### EC2 Savings Plans 类型

#### 1. Compute Savings Plans（推荐）
**优势：**
- 最大灵活性
- 自动适用于 EC2、Fargate、Lambda
- 可跨区域、实例族、大小、操作系统、租期

**适用场景：**
- 多区域部署
- 频繁更换实例类型
- 使用多种 AWS 计算服务
- 业务快速增长，架构可能调整

**示例：**
```
承诺：$10/小时，3年期
自动应用于：
- us-east-1 的 c5.2xlarge (Linux)
- us-west-2 的 m5.4xlarge (Windows)
- ap-southeast-1 的 Fargate 任务
- Lambda 函数调用
```

#### 2. EC2 Instance Savings Plans
**优势：**
- 比 Compute SP 折扣更高
- 可跨实例大小、操作系统、租期
- 限定在特定区域和实例族

**适用场景：**
- 单一区域部署
- 确定使用特定实例族（如 m5、c5）
- 不需要跨区域灵活性

**示例：**
```
承诺：$5/小时，us-east-1，m5 实例族
自动应用于：
- m5.large
- m5.xlarge
- m5.2xlarge
但不适用于 c5 或其他区域
```

### EC2 Reserved Instances

#### RI 类型

**1. Standard RI（标准预留实例）**
- 最高折扣（最高75%）
- 可修改可用区、实例大小（同族内）
- 可在 RI 市场出售
- 不可更改区域、实例族、操作系统

**2. Convertible RI（可转换预留实例）**
- 较高折扣（最高54%）
- 可更改实例族、操作系统、租期
- 不可在市场出售
- 更适合长期但不确定配置的场景

**3. Scheduled RI（计划预留实例）**
- 针对定期重复的工作负载
- 按天、周、月的特定时间段预留
- 已停止新购买（AWS 不再提供）

#### 付款选项

| 付款方式 | 预付金额 | 折扣率 | 现金流影响 | 推荐场景 |
|---------|---------|--------|-----------|---------|
| **全预付 (All Upfront)** | 100% | 最高 | 一次性大额支出 | 预算充足，追求最大节省 |
| **部分预付 (Partial Upfront)** | ~50% | 中等 | 平衡 | 平衡现金流和节省 |
| **无预付 (No Upfront)** | 0% | 较低 | 按月支付 | 现金流紧张，仍需承诺 |

---

## 🗄️ RDS 成本优化

### RDS Reserved Instances 详解

RDS 只支持 Reserved Instances，不支持 Savings Plans。

#### RDS RI 特点

**覆盖范围：**
- Amazon RDS（MySQL, PostgreSQL, MariaDB, Oracle, SQL Server）
- Amazon Aurora（MySQL 兼容版、PostgreSQL 兼容版）

**灵活性：**
- 可跨可用区应用
- 可修改实例大小（同族内）
- 不可跨区域
- 不可更改数据库引擎

#### RDS RI 类型

**1. Standard RI**
- 最高折扣
- 固定实例类型和区域
- 可修改可用区

**2. 无 Convertible RI**
- RDS 不提供可转换 RI
- 需要更换引擎或区域需重新购买

#### 实例大小灵活性

RDS RI 支持同族内的实例大小灵活性：

```
购买：1 x db.m5.4xlarge RI

可自动应用于：
- 2 x db.m5.2xlarge
- 4 x db.m5.xlarge
- 8 x db.m5.large
- 16 x db.m5.small（如果支持）

或反向：
- 0.5 x db.m5.8xlarge
```

**归一化因子表：**

| 实例大小 | 归一化因子 |
|---------|-----------|
| small | 1 |
| medium | 2 |
| large | 4 |
| xlarge | 8 |
| 2xlarge | 16 |
| 4xlarge | 32 |
| 8xlarge | 64 |
| 16xlarge | 128 |

---

## 🎯 购买决策流程

### 步骤 1：分析当前使用情况

#### 使用 AWS Cost Explorer

1. **查看历史使用模式**
```bash
# 使用 AWS CLI 获取过去 6 个月的使用数据
aws ce get-cost-and-usage \
  --time-period Start=2025-09-01,End=2026-03-01 \
  --granularity MONTHLY \
  --metrics "UnblendedCost" "UsageQuantity" \
  --group-by Type=DIMENSION,Key=INSTANCE_TYPE \
  --filter file://filter.json
```

2. **识别稳定工作负载**
- 查找连续 3-6 个月使用率 >75% 的实例
- 识别 24/7 运行的实例
- 排除测试/开发环境的临时实例

#### 使用 AWS Compute Optimizer

```bash
# 获取 EC2 推荐
aws compute-optimizer get-ec2-instance-recommendations \
  --region us-east-1

# 获取 RDS 推荐（通过 Cost Explorer）
aws ce get-reservation-purchase-recommendation \
  --service "Amazon RDS" \
  --lookback-period-in-days SIXTY_DAYS \
  --term-in-years ONE_YEAR \
  --payment-option PARTIAL_UPFRONT
```

### 步骤 2：计算推荐承诺量

#### EC2 Savings Plans 计算

```python
# 示例计算脚本
baseline_hourly_cost = 100  # 当前按需成本 $/小时
coverage_target = 0.80      # 目标覆盖率 80%
discount_rate = 0.40        # 预期折扣 40%

# 推荐承诺
recommended_commitment = baseline_hourly_cost * coverage_target * (1 - discount_rate)
# = 100 * 0.80 * 0.60 = $48/小时

print(f"推荐承诺: ${recommended_commitment}/小时")
print(f"年度成本: ${recommended_commitment * 24 * 365:,.2f}")
```

#### RDS RI 计算

```
当前运行实例：
- 3 x db.m5.xlarge (us-east-1a) - 24/7 运行
- 2 x db.m5.2xlarge (us-east-1b) - 24/7 运行
- 1 x db.m5.large (us-east-1c) - 仅工作时间

推荐购买：
- 3 x db.m5.xlarge RI (1年期，部分预付)
- 2 x db.m5.2xlarge RI (1年期，部分预付)
- 不购买 db.m5.large RI（使用率不足）
```

### 步骤 3：选择承诺期限和付款方式

#### 决策矩阵

| 业务场景 | 推荐期限 | 推荐付款 | 理由 |
|---------|---------|---------|------|
| 稳定生产环境，3年+ | 3年 | 全预付 | 最大节省 |
| 稳定生产环境，预算有限 | 3年 | 部分预付 | 平衡节省和现金流 |
| 增长中的业务 | 1年 | 部分预付 | 灵活性和节省平衡 |
| 现金流紧张 | 1年 | 无预付 | 最小前期投入 |
| 不确定的架构 | 1年 | 部分预付 + Convertible RI | 保留调整空间 |

---

## 📝 操作步骤详解

### EC2 Savings Plans 购买步骤

#### 方法 1：通过 AWS Console

**步骤 1：访问 Savings Plans 页面**
1. 登录 AWS Console
2. 导航到 **AWS Cost Management** > **Savings Plans**
3. 点击 **Purchase Savings Plans**

**步骤 2：查看推荐**
1. AWS 会基于历史使用显示推荐
2. 查看推荐的承诺金额、期限、付款选项
3. 查看预计节省金额

**步骤 3：自定义 Savings Plan**
1. 选择 **Savings Plan type**:
   - Compute Savings Plans
   - EC2 Instance Savings Plans
2. 选择 **Term**: 1年 或 3年
3. 选择 **Payment option**:
   - All upfront
   - Partial upfront
   - No upfront
4. 输入 **Hourly commitment** ($/小时)

**步骤 4：审查和购买**
1. 查看承诺详情
2. 查看预计节省
3. 确认付款信息
4. 点击 **Add to cart** 和 **Submit order**

#### 方法 2：通过 AWS CLI

```bash
# 1. 获取 Savings Plans 推荐
aws savingsplans describe-savings-plans-offering-rates \
  --service-codes '["AmazonEC2"]' \
  --savings-plan-types '["Compute"]' \
  --products '["EC2"]' \
  --region us-east-1

# 2. 创建 Savings Plan
aws savingsplans create-savings-plan \
  --savings-plan-offering-id <offering-id> \
  --commitment 10.00 \
  --upfront-payment-amount 43800.00 \
  --purchase-time 2026-03-02T00:00:00Z \
  --tags Key=Environment,Value=Production
```

#### 方法 3：通过 Terraform

```hcl
# terraform/savings_plans.tf
resource "aws_savingsplans_plan" "compute_savings_plan" {
  savings_plan_type = "Compute"
  term              = "OneYear"
  payment_option    = "PartialUpfront"
  commitment        = "10.00"  # $/hour

  tags = {
    Name        = "Production Compute Savings Plan"
    Environment = "Production"
    ManagedBy   = "Terraform"
  }
}
```

### EC2 Reserved Instances 购买步骤

#### 通过 AWS Console

**步骤 1：访问 EC2 RI 页面**
1. 登录 AWS Console
2. 导航到 **EC2** > **Reserved Instances**
3. 点击 **Purchase Reserved Instances**

**步骤 2：配置 RI**
1. **Instance type**: 选择实例类型（如 m5.xlarge）
2. **Platform**: 选择操作系统（Linux/Windows）
3. **Tenancy**: Default 或 Dedicated
4. **Term**: 1年 或 3年
5. **Offering class**: Standard 或 Convertible
6. **Payment option**: All/Partial/No Upfront
7. **Instance count**: 购买数量

**步骤 3：审查和购买**
1. 查看定价详情
2. 查看预计节省
3. 点击 **Add to Cart** 和 **Purchase**

#### 通过 AWS CLI

```bash
# 1. 搜索可用的 RI offerings
aws ec2 describe-reserved-instances-offerings \
  --instance-type m5.xlarge \
  --product-description "Linux/UNIX" \
  --offering-class standard \
  --instance-tenancy default \
  --filters Name=duration,Values=31536000 \
  --region us-east-1

# 2. 购买 RI
aws ec2 purchase-reserved-instances-offering \
  --reserved-instances-offering-id <offering-id> \
  --instance-count 3 \
  --region us-east-1
```

### RDS Reserved Instances 购买步骤

#### 通过 AWS Console

**步骤 1：访问 RDS RI 页面**
1. 登录 AWS Console
2. 导航到 **RDS** > **Reserved instances**
3. 点击 **Purchase reserved DB instance**

**步骤 2：配置 RDS RI**
1. **DB engine**: 选择数据库引擎（MySQL, PostgreSQL, Aurora 等）
2. **DB instance class**: 选择实例类型（db.m5.xlarge）
3. **Multi-AZ**: 是否多可用区部署
4. **Term**: 1年 或 3年
5. **Offering type**: Standard
6. **Payment option**: All/Partial/No Upfront
7. **Instance count**: 购买数量

**步骤 3：审查和购买**
1. 查看定价详情
2. 查看预计节省
3. 点击 **Submit**

#### 通过 AWS CLI

```bash
# 1. 查看可用的 RDS RI offerings
aws rds describe-reserved-db-instances-offerings \
  --db-instance-class db.m5.xlarge \
  --product-description mysql \
  --duration 31536000 \
  --offering-type "Partial Upfront" \
  --region us-east-1

# 2. 购买 RDS RI
aws rds purchase-reserved-db-instances-offering \
  --reserved-db-instances-offering-id <offering-id> \
  --reserved-db-instance-id my-rds-ri-001 \
  --db-instance-count 2 \
  --region us-east-1 \
  --tags Key=Environment,Value=Production
```

---

## ✅ 最佳实践

### 1. 分阶段购买策略

**不要一次性购买全部承诺**

```
推荐方法：
第1个月：购买 50% 的推荐承诺
第2-3个月：监控覆盖率和利用率
第4个月：根据实际情况调整，购买额外 20-30%
持续优化：每季度审查一次
```

**原因：**
- 避免过度承诺
- 保留灵活性应对业务变化
- 降低风险

### 2. 混合策略

**组合使用不同的成本优化工具**

```
生产环境架构示例：

核心稳定工作负载（70%）：
├─ 3年期 Compute Savings Plans (40%)
├─ 1年期 EC2 Instance Savings Plans (20%)
└─ RDS Reserved Instances (10%)

可变工作负载（20%）：
└─ 按需实例

突发工作负载（10%）：
└─ Spot 实例
```

### 3. 覆盖率目标

**推荐覆盖率：**
- 生产环境：70-85%
- 开发/测试环境：0-30%
- 总体：60-75%

**不要追求 100% 覆盖率**
- 保留灵活性
- 避免过度承诺
- 应对突发需求

### 4. 利用率监控

**目标利用率：>95%**

```bash
# 每周检查 Savings Plans 利用率
aws savingsplans describe-savings-plans \
  --savings-plan-arns <arn> \
  --region us-east-1

# 检查 RI 利用率
aws ce get-reservation-utilization \
  --time-period Start=2026-02-01,End=2026-03-01 \
  --granularity MONTHLY
```

### 5. 标签策略

**为所有资源添加标签**

```
必需标签：
- Environment: Production/Staging/Development
- CostCenter: 成本中心代码
- Owner: 负责团队
- Project: 项目名称
- Application: 应用名称

示例：
aws ec2 create-tags \
  --resources i-1234567890abcdef0 \
  --tags Key=Environment,Value=Production \
         Key=CostCenter,Value=CC-1001 \
         Key=Owner,Value=DevOps-Team
```

### 6. 自动化推荐

**使用 AWS Cost Explorer API 自动获取推荐**

```python
import boto3
import json

ce_client = boto3.client('ce', region_name='us-east-1')

# 获取 Savings Plans 推荐
response = ce_client.get_savings_plans_purchase_recommendation(
    SavingsPlansType='COMPUTE_SP',
    TermInYears='ONE_YEAR',
    PaymentOption='PARTIAL_UPFRONT',
    LookbackPeriodInDays='SIXTY_DAYS'
)

print(json.dumps(response, indent=2, default=str))
```

---

## ⚠️ 注意事项和风险

### 关键注意事项

#### 1. 承诺是不可取消的

**风险：**
- 购买后无法退款
- 即使不使用也需要支付

**缓解措施：**
- 从小额开始
- 基于历史数据做决策
- 保持 15-25% 的按需容量

#### 2. Savings Plans 不提供容量保证

**影响：**
- 在容量受限的区域可能无法启动实例
- 高峰期可能面临容量不足

**解决方案：**
- 对关键工作负载使用 On-Demand Capacity Reservations
- 或使用 EC2 RI with capacity reservation

#### 3. 区域锁定（RI）

**EC2 RI 和 RDS RI 限制：**
- 只能在购买的区域使用
- 无法跨区域转移

**规划建议：**
- 确认长期区域策略
- 多区域部署考虑使用 Compute Savings Plans

#### 4. 实例族锁定（EC2 Instance SP 和 RI）

**限制：**
- EC2 Instance Savings Plans 限定实例族
- Standard RI 无法更改实例族

**建议：**
- 确认实例族选择
- 不确定时使用 Compute Savings Plans 或 Convertible RI

#### 5. RDS 引擎锁定

**限制：**
- RDS RI 无法更改数据库引擎
- MySQL RI 不能用于 PostgreSQL

**规划：**
- 确认长期数据库引擎策略
- 迁移计划需考虑 RI 到期时间

#### 6. 付款方式影响

**全预付风险：**
- 大额前期支出
- 如果业务变化，资金已锁定

**无预付风险：**
- 折扣率较低
- 仍需承诺期限

**建议：**
- 稳定工作负载：部分预付或全预付
- 增长业务：部分预付
- 现金流紧张：无预付

#### 7. 账单复杂性

**挑战：**
- Savings Plans 和 RI 的应用顺序复杂
- 多个承诺可能重叠
- 难以追踪实际节省

**解决方案：**
- 使用 AWS Cost Explorer 的 Savings Plans 和 RI 报告
- 设置 Cost Anomaly Detection
- 定期审查账单

### 常见错误

#### ❌ 错误 1：过度承诺

```
错误示例：
当前使用：$100/小时
购买：$95/小时 Savings Plans

问题：只留 5% 灵活性，业务下降时浪费严重
```

**正确做法：**
```
当前使用：$100/小时
购买：$70-80/小时 Savings Plans
保留：20-30% 按需容量
```

#### ❌ 错误 2：忽略增长

```
错误：基于当前使用购买 3 年期
结果：6 个月后业务增长 50%，新增成本全是按需价格
```

**正确做法：**
- 预测增长趋势
- 分阶段购买
- 或选择 1 年期

#### ❌ 错误 3：混淆不同类型

```
错误：购买 EC2 Instance Savings Plans 期望覆盖 Fargate
结果：Fargate 不被覆盖
```

**正确做法：**
- 了解每种类型的覆盖范围
- Fargate/Lambda 需要 Compute Savings Plans

#### ❌ 错误 4：忽略测试环境

```
错误：为测试环境购买 RI
结果：测试环境经常关闭，RI 利用率低
```

**正确做法：**
- 测试环境使用按需或 Spot 实例
- 只为 24/7 运行的资源购买承诺

---

## 📊 监控和优化

### 关键指标

#### 1. Savings Plans 利用率

**目标：>95%**

```
利用率 = 实际使用的承诺金额 / 总承诺金额

示例：
承诺：$10/小时
实际使用：$9.5/小时
利用率：95%
```

**监控方法：**
```bash
# AWS CLI
aws savingsplans describe-savings-plans \
  --region us-east-1

# 查看详细利用率
aws ce get-savings-plans-utilization \
  --time-period Start=2026-02-01,End=2026-03-01 \
  --granularity DAILY
```

#### 2. Savings Plans 覆盖率

**目标：70-85%**

```
覆盖率 = Savings Plans 覆盖的支出 / 总支出

示例：
总 EC2 支出：$100/小时
Savings Plans 覆盖：$75/小时
覆盖率：75%
```

**监控方法：**
```bash
aws ce get-savings-plans-coverage \
  --time-period Start=2026-02-01,End=2026-03-01 \
  --granularity MONTHLY
```

#### 3. Reserved Instances 利用率

**目标：>95%**

```bash
aws ce get-reservation-utilization \
  --time-period Start=2026-02-01,End=2026-03-01 \
  --granularity MONTHLY \
  --filter file://filter.json
```

#### 4. Reserved Instances 覆盖率

**目标：70-85%**

```bash
aws ce get-reservation-coverage \
  --time-period Start=2026-02-01,End=2026-03-01 \
  --granularity MONTHLY
```

### 设置告警

#### CloudWatch 告警

```bash
# 创建 Savings Plans 利用率告警
aws cloudwatch put-metric-alarm \
  --alarm-name "SavingsPlans-Low-Utilization" \
  --alarm-description "Alert when SP utilization < 90%" \
  --metric-name "SavingsPlansUtilization" \
  --namespace "AWS/SavingsPlans" \
  --statistic Average \
  --period 86400 \
  --evaluation-periods 1 \
  --threshold 90 \
  --comparison-operator LessThanThreshold \
  --alarm-actions arn:aws:sns:us-east-1:123456789012:billing-alerts
```

#### AWS Budgets

```bash
# 创建 Savings Plans 预算
aws budgets create-budget \
  --account-id 123456789012 \
  --budget file://savings-plans-budget.json \
  --notifications-with-subscribers file://notifications.json
```

### 定期审查清单

#### 每周审查
- [ ] 检查 Savings Plans 利用率
- [ ] 检查 RI 利用率
- [ ] 查看异常支出

#### 每月审查
- [ ] 分析覆盖率趋势
- [ ] 识别未覆盖的工作负载
- [ ] 评估新的购买机会
- [ ] 审查即将到期的 RI

#### 每季度审查
- [ ] 全面成本优化分析
- [ ] 调整承诺策略
- [ ] 评估架构变化影响
- [ ] 更新成本预测

#### 年度审查
- [ ] 评估整体成本优化效果
- [ ] 规划下一年的承诺策略
- [ ] 审查多年期承诺的续约
- [ ] 更新成本优化政策

---

## 🛠️ 实用工具和脚本

### 1. 利用率监控脚本

```python
#!/usr/bin/env python3
"""
Savings Plans and RI Utilization Monitor
"""
import boto3
from datetime import datetime, timedelta
import json

def check_savings_plans_utilization():
    ce = boto3.client('ce', region_name='us-east-1')
    
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=30)
    
    response = ce.get_savings_plans_utilization(
        TimePeriod={
            'Start': start_date.strftime('%Y-%m-%d'),
            'End': end_date.strftime('%Y-%m-%d')
        },
        Granularity='MONTHLY'
    )
    
    utilization = response['Total']['Utilization']['UtilizationPercentage']
    print(f"Savings Plans Utilization: {utilization}%")
    
    if float(utilization) < 90:
        print("⚠️  WARNING: Utilization below 90%")
    else:
        print("✅ Utilization is healthy")
    
    return utilization

def check_ri_utilization():
    ce = boto3.client('ce', region_name='us-east-1')
    
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=30)
    
    response = ce.get_reservation_utilization(
        TimePeriod={
            'Start': start_date.strftime('%Y-%m-%d'),
            'End': end_date.strftime('%Y-%m-%d')
        },
        Granularity='MONTHLY'
    )
    
    utilization = response['Total']['UtilizationPercentage']
    print(f"Reserved Instances Utilization: {utilization}%")
    
    if float(utilization) < 90:
        print("⚠️  WARNING: RI Utilization below 90%")
    else:
        print("✅ RI Utilization is healthy")
    
    return utilization

if __name__ == "__main__":
    print("=== AWS Cost Optimization Monitor ===\n")
    check_savings_plans_utilization()
    print()
    check_ri_utilization()
```

### 2. 推荐获取脚本

```bash
#!/bin/bash
# get-recommendations.sh

echo "=== Savings Plans Recommendations ==="
aws ce get-savings-plans-purchase-recommendation \
  --savings-plan-type COMPUTE_SP \
  --term-in-years ONE_YEAR \
  --payment-option PARTIAL_UPFRONT \
  --lookback-period-in-days SIXTY_DAYS \
  --region us-east-1 \
  --query 'SavingsPlansPurchaseRecommendation.SavingsPlansPurchaseRecommendationDetails[0]' \
  --output table

echo ""
echo "=== RDS RI Recommendations ==="
aws ce get-reservation-purchase-recommendation \
  --service "Amazon RDS" \
  --lookback-period-in-days SIXTY_DAYS \
  --term-in-years ONE_YEAR \
  --payment-option PARTIAL_UPFRONT \
  --region us-east-1 \
  --query 'Recommendations[0:3]' \
  --output table
```

### 3. 成本报告生成器

```python
#!/usr/bin/env python3
"""
Generate monthly cost optimization report
"""
import boto3
from datetime import datetime, timedelta
import csv

def generate_cost_report():
    ce = boto3.client('ce', region_name='us-east-1')
    
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=30)
    
    # Get cost and usage
    response = ce.get_cost_and_usage(
        TimePeriod={
            'Start': start_date.strftime('%Y-%m-%d'),
            'End': end_date.strftime('%Y-%m-%d')
        },
        Granularity='MONTHLY',
        Metrics=['UnblendedCost', 'UsageQuantity'],
        GroupBy=[
            {'Type': 'DIMENSION', 'Key': 'SERVICE'},
            {'Type': 'DIMENSION', 'Key': 'PURCHASE_TYPE'}
        ]
    )
    
    # Write to CSV
    with open('cost_report.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Service', 'Purchase Type', 'Cost', 'Usage'])
        
        for result in response['ResultsByTime']:
            for group in result['Groups']:
                service = group['Keys'][0]
                purchase_type = group['Keys'][1]
                cost = group['Metrics']['UnblendedCost']['Amount']
                usage = group['Metrics']['UsageQuantity']['Amount']
                
                writer.writerow([service, purchase_type, cost, usage])
    
    print("Report generated: cost_report.csv")

if __name__ == "__main__":
    generate_cost_report()
```

---

## 📋 快速参考

### 决策速查表

| 需求 | 推荐方案 | 期限 | 付款 |
|------|---------|------|------|
| 最大灵活性 | Compute Savings Plans | 1年 | 部分预付 |
| 最大节省 | 3年 Standard RI | 3年 | 全预付 |
| 跨区域部署 | Compute Savings Plans | 1-3年 | 部分预付 |
| 单区域 EC2 | EC2 Instance Savings Plans | 1-3年 | 部分预付 |
| RDS 数据库 | RDS RI | 1-3年 | 部分预付 |
| 不确定配置 | Convertible RI | 1年 | 部分预付 |
| 现金流紧张 | Compute Savings Plans | 1年 | 无预付 |
| 容量保证 | Standard RI + Capacity Reservation | 1-3年 | 部分预付 |

### 常用 AWS CLI 命令

```bash
# Savings Plans
aws savingsplans describe-savings-plans
aws ce get-savings-plans-utilization --time-period Start=2026-02-01,End=2026-03-01
aws ce get-savings-plans-coverage --time-period Start=2026-02-01,End=2026-03-01
aws ce get-savings-plans-purchase-recommendation --savings-plan-type COMPUTE_SP

# EC2 Reserved Instances
aws ec2 describe-reserved-instances
aws ce get-reservation-utilization --time-period Start=2026-02-01,End=2026-03-01
aws ce get-reservation-coverage --time-period Start=2026-02-01,End=2026-03-01
aws ce get-reservation-purchase-recommendation --service "Amazon EC2"

# RDS Reserved Instances
aws rds describe-reserved-db-instances
aws ce get-reservation-purchase-recommendation --service "Amazon RDS"

# Cost and Usage
aws ce get-cost-and-usage --time-period Start=2026-02-01,End=2026-03-01 --granularity MONTHLY --metrics UnblendedCost
```

### 重要链接

- **AWS Cost Explorer**: https://console.aws.amazon.com/cost-management/home#/cost-explorer
- **Savings Plans Console**: https://console.aws.amazon.com/cost-management/home#/savings-plans
- **EC2 RI Console**: https://console.aws.amazon.com/ec2/home#ReservedInstances
- **RDS RI Console**: https://console.aws.amazon.com/rds/home#reserved-instances
- **AWS Pricing Calculator**: https://calculator.aws/
- **AWS Cost Optimization Hub**: https://console.aws.amazon.com/cost-management/home#/cost-optimization-hub

---

## 📞 支持和资源

### 获取帮助

1. **AWS Support**
   - 通过 AWS Support Center 创建案例
   - 选择 "Account and Billing Support"

2. **AWS Account Team**
   - 联系您的 AWS 客户经理
   - 请求成本优化审查

3. **AWS Well-Architected Review**
   - 请求成本优化支柱审查
   - 获取专业建议

### 学习资源

- **AWS Cost Optimization Workshop**: https://catalog.workshops.aws/well-architected-cost-optimization
- **AWS Cost Management Documentation**: https://docs.aws.amazon.com/cost-management/
- **AWS re:Invent Sessions**: 搜索 "Cost Optimization"
- **AWS Blogs**: https://aws.amazon.com/blogs/aws-cost-management/

---

## 📝 总结

### 关键要点

1. **从小开始**：不要一次性承诺全部容量
2. **混合策略**：组合使用 Savings Plans、RI 和按需实例
3. **持续监控**：定期检查利用率和覆盖率
4. **保持灵活性**：保留 15-25% 的按需容量
5. **基于数据决策**：使用历史数据和 AWS 推荐

### 实施路线图

**第1个月：分析和规划**
- 分析历史使用数据
- 识别稳定工作负载
- 获取 AWS 推荐
- 制定购买计划

**第2个月：初始购买**
- 购买 50% 的推荐承诺
- 设置监控和告警
- 建立审查流程

**第3-4个月：监控和调整**
- 监控利用率和覆盖率
- 识别优化机会
- 购买额外承诺（如需要）

**持续优化**
- 每周检查利用率
- 每月审查覆盖率
- 每季度调整策略
- 年度全面审查

### 预期成果

通过正确实施 Savings Plans 和 Reserved Instances：

- **成本节省**：30-70% 的计算成本降低
- **可预测性**：更稳定的月度账单
- **优化运营**：更好的资源规划
- **业务价值**：将节省投资于创新

---

**文档版本**: 1.0  
**最后更新**: 2026-03-02  
**维护者**: AWS Cost Optimization Team

---

## 附录 A：术语表

| 术语 | 定义 |
|------|------|
| **Savings Plans** | 承诺使用特定金额计算资源的定价模型 |
| **Reserved Instances (RI)** | 预留特定配置实例的定价模型 |
| **Compute Savings Plans** | 最灵活的 Savings Plans，适用于 EC2、Fargate、Lambda |
| **EC2 Instance Savings Plans** | 限定实例族的 Savings Plans |
| **Standard RI** | 标准预留实例，最高折扣但灵活性较低 |
| **Convertible RI** | 可转换预留实例，可更改配置 |
| **Utilization** | 利用率，实际使用的承诺百分比 |
| **Coverage** | 覆盖率，承诺覆盖的总支出百分比 |
| **On-Demand** | 按需定价，无承诺 |
| **Spot Instances** | 竞价实例，最低价格但可能被中断 |

## 附录 B：计算示例

### 示例 1：EC2 Savings Plans ROI 计算

```
场景：
- 当前按需成本：$10,000/月
- 稳定使用：80%
- 选择：1年期 Compute Savings Plans，部分预付，40% 折扣

计算：
稳定成本 = $10,000 × 80% = $8,000/月
Savings Plans 成本 = $8,000 × (1 - 40%) = $4,800/月
按需成本（剩余 20%）= $10,000 × 20% = $2,000/月

总成本 = $4,800 + $2,000 = $6,800/月
月度节省 = $10,000 - $6,800 = $3,200
年度节省 = $3,200 × 12 = $38,400
节省率 = 32%
```

### 示例 2：RDS RI ROI 计算

```
场景：
- 3 x db.m5.xlarge，24/7 运行
- 按需价格：$0.384/小时/实例
- RI 价格（1年部分预付）：$0.246/小时/实例，38% 折扣

计算：
按需年度成本 = $0.384 × 24 × 365 × 3 = $10,091
RI 年度成本 = $0.246 × 24 × 365 × 3 = $6,461
年度节省 = $10,091 - $6,461 = $3,630
节省率 = 36%
```

---

**结束语**

成本优化是一个持续的过程，而不是一次性的任务。通过正确使用 Savings Plans 和 Reserved Instances，您可以显著降低 AWS 成本，同时保持业务灵活性。

记住：**从小开始，持续监控，不断优化**。

如有任何问题，请联系您的 AWS 客户团队或通过 AWS Support 获取帮助。
