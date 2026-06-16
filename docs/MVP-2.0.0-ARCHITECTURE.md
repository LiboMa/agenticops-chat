# MVP-2.0.0 "Methos" — 架构升级决策文档

> 2026-06-11 · 基于 5 路深度调研（业界竞品 / ITSM 流程 / Self-improving SOTA / 多云-IDC 抽象 / 代码全量审计）的综合产出
> 分支：`MVP-2.0.0.methos-release`

---

## 0. 一句话结论

**AgenticOps 2.0 的制胜定位 = "Governed Autonomy + Provable Self-Improvement + Open Multi-Cloud"**
（可治理的自治 + 可证明的自我进化 + 开放自托管多云）

业界所有玩家都在喊 "autonomous AI SRE"，但调研证实三个无人占据的空位，而它们恰好都长在我们已有的架构骨架上。

---

## 1. 调研核心发现（驱动决策的事实）

### 1.1 市场窗口（竞品全景，2026-06 验证）

| 玩家 | 状态 | 关键事实 |
|------|------|---------|
| **Azure SRE Agent** | GA 2026-03 | 微软内部 1300+ agents、35000+ 事件；自适应记忆；reader→autonomous 双档；**只限 Azure**；$292/月/agent + token 计费 |
| **AWS DevOps Agent** | GA ~2026-04 | 明确宣称 multicloud+on-prem；与 Dynatrace/Datadog/ServiceNow/PagerDuty 集成；credits 捆绑 Support Plan |
| **Datadog Bits AI SRE** | GA 2025-12 | "首个 GA 自治 agent"；每个告警触发即调查；iFood MTTR -70%；**定价不透明被诟病** |
| **PagerDuty AI Agents** | GA 2025-10 | SRE/Scribe/Shift/Insights 四 agent；"shared agent memory"、自更新 runbook |
| **ServiceNow** | 2025 全年 | AI Agent Orchestrator + Control Tower + **Zurich 版起原生支持 MCP client/server + A2A v0.3 外部 agent 注册** |
| **Cleric** | $9.8M, Gartner Cool Vendor 2025 | "首个 self-learning AI SRE"、operational memory、**read-only 默认**、"accuracy is measured, not claimed" — 离我们定位最近的对手 |
| **Traversal** | $48M, Amex 战投 | Amex MTTR -32%、RCA 准确率 82%；BYOC 部署 |
| **CNCF 开源层** | HolmesGPT/kagent/K8sGPT | 都只是积木，**没有一个带完整事件生命周期（状态机/审批/修复闭环）** |

**命名预警**：Cisco 自 2025-06 起大规模使用 "AgenticOps" 作为品类营销词（AI Canvas）。这验证了品类，但有品牌碰撞风险 — 建议对外叙事用 "**the open AgenticOps platform**" 框架。

### 1.2 五个可引用的客户级数据（已逐一溯源验证）

1. **Gartner**: 到 2029 年 **70%** 的企业将部署 agentic AI 运维基础设施（2025 年 <5%）
2. **Gartner**: **>40%** 的 agentic AI 项目将在 2027 年底前被取消 — 主因：成本失控、价值不清、**风控不足** → 这正是 Governed Autonomy 的卖点
3. **Splunk/Oxford Economics 2026**: 全球 2000 强非计划停机成本 **$600B/年**（两年涨 50%），平均每家 **$300M/年**
4. **New Relic 2025**: 高影响故障中位成本 **$2M/小时（$33,333/分钟）**
5. **学术基准**: 最强 agent 仅解决 ITBench **13.8%** SRE 场景 / OpenRCA **11.34%** 根因案例 → 行业天花板极低，可证明的改进曲线 = 降维打击

### 1.3 三大白地（无人做好，且都长在我们骨架上）

