# AgenticOps v2.0.0 Release — 治理型自治 + 企业流程 + 预防性运维

> **版本**: 2.0.0 | **日期**: 2026-06-12 (updated 2026-07-03) | **分支**: `MVP-2.0.0-release`

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

> **2.0.0 补丁（账户寻址重构，2026-06-15）**：早期实现用一个隐式的 `_active_account_var` ContextVar 记录"当前账户"，但 Strands SDK 用 `asyncio.to_thread` + `contextvars.copy_context()` 执行每个同步 `@tool`，工具内对 ContextVar 的写入一返回就被丢弃 —— 导致 `run_on_host(ssm)` 静默回退到本地默认凭证链（事故 TRC-bc600aa9：CloudTrail 把 SendCommand 记到本地 IAM 用户而非 AssumeRole 会话），同时 `_get_session` 系消费方在真实会话里 100% fail-closed 报错。**已用「账户寻址执行」彻底重写**，根因消除。

**核心契约：账户是目标的属性，不是隐式全局状态。** 新模块 `credentials/resolver.py` 统一解析：

- **显式 account 参数 → 库存反查（按 instance-id / cluster-name）→ 单账户默认 → fail-closed 列出账户名**。所有业务工具（`run_on_host` / `run_kubectl` / `run_aws_cli` / `describe_*` / network / eks / cloudwatch / cloudtrail）都带 `account` 参数。
- **唯一合法的"本地链"路径** = 注册的 `environment`-源账户（经 provider 层解析 + `GetCallerIdentity` 校验），**没有任何隐式 ambient 回退分支**。
- 子进程注入前 strip 全部 `AWS_*`（清单扩展到 `ARM_* / GOOGLE_* / ALIBABA_CLOUD_*`）；统一入口 `get_subprocess_env_for_account(account[, region])`，覆盖 run_aws_cli / kubectl / ssm。
- 会话缓存双键 `{provider}:{name}:{region}` 与 `{account_id}:{region}`（线程安全，单一归属）。
- AssumeRole 自动续期：botocore 原生 `DeferredRefreshableCredentials`，长任务不再 1 小时过期。
- 纵深校验：`GetCallerIdentity().Account` 必须匹配配置的 account_id，否则 fail-closed。
- **主机访问降级阶梯（像人类 SRE）**：`run_on_host(method="auto")` 先走 SSM，失败时按 botocore 错误码分类（InvalidInstanceId / TargetNotConnected / AccessDenied / Timeout），用库存 IP 自动降级 SSH（支持注册 ssh 账户 + `ssh_default_user`/`ssh_default_key_path`/`ssh_bastion_host` ProxyJump），返回完整尝试轨迹。
- 删除：`_active_account_var` / `_set_active_account` / `_get_active_account` / `get_account_subprocess_env` 及所有 ambient 回退分支；日志签名 `uses default credentials (no active account context)` 已从代码库消失。

**通知渠道键名修复（2026-06-18）**：`SESNotifier` 读 `config["to"]` 但 UI/`channels.yaml` 用的键是 `recipients` → `recipients=[]` → `send()` 静默 `return False` 从不调 SES（`ops-ses-email` 渠道完全不发邮件）；`EmailNotifier`(SMTP) 同类错配（`smtp_user`/`from_email`/`to_emails` vs UI 的 `username`/`from_addr`/`to_addrs`）。两者改为优先读 UI/YAML 键、旧键作向后兼容别名，已在远程实例实发验证（`send()=True`）。

## 九、Token & Cost Observability

> **"花了多少钱？谁花的？哪个 Agent 最贵？"** —— 从"能跑"到"跑得起"的成本可视化闭环。

**交付**：`cost.py` + `services/cost_service.py` + `web/routers/cost.py` + CLI `aiops cost` + Frontend dashboard + per-message footer

### 核心架构

| 层 | 模块 | 职责 |
|----|------|------|
| 纯计算 | `cost.py` | `compute_cost(model_id, tokens) → USD`，基于 `config.token_cost_table`（per-1M rates），never raises |
| 写入快照 | `agent_log_service` | 每次 agent 调用时计算 `cost_usd` + 记录 `actor_type/actor_id` + `cache_write_tokens`，火写即忘 |
| 聚合 | `cost_service.cost_summary()` | 实时 GROUP BY agent_logs，无 rollup 表；支持 bucket=hour/day/month/year × group_by=agent/actor/model/none |
| API | `GET /api/cost/summary` | period 快捷（7d/30d/month/year）+ 任意 start/end + filters |
| CLI | `aiops cost --period month --by agent` | Rich table：totals + breakdown |
| 前端 Dashboard | AgentMetrics → CostDashboard | KPI scorecards + recharts stacked-bar/line 混合图 + donut 占比 |
| 前端 per-message | TokenMetrics footer | `↑in ↓out Σtotal · $cost ▾`，展开查 sub-agent 明细（trace timeline） |

### Actor 归因

每条 token 消耗归属到触发源：

| actor_type | 来源 | actor_id |
|-----------|------|----------|
| `user` | Web chat SSE | request.state.user |
| `cli` | CLI REPL / headless | OS username |
| `system` | Pipeline / RCA / resolution services | — |
| `schedule` | Scheduler 定时巡检 | schedule name |

### Schema 变更（additive, nullable）

- `AgentLog` += `cache_write_tokens`, `cost_usd`, `actor_type`, `actor_id` + index `idx_agent_log_actor_time`
- `ChatMessage` += `trace_id`（关联 agent_logs 链路）
- `ChatMessageResponse` += `trace_id`, `cost_usd`

