# AgenticAIOps - 任务清单

## 任务状态说明

| 状态 | 图标 | 说明 |
|------|------|------|
| 已完成 | ✅ | 功能已实现并测试 |
| 进行中 | 🔄 | 正在开发中 |
| 待开始 | ⏳ | 计划中，尚未开始 |
| 阻塞 | 🚫 | 被其他任务阻塞 |

---

## 1. 已完成任务 (Completed)

### 1.1 核心框架

| ID | 任务 | 状态 | 完成日期 |
|----|------|------|----------|
| TASK-001 | 项目结构搭建 | ✅ | 2024-02 |
| TASK-002 | 配置管理模块 (Pydantic Settings) | ✅ | 2024-02 |
| TASK-003 | 数据模型设计 (SQLAlchemy ORM) | ✅ | 2024-02 |
| TASK-004 | 数据库初始化逻辑 | ✅ | 2024-02 |

### 1.2 SCAN模块

| ID | 任务 | 状态 | 完成日期 |
|----|------|------|----------|
| TASK-010 | AWS服务定义配置 (15种服务) | ✅ | 2024-02 |
| TASK-011 | 跨账户STS AssumeRole实现 | ✅ | 2024-02 |
| TASK-012 | 资源扫描器核心逻辑 | ✅ | 2024-02 |
| TASK-013 | 分页处理支持 | ✅ | 2024-02 |
| TASK-014 | 区域动态发现 | ✅ | 2024-02 |
| TASK-015 | 资源Upsert逻辑 | ✅ | 2024-02 |

### 1.3 MONITOR模块

| ID | 任务 | 状态 | 完成日期 |
|----|------|------|----------|
| TASK-020 | CloudWatch指标采集 | ✅ | 2024-02 |
| TASK-021 | 服务特定指标方法 (EC2/Lambda/RDS) | ✅ | 2024-02 |
| TASK-022 | CloudWatch Logs查询 | ✅ | 2024-02 |
| TASK-023 | 指标数据持久化 | ✅ | 2024-02 |
| TASK-024 | 采集调度器 | ✅ | 2024-02 |

### 1.4 DETECT模块

| ID | 任务 | 状态 | 完成日期 |
|----|------|------|----------|
| TASK-030 | 规则引擎框架 | ✅ | 2024-02 |
| TASK-031 | 阈值规则实现 | ✅ | 2024-02 |
| TASK-032 | 范围规则实现 | ✅ | 2024-02 |
| TASK-033 | 默认规则集 (11条) | ✅ | 2024-02 |
| TASK-034 | Z-Score统计检测 | ✅ | 2024-02 |
| TASK-035 | IQR异常检测 | ✅ | 2024-02 |
| TASK-036 | 移动平均检测 | ✅ | 2024-02 |
| TASK-037 | 异常持久化 | ✅ | 2024-02 |

### 1.5 ANALYZE模块

| ID | 任务 | 状态 | 完成日期 |
|----|------|------|----------|
| TASK-040 | Bedrock LLM集成 | ✅ | 2024-02 |
| TASK-041 | RCA Prompt构建 | ✅ | 2024-02 |
| TASK-042 | 结构化响应解析 | ✅ | 2024-02 |
| TASK-043 | RCA结果存储 | ✅ | 2024-02 |
| TASK-044 | 上下文增强（指标/元数据） | ✅ | 2024-02 |

### 1.6 REPORT模块

| ID | 任务 | 状态 | 完成日期 |
|----|------|------|----------|
| TASK-050 | 每日报告生成 | ✅ | 2024-02 |
| TASK-051 | 异常报告生成 | ✅ | 2024-02 |
| TASK-052 | 资源清单报告 | ✅ | 2024-02 |
| TASK-053 | 报告文件存储 | ✅ | 2024-02 |

### 1.7 AGENT模块