| 白地 | 业界现状 | 我们已有的地基 |
|------|---------|--------------|
| ① **可治理的自治**（autonomy you can audit） | Azure 只有 2 档开关；无人把"每个动作的自治等级"做成可审计的产品对象 | L0-L4 风险分级 + 9 态状态机 + 审批门控 + PipelineEvent 审计已存在，缺**策略引擎**把规则从硬编码变成可声明、可审计的 policy |
| ② **可证明的自我进化**（provable self-improvement） | 所有厂商都说 "learns from incidents"，**零厂商公布改进曲线**；Cleric 最接近但闭源黑盒 | Hermes 记忆 + Skills 自治（草稿→安全扫描→发布→谱系→归档回滚）业界独一份，缺**度量层**（MTTR-per-pattern、首次修复率、复发加速比） |
| ③ **开放自托管多云+IDC** | 超大厂 agent 锁自家云；SaaS 创业公司进不了主权/中国区 | providers/{aws,azure,gcp,alicloud} ABC 已建（887 LOC），缺**能力分型接口** + SSH/Prometheus 两个 IDC provider |

---

## 2. MVP-2.0.0 四大支柱（本次落地）

### 支柱 A：Governed Autonomy Policy Engine（治理型策略引擎）

**问题**：审计发现 auto-approve 硬编码在 `services/pipeline_service.py`（`if risk_level in (L0, L1)`）。无法按客户/环境/资源/时间窗定制，无法解释"为什么自动批了"。

**方案**：`services/policy_engine.py` + `config/policies.yaml`

```yaml
# config/policies.yaml — 声明式自治策略（可审计工件）
version: 1
defaults:
  action: require_human          # 兜底永远保守
rules:
  - name: auto-approve-low-risk
    match: { risk_level: [L0, L1] }
    action: auto_approve
    itsm_change_type: standard   # SOC2: 即使全自动也要落标准变更记录
  - name: blast-radius-escalation
    match: { blast_radius_gte: 3 }     # 图引擎：影响≥3个下游服务
    action: escalate              # 升一级审批
  - name: freeze-window
    match: { in_change_freeze: true }
    action: block
  - name: medium-risk-itsm-gated
    match: { risk_level: [L2, L3] }
    action: require_itsm_change   # ServiceNow normal change 审批后才执行
    itsm_change_type: normal
```

**关键设计**：
- `PolicyDecision(action, rule_name, reasons[], itsm_change_type)` — 每次决策记入 PipelineEvent（审计链）
- 默认策略文件复刻现有行为（L0/L1 auto）→ **零破坏性**
- 图引擎 blast-radius 作为策略输入（业界只有 Causely 卖这个，且它不执行）
- ITIL 映射：L0/L1=Standard Change（预授权模板，模板本身就是人类一次性授权的审计证据）、L2/L3=Normal Change、L4=Emergency Change
- SoD（职责分离）：执行身份 ≠ 审批身份，审批委托永远留在 ITSM/IM 侧

### 支柱 B：ITSM Bridge（企业流程桥）

**问题**：企业买家 Day-1 要求（采购就绪度报告 4.4 节）；SOC2 CC8.1 要求**每一次自动修复都有变更记录**（Type II 审计会抽样 5-25 个变更要证据）。当前通知层是单向 fire-and-forget。

**方案**：新模块 `src/agenticops/itsm/`

```
itsm/
├── base.py        # ITSMAdapter ABC: create_incident / update_incident_state /
│                  #   append_worknote / create_change / get_change_approval /
│                  #   close_change / create_kb_article
├── servicenow.py  # Table API + sn_chg_rest（含 conflict 检查、审批轮询 30-60s）
├── jira.py        # JSM servicedeskapi（request + approval 读取）
├── bridge.py      # 订阅 pipeline 事件 → 状态机映射 → 调 adapter；dry_run 模式
└── (ITSMLink 表)  # entity_type/entity_id ↔ external system/id/number/url（幂等键）
```

**9 态状态机 ↔ ServiceNow 映射**（调研逐字段验证，含陷阱修正）：

| AgenticOps | SN incident.state | SN change.state |
|---|---|---|
| open | New(1) | — |
| investigating / acknowledged | In Progress(2) | — |
| root_cause_identified | In Progress + RCA work_notes | — |
| fix_planned | 不变 | New(-5)→Assess(-4)（normal）/ 直接 Scheduled（standard 模板） |
| fix_approved | 不变 | Scheduled(-2), approval=approved |
| fix_executing | 不变 | Implement(-1) + 逐命令 work_notes |
| fix_executed | 不变 | Review(0) |
| resolved | **Resolved(6)**（永不写 7，Close 是客户流程） | Closed(3) + close_code=successful |

