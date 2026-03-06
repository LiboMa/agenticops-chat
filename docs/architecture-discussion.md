# AgenticOps 架构讨论记录

> 持续更新文档，记录架构设计讨论和决策过程。

## 讨论时间线

- **Session 1**: 2026-02-08

---

## 一、项目定位

### 核心定位

基于 LLM Multi-Agent 的 AWS 云运维平台，定位为"驻场 SRE"——主动巡检、发现问题、给出方案、经人工确认后执行修复。

### 与 AWS DevOps Agent 的差异化

| 维度 | AWS DevOps Agent | AgenticOps |
|------|-----------------|-------------|
| 运行模式 | 被动响应（用户点"Investigate"） | 主动巡检 + 被动响应 |
| 架构 | 黑盒 SaaS，单 Agent | 开源，Multi-Agent，可定制 |
| 知识积累 | 无用户侧知识沉淀 | Knowledge Base 持续积累 Pattern 和 SOP |
| 工具范围 | 只用 AWS 内部 API | 可扩展（MCP、Code Interpreter） |
| 修复能力 | 只给建议，不执行 | 可执行（人工审批后） |
| 多账号 | 单账号 | 多账号管理 |
| 定制化 | 不可定制 | 完全可定制 |

### 自动化级别定位：L3-L4（甜蜜点）

| 级别 | 描述 | 是否覆盖 |
|------|------|----------|
| L1 | 告警转发 | ❌ |
| L2 | 智能摘要（降噪+聚合+优先级） | ✅ Detect Agent |
| L3 | 根因定位 + 修复建议 | ✅ RCA Agent |
| L4 | 人工确认后自动执行修复 | ✅ SRE Agent |
| L5 | 完全自主修复 | ❌ 明确不做 |

### 前沿性分析

- Agentic AIOps（LLM Agent 做自主推理和多步骤编排）是 2024-2026 年前沿方向
- AIOpsLab（微软 2024）刚开始系统性研究该方向
- AWS 2025 年推出 AgentCore/Strands SDK，基础设施层刚成熟
- 市面上真正用 Multi-Agent 架构做 AIOps 的开源项目极少
- **壁垒不在架构，在于**：KB 中 SOP/Pattern 的质量、RCA 准确率、对 AWS 服务特性的深度理解

---

## 二、Multi-Agent 架构设计

### Agent 清单

1. **主 Agent** — 交互、协调、派发任务
2. **Scan Agent** — 主动抓取资源清单
3. **Detect Agent** — 健康检查，被动优先（CloudWatch Alarms），主动为辅
4. **RCA Agent** — 根因分析，结合 SOP 和 Pattern
5. **Security Agent** — 安全事件/CVE（后续）
6. **SRE Agent** — 故障修复，人工审批后执行（第二期）
7. **Reporter Agent** — 复盘专家，沉淀结构化案例，驱动知识飞轮

### Agent 间通信模型

**原则：数据流通过 Metadata（解耦），控制流通过主 Agent（集中）。**

三种运行模式：

- **模式 A - 同步编排**：用户 CLI 指令 → 主 Agent → 子 Agent → 返回结果
- **模式 B - 异步巡检**：Scheduler → Detect Agent → 写入 Metadata → 通知用户
- **模式 C - 事件驱动链式反应**：Alarm → Detect → RCA → Fix_Plan → 等待审批

Critical severity 可设快速通道：Detect 直接触发 RCA，事后通知主 Agent。

### Agent 框架选型

| 维度 | LangChain | Strands SDK |
|------|-----------|-------------|
| 成熟度 | 生态大，API 变动频繁 | AWS 2025 新推，API 稳定但生态小 |
| Multi-Agent | 需要 LangGraph，学习曲线陡 | 原生 agent-as-tool |
| AgentCore 部署 | 需要适配层 | 原生兼容 |
| MCP 支持 | 通过 adapter | 原生内置 |
| 可观测性 | 需要 LangSmith 或自建 | 内置 trace/span，集成 CloudWatch |

**结论**：如果确定 Production 用 AgentCore，Strands SDK 是更自然的选择。建议做薄抽象层保留灵活性。

---

## 三、核心技术决策

### Metadata 设计