| ID | 任务 | 状态 | 完成日期 |
|----|------|------|----------|
| TASK-060 | LangChain Agent框架 | ✅ | 2024-02 |
| TASK-061 | 工具注册 (8个) | ✅ | 2024-02 |
| TASK-062 | 对话循环实现 | ✅ | 2024-02 |
| TASK-063 | 命令解析器 | ✅ | 2024-02 |

### 1.8 CLI模块

| ID | 任务 | 状态 | 完成日期 |
|----|------|------|----------|
| TASK-070 | Typer CLI框架 | ✅ | 2024-02 |
| TASK-071 | 账户管理命令 | ✅ | 2024-02 |
| TASK-072 | 扫描/监控命令 | ✅ | 2024-02 |
| TASK-073 | 检测/分析命令 | ✅ | 2024-02 |
| TASK-074 | 报告/对话命令 | ✅ | 2024-02 |
| TASK-075 | Rich美化输出 | ✅ | 2024-02 |

### 1.9 WEB模块

| ID | 任务 | 状态 | 完成日期 |
|----|------|------|----------|
| TASK-080 | FastAPI应用框架 | ✅ | 2024-02 |
| TASK-081 | 仪表板页面 | ✅ | 2024-02 |
| TASK-082 | 资源列表页面 | ✅ | 2024-02 |
| TASK-083 | 异常列表/详情页面 | ✅ | 2024-02 |
| TASK-084 | 报告列表页面 | ✅ | 2024-02 |
| TASK-085 | HTMX动态交互 | ✅ | 2024-02 |
| TASK-086 | Tailwind样式 | ✅ | 2024-02 |

### 1.10 测试

| ID | 任务 | 状态 | 完成日期 |
|----|------|------|----------|
| TASK-090 | 数据模型测试 | ✅ | 2024-02 |
| TASK-091 | 规则引擎测试 | ✅ | 2024-02 |
| TASK-092 | 统计检测器测试 | ✅ | 2024-02 |

### 1.11 Bug修复

| ID | 任务 | 状态 | 完成日期 |
|----|------|------|----------|
| TASK-BUG-001 | 修复SQLAlchemy `metadata`保留字冲突 | ✅ | 2024-02 |
| TASK-BUG-002 | 修复移动平均检测std=0时的Bug | ✅ | 2024-02 |
| TASK-BUG-003 | 修复测试数据库隔离问题 | ✅ | 2024-02 |

### 1.12 Phase 2 — 调度/通知/认证/集成测试

| ID | 任务 | 状态 | 完成日期 |
|----|------|------|----------|
| TASK-100 | 定时调度器 (scheduler/scheduler.py + API endpoints) | ✅ | 2025 |
| TASK-101 | 邮件通知 (notify/notifier.py EmailNotifier) | ✅ | 2025 |
| TASK-102 | Slack通知 (notify/notifier.py SlackNotifier) | ✅ | 2025 |
| TASK-103 | 通用Webhook通知 (notify/notifier.py WebhookNotifier，替代PagerDuty) | ✅ | 2025 |
| TASK-104 | Web认证 (auth/ 模块 + JWT sessions + API keys) | ✅ | 2025 |
| TASK-105 | 集成测试 (tests/integration/ AWS Mock测试，229项测试全部通过) | ✅ | 2025 |
| TASK-110 | 知识库模块 (kb/ 模块，向量嵌入 + 关键词搜索) | ✅ | 2025 |
| TASK-114 | 资源拓扑图 (graph/ 模块 + React Flow 前端) | ✅ | 2025 |
| TASK-123 | 审计日志 (audit/ 模块 + API endpoints) | ✅ | 2025 |

### 1.13 Phase 3 — Strands多智能体架构迁移

