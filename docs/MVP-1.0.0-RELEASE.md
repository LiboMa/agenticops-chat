# AgenticOps v1.0.0 MVP — 架构与功能说明

> **版本**: 1.0.0-MVP | **日期**: 2026-03-10 | **代号**: mvp-0.9.0-beta → 1.0.0

---

## 一、产品定位

AgenticOps（`aiops`）是一个基于多智能体架构的 **AI 运维助手**，核心能力：

- **对话式运维**：通过 CLI / Web / IM 三端与 AI Agent 自然语言交互
- **自动闭环修复**：从告警检测 → 根因分析 → 修复计划 → 审批执行 → 验证解决的全链路自动化
- **多云资源管理**：跨 AWS 账户的资源扫描、拓扑可视化、健康监控

**技术栈**: Python 3.12 + Strands Agent SDK + AWS Bedrock (Claude 4.5/4.6) + FastAPI + React/TypeScript + SQLite/PostgreSQL

---

## 二、系统架构

```
                           ┌─────────────────────────────────┐
                           │         用户接入层               │
                           │  CLI (aiops chat)                │
                           │  Web Dashboard (React + SSE)     │
                           │  IM (Feishu/Slack/DingTalk/WeCom)│
                           └──────────────┬──────────────────┘
                                          │
                           ┌──────────────▼──────────────────┐
                           │      Main Agent (路由器)          │
                           │   Opus 4.6 · 纯路由，不直接调工具  │
                           └──┬───┬───┬───┬───┬───┬──────────┘
                              │   │   │   │   │   │
            ┌─────────────────┤   │   │   │   │   └──────────────────┐
            ▼                 ▼   ▼   ▼   ▼   ▼                     ▼
    ┌──────────────┐ ┌────────┐ ┌───┐ ┌───┐ ┌────────┐    ┌──────────────┐
    │  Scan Agent  │ │ Detect │ │RCA│ │SRE│ │Executor│    │  Reporter    │
    │  Haiku 4.5   │ │Haiku   │ │4.6│ │4.6│ │ Opus   │    │  Haiku 4.5   │
    │  资源发现     │ │健康监控 │ │根因│ │修复│ │ 执行    │    │  报告生成     │
    └──────┬───────┘ └───┬────┘ └─┬─┘ └─┬─┘ └───┬────┘    └──────┬───────┘
           │             │        │     │       │                │
           └─────────────┴────────┴─────┴───────┴────────────────┘
                                  │
                    ┌─────────────▼─────────────────┐
                    │        基础设施层               │
                    │  AWS (STS AssumeRole 跨账户)    │
                    │  CloudWatch · CloudTrail · EKS  │
                    │  SQLite / PostgreSQL (pgvector)  │
                    │  S3 (报告/KB 向量存储)           │
                    │  Graph Engine (NetworkX)         │
                    │  Agent Skills (11 领域技能包)     │
                    └─────────────────────────────────┘
```

### 模型分层策略

| 层级 | 模型 | 用途 | Input $/M | Output $/M |
|------|------|------|-----------|------------|
| **Default** | Opus 4.6 | Main/SRE/RCA/Executor — 需要强推理 | $15.00 | $75.00 |
| **Mid-tier** | Sonnet 4.6 | Main(路由)/Executor — 均衡性价比 | $3.00 | $15.00 |
| **Cheap** | Haiku 4.5 | Scan/Detect/Reporter — 工具编排为主 | $0.80 | $4.00 |
| **Strong** | Opus 4.6 | RCA/SRE — 复杂推理 | $15.00 | $75.00 |

可用 Model ID:
- Opus 4.6: `anthropic.claude-opus-4-6-v1` / `global.anthropic.claude-opus-4-6-v1`
- Sonnet 4.6: `anthropic.claude-sonnet-4-6` / `global.anthropic.claude-sonnet-4-6`
- Haiku 4.5: `anthropic.claude-haiku-4-5-20251001-v1:0` / `global.anthropic.claude-haiku-4-5-20251001-v1:0`

> 当前分层 (Opus+Haiku): 单次修复 ~$1.36
> 优化分层 (Opus+Sonnet+Haiku): 单次修复 ~$0.58 (降低 57%)
> 优化分层 + Prompt Caching: 单次修复 ~$0.25 (降低 82%)
> 详见 `docs/PERFORMANCE-OPTIMIZATION-CN.md`

---

## 三、核心功能清单

### 3.1 自动闭环修复流水线