**建议用 SQLite 而非 JSON file**（单文件、零配置、支持并发读、有事务保证）。

关键字段：
- `accounts` — 账号配置
- `inventory` — 资源清单（含 `managed: true/false` 标记是否接管）
- `health_issues` — 健康问题（含完整生命周期状态机）
- `rca_results` — 根因分析结果
- `fix_plans` — 修复方案

Health Issue 生命周期：
```
open → investigating → root_cause_identified → fix_planned → fix_approved → fix_executed → resolved
```

每次写入带时间戳和 agent_id，可追溯。

### Detect Agent 的"被动优先"实现

```
Scan Agent 扫描资源
  → Detect Agent 检查是否有对应 CloudWatch Alarm
    → 没有 Alarm → 建议创建（或自动创建基础 Alarm）
    → 有 Alarm → 检查状态
      → ALARM → 深查（Metrics + Logs + CloudTrail）
      → OK → 跳过或低优先级抽查
```

### Knowledge Base 结构

```
knowledge_base/
├── sops/                    # 标准排查手册
│   ├── ec2-cpu-high.md
│   ├── rds-connection-exhausted.md
│   └── lambda-timeout.md
├── patterns/                # 抽象化故障模式
│   ├── cascade-failure.md
│   └── resource-exhaustion.md
├── cases/                   # 结构化案例（Reporter 生成）
│   └── 2026-02-08-rds-outage.md
└── index.json               # 向量索引元数据
```

KB 检索策略演进：
1. 前期：resource_type + anomaly_type 规则匹配
2. 中期：Bedrock Knowledge Base 向量检索
3. 后期：Pattern matching（issue 组合匹配）

### 冷启动策略

1. 预置 20-30 个常见 AWS 故障 SOP（RDS CPU 高、Lambda 超时、ECS OOM 等）
2. 用 LLM 基于 AWS 文档生成初始 SOP，人工审核后入库
3. 结构化提取 AWS 官方 Troubleshooting 文档

---

## 四、安全与权限

### 操作分级

| Level | 描述 | 确认方式 |
|-------|------|----------|
| L0 | 只读（查看、拉取日志） | 无需确认 |
| L1 | 低风险写（重启 ECS Task、清理旧版本） | 单次确认 |
| L2 | 中风险写（修改 SG 规则、更新 RDS 参数） | 二次确认 + 原因说明 |
| L3 | 高风险写（删除资源、修改 IAM、DB failover） | 确认码 + 回滚方案 |

### IAM 权限分离

```
AgenticOps-ReadOnly-Role    → Scan Agent, Detect Agent, RCA Agent
AgenticOps-Operator-Role    → SRE Agent（仅在用户审批后临时 assume，执行完释放）
```

### 必要 IAM 权限补充

现有权限需增加：
- `cloudtrail:LookupEvents` — 变更关联（RCA 准确率提升的关键）
- CloudWatch Alarm 相关权限（Detect Agent）

---

## 五、多账户与 Cross-Region 架构

### 5.1 复杂度分析

多账户 × 多 Region × 多 Agent 的完整方案，复杂度约为单账户的 3-4 倍。主要来源：

| 复杂度来源 | 影响 |
|-----------|------|
| 每个 Tool 要处理 scope 路由 | 代码量 ×1.5 |
| STS session 缓存和生命周期管理 | 新增子系统 |
| Metadata 查询全部要带 account 过滤 | 每个查询变复杂 |
| Agent prompt 理解 scope 语义 | Token 消耗增加，幻觉风险增加 |
| 跨账户关联分析 | RCA context window 可能不够 |

### 5.2 核心设计原则：多账户透明

> **Agent 层不感知账户概念。多账户路由由 Tool 层的 RuntimeContext 处理。Agent 的 system_prompt 和 tool 签名在单账户和多账户模式下完全一致。**

架构分层：

```
┌─────────────────────────────────────────────┐
│  Agent 层 — 完全不知道多账户的存在           │
│  只看到: "scan EC2" → "found 15 instances"  │
├─────────────────────────────────────────────┤
│  Tool 层 — 吸收多账户复杂度                  │
│  内部: resolve accounts → loop → aggregate  │
├─────────────────────────────────────────────┤
│  Metadata 层 — 天然支持多账户                │
│  Resource 表有 account_id 外键              │
├─────────────────────────────────────────────┤
│  CLI 层 — 用户控制 scope                     │
│  --account / --all / --group                │
└─────────────────────────────────────────────┘
```

