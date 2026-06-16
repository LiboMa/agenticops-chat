# AgenticOps v2.0.0 "Methos" Release — 治理型自治 + 企业流程 + 预防性运维

> **版本**: 2.0.0 (Methos) | **日期**: 2026-06-12 | **分支**: `MVP-2.0.0.methos-release`

---

## 一、版本概述

v2.0.0 是从「能自动修」到「**敢交给它修**」的跨越版本。围绕四大支柱 + 预防三件套 + 凭证安全硬化展开：

| 主题 | 一句话 |
|------|--------|
| **支柱 A** Governed Autonomy | 自动审批从硬编码变成声明式策略文件（policies.yaml），每次决策可审计 |
| **支柱 B** ITSM Bridge | 每次自动修复自动落 ServiceNow/Jira 变更记录（SOC2 CC8.1 证据链） |
| **支柱 C** Multi-Cloud 能力层 | Capability 分型 + SSH/Prometheus/Kubernetes 三个新 provider（IDC 故事） |
| **支柱 D** 自我进化度量 | MTTR 复发曲线 / 首次修复率 / 自动化率 —— 从"声称会学习"到"证明在学习" |
| **预防三件套** | SPOF/容量巡检 + RCA 拓扑上下文 + 执行前影响模拟门 |
| **凭证安全硬化** | 多账户串号防护 6 条铁律全部落地（fail-closed + 身份校验 + 自动续期） |

---

## 二、支柱 A：Governed Autonomy Policy Engine

**问题**：auto-approve 硬编码 `if risk_level in (L0, L1)`，无法按环境/资源/时间窗定制，无法解释"为什么自动批了"。

**交付**：`services/policy_engine.py` + `config/policies.yaml`

- 声明式规则，自上而下首条匹配生效；动作：`auto_approve / require_human / require_itsm_change / block / escalate`
- 匹配维度：`risk_level / severity / provider / resource_pattern / blast_radius_gte / impact_severity / in_change_freeze`
- 变更冻结窗口（freeze_windows）：冻结期一切自动执行硬停
- `PolicyDecision(action, rule_name, reasons[])` 全量记入 PipelineEvent 时间线 —— 审计链
- 默认策略复刻历史行为（L0/L1 auto），**零破坏性**；策略文件加载失败 fail-closed 回退内置保守默认

ITIL 映射：L0/L1 = Standard Change（预授权模板）、L2/L3 = Normal Change、L4 = Emergency（永不自动）。

## 三、支柱 B：ITSM Bridge

**交付**：`src/agenticops/itsm/`（base ABC + servicenow + jira + bridge + ITSMLink 表）

- 订阅 pipeline 事件 → 9 态 HealthIssue 状态机映射到 SN incident/change 状态（调研逐字段验证，含 sn_chg_rest 无审批端点等陷阱修正）
- `require_itsm_change` 策略动作：fix plan 等待外部 ITSM 变更审批后才执行
- 默认 `itsm_dry_run: true` —— 打印完整 API 调用序列，即开即 demo
- 幂等：ITSMLink 表（entity ↔ external id）防重复创建

## 四、支柱 C：Multi-Cloud + IDC Capability Layer

**交付**：`providers/base.py` 纯增量扩展 + 三个新 provider

- `Capability` 枚举（INVENTORY/METRICS/LOGS/AUDIT/ALARMS/EXECUTE/COST/CLI）+ `ResourceRef` URN（`urn:agops:{provider}:{account}:{region}:{service}:{type}:{id}`，native_id 永远保留云原生原文）
- `SupportsInventory / SupportsMetrics / SupportsExecute` Protocol —— `capabilities()` 结构化推导
- **SSHProvider**：execute + 单机 inventory，复用 skills/security.py 命令分级门控；GCP exec 路径 + 任意云 VM 逃生通道
- **PrometheusProvider**：PromQL query_range + targets 即免费主机盘点，零新依赖
- **KubernetesProvider**：形式化 run_kubectl（kubeconfig+context 凭证 schema）—— EKS/AKS/GKE/k3s 一个 provider 通吃