```
告警 ──→ 检测 ──→ RCA ──→ 修复计划 ──→ 审批 ──→ 执行 ──→ 解决
 │               │          │           │         │        │
 │ Webhook/IM    │ Agent    │ KB+SOP    │ L0-L3   │ Auto   │ RAG
 │ 双管道接入     │ 分析     │ 向量检索   │ 风险评级 │ /人工   │ 蒸馏
```

**关键特性：**

| 特性 | 说明 |
|------|------|
| 双管道告警接入 | Webhook（Prometheus/CloudWatch/Datadog/PagerDuty/Grafana）+ IM Agent（5步验证） |
| 指纹去重 | SHA-256(source+resource+title)，5分钟窗口，防止重复告警 |
| 一个 Issue 一个修复计划 | Replace 模式：draft 更新、locked 拒绝、terminal 后允许新建 |
| 四级风险分级 | L0(只读) · L1(低风险,自动审批) · L2(影响服务) · L3(高风险,人工审批) |
| 三开关门控 | `auto_fix_enabled` · `executor_auto_approve_l0_l1` · `executor_enabled` |
| 状态机 | 9 种状态、有向转移、非法跳转返回 409 |
| Pipeline 事件追踪 | 12 种事件类型 × 6 阶段，`TRC-{hex}` 全链路追踪 |

**验证结果（EKS Lab 10 场景）：**

| 指标 | 目标 | 实际 |
|------|------|------|
| 自动修复率 | ≥7/10 | **10/10** ✅ |
| 平均检测时间 | ≤3 min | **~2 min** ✅ |
| 平均 MTTR | ≤10 min | **~6.3 min** ✅ |
| 单次成本 | ≤$3 | **~$2-3** ✅ |

10 个验证场景：OOM Kill、Bad Image、Redis Crash、DiskPressure、PodPending、Readiness Probe、CoreDNS Down、PVC Pending、HPA Maxed、Service Deleted

### 3.2 三端交互（CLI + Web + IM）

| 接入端 | 能力 |
|--------|------|
| **CLI** | 交互式 REPL (`aiops chat`) + 无头模式 (`aiops chat "query"`) + 管道输入 |
| **Web** | React 仪表盘 + SSE 实时流式 + 文件上传 + 16 个页面 |
| **IM** | Feishu WebSocket + Slack（计划中）+ 告警频道路由 |

**共享功能：** `@file` 附件 · `I#/R#` 引用 · `/send_to` 转发 · `/channel` 管理 · `/focus` 扫描范围 · `/detail` 输出详度 · 多模态（图片/文档）

### 3.3 资源扫描与拓扑

- **扫描**: 15+ AWS 服务类型（EC2、RDS、Lambda、S3、ECS、EKS、DynamoDB、SQS、SNS、VPC...）
- **拓扑图引擎**: 22 种节点类型、10 种边类型（NetworkX → ReactFlow 可视化）
- **SRE 分析**: 单点故障检测 · 容量风险分析 · 依赖链分析 · 变更模拟
- **扫描聚焦**: computing / networking / databases / storage / security / billing / all

### 3.4 知识库与 RAG

- **向量存储**: SQLite（本地）/ PostgreSQL pgvector / S3 numpy blobs
- **自动流程**: 修复成功 → RAG 向量化 → Case 蒸馏 → 写入 KB
- **Agent 使用**: RCA Agent 查询 SOP + 相似案例辅助分析

### 3.5 Agent Skills（11 个领域技能包）

| 技能 | 覆盖 |
|------|------|
| linux-admin | 进程/磁盘/内存/网络排查 |
| network-engineer | 路由/防火墙/TCP/VPN/MTU |
| kubernetes-admin | Pod/Node/CNI/CoreDNS/PVC/HPA |
| database-admin | RDS/DynamoDB/ElastiCache |
| elasticsearch | 集群健康/DSL/JVM/ILM |
| monitoring | CloudWatch/Prometheus/SLI/SLO |
| log-analysis | CloudWatch Insights/日志模式 |
| aws-compute | EC2/ECS/EKS/Lambda |
| aws-storage | S3/EBS/EFS |
| local-os-operator | 本地文件读取/搜索（动态注册） |
| web-research | 公开网页抓取/状态页/CVE 查询（动态注册） |

> 渐进式加载：系统提示 ~636 tokens（技能列表），按需加载技能体 ~3-5K tokens

### 3.6 通知系统