Token 消耗对比：

| 方案 | 每次调用 token 消耗 |
|------|-------------------|
| Agent 理解多账户（❌ 不推荐） | prompt +500 token + 每个账户一轮 tool call |
| Tool 层吸收（✅ 推荐） | 和单账户完全一样，零增加 |

### 5.3 Cross-Region 策略

**推荐：Tool 内部并行，Agent 无感知。**

```python
@tool
def scan_ec2(regions: str = "all") -> str:
    accounts = ctx.resolve_accounts()
    all_results = []
    for account in accounts:           # 账户串行（各自 STS session）
        with ThreadPoolExecutor() as executor:  # Region 并行（共享 credentials）
            futures = {executor.submit(_scan_region, account, r): r
                       for r in resolve_regions(regions, account)}
            for future in as_completed(futures):
                all_results.extend(future.result())
    return format_results(all_results)
```

原则：**Account 串行（安全），Region 并行（性能）。**

### 5.4 渐进式多账户演进

```
Step 1 (Phase 1): 单账户，Agent 完全不知道"账户"概念
  → Tool 内部 _get_active_account()，零额外复杂度

Step 2 (Phase 2-3): 多账户，Agent 仍然无感知
  → CLI 加 --account/--all 参数
  → Tool 层加 RuntimeContext.resolve_accounts()
  → Agent prompt 和 tool 签名不变

Step 3 (Phase 3+): 跨账户关联（仅 RCA Agent 按需使用）
  → 加 collect_fault_domain tool
  → 只在分析时才跨账户采集
```

### 5.5 Landing Zone / 多账户拓扑

#### 典型企业 Landing Zone 结构

```
AWS Organization
├── Management Account          (Organizations, Billing, SSO)
├── Network Account             (Transit Gateway, VPC, VPN, Route53)
├── Shared Services Account     (AD, DNS, CI/CD pipelines)
├── Security Account            (GuardDuty, SecurityHub, CloudTrail 聚合)
├── Log Archive Account         (集中日志存储)
├── Workload - Production       (EKS, RDS, Lambda, ALB)
├── Workload - Staging          (同上，隔离环境)
└── Sandbox                     (开发实验)
```

#### 核心挑战

一个故障的实际链路可能跨越多个账户：

```
用户 → Route53 (Network Account)
     → ALB (Workload-Prod)
     → EKS Pod (Workload-Prod)
     → Transit Gateway (Network Account)  ← 问题可能在这里
     → 目标微服务 (另一个 Workload Account)
```

如果 Detect Agent 只看 Workload-Prod，它能看到 EKS 超时和 ALB 5xx，但看不到 Transit Gateway 丢包（在 Network Account）。RCA 拿到的上下文是残缺的。

#### 解决方案：Account Topology + Fault Domain

**第一层：Account Topology（静态配置，用户配置一次）**

```python
class AccountTopology(Base):
    """账户间的依赖关系。"""
    __tablename__ = "account_topology"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_account_id: Mapped[int] = mapped_column(ForeignKey("cloud_accounts.id"))
    target_account_id: Mapped[int] = mapped_column(ForeignKey("cloud_accounts.id"))
    relationship_type: Mapped[str] = mapped_column(String(50))
    # network_dependency:  Workload → Network Account
    # log_aggregation:     All → Log Archive Account
    # security_monitor:    All → Security Account
    # service_dependency:  Workload-A → Workload-B
    description: Mapped[str] = mapped_column(String(200))
```

CLI 配置：

```bash
aiops topology add workload-prod --depends-on network --type network_dependency
aiops topology add --all --depends-on log-archive --type log_aggregation
aiops topology add workload-prod --depends-on workload-shared --type service_dependency
```

**第二层：Fault Domain（动态推断，Tool 层自动扩展）**

当 RCA Agent 分析问题时，`collect_fault_domain` tool 根据 topology 自动跨账户采集：