| ID | 任务 | 状态 | 完成日期 |
|----|------|------|----------|
| TASK-200 | Strands Multi-Agent 架构迁移（从 LangChain 迁移） | ✅ | 2026-02 |
| TASK-201 | HealthIssue 数据模型（替代 Anomaly） | ✅ | 2026-02 |
| TASK-202 | FixPlan 数据模型 + SRE Agent | ✅ | 2026-02 |
| TASK-203 | RCA Agent（集成知识库搜索） | ✅ | 2026-02 |
| TASK-204 | 网络拓扑分析（VPC/EKS） | ✅ | 2026-02 |
| TASK-205 | React SPA 前端 | ✅ | 2026-02 |
| TASK-206 | HealthIssue/FixPlan/Schedule/Notification API endpoints | ✅ | 2026-02-22 |
| TASK-207 | ThinkingDisplay spinner 动画修复 | ✅ | 2026-02-22 |
| TASK-208 | Chat Token 用量追踪 | ✅ | 2026-02-22 |

---

## 2. 进行中任务 (In Progress)

### 2.1 EKS Chaos Lab — 端到端测试

| ID | 任务 | 状态 | 说明 |
|----|------|------|------|
| TASK-300 | EKS Chaos Lab 基础设施脚本 | ✅ | `infra/eks-chaos-lab/` — 21个文件，本地验证全部通过 |
| TASK-301 | EKS 集群创建 & 工作负载部署 | 🔄 | `setup.sh` 手动执行中 |
| TASK-302 | CloudWatch 告警链路测试 | ⏳ | 6个告警 → detect agent → HealthIssue |
| TASK-303 | Chaos 注入 & Agent 检测验证 | ⏳ | 5种故障场景逐个测试 (pod-kill, node-drain, resource-stress, network-chaos, config-break) |
| TASK-304 | RCA + SRE Agent 修复流程验证 | ⏳ | analyze issue → fix issue → 端到端闭环 |
| TASK-305 | 清理 & 测试报告 | ⏳ | cleanup.sh + 测试结果记录 |

### 2.2 多监控源 Provider 设计 (待 Chaos Lab 完成后启动)

| ID | 任务 | 状态 | 说明 |
|----|------|------|------|
| TASK-310 | Monitoring Provider 抽象层设计 | ⏳ | 定义统一 Provider 接口 (list_alarms, get_metrics, query_logs) |
| TASK-311 | CloudWatch Provider 实现 | ⏳ | 将现有 CloudWatch 工具重构为第一个 Provider |
| TASK-312 | Prometheus Provider 实现 | ⏳ | 对接 Prometheus API (PromQL 查询 + Alertmanager 告警) |
| TASK-313 | Datadog Provider 实现 | ⏳ | 对接 Datadog API (monitors + metrics + logs) |
| TASK-314 | Provider 注册 & 账户关联机制 | ⏳ | 账户配置中声明使用哪些 Provider，Agent 按需调用 |

**架构决策记录 (ADR-001)**:
> 采用 **路线 A — Provider 模式** 优先：为每个监控数据源实现独立的 Provider adapter，Agent 根据账户配置按需调用。
> 后续如需统一告警收敛（路线 B — Webhook 聚合层），可在 Provider 之上叠加，两者不冲突。
> 优先顺序：CloudWatch (已有) → Prometheus → Datadog → 其他。

---

## 3. 待开始任务 (Backlog)

### 3.1 高优先级 (P1)

*全部已完成，已移至 1.12 节*

### 3.2 中优先级 (P2)

| ID | 任务 | 描述 | 依赖 | 预估工作量 | 状态 |
|----|------|------|------|-----------|------|
| TASK-110 | 知识库模块 | RCA模式存储和检索 | - | 5天 | ✅ 已移至 1.12 |
| TASK-111 | 趋势图表 | 指标趋势可视化 | - | 3天 | ⏳ 待开始 |
| TASK-112 | 自定义规则UI | Web界面配置检测规则 | TASK-104 ✅ | 4天 | ⏳ 待开始 |
| TASK-113 | 异常聚合 | 相似异常自动聚合 | - | 3天 | ⏳ 待开始 |
| TASK-114 | 资源拓扑图 | 资源依赖关系可视化 | - | 5天 | ✅ 已移至 1.12 |
| TASK-115 | 批量操作 | 异常批量确认/忽略 | - | 2天 | ⏳ 待开始 |