- **7 种渠道**: Slack · Feishu · DingTalk · WeCom · Email/SMTP · SNS · Webhook
- **YAML 配置**: `config/channels.yaml` 为唯一配置源（无 DB 存储）
- **自动通知**: 7 个流水线事件点自动推送（fire-and-forget）
- **IM 回溯**: 告警来自哪个 IM 对话，修复结果就回到哪个对话

### 3.7 Web 仪表盘

- **16 个页面**: Dashboard · Chat · Resources · Anomalies · AnomalyDetail · FixPlans · FixPlanDetail · Reports · ReportDetail · Network · Schedules · ScheduleDetail · Notifications · NotificationLogs · Accounts · AuditLog
- **81 个 API 端点**（17 组）
- **23 个 TanStack Query hooks**（自动刷新）

### 3.8 部署与运维

| 命令 | 说明 |
|------|------|
| `aiops init` | 5 步引导向导（自动检测 AWS 上下文） |
| `aiops init --config setup.json` | 零提示模式 |
| `aiops quickstart --yes` | 一键初始化 + 启动 |
| CloudFormation 模板 | EC2+ALB + 可选 RDS/EFS + S3 + IAM |

**部署模式**: 本地（SQLite）或 云端（RDS pgvector + S3）

### 3.9 可观测性与安全

- **30+ 配置项**: 全部通过 `AIOPS_*` 环境变量或 `.env` 控制
- **Trace ID**: `TRC-{hex}` 贯穿 HealthIssue / PipelineEvent / AlertEvent / 日志
- **健康检查**: DB 连通性 · AWS 凭证 · 磁盘空间
- **安全**: 三级命令分类（readonly/write/blocked）· 敏感文件黑名单 · API 认证中间件（可选）

---

## 四、API 概览（81 端点）

| 分组 | 数量 | 路径 |
|------|------|------|
| Health Issues | 8 | `/api/health-issues` |
| Fix Plans | 6 | `/api/fix-plans` |
| Schedules | 7 | `/api/schedules` |
| Notifications | 7 | `/api/notifications` |
| Chat (SSE) | 5 | `/api/chat/sessions` |
| Reports | 5 | `/api/reports` |
| Resources | 5 | `/api/resources` |
| Network/Topology | 6 | `/api/topology` |
| Graph Engine | 12 | `/api/graph/*` |
| SRE Analysis | 5 | `/api/graph/vpc/{id}/*` |
| Anomalies (兼容) | 5 | `/api/anomalies` |
| Accounts | 5 | `/api/accounts` |
| Audit Log | 2 | `/api/audit-log` |
| Stats/Health | 3 | `/api/stats`, `/api/health` |
| Auth | 3 | `/api/auth` |
| IM/Docs | 6 | `/api/im-aliases`, `/api/local-docs`, `/api/im/bots` |
| SPA | 1 | `/app/{path}` |

---

## 五、测试覆盖

| 测试文件 | 用例数 | 覆盖 |
|----------|--------|------|
| test_fix_plan_consolidation.py | 17 | 修复计划去重/替换 |
| test_state_machine.py | 75 | Issue 状态机 |
| test_detail_level.py | 31 | 输出详度控制 |
| test_auto_fix_pipeline.py | 20 | 自动修复流水线 |
| test_aws_cli_tool.py | 42 | AWS CLI 安全分类 |
| test_cloud_init.py | 39 | 初始化/云部署 |
| test_graph_algorithms.py | 30+ | 拓扑图算法 |
| test_eks_tools.py | 20+ | EKS 工具 |
| test_v2_features.py | 54 | IM/告警路由 |
| test_multimodal.py | 37 | 多模态文件 |
| test_models.py | 20+ | 数据模型 |
| **合计** | **~450+** | — |

---

## 六、Quick Demo（5 分钟上手）

### 环境准备

```bash
# 1. 克隆 & 安装
git clone https://github.com/LiboMa/agenticops-chat.git
cd agenticops-chat
pip install -e .

# 2. 配置 AWS 凭证（需要 Bedrock 访问权限）
export AWS_PROFILE=your-profile
# 或 export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...

# 3. 一键初始化（自动检测 AWS 上下文，默认 local 模式）
aiops init --yes
```

### Demo 1：CLI 对话（资源扫描）

```bash
# 交互模式
aiops chat
> scan us-east-1
> 有多少个运行中的 EC2 实例？
> /focus computing    # 聚焦计算资源
> scan

# 无头模式（适合脚本/管道）
aiops chat "list all RDS instances in us-east-1"
aiops chat -d concise "quick status of my AWS account"
```