## 五、支柱 D：Self-Improvement Metrics

**交付**：`services/metrics_service.py` + `GET /api/metrics/improvement`

| 指标 | 客户语言 |
|------|---------|
| MTTR by fingerprint（复发曲线） | "第 3 次遇到同类故障，MTTR 下降 N%" —— 全行业没人敢放的图 |
| 首次修复率 (first-time-fix) | 最强的单一客户数字 |
| 自动化率 | FixPlan 由 agent/policy 批准的占比（信任曲线） |

实测（本地生产库，90 天窗口）：109 个已解决 issue、平均 MTTR 153.7 分钟、首次修复率 55.7%、自动化率 95%。

## 六、预防三件套（Prevention-First）

> 图引擎里已写好的能力此前是"有代码无消费者"。本版把它们接进决策路径 —— 事故发生前预警、出事时秒答"改了什么"、修复前模拟防二次事故。全部 fail-soft：图数据缺失时行为与之前完全一致。

### P1 巡检图风险（`patrol_graph_checks_enabled`）
HealthPatrol 新增第 3 步 `AnalyzeGraphRisksStep`：纯代码跑 SPOF 检测（割点/桥）+ 容量风险分析（子网 IP 耗尽、EKS pod 上限），零 LLM 零 AWS 调用（读持久化 GraphStore）。发现项创建 HealthIssue（`source=graph_patrol`）但 **auto_rca=False** —— 结构性风险走设计评审，不走 CloudTrail 取证。指纹去重自动归集重复巡检发现。

### P2 RCA 拓扑上下文（`rca_topology_context_enabled`）
每次 RCA 调用自动注入 TOPOLOGY CONTEXT 块：资源图邻域（上下游依赖、爆炸半径）+ 最近拓扑变更历史（graph_snapshots）。注入**调用 prompt** 而非 system prompt —— prompt-cache 安全。"80% 的事故源于变更"，现在 RCA 开局就知道改了什么。

### P4 执行前模拟门（policies.yaml 规则即开关）
审批前自动跑 `simulate_fix_impact()`（图引擎 impact_analysis）：这个资源如果中断会孤立几个子网、断几条关键路径？新策略匹配字段 `impact_severity`，新规则 `impact-severity-escalation`（critical/high → 升一级审批）。同时修复跨账户资源 ID 碰撞：图节点查找按 account 过滤（`_find_graph_node(resource_id, account_id)`）。

## 七、System Prompt 层修复（S1-S7）

| # | 修复 | 效果 |
|---|------|------|
| S1 | `build_system_prompt` 稳定性重排：base → skills → rules → **memory 最后** | memory 每次构建都变（touch_last_used），移到尾部后不再炸掉整个 Bedrock prompt-cache 前缀 |
| S2 | 模型配置漂移：scan legacy `opus-4-1` / detect 不存在的 `opus-4-7` → 双双改为 `sonnet-4-6`；新增 `validate_agent_model_ids()` 启动告警 | 窗口从错误 fallback 40 恢复为 80/80；成本回归设计意图 |
| S3 | Prompt 卫生：两处中文 TODO/规则出 prompt；RCA↔SRE 1,349 字符逐字重复块抽取到 preamble 共享构造器 | 单一来源维护；疑问句不再被当指令发给模型 |
| S4 | Memory 注入带 `[file: 文件名]` | agent 可通过 memory_manage 引用/修正具体记忆 —— 自优化回路闭环 |
| S6 | Executor prompt 构建时插值（原 import 期 f-string 冻结） | 运行时改 executor 配置即生效，无需重启 |
| S7 | 7 个 sub-agent tool docstring 重写为路由契约（USE FOR 关键词 + NOT FOR 边界） | 两步走第一步：docstring 与 MAIN_SYSTEM_PROMPT 路由规则互为冗余；下一版有回放评测后删规则拿 ~2,000 tok/turn 瘦身 |