```python
@tool
def collect_fault_domain(health_issue_id: int) -> str:
    """根据账户拓扑，自动采集跨账户的关联信号。"""
    issue = get_health_issue(health_issue_id)
    account = get_account_for_resource(issue.resource_id)
    dependencies = get_topology_dependencies(account.id)

    signals = {}
    for dep in dependencies:
        dep_session = get_session(dep.target_account)
        if dep.relationship_type == "network_dependency":
            signals["network"] = check_network_health(dep_session, region)
        elif dep.relationship_type == "log_aggregation":
            signals["centralized_logs"] = search_centralized_logs(dep_session, ...)
        elif dep.relationship_type == "service_dependency":
            signals["upstream_health"] = check_service_health(dep_session, ...)
    return format_signals(signals)
```

**第三层：RCA Agent 消费聚合后的上下文**

RCA Agent 不需要知道数据来自哪个账户，它看到的是完整的故障域视图：

```
## Direct Signals (same account)
- ALB 5xx rate: 12%, EKS Pod restart: 3

## Fault Domain Signals (cross-account, auto-collected)
- Network: Transit Gateway packet loss 8% ← 关键线索
- Centralized Logs: "connection reset by peer" × 47
- Upstream: payment-service healthy

## Recent Changes (cross-account CloudTrail)
- Network Account: 30min ago, ModifyTransitGatewayRouteTable ← 根因
```

#### Fault Domain 的渐进式实施

| Phase | 能力 | Token 增加 |
|-------|------|-----------|
| Phase 1-2 | 无，单账户独立工作 | 0 |
| Phase 3 | 加入 AccountTopology + collect_fault_domain | ~500-1000/次 RCA |
| Phase 4 | 智能拓扑发现（分析 TGW/VPC Peering 自动推断） | 仅发现时消耗 |

---

## 六、现有代码的改进方向

基于对当前 AgenticOps 代码的分析：

### 优先级 1：CloudTrail 变更关联

80% 的生产故障由人为变更引起。在 RCA 分析时查询故障时间窗口前后的 CloudTrail 事件，注入 prompt 上下文。

### 优先级 2：资源依赖图

当前 AWSResource 模型是扁平的，缺少资源间依赖关系。需要 ResourceDependency 表，通过分析 SG 规则、Lambda 环境变量、ECS Task Definition 等自动发现依赖。

### 优先级 3：历史故障 Few-shot

RCA prompt 中加入历史相似案例（同 resource_type + anomaly_type，confidence > 0.7），提升分析准确率。

### 其他改进

- 单体 OpsAgent（1000+ 行）拆分为 Router Agent + Specialist Agent
- 检测模型增加周期性处理和趋势检测（当前只有 Z-score）
- Pipeline 增加 checkpoint 和状态持久化

---

## 七、工具演进路线

```
L1（现在）: 预定义 boto3 tool，覆盖 80% 场景
L2（中期）: MCP 动态工具发现，Agent 通过 MCP Server 获取可用工具列表
L3（后期）: Code Interpreter，Agent 现场写代码执行
```

L3 安全边界：
- Docker 沙箱 + STS 短期 token + 最小权限
- 代码静态分析（禁止网络外传、禁止读取 key）
- **只允许读操作**，写操作必须走 SRE Agent 审批流程

---

## 八、成本控制

- Detect Agent 巡检：规则引擎 + Alarm 状态检查为主，**只在判断告警关联性时调用 LLM**
- RCA Agent：每次分析调用 LLM（合理）
- Reporter Agent：按需或每日生成（避免每小时）
- 在 Metadata 中记录每个 Agent 的 LLM 调用次数和 token 消耗

---

## 九、系统自身的可观测性

- Agent 执行日志（每次 tool 调用、LLM 调用、结果）
- 用户反馈机制（RCA 结果 👍/👎）
- 反馈数据回流 Knowledge Base

---

## 十、实施路径