已验证的陷阱：incident state 没有 4/5；sn_chg_rest **没有** GET approvals 端点（轮询 `sysapproval_approver` 表或 change.approval 字段）；work_notes 是 write-only journal；PagerDuty REST 写 incident 必须带 `From:` header。

**v1 范围**：ServiceNow + Jira 两个 adapter，`itsm_dry_run: true` 默认（dry-run 打印完整 API 调用序列 → 这本身就是绝佳的 demo 与售前材料）。PagerDuty 留在 notify 层（它是寻呼不是变更管理）。

### 支柱 C：Multi-Cloud + IDC Capability Layer（多云能力分型层）

**问题**：providers ABC 只有 `resolve_credentials/cli_tool/sdk_session`，是"凭证层"不是"能力层"；agents 仍硬编码 AWS 工具；无 IDC 故事。

**方案**（采纳调研的 capability-typed protocol 设计，对现有 ABC **纯增量**）：

```python
class Capability(str, Enum):
    INVENTORY / METRICS / LOGS / AUDIT / ALARMS / EXECUTE / COST / CLI

@dataclass(frozen=True)
class ResourceRef:
    # urn:agops:{provider}:{account}:{region}:{service}:{type}:{id}
    # native_id 永远保留云原生 ID 原文（ARN / Azure resource ID / GCP full name）

class SupportsInventory(Protocol): def list_resources(...) -> list[ResourceRef]
class SupportsMetrics(Protocol):   def query_metrics(...) -> list[dict]
class SupportsExecute(Protocol):   def execute(...) -> dict
# CloudProvider.capabilities() → 运行时能力发现，agent 路由前先查
```

**新 provider（IDC 故事的最小可信集）**：
- `SSHProvider` — execute + 单机 inventory。同时也是 GCP 的 exec 路径（GCP 无 SSM 等价物）+ 任何云 VM 的逃生通道。复用 skills/security.py 命令分级门控。
- `PrometheusProvider` — `query_range`（PromQL）+ `/api/v1/targets` 即免费主机盘点。零新依赖。
- `KubernetesProvider`（轻量）— 形式化现有 run_kubectl：kubeconfig+context 凭证 schema。EKS/AKS/GKE/k3s/OpenShift 一个 provider 通吃 = 最便宜的 "multi-everything"。

**Azure/GCP 读路径（Phase 2，本次接口就绪+实现骨架）**：
- Azure Resource Graph：**一条 KQL 盘点整个租户**（`ResourceGraphClient.resources()`，免费，Reader 权限即可，15 queries/5s 限流带 header 感知退避）
- GCP Cloud Asset Inventory：`search_all_resources(scope="organizations/X")` **一次调用扫全组织**
- 战略洞察：**最难的 provider（AWS，需逐服务枚举）我们已经建完了；Azure/GCP 反而更便宜** — 各自一个索引化查询 API 搞定全量盘点。

**凭证铁律延伸**：子进程注入前 strip 清单从 `AWS_*` 扩展到 `ARM_* / GOOGLE_* / ALIBABA_CLOUD_*`（对称防串号）。

### 支柱 D：Self-Improvement Metrics（自我进化度量层）

**问题**：调研确认**全行业没有任何厂商公布 agent 改进曲线** — 而我们的 DB（HealthIssue 时间戳 / FixExecution 状态 / RCAResult 置信度 / SOPRecord 使用计数 / skills last_used）今天就能算出来。这是从"声称会学习"到"证明在学习"的最后一公里，也是 pitch deck 的核心图表。

**方案**：`services/metrics_service.py` + `GET /api/metrics/improvement`