**S5 防回归**：新增 `tests/test_prompt_budget.py` —— 7 agent prompt 尺寸金样（±25%）、skills XML 预算（<5,000 字符）、CJK 卫生、memory 末位顺序断言、docstring 路由关键词断言。任何 prompt 膨胀/退化 CI 直接报警。

## 八、凭证安全硬化（多账户串号防护）

6 条铁律全部落地（详见 CLAUDE.md「凭证安全铁律」）：

- 业务路径禁止裸用 boto3，必须经 provider 层取目标账户凭证；解析失败显式报错，**禁止静默回退 ambient**
- 子进程注入前 strip 全部 `AWS_*`（清单扩展到 `ARM_* / GOOGLE_* / ALIBABA_CLOUD_*`）；统一入口 `get_account_subprocess_env()`，覆盖 run_aws_cli / kubectl / ssm
- 会话缓存 key 含 account（`{account}:{region}`）；`_active_account_var` ContextVar 精确绑定，无上下文 fail-closed
- AssumeRole 自动续期：botocore 原生 `DeferredRefreshableCredentials`，长任务不再 1 小时过期
- 纵深校验：`GetCallerIdentity().Account` 必须匹配配置的 account_id，否则 fail-closed

## 九、其他交付

- **ACP Enhanced Backend**：新增 Kiro CLI + Codex 两个 provider（共享自实现 JSON-RPC/stdio AcpClient）；`enhanced_task` 流式输出桥接到 chat SSE；Settings → Enhanced Backend 选择器。默认关闭。
- **品牌 Logo**：全新 SVG logo + icon（`frontend/public/`：logo.svg / logo-icon.svg / favicon-16/32 / logo-192/512），侧栏品牌位从渐变字母 "A" 占位升级为正式 logo，favicon 全套接入 index.html。
- **文档**：`docs/MVP-2.0.0-ARCHITECTURE.md`（架构决策 + 调研依据 + YAGNI 清单）、`docs/WORKFLOW.md` 新增 Prevention hooks 节 + 凭证 AuthN/AuthZ 流程图。

## 十、新增配置（settings.yaml）

| 键 | 默认 | 说明 |
|----|------|------|
| `policy_engine_enabled` | `true` | 声明式策略引擎（false = 退回 legacy L0/L1 硬编码） |
| `policy_file` | `config/policies.yaml` | 策略文件路径 |
| `itsm_enabled` / `itsm_dry_run` | `false` / `true` | ITSM 桥 + dry-run 模式 |
| `patrol_graph_checks_enabled` | `true` | 巡检 SPOF/容量风险步骤 |
| `rca_topology_context_enabled` | `true` | RCA 拓扑上下文注入 |

## 十一、测试与验证

- **62 个新测试**：prompt 预算金样 + 卫生回归（27）、策略模拟门（11）、巡检图步骤（6+12 更新）、RCA 拓扑块（7）—— 全绿
- 全量套件 2,600+ 通过；已在干净树上验证剩余失败均为 pre-existing（test_chat_session_rename 等 ~23 个，与本版改动无关）
- 前端 `npx tsc --noEmit` 通过；dist 已重建（logo + favicon 入包）

## 十二、升级说明

1. 零破坏性：所有新行为受配置门控且默认值复刻旧行为（policy 默认规则 = legacy L0/L1；模拟门 fail-soft）
2. `config/policies.yaml` 首次纳入版本管理 —— 这是自治契约文件，修改需评审
3. scan/detect 模型已切换 Sonnet 4.6（成本下降，窗口修复）；如需 Opus 在 settings.yaml 显式覆盖
4. 下一版（roadmap）：执行后验证回路（VerifyGate）、Reconciler 对账循环、回放评测 CI 门 —— 详见架构文档第 3 节