### 3.3 低优先级 (P3)

| ID | 任务 | 描述 | 依赖 | 预估工作量 | 状态 |
|----|------|------|------|-----------|------|
| TASK-120 | Azure支持 | Azure资源扫描 | - | 10天 | ⏳ 待开始 |
| TASK-121 | GCP支持 | GCP资源扫描 | - | 10天 | ⏳ 待开始 |
| TASK-122 | RBAC权限 | 角色权限控制 | TASK-104 ✅ | 5天 | ⏳ 待开始 |
| TASK-123 | 审计日志 | 操作审计追踪 | - | 3天 | ✅ 已移至 1.12 |
| TASK-124 | API文档 | OpenAPI文档自动生成 | - | 1天 | 部分完成 (FastAPI自动生成OpenAPI) |
| TASK-125 | Docker部署 | Dockerfile和compose | - | 2天 | ⏳ 待开始 |
| TASK-126 | K8s部署 | Helm Chart | TASK-125 | 3天 | ⏳ 待开始 |

### 3.4 监控源扩展 (P2, 依赖 TASK-303 完成)

| ID | 任务 | 描述 | 依赖 | 状态 |
|----|------|------|------|------|
| TASK-310 | Monitoring Provider 抽象层 | 统一接口: list_alarms, get_metrics, query_logs | TASK-303 | ⏳ 待开始 |
| TASK-311 | CloudWatch Provider | 重构现有工具为 Provider 实现 | TASK-310 | ⏳ 待开始 |
| TASK-312 | Prometheus Provider | PromQL + Alertmanager 对接 | TASK-310 | ⏳ 待开始 |
| TASK-313 | Datadog Provider | Monitors + Metrics + Logs API 对接 | TASK-310 | ⏳ 待开始 |
| TASK-314 | Provider 注册机制 | 账户配置关联 Provider，Agent 按需调用 | TASK-310 | ⏳ 待开始 |

---

## 4. 版本规划

### v0.1.0 (MVP) - ✅ 已完成
- 核心功能：SCAN, MONITOR, DETECT, ANALYZE, REPORT
- 接口：CLI, Web基础版, Agent

### v0.2.0 - ✅ 已完成
- **主题**: 调度与通知
- **任务**: TASK-100 ~ TASK-105
- **里程碑**:
  - [x] 定时调度扫描/检测 (scheduler/scheduler.py)
  - [x] 多渠道告警通知 (Email + Slack + Webhook)
  - [x] 通知配置管理
  - [x] Web认证 (JWT sessions + API keys)
  - [x] 集成测试 (229项测试)

### v0.3.0 - 部分完成
- **主题**: 安全与可视化
- **任务**: TASK-104, TASK-111, TASK-114
- **里程碑**:
  - [x] Web用户认证 (TASK-104)
  - [ ] 指标趋势图表 (TASK-111 ⏳)
  - [x] 资源拓扑图 (TASK-114，graph/ 模块 + React Flow)

### v0.4.0 - 部分完成
- **主题**: 智能增强
- **任务**: TASK-110, TASK-112, TASK-113
- **里程碑**:
  - [x] RCA知识库 (TASK-110，kb/ 模块，向量嵌入 + 关键词搜索)
  - [ ] 自定义规则 (TASK-112 ⏳)
  - [ ] 异常聚合 (TASK-113 ⏳)

### v0.5.0 - ✅ 已完成 (2026-02)
- **主题**: Strands 多智能体架构
- **任务**: TASK-200 ~ TASK-208
- **里程碑**:
  - [x] 从 LangChain 迁移至 Strands Multi-Agent
  - [x] HealthIssue / FixPlan 数据模型
  - [x] SRE Agent + RCA Agent
  - [x] 网络拓扑分析 (VPC/EKS)
  - [x] React SPA 前端
  - [x] 全套 API endpoints
  - [x] Chat 体验优化 (spinner + token 追踪)