```
Phase 1: 核心骨架
  ├── 主 Agent + Scan Agent + CLI 交互
  ├── Metadata 层（SQLite）
  └── 基础 Knowledge Base 结构

Phase 2: 检测与分析
  ├── Detect Agent（Alarms 优先）
  ├── RCA Agent + SOP 匹配
  ├── CloudTrail 变更关联
  └── 多账户支持（Tool 层 RuntimeContext，Agent 无感知）

Phase 3: 闭环 + 跨账户
  ├── SRE Agent（只生成修复建议）
  ├── Reporter Agent + 案例沉淀
  ├── Knowledge Base 向量化
  ├── Account Topology 配置 + Fault Domain 采集
  └── CLI: aiops topology add/list/remove

Phase 4: 进化
  ├── MCP 动态工具
  ├── Code Interpreter（只读沙箱）
  ├── 智能拓扑发现（自动推断账户依赖）
  └── AgentCore 部署
```

---

## 十一、必要约束（来自原始设计文档）

1. 功能优先
2. CLI → API → UI（"把 CLI 做极致，API 自然就有了"）
3. 模块化、分批次
4. Human-in-the-loop：最重要的信息和建议主动给使用者，最终由人决断

---

## 待讨论事项

- [x] Agent 框架最终选型确认 → **Strands Agents SDK** (2026-02-08)
- [x] 多账户架构方案确认 → **Tool 层吸收，Agent 无感知** (2026-02-08)
- [x] Cross-Region 策略确认 → **Tool 内部并行（Account 串行，Region 并行）** (2026-02-08)
- [x] Landing Zone 跨账户 RCA 方案 → **Account Topology + Fault Domain** (2026-02-08)
- [ ] Metadata 存储方案确认（SQLite vs JSON vs 混合）
- [ ] Detect Agent 是否有写权限（自动创建基础 Alarm）
- [ ] 预置 SOP 的优先级列表
- [ ] AgentCore 部署的时间节点
- [ ] Code Interpreter 沙箱方案细化

---

*最后更新: 2026-02-09*


## Session 3: 2026-03-01 — 自愈闭环架构：告警驱动 + 巡检预测

### 讨论背景

在运行 detect_agent 后发现 Issue #67（EKS 集群 `agenticops-chaos-lab`
被用户手动删除后，
Detect 基于旧 Inventory 报出 CRITICAL 误报），引发了对 Inventory 与 Detect
同步机制的深入讨论，
最终演进为完整的自愈闭环架构设计。

### 核心问题

1. **Inventory 是静态快照** — Scan 后 AWS 侧发生变更，Detect
基于旧数据检查导致误报
2. **当前流程是线性手动的** — 需要人工依次触发 Scan → Detect → RCA → Fix
3. **缺乏预测能力** — 只能发现"已发生"的问题，无法预见"即将发生"的问题

### 架构决策：两条流水线，一个闭环

#### 核心理念

> 告警止血 + 巡检预测，共享同一套 RCA → Fix → Resolve 后端。

#### 流水线 A：告警驱动（被动止血，实时）

```
多源告警接入 (CloudWatch / Prometheus / Datadog / PagerDuty / Custom)
    │
    ▼
告警聚合/关联引擎 (Alert Correlation)
  - 时间窗口 30-60s 聚合
  - 资源依赖图关联同根因告警
  - 去重：5 个告警 → 1 个 Incident
    │
    ▼
Inventory 预检
  - 资源在库且 TTL 有效？ → 跳过 Scan，直接 Detect
  - 资源不在库？ → 局部 Scan → 再 Detect
    │
    ▼
Detect (局部, shallow)
  - 只查告警相关资源 + Blast Radius（依赖图扩展 N 层）
    │
    ▼
[进入统一后端]
```

**关键洞察（由用户提出）：在应用级别，事件告警比资源变更更普遍、更实际。
告警才是驱动整个流程的第一推动力。**

#### 流水线 B：定时巡检（主动预测，周期性）

```
Cron (每 1-4 小时)
    │
    ▼
Scan (全量/增量) → 刷新 Inventory + TTL
    │
    ▼
Detect (全量, deep=true)
  - 拉取历史指标做趋势分析
    │
    ▼
趋势预测引擎
  - 磁盘 72% + 2%/天 → 14 天后满
  - 子网 IP 65% → 3 周后耗尽
  - DB 连接峰值递增 → 下月触顶
  - 证书到期倒计时
    │
    ▼
生成预测性 Issue → [进入统一后端]
```

**关键洞察：巡检的价值不在于"现在有没有问题"，而在于"照这趋势，未来会不会出问题"。
**