| 指标 | 计算来源 | 客户语言 |
|------|---------|---------|
| **MTTR by pattern** | HealthIssue(detected_at→resolved_at) 按 issue 指纹分组 | "同类问题第 N 次出现修得多快" |
| **复发加速比**（improvement curve★） | 同 fingerprint 的 issue 按出现序号的 MTTR 曲线 | "第 3 次遇到同类故障，MTTR 下降 N%" — **全行业没人敢放的图** |
| **首次修复率** (first-time-fix) | FixExecution 首次执行即 succeeded 的占比 | 最强的单一客户数字 |
| **自动化率 / 人工覆盖率** | FixPlan approved_by 含 agent: 前缀占比；人工拒绝/回滚占比 | 信任曲线（安全 KPI） |
| **知识复用率** | SOPRecord.application_count、skills touch_used、memory last_used | "您的运维知识在被复用，不是在腐烂" |
| **每次修复成本** | AgentLog tokens × 模型单价 | $0.25-3/次 vs SRE 人工 $37-75/次 |

文献支撑（验证过的数字，写进 PPT）：Voyager 技能库 = 任务速度 **15.3x**；Reflexion 自我反思 = 80%→**91%**；AWM 工作流记忆 = **+51.1%**；STRATUS 事务性不回退（TNR）= 缓解能力 **≥1.5x**。我们的 memory+skills 架构正是这些机制的工程化合体。

---

## 3. 增益性改造（编入支柱，不单列）

1. **Verified-success-only distillation**（Voyager 规则）：只有 post-fix 验证通过的修复才触发 skill/memory 蒸馏 — 在 resolution_service 挂钩（Phase 2 wiring）。
2. **Reflexion failure memos**：验证失败或人工 override 时强制写一条 `type=feedback` 的"我为什么错了"记忆。
3. **LLM-as-judge plan review**：Haiku 对每个 FixPlan 按 rubric（爆炸半径/可逆性/前置条件覆盖）打分，作为 policy engine 的输入信号（Phase 2）。
4. **Eval harness 三环**（Phase 2-3 路线图，写进 PPT 的 roadmap）：
   - Ring 1 黄金事件回放（夜跑，memory ON/OFF 对照 → 学习效应一图呈现）
   - Ring 2 故障注入实验室（已有 infra/eks-lab 10 场景，升级成 AIOpsLab 式 oracle 评分）
   - Ring 3 公开基准（直接跑 ITBench/AIOpsLab，"AgenticOps 解决 X% vs 业界 13.8%" = 最强第三方背书）

## 4. 明确不做（YAGNI，按调研证据砍掉）

- ❌ 完整 World Model / Active Inference — 调研结论：2026 仍是 hype；图引擎 blast-radius 预检 + 指标门控验证已覆盖其实用 80%
- ❌ 自建语义网关/告警聚合 — 维持既有判断：让 Datadog/Prometheus 干告警的事
- ❌ Kafka / 重型事件总线 — pipeline_events + 进程内订阅够用到企业版
- ❌ 嵌入 Steampipe/CloudQuery 作为核心 — AGPL/商业许可证 + 凭证铁律冲突；可作为可选 skill 子进程调用
- ❌ SaaS 多租户 / SOC2 认证本身 — 2.0 做的是"审计就绪的证据链"，认证是商业阶段的事

## 5. 实施清单（本分支落地）

| # | 交付物 | 文件 | 状态 |
|---|--------|------|------|
| 1 | Policy Engine + policies.yaml + 接线 pipeline_service | services/policy_engine.py | ✅ Done |
| 2 | ITSM Bridge（SN+Jira, dry-run）+ ITSMLink 表 + 事件订阅 | itsm/* | ✅ Done |
| 3 | Capability/ResourceRef/Protocols + SSH/Prometheus/K8s providers | providers/* | ✅ Done |
| 4 | Metrics Service + /api/metrics/improvement | services/metrics_service.py | ✅ Done |
| 5 | 全量测试通过 + 文档更新 | tests/* docs/* | ✅ 526/527 pass |
| 6 | 客户级 PPT + Demo 脚本 | docs/AgenticOps-2.0-Methos.pptx | ✅ Done |
| 7 | Azure ARG / GCP CAI 读路径实装、蒸馏验证门、eval Ring1 | — | 2.1 |

---

*依据：5 路并行深度调研报告（业界 40+ 源验证 / ServiceNow Zurich API 逐端点验证 / 30+ 论文基准数字溯源 / 4 云 SDK 入口验证 / 130 文件代码审计），关键数字均经对抗性复核。*