### 前端变更

- 新增 recharts 依赖
- `useCostSummary` hook（TanStack Query → `/api/cost/summary`）
- `useTraceTimeline` hook（per-message expand）
- `TokenMetrics.tsx` 重写为可展开 footer（单击展开 sub-agent 表格）
- `AgentMetrics.tsx` 新增 CostDashboard section + timeline 适配新 API 形状（`.calls` / `.totals`）
- `AgentLogTimeline` 类型更新匹配后端响应

## 十、其他交付

- **web_search（DuckDuckGo）**：`web-research` skill v1.1 新增 `web_search` 工具（lite→html 双端点降级、零新依赖、广告过滤、uddg 解链）；agent 可先搜后 `web_fetch` 深读。
- **ACP Enhanced Backend**：新增 Kiro CLI + Codex 两个 provider（共享自实现 JSON-RPC/stdio AcpClient）；`enhanced_task` 流式输出桥接到 chat SSE；Settings → Enhanced Backend 选择器。默认关闭。
- **品牌 Logo**：全新 SVG logo + icon（`frontend/public/`：logo.svg / logo-icon.svg / favicon-16/32 / logo-192/512），侧栏品牌位从渐变字母 "A" 占位升级为正式 logo，favicon 全套接入 index.html。
- **文档**：`docs/MVP-2.0.0-ARCHITECTURE.md`（架构决策 + 调研依据 + YAGNI 清单）、`docs/WORKFLOW.md` 新增 Prevention hooks 节 + 凭证 AuthN/AuthZ 流程图 + Token & Cost Observability 节。

## 十一、新增配置（settings.yaml）

| 键 | 默认 | 说明 |
|----|------|------|
| `policy_engine_enabled` | `true` | 声明式策略引擎（false = 退回 legacy L0/L1 硬编码） |
| `policy_file` | `config/policies.yaml` | 策略文件路径 |
| `itsm_enabled` / `itsm_dry_run` | `false` / `true` | ITSM 桥 + dry-run 模式 |
| `patrol_graph_checks_enabled` | `true` | 巡检 SPOF/容量风险步骤 |
| `rca_topology_context_enabled` | `true` | RCA 拓扑上下文注入 |
| `token_cost_table` | (4 models) | Per-model per-1M-token USD rates（input/output/cache_read/cache_write）|

## 十二、测试与验证

- **Token & Cost Observability（23 新测试）**：`test_cost.py`(5) + `test_cost_migration.py`(9) + `test_agent_log_cost.py`(1) + `test_cost_service.py`(3) + `test_cost_api.py`(4) + `test_actor_attribution.py`(4) + `test_message_token_usage.py`(2) + `test_cli_cost.py`(2)；加上 179 个相邻区域回归测试全绿
- **62 个新测试**：prompt 预算金样 + 卫生回归（27）、策略模拟门（11）、巡检图步骤（6+12 更新）、RCA 拓扑块（7）—— 全绿
- **账户寻址重构（补丁）**：新增 `tests/test_account_resolver.py`（18）+ 重写凭证/执行套件（subprocess 注入、会话隔离、execution 阶梯、SSM 错误分类、run_kubectl/run_aws_cli 账户解析）；改动区 419 测试全绿
- **通知键名修复（补丁）**：`tests/test_notifier.py` 新增 `TestConfigKeyMapping`（5）—— SES/SMTP 的 recipients 键映射回归；152 notifier 测试全绿
- 全量套件 3,100+ 通过；已在干净树上验证剩余失败均为 pre-existing（test_chat_session_rename / 过期 Bedrock 模型 / SES-SNS 凭证等，与本版改动无关）
- 前端 `npx tsc --noEmit` 通过；dist 已重建（logo + favicon 入包）
- **远程部署验证**：`iac/deploy-sg`（ap-southeast-1，`i-0935450a95f321942`）已部署 main 最新；运行环境核验旧符号不可导入、`run_on_host` 默认 `method=auto`、日志无事故签名；`ops-ses-email` 实发 `send()=True`

## 十三、升级说明

1. 零破坏性：所有新行为受配置门控且默认值复刻旧行为（policy 默认规则 = legacy L0/L1；模拟门 fail-soft）
2. `config/policies.yaml` 首次纳入版本管理 —— 这是自治契约文件，修改需评审
3. scan/detect 模型已切换 Sonnet 4.6（成本下降，窗口修复）；如需 Opus 在 settings.yaml 显式覆盖
4. **凭证调用方式变更**：业务工具改为账户寻址 —— 多账户部署需对 `run_on_host` / `run_kubectl` / `run_aws_cli` / `describe_*` 传 `account='<name>'`（单账户部署自动解析，无需改动）。旧的 `assume_role` 工具保留但仅用于预热/校验，不再是必需的前置步骤。新增 SSH 降级配置 `ssh_default_user` / `ssh_default_key_path` / `ssh_bastion_host`（默认空）。
5. **访问地址**：自定义域名 `agenticops.tinyboat.blog` 依赖外部域名续费；在恢复前临时使用 CloudFront 默认域名 `https://d1o50vxhknqf6d.cloudfront.net`（即开即用，与自定义域名无关）。SES 仍在 sandbox —— 发给非验证收件人需在 SES 控制台申请生产权限。
6. 下一版（roadmap）：执行后验证回路（VerifyGate）、Reconciler 对账循环、回放评测 CI 门 —— 详见架构文档第 3 节