### Demo 2：Web 仪表盘

```bash
# 启动后端
uvicorn agenticops.web.app:app --host 0.0.0.0 --port 8000

# 前端开发（另一个终端）
cd src/agenticops/web/frontend
npm install && npm run dev

# 浏览器打开 http://localhost:5173
# → Dashboard: 资源/告警概览
# → Chat: 实时流式对话
# → Network: 拓扑可视化 + SRE 分析面板
# → Anomalies: 告警列表 → 点击进入详情 → Pipeline 时间线
```

### Demo 3：自动修复流水线（需要 EKS 集群）

```bash
# 1. 模拟一个 OOM 告警（通过 Webhook）
curl -X POST http://localhost:8000/api/webhooks/alert \
  -H "Content-Type: application/json" \
  -d '{
    "status": "firing",
    "alerts": [{
      "labels": {
        "alertname": "KubePodOOMKilled",
        "namespace": "default",
        "pod": "app-server-abc123"
      },
      "annotations": {
        "summary": "Pod app-server OOM killed",
        "description": "Container exceeded memory limit (256Mi)"
      },
      "startsAt": "2026-03-10T10:00:00Z"
    }]
  }'

# 2. 观察自动流水线（Web 或 CLI）
aiops chat "show issue #1"          # 查看告警详情
aiops chat "show timeline for I#1"  # 查看 Pipeline 事件时间线

# 流水线自动执行：
# → 创建 HealthIssue → 自动 RCA → SRE 生成修复计划
# → L0/L1 自动审批 → Executor 执行 → 验证 → 解决
```

### Demo 4：IM 告警路由（需要飞书/Slack 配置）

```yaml
# config/channels.yaml
feishu-ops-alert:
  type: feishu
  role: alert          # 所有消息走 Agent 分析
  enabled: true
  app_name: default
  chat_id: "oc_xxxxx"

feishu-ops-chat:
  type: feishu
  role: chat           # 普通对话
  enabled: true
  app_name: default
  chat_id: "oc_yyyyy"
```

```bash
# IM 中发送告警 → Agent 自动分析 → 真告警创建 HealthIssue → 修复流水线
# IM 中普通对话 → Agent 正常回复（不触发告警流程）
```

### Demo 5：通知转发

```bash
aiops chat
> /channel list                              # 查看所有通知渠道
> /channel test feishu-ops-alert             # 测试发送
> /send_to feishu-ops-chat "系统巡检完成，无异常"  # 手动发送消息
> /send_to feishu-ops-chat #R1               # 转发报告
```

---

## 七、配置速查

### 环境变量（关键项）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AIOPS_BEDROCK_REGION` | `us-east-1` | Bedrock 区域 |
| `AIOPS_BEDROCK_MODEL_ID` | Opus 4.6 | 推理 Agent 模型 |
| `AIOPS_BEDROCK_MODEL_ID_CHEAP` | Haiku 4.5 | 工具编排 Agent 模型 |
| `AIOPS_AUTO_FIX_ENABLED` | `true` | 自动修复主开关 |
| `AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1` | `true` | L0/L1 自动审批 |
| `AIOPS_NOTIFICATIONS_ENABLED` | `true` | 自动通知开关 |
| `AIOPS_SCAN_FOCUS` | `all` | 扫描聚焦范围 |
| `AIOPS_AGENT_OUTPUT_DETAIL` | `medium` | 输出详度 |
| `AIOPS_DEPLOYMENT_PROFILE` | `local` | 部署模式 |
| `AIOPS_API_AUTH_ENABLED` | `false` | API 认证开关 |

### 零提示部署（JSON 配置文件）

```bash
# 生成配置模板
aiops init --generate-config

# 编辑 setup.json 后一键部署
aiops quickstart --config setup.json --yes
```

---

## 八、已知边界（1.0.0 不含）

| 项目 | 状态 | 说明 |
|------|------|------|
| Web API Router 拆分 | 延后 | app.py ~4000 行 → app.py + schemas.py + 8 routers/（见下方路线图） |
| CLI 模块拆分 | 延后 | main.py ~4300 行 → 5 模块（见下方路线图） |
| OpenTelemetry | 延后 | SDK 内置支持，需外部 Jaeger/Tempo 后端 |
| 跨区域网络拓扑 | 部分 | 单区域完成，多区域合并待完善 |
| 结构化 FixPlan Step | 跳过 | LLM 推理足够准确（~95%），不需要强 schema |
| Slack WebSocket | 计划中 | Feishu 已完成，Slack 架构相同 |
| Hook 审计日志 | 延后 | Strands SDK 12 种事件类型，当前未接入 |