#### 统一后端：RCA → Fix → Resolve

```
统一 Issue 管理层 (告警 Issue + 预测 Issue，去重/优先级排序)
    │
    ▼
RCA Agent (CloudTrail + Metrics + Logs + Knowledge Base)
    │
    ▼
Fix Plan + 风险分级门控
  - L0 无风险 (清日志、重启 Pod) → 全自动
  - L1 低风险 (扩容 ASG) → 可自动
  - L2 中风险 (改 SG、切 DB) → 需人工确认
  - L3 高风险 (删资源、改 IAM) → 必须审批
    │
    ▼
执行 → Post-Check 验证
  - 通过 → Resolved ✅
  - 失败 → Rollback + 升级人工 🔴
  - 30 分钟内复发 → 标记"反复发作" → 升级为架构问题 📋
    │
    ▼
知识沉淀 (已解决 Case → Knowledge Base → 加速未来 RCA)
```

### 两条流水线对比

| 维度 | 流水线 A：告警止血 | 流水线 B：巡检预测 |
|------|-------------------|-------------------|
| 触发 | Alert 事件（被动） | Cron 定时（主动） |
| Scan | 条件触发（Inventory 缺失时才跑） | 全量/增量（刷新 Inventory） |
| Detect 范围 | 局部 — 告警资源 + Blast Radius | 全局 — 所有托管资源 |
| Detect 深度 | shallow — 当前状态 | deep — 历史趋势 + 预测 |
| 核心问题 | "现在出了什么问题？" | "照这趋势，未来会出什么问题？" |
| 时效要求 | 秒级 ~ 分钟级 | 小时级 |
| Issue 类型 | 告警 Issue（urgent） | 预测 Issue（proactive） |
| 价值 | 减少 MTTR | 减少事故数量 |

### 关键设计决策

1. **告警聚合层** — 30-60s 时间窗口 + 依赖图关联 + 去重，避免同一故障触发多轮 RCA
2. **Inventory TTL 机制** — 告警进来先查 Inventory，TTL 内跳过
Scan，过期或缺失才局部 Scan
3. **Blast Radius 分析** — 从告警资源沿依赖图扩展 N 层，Detect 只查爆炸半径内资源
4. **趋势预测引擎** —
线性外推（磁盘/IP/连接数）、到期倒计时（证书）、周期性峰值预测
5. **Fix 风险分级门控** — L0-L3 四级，与现有 approve_fix_plan 机制对齐
6. **反馈闭环** — Post-Check + Rollback + 反复发作检测 + 知识沉淀

### 与现有系统的映射

| 架构组件 | 当前状态 | 需要建设 |
|---------|---------|---------|
| 多源告警接入 | ✅ CloudWatch + 外部 Provider | 🔨 告警聚合/关联引擎 |
| Inventory | ✅ scan_agent | 🔨 TTL 机制 + 条件触发 |
| Detect | ✅ detect_agent (shallow + deep) | 🔨 Blast Radius 局部检测 |
| 依赖图 | ✅ 网络拓扑（VPC 级） | 🔨 扩展到全资源类型 |
| RCA | ✅ rca_agent | ✅ 已有 |
| Fix Plan | ✅ sre_agent + 风险分级 | ✅ 已有 |
| 审批门控 | ✅ approve_fix_plan (L0-L3) | ✅ 已有 |
| Auto Fix | ✅ executor_agent | ✅ 已有 |
| Post-Check | ✅ 执行器内置 | 🔨 反复发作检测 |
| 趋势预测 | ❌ | 🔨 需新建 |
| 知识沉淀 | ✅ Knowledge Base + Case Study | 🔨 自动沉淀闭环 |

### 建设优先级

**Phase 1（短期，价值最大）：**
- 告警聚合层 — 减少噪音和重复工作
- Inventory TTL + 条件 Scan — 告警响应提速

**Phase 2（中期）：**
- 资源依赖图 + Blast Radius — 精准局部 Detect
- 反复发作检测 — 避免反复修同一个问题

**Phase 3（长期）：**
- 趋势预测引擎 — 从被动响应走向主动预防
- 知识自动沉淀 — RCA 越做越快，形成飞轮