### v0.6.0 - 进行中 (2026-02)
- **主题**: 端到端验证 & 多监控源
- **任务**: TASK-300 ~ TASK-314
- **里程碑**:
  - [x] EKS Chaos Lab 基础设施 (TASK-300)
  - [ ] CloudWatch 告警链路端到端验证 (TASK-301 ~ TASK-305)
  - [ ] Monitoring Provider 抽象层 (TASK-310)
  - [ ] CloudWatch Provider 重构 (TASK-311)
  - [ ] Prometheus Provider (TASK-312)
  - [ ] Datadog Provider (TASK-313)

### v1.0.0 - 长期
- **主题**: 生产就绪
- **任务**: TASK-111, TASK-112, TASK-113, TASK-115, TASK-122, TASK-125, TASK-126
- **里程碑**:
  - [ ] 趋势图表 (TASK-111)
  - [ ] 自定义规则UI (TASK-112)
  - [ ] 异常聚合 (TASK-113)
  - [ ] 批量操作 (TASK-115)
  - [ ] RBAC权限控制 (TASK-122)
  - [x] 审计日志 (TASK-123 ✅)
  - [ ] 容器化部署 (TASK-125, TASK-126)

---

## 5. 技术债务

| ID | 描述 | 优先级 | 影响范围 | 状态 |
|----|------|--------|----------|------|
| DEBT-001 | datetime.utcnow() 弃用警告 | 低 | models.py | 待修复 |
| DEBT-002 | 测试覆盖率需持续提升 (当前229项测试) | 中 | 全局 | 持续改进中 |
| DEBT-003 | 缺少类型存根 | 低 | 全局 | 待修复 |
| DEBT-004 | 硬编码的默认配置 | 低 | rules.py | 待修复 |
| DEBT-005 | ChatContext 在 context.py 和 main.py 中重复定义 | 中 | cli/ | 待重构 |

---

## 6. 已知问题

| ID | 问题 | 严重程度 | 状态 | 备注 |
|----|------|----------|------|------|
| ISSUE-001 | ~~SQLAlchemy metadata保留字冲突~~ | 高 | ✅ 已修复 | 重命名为resource_metadata |
| ISSUE-002 | ~~移动平均检测std=0时失效~~ | 中 | ✅ 已修复 | 添加零标准差处理 |
| ISSUE-003 | ~~测试数据库隔离失败~~ | 中 | ✅ 已修复 | 直接更新settings对象 |

---

## 7. 下一步行动

### 立即行动 (本周)
1. [ ] 修复 datetime.utcnow() 弃用警告 (DEBT-001)
2. [ ] 重构 ChatContext 消除 main.py / context.py 重复定义 (DEBT-005)
3. [ ] 补充 Phase 3 (Strands) 相关单元测试

### 短期计划 (本月)
1. [ ] 指标趋势图表 (TASK-111)
2. [ ] 自定义规则UI (TASK-112)
3. [ ] 异常聚合 (TASK-113)

### 中期计划 (下季度)
1. [ ] 批量操作 (TASK-115)
2. [ ] RBAC权限控制 (TASK-122)
3. [ ] Docker / K8s 部署 (TASK-125, TASK-126)
4. [ ] 多云支持评估 (Azure / GCP)

---

## 8. 会议记录

### 2024-02-05 测试修复
- 修复3个测试失败问题
- 原因1: SQLAlchemy `metadata` 保留字
- 原因2: 移动平均检测边界条件
- 原因3: 测试数据库隔离
- 当时状态: 26/26 测试通过

### 2026-02-22 Phase 3 完成 & 任务清单更新
- Strands Multi-Agent 架构迁移全部完成 (TASK-200 ~ TASK-208)
- 当前状态: 229/229 测试通过 (含 integration/ AWS Mock 测试)
- 所有 P1 高优先级 Backlog 已清空
- 下一阶段重点: 趋势图表、自定义规则UI、异常聚合