---

## 九、1.0.0 代码瘦身摘要

### 归档文件

根目录 4 个旧设计文档 + docs/ 目录 12 个早期设计/需求/评审文档已移至 `docs/archive/`：

```
docs/archive/
├── 06-Reporter-Agent-Design.md        # 旧 Reporter 设计
├── AWS-Savings-Plan-RI-Guide.md       # AWS 成本参考
├── H200_Qwen_Benchmark_Report.md      # GPU 基准报告
├── New-architecture-beta.md           # 早期架构草案
├── DESIGN.md                          # v0.1 设计文档
├── REQUIREMENTS.md                    # 早期需求
├── TASKS.md                           # 任务追踪
├── technical-spec.md                  # 技术规格
├── agent-vision-and-evolution.md      # Agent 演进愿景
├── architecture-discussion*.md (×2)   # 架构讨论记录
├── research-holmesgpt-keep-comparison.md  # 竞品对比
├── web_service_workflow.md            # Web 流程
├── feature-pending                    # 待办草案
├── designs/                           # 旧设计子目录
└── reviews/                           # 旧评审子目录
```

### CLAUDE.md 精简

839 行 → ~130 行。删除所有变更历史记录（由 memory 文件和 git log 接管），只保留：架构图、模块表、配置表、构建命令、受保护文件清单。

### 保留不动

- `RAW-Idea-latest-v3.md` — 核心创意文档
- `docs/use-cases/*` — 手写用例
- `docs/cases/*` — 闭环验证 10 个案例
- `docs/WORKFLOW.md` — 用户工作流文档
- Legacy `Anomaly`/`OpsAgent` 模型 — 仍被 pipeline/scheduler 引用

---

## 十、1.0.1 重构路线图

### app.py 拆分（~4000 行 → 10 个文件）

```
web/
├── app.py              # FastAPI 入口、中间件、startup/shutdown (~300L)
├── schemas.py          # 所有 Pydantic 请求/响应模型 (~300L)
└── routers/
    ├── health_issues.py   # /api/health-issues/* (~300L)
    ├── fix_plans.py       # /api/fix-plans/* (~300L)
    ├── chat.py            # /api/chat/* + SSE streaming (~400L)
    ├── schedules.py       # /api/schedules/* (~200L)
    ├── notifications.py   # /api/notifications/* (~250L)
    ├── resources.py       # /api/resources/*, accounts, network (~400L)
    ├── im.py              # /api/im/*, webhook callbacks (~500L)
    └── admin.py           # auth, audit, settings, stats (~400L)
```

### main.py 拆分（~4300 行 → 5 个文件）

```
cli/
├── main.py         # Entry point, chat(), main() (~500L)
├── commands.py     # Typer commands: get/describe/create/delete/update/run (~900L)
├── slash.py        # 全部 _slash_* 处理器 + handle_slash_command() (~1200L)
├── service.py      # service start/stop/status/restart/logs, PID (~400L)
└── renderers.py    # 表格/Markdown/JSON/YAML 输出 + pager (~300L)
```

---

## 十一、未来演进路线图

### A. Self-improving Skills（技能自进化）

**已实现基础**：`skills/evolution.py`（229 行）— 草稿技能创建、更新、LLM 自动生成。

**完整愿景**：

```
案例闭环                    知识蒸馏                     技能进化
HealthIssue → RCA →  ──►  RAG Pipeline  ──►  SOP 匹配/创建  ──►  Skill 自动升级
  Execute → Resolve        (vector store)     (sop_identifier)     (evolution.py)
                                              (sop_upgrader)       (auto SKILL.md)
```

| 阶段 | 状态 | 说明 |
|------|------|------|
| 案例蒸馏 → KB | 已实现 | `pipeline/rag_pipeline.py`：resolved 的 Issue 自动向量化入 KB |
| SOP 匹配 | 已实现 | `pipeline/sop_identifier.py`：新 Issue 自动匹配已有 SOP |
| SOP 创建/升级 | 已实现 | `pipeline/sop_upgrader.py`：无匹配时自动生成新 SOP |
| 草稿 Skill 生成 | 已实现 | `skills/evolution.py`：LLM 从描述生成 SKILL.md |
| 自动创建 Skill | 已实现 | Agent 检测无匹配 Skill → 询问用户确认 → 自动生成并发布激活（`create_skill(publish=True)`） |
| 自动 Skill 升级 | 计划中 | 根据多次案例反馈，自动优化 Skill 的决策树和参考文档 |
| Skill 版本管理 | 计划中 | 草稿 → 审核 → 发布 → 归档生命周期 |
| 跨案例学习 | 计划中 | 从相似案例中提取共性模式，合并进 Skill references |

**目标**：系统每解决一个新类型的问题，自动沉淀为可复用的 Skill 知识，下次遇到类似问题时更快、更准。

### B. Dynamic System Prompt（动态系统提示词）

**已实现基础**：

| 组件 | 状态 | 机制 |
|------|------|------|
| 输出详细度 | 已实现 | `agent_output_detail` → ContextVar → `build_prompt_with_skills()` 注入 OUTPUT RULES |
| Scan Focus | 已实现 | `scan_focus` → ContextVar → Main Agent 系统提示词注入 SCAN FOCUS 段 |
| Skills XML | 已实现 | `<available_skills>` XML 块在 agent 创建时动态注入 |
| 告警频道提示词 | 已实现 | `_ALERT_CHANNEL_PROMPT` 在 IM 告警频道时包裹用户消息 |

**完整愿景**：

```
Agent System Prompt = 基础角色定义
                    + 动态 Skills XML（按需加载）
                    + 动态 Output Rules（按详细度）
                    + 动态 Context（scan_focus, account, region）
                    + 动态 KB/SOP（基于当前 Issue 的相关知识）
                    + 动态 History Summary（上下文压缩摘要）
```

| 阶段 | 状态 | 说明 |
|------|------|------|
| Skill 按需加载 | 已实现 | `activate_skill()` 运行时注册工具 + 注入知识 |
| 输出格式动态化 | 已实现 | concise/medium/detailed 三级规则 |
| 上下文变量注入 | 已实现 | scan_focus, detail_level 通过 ContextVar 传递 |
| KB/SOP 上下文注入 | 计划中 | 当 Agent 处理 Issue 时，自动检索相关 SOP 作为 few-shot 上下文 |
| 对话历史压缩 | 已实现 | `SlidingWindowConversationManager(window_size=40)` 滑动窗口 |
| 自适应模型选择 | 计划中 | 根据任务复杂度自动切换 Haiku → Sonnet → Opus |
| Prompt 版本管理 | 计划中 | System prompt 模板化，支持 A/B 测试和回滚 |

### C. Strands SDK 深度集成

当前仅使用 SDK ~5 个核心参数。以下 SDK 能力已评估，待逐步接入：

| SDK 能力 | 优先级 | 收益 |
|----------|--------|------|
| **Hook 系统** (12 事件类型) | 高 | AuditHookProvider — 自动记录所有工具调用，审计合规 |
| **S3SessionManager** | 高 | 替换自定义 ChatSessionManager，原生持久化 |
| **Interrupt/HITL** | 中 | Executor 审批门控：暂停 → 人工审批 → 恢复执行 |
| **Structured Output** | 中 | `structured_output_model=BaseModel`，类型化 Agent 响应 |
| **Plugin 系统** | 中 | 安全审计、Token 计量等横切关注点 |
| **Swarm/Graph** | 低 | 原生多 Agent 编排（当前 agents-as-tools 模式已够用） |
| **A2A Protocol** | 低 | 跨框架 Agent 通信（Strands ↔ LangGraph/CrewAI） |
| **OpenTelemetry** | 低 | 需外部 Jaeger/Tempo 后端，当前 TRC-xxx 够用 |

### D. 其他规划

| 项目 | 优先级 | 说明 |
|------|--------|------|
| Slack WebSocket | 高 | 与 Feishu WS 架构相同，复用 `_ALERT_CHANNEL_PROMPT` |
| 多云支持 | 中 | GCP / Azure 资源扫描（当前仅 AWS） |
| Dashboard 增强 | 中 | 实时指标仪表盘、成本趋势图、SLA 追踪 |
| Graph 跨区域合并 | 中 | 多 VPC/多 Region 拓扑统一视图 |
| Kubernetes Operator | 低 | CRD 定义 + Controller，原生 K8s 部署方式 |
| SaaS 化 | 低 | 多租户隔离、计费、用户管理 |

---

*Generated for AgenticOps v1.0.0-MVP · 2026-03-10*
