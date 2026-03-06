# AgenticAIOps - 系统设计文档

## 概述

AgenticOps (`aiops`) 是一个 Agent-First 的 AWS 云运维平台，通过 LLM Multi-Agent 架构实现自动化的资源扫描、异常检测、根因分析、修复计划制定与执行，以及多渠道通知。支持 CLI、Web Dashboard、IM Bot（飞书/钉钉/企业微信）三入口。

**版本**: 0.3.0
**技术栈**: Python 3.11+, SQLAlchemy, FastAPI, Strands Agents SDK, AWS Bedrock (Claude Sonnet 4.6 / Haiku 4.5 / Opus 4.6)

---

## 1. 系统架构

### 1.1 整体架构图

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              AgenticOps                                      │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐               │
│   │   CLI    │   │   Web    │   │  IM Bot  │   │ Webhook  │               │
│   │(aiops    │   │(FastAPI +│   │(飞书/钉钉│   │(Prometheus│              │
│   │ chat)    │   │ React)   │   │/企业微信)│   │/CW/DD)   │               │
│   └────┬─────┘   └────┬─────┘   └────┬─────┘   └────┬─────┘               │
│        │              │              │              │                        │
│        └──────────────┴──────┬───────┴──────────────┘                       │
│                              │                                               │
│   ┌──────────────────────────┴────────────────────────────┐                 │
│   │        Preprocessing (I#/R# refs, @file, multimodal)  │                 │
│   └──────────────────────────┬────────────────────────────┘                 │
│                              │                                               │
│   ┌──────────────────────────┴────────────────────────────┐                 │
│   │                 Agent Layer (7 Agents)                  │                 │
│   │  Main(Router) → Scan, Detect, RCA, SRE, Executor, Rpt │                 │
│   └───┬──────┬──────┬──────┬──────┬──────┬──────┬─────────┘                 │
│       │      │      │      │      │      │      │                            │
│   ┌───┴──────┴──────┴──────┴──────┴──────┴──────┴──────────┐               │
│   │                Backend Services                         │               │
│   │  Pipeline │ RCA Trigger │ Executor │ Resolution │ Notify│               │
│   └───┬──────┴──────┬──────┴──────┬────┴──────┬────┴───────┘               │
│       │             │             │           │                              │
│   ┌───┴──────┐  ┌───┴──────┐  ┌──┴─────┐  ┌─┴──────────┐                 │
│   │  Skills  │  │Knowledge │  │ Graph  │  │    Data     │                 │
│   │ (12 pkgs)│  │Base (RAG)│  │(NX topo│  │  (SQLite)  │                 │
│   └──────────┘  └──────────┘  └────────┘  └────────────┘                 │
│                                                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│   │  Notify  │  │   IM     │  │   Auth   │  │  Audit   │                  │
│   │(Slack/   │  │(Feishu/  │  │(APIKey/  │  │(AuditLog)│                  │
│   │Email/SNS │  │DingTalk/ │  │Session)  │  │          │                  │
│   │/Webhook) │  │WeCom WS) │  │          │  │          │                  │
│   └──────────┘  └──────────┘  └──────────┘  └──────────┘                  │
│                                                                              │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │
┌──────────────────────────────┴───────────────────────────────────────────────┐
│                          External Services                                    │
├──────────────────┬──────────────────┬────────────────────────────────────────┤
│   AWS Services   │  AWS CloudWatch  │         AWS Bedrock                    │
│ (EC2,Lambda,RDS  │  (Metrics/Logs)  │  Sonnet 4.6 (default)                │
│  S3,ECS,EKS...) │  + CloudTrail    │  Haiku 4.5 (scan/detect/report)      │
│                  │                  │  Opus 4.6 (executor/complex)          │
└──────────────────┴──────────────────┴────────────────────────────────────────┘
```

### 1.2 模块结构

```
src/agenticops/
├── __init__.py              # 版本定义 (0.2.0)
├── config.py                # 配置管理 (Pydantic Settings)
├── models.py                # 数据模型 (SQLAlchemy ORM + 连接池)
│
├── scan/                    # SCAN - 资源发现模块
│   ├── scanner.py          # 跨账户扫描器
│   ├── services.py         # 15种AWS服务定义
│   └── regions.py          # 区域发现与管理
│
├── monitor/                 # MONITOR - 监控模块
│   ├── cloudwatch.py       # CloudWatch指标/日志采集
│   └── collector.py        # 定时采集调度器
│
├── detect/                  # DETECT - 检测模块
│   ├── detector.py         # 统计检测器 (Z-score, IQR, Moving Avg)
│   └── rules.py            # 规则引擎 (阈值规则, 范围规则)
│
├── analyze/                 # ANALYZE - 分析模块
│   └── rca.py              # Bedrock LLM根因分析
│
├── report/                  # REPORT - 报告模块
│   └── generator.py        # 多格式报告生成
│
├── agents/                  # AGENTS - Strands多智能体模块
│   ├── scan_agent.py       # Scan Agent — 资源扫描智能体
│   ├── detect_agent.py     # Detect Agent — 异常检测智能体
│   ├── rca_agent.py        # RCA Agent — 根因分析智能体
│   ├── sre_agent.py        # SRE Agent — 站点可靠性工程智能体
│   ├── executor_agent.py   # Executor Agent — 修复执行智能体 (L0-L3, 多后端)
│   ├── reporter_agent.py   # Reporter Agent — 报告生成智能体
│   └── main_agent.py       # Main Agent — 主编排智能体 (纯路由)
│
├── tools/                   # TOOLS - Agent工具模块
│   └── (10个工具模块)       # 40+ 工具函数
│
├── graph/                   # GRAPH - 网络拓扑模块
│   └── ...                  # 网络拓扑图引擎 + 图算法
│
├── kb/                      # KB - 知识库模块
│   └── ...                  # 向量嵌入知识库 (Titan V2)
│
├── data/                    # DATA - 数据工具模块
│   └── ...                  # 数据实用工具
│
├── pipeline/                # PIPELINE - 管道编排模块
│   └── orchestrator.py     # 多步骤管道编排器
│
├── scheduler/               # SCHEDULER - 调度模块
│   └── scheduler.py        # Cron调度器
│
├── services/                # SERVICES - 后台服务模块
│   ├── pipeline_service.py # 自动修复管线 (RCA→SRE→Approve→Execute)
│   ├── rca_service.py      # 自动RCA触发器
│   ├── executor_service.py # 后台执行轮询服务
│   ├── resolution_service.py # 后处理 (RAG管线 + case蒸馏)
│   └── notification_service.py # 事件自动通知 (7个触发点)
│
├── skills/                  # SKILLS - Agent技能模块
│   ├── loader.py           # 技能发现、YAML解析、XML生成
│   ├── security.py         # 三级安全分类 (shell + kubectl)
│   ├── tools.py            # activate_skill, read_skill_reference, list_skills
│   └── execution.py        # run_on_host (SSM/SSH), run_kubectl (EKS)
│
├── im/                      # IM - 即时通讯模块
│   ├── feishu_ws.py        # 飞书WebSocket长连接 (outbound, 免公网)
│   ├── feishu_gateway.py   # 飞书HTTP回调网关
│   ├── dingtalk_gateway.py # 钉钉HTTP回调网关
│   ├── wecom_gateway.py    # 企业微信HTTP回调网关
│   ├── gateway.py          # IM网关抽象基类
│   └── session_manager.py  # IM会话Agent管理
│
├── notify/                  # NOTIFY - 通知模块
│   ├── notifier.py         # 多渠道通知 (Feishu/Slack/Email/DingTalk/WeCom/SNS/Webhook)
│   └── im_config.py        # YAML-only频道配置 (channels.yaml) + IM应用凭证管理
│
├── auth/                    # AUTH - 认证模块
│   ├── models.py           # User, APIKey, Session模型
│   └── service.py          # 认证服务
│
├── audit/                   # AUDIT - 审计模块
│   ├── models.py           # AuditLog模型
│   └── service.py          # 审计日志服务
│
├── cli/                     # CLI - 命令行接口
│   ├── main.py             # ~3200行, kubectl风格命令 + 35个聊天斜杠命令
│   ├── context.py          # ChatContext 会话状态
│   ├── display.py          # ThinkingDisplay 进度显示 + TokenUsage 统计
│   └── formatters.py       # 表格样式、Markdown/JSON渲染
│
├── chat/                    # CHAT - 聊天预处理模块
│   ├── preprocessor.py     # I#/R# 引用解析、@file、多模态
│   ├── file_reader.py      # 文件内容提取 (text/DOCX/PDF/images)
│   ├── send_to.py          # /send_to 命令处理器
│   └── channel.py          # /channel 命令处理器
│
├── integrations/            # INTEGRATIONS - 外部集成
│   └── parsers.py          # Prometheus/CloudWatch/Datadog/PagerDuty 告警解析
│
└── web/                     # WEB - Web仪表板
    ├── app.py              # FastAPI + 81 REST API端点 + SSE Chat + Webhook
    ├── session_manager.py  # ChatSessionManager (per-session Agent, TTL清理)
    └── frontend/           # React + TypeScript + Tailwind (16页面, 22 hooks)
```

---

## 2. 数据模型

### 2.1 实体关系图 (ERD)

```
┌─────────────────┐       ┌──────────────────┐       ┌─────────────────┐
│   AWSAccount    │──1:N──│   AWSResource    │       │ MetricDataPoint │
├─────────────────┤       ├──────────────────┤       ├─────────────────┤
│ id (PK)         │       │ id (PK)          │       │ id (PK)         │
│ name (unique)   │       │ account_id (FK)  │       │ resource_id     │
│ account_id      │       │ resource_id      │       │ metric_namespace│
│ role_arn        │       │ resource_arn     │       │ metric_name     │
│ external_id     │       │ resource_type    │       │ dimensions      │
│ regions[]       │       │ resource_name    │       │ timestamp       │
│ is_active       │       │ region           │       │ value           │
│ created_at      │       │ status           │       │ unit            │
│ last_scanned_at │       │ resource_metadata│       │ statistic       │
└────────┬────────┘       │ tags             │       └─────────────────┘
         │                │ created_at       │
         │                │ updated_at       │
         │                └──────────────────┘
         │
         │1:N
         ▼
┌──────────────────┐
│ MonitoringConfig │
├──────────────────┤
│ id (PK)          │
│ account_id (FK)  │
│ service_type     │
│ is_enabled       │
│ metrics_config   │
│ logs_config      │
│ thresholds       │
│ created_at       │
│ updated_at       │
└──────────────────┘

┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│  HealthIssue    │──1:N──│   RCAResult     │──1:N──│    FixPlan      │
├─────────────────┤       ├─────────────────┤       ├─────────────────┤
│ id (PK)         │       │ id (PK)         │       │ id (PK)         │
│ resource_id     │       │ issue_id (FK)   │       │ rca_id (FK)     │
│ resource_type   │       │ analysis_type   │       │ title           │
│ region          │       │ root_cause      │       │ description     │
│ issue_type      │       │ confidence_score│       │ risk_level      │
│ severity        │       │ contributing_   │       │ status          │
│ title           │       │   factors[]     │       │ approved_by     │
│ description     │       │ recommendations│       │ approved_at     │
│ metric_name     │       │ related_        │       │ created_at      │
│ expected_value  │       │   resources[]   │       │ updated_at      │
│ actual_value    │       │ llm_model       │       └────────┬────────┘
│ deviation_%     │       │ llm_prompt      │                │1:N
│ raw_data        │       │ llm_response    │                ▼
│ status          │       │ created_at      │       ┌─────────────────┐
│ fingerprint     │       └─────────────────┘       │  FixExecution   │
│ occurrence_count│                                  ├─────────────────┤
│ first_seen      │       ┌─────────────────┐       │ id (PK)         │
│ last_seen       │       │     Report      │       │ plan_id (FK)    │
│ detected_at     │       ├─────────────────┤       │ status          │
│ resolved_at     │       │ id (PK)         │       │ steps_result    │
└─────────────────┘       │ report_type     │       │ started_at      │
                          │ title           │       │ completed_at    │
                          │ summary         │       │ error_message   │
                          │ content_markdown│       └─────────────────┘
                          │ content_html    │
                          │ file_path       │
                          │ report_metadata │
                          │ created_at      │
                          └─────────────────┘

┌─────────────────┐       ┌──────────────────────┐
│    Schedule     │──1:N──│ ScheduleExecution    │
├─────────────────┤       ├──────────────────────┤
│ id (PK)         │       │ id (PK)              │
│ name            │       │ schedule_id (FK)     │
│ cron_expr       │       │ started_at           │
│ task_type       │       │ completed_at         │
│ task_config     │       │ status               │
│ is_enabled      │       │ result               │
│ created_at      │       │ error_message        │
│ updated_at      │       └──────────────────────┘
└─────────────────┘

┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
│  NotificationLog     │  │    ChatSession       │  │    ChatMessage       │
├──────────────────────┤  ├──────────────────────┤  ├──────────────────────┤
│ id (PK)              │  │ id (PK, UUID)        │  │ id (PK)              │
│ channel_name (str)   │  │ title                │  │ session_id (FK)      │
│ event_type           │  │ created_at           │  │ role                 │
│ message              │  │ updated_at           │  │ content              │
│ status               │  │                      │  │ attachments (JSON)   │
│ sent_at              │  └──────────────────────┘  │ created_at           │
└──────────────────────┘                             └──────────────────────┘

┌──────────────────────┐  ┌──────────────────────┐
│     LocalDoc         │  │     IMAlias          │
├──────────────────────┤  ├──────────────────────┤
│ id (PK)              │  │ id (PK)              │
│ file_path (unique)   │  │ name (unique)        │
│ file_type            │  │ platform             │
│ size_bytes           │  │ chat_id              │
│ created_by           │  │ app_name             │
│ created_at           │  │ created_at           │
└──────────────────────┘  └──────────────────────┘

┌─────────────────────┐   ┌──────────────────────┐
│  CaseStudyRecord    │   │    AgentLog          │
├─────────────────────┤   ├──────────────────────┤
│ id (PK)             │   │ id (PK)              │
│ title               │   │ agent_name           │
│ category            │   │ session_id           │
│ symptoms            │   │ input                │
│ root_cause          │   │ output               │
│ resolution          │   │ tool_calls           │
│ embedding           │   │ tokens_used          │
│ created_at          │   │ duration_ms          │
└─────────────────────┘   │ created_at           │
                          └──────────────────────┘

注意:
- Anomaly 实体已弃用 (DEPRECATED)，由 HealthIssue 取代
- NotificationChannel 已从 DB 移除 — 通知渠道配置现由 config/channels.yaml 管理 (YAML-only)
- NotificationLog.channel_name 为字符串字段（不再是外键）
- HealthIssue 新增 fingerprint/occurrence_count/first_seen/last_seen 用于告警去重
```

### 2.2 枚举类型

| 枚举 | 值 |
|------|-----|
| `ResourceStatus` | running, stopped, terminated, available, unknown |
| `AnomalySeverity` | low, medium, high, critical |
| `AnomalyStatus` | open, acknowledged, resolved |
| `HealthIssueStatus` | open, investigating, root_cause_identified, fix_planned, fix_approved, fix_executed, fix_failed, resolved, acknowledged |
| `FixPlanStatus` | draft, pending_approval, approved, rejected |
| `FixPlanRiskLevel` | L0, L1, L2, L3 |
| `RuleOperator` | >, >=, <, <=, ==, != |

> **HealthIssue 状态机**: 状态转换受 `validate_status_transition()` 严格约束（`_ISSUE_TRANSITIONS` 有向邻接图），agent tool 和 API 均返回 409 Conflict 于非法转换。

---

## 3. 核心模块设计

### 3.1 SCAN - 资源扫描

**功能**: 发现并记录AWS云资源

**支持的AWS服务** (15种):
| 服务 | Boto3客户端 | 列表方法 | CloudWatch命名空间 |
|------|------------|----------|-------------------|
| EC2 | ec2 | describe_instances | AWS/EC2 |
| Lambda | lambda | list_functions | AWS/Lambda |
| RDS | rds | describe_db_instances | AWS/RDS |
| S3 | s3 | list_buckets | AWS/S3 |
| ECS | ecs | list_clusters | AWS/ECS |
| EKS | eks | list_clusters | AWS/EKS |
| DynamoDB | dynamodb | list_tables | AWS/DynamoDB |
| SQS | sqs | list_queues | AWS/SQS |
| SNS | sns | list_topics | AWS/SNS |
| ElastiCache | elasticache | describe_cache_clusters | AWS/ElastiCache |
| CloudFront | cloudfront | list_distributions | AWS/CloudFront |
| APIGateway | apigateway | get_rest_apis | AWS/ApiGateway |
| StepFunctions | stepfunctions | list_state_machines | AWS/States |
| Kinesis | kinesis | list_streams | AWS/Kinesis |
| Redshift | redshift | describe_clusters | AWS/Redshift |

**跨账户访问**:
```python
# STS AssumeRole 流程
sts_client.assume_role(
    RoleArn=account.role_arn,
    RoleSessionName="AgenticOps",
    ExternalId=account.external_id  # 可选
)
```

### 3.2 MONITOR - 监控采集

**功能**: 采集CloudWatch指标和日志

**指标采集**:
- 支持自定义维度 (Dimensions)
- 可配置周期 (默认300秒)
- 支持多种统计类型: Average, Sum, Max, Min, SampleCount

**日志查询**:
- CloudWatch Logs Insights 查询
- 异步轮询结果
- Lambda错误日志提取

### 3.3 DETECT - 异常检测

**检测方法**:

| 方法 | 算法 | 阈值 | 适用场景 |
|------|------|------|---------|
| Z-Score | 标准差偏离 | 3σ (99.7%) | 正态分布指标 |
| IQR | 四分位距 | 1.5x IQR | 有离群值数据 |
| Moving Average | 滑动窗口均值 | 2σ | 时序趋势数据 |

**规则引擎** (11条默认规则):
```
EC2:
  - CPUUtilization > 90% → CRITICAL
  - CPUUtilization > 70% → MEDIUM

Lambda:
  - Errors > 10 → HIGH
  - Throttles > 0 → MEDIUM
  - Duration > 10000ms → MEDIUM

RDS:
  - CPUUtilization > 80% → HIGH
  - DatabaseConnections > 100 → MEDIUM
  - FreeStorageSpace < 1GB → CRITICAL

SQS:
  - ApproximateNumberOfMessagesVisible > 10000 → HIGH
```

### 3.4 ANALYZE - 根因分析

**LLM集成**:
- 使用 Strands RCA Agent，集成知识库搜索 (SOPs + 案例库) + Agent Skills (12 个领域技能包)
- 默认模型: Claude Sonnet 4.6 (通过 AWS Bedrock)
- 分层模型: Haiku 4.5 (scan/detect/reporter), Sonnet 4.6 (rca/sre/main), Opus 4.6 (executor/复杂场景)

**RCA输出结构**:
```json
{
  "root_cause": "详细的根本原因描述",
  "confidence_score": 0.85,
  "contributing_factors": ["因素1", "因素2"],
  "recommendations": ["建议1", "建议2"],
  "related_resources": ["相关资源ARN"]
}
```

### 3.5 REPORT - 报告生成

**报告类型**:
| 类型 | 内容 | 格式 |
|------|------|------|
| daily | 每日概览、异常统计、建议 | Markdown/HTML |
| anomaly | 单个异常详情+RCA | Markdown |
| inventory | 资源清单按服务分组 | Markdown |

### 3.6 AGENT - Strands 多智能体系统

**架构**: 基于 Strands Agents SDK 的多智能体编排（agent-as-tool 模式），共 7 个专用 Agent，40+ 工具函数。所有 Agent 使用集中配置：`settings.bedrock_model_id*`, `settings.bedrock_max_tokens`, `settings.bedrock_window_size`，并通过 `SlidingWindowConversationManager(window_size=40, per_turn=True)` 防止上下文溢出。

**智能体列表** (7个):

| Agent | 职责 | 模型 | 说明 |
|-------|------|------|------|
| **Main Agent** | 主编排 (纯路由) | Sonnet 4.6 | 协调其他Agent，处理用户交互，任务路由。不直接调用AWS工具 |
| **Scan Agent** | 资源扫描 | Haiku 4.5 | 跨账户AWS资源发现与同步 (15种服务) |
| **Detect Agent** | 异常检测 | Haiku 4.5 | CloudWatch告警 + 统计检测 + 规则引擎，发现健康问题 |
| **RCA Agent** | 根因分析 | Sonnet 4.6 | 结合知识库 (SOPs + 案例库) + Skills + CloudTrail 进行深度根因分析 |
| **SRE Agent** | 站点可靠性 | Sonnet 4.6 | 修复计划制定、风险评估 (L0-L3)、运维查询 |
| **Executor Agent** | 修复执行 | Opus 4.6 | 读取审批后的 FixPlan，多后端执行 (AWS CLI + SSM/SSH + kubectl) |
| **Reporter Agent** | 报告生成 | Haiku 4.5 | 多格式报告生成与分发 (daily/incident/inventory) |

**工具模块**: 10个工具模块，共 40+ 工具函数，覆盖资源扫描、指标采集、异常检测、根因分析、报告生成、知识库检索、网络拓扑、图算法 (SPOF/容量/依赖链/变更模拟)、调度管理、通知发送、文件操作等功能。

**动态输出规则**: 通过 `contextvars.ContextVar` 控制 Agent 输出详细度（concise/medium/detailed），`build_prompt_with_skills()` 在 Agent 创建时注入对应级别的 OUTPUT FORMAT RULES。

---

## 4. 接口设计

### 4.1 CLI命令 (kubectl风格)

**命令组结构**:
```
aiops <verb> <resource> [options]
```

| 命令组 | 描述 |
|--------|------|
| `get` | 列出资源 (accounts, resources, anomalies, reports, schedules, channels) |
| `describe` | 查看资源详情 (account, resource, anomaly, report) |
| `create` | 创建资源 (account, schedule, channel) |
| `delete` | 删除资源 (account, schedule) |
| `update` | 更新资源 (account, anomaly, schedule) |
| `run` | 执行操作 (scan, detect, analyze, report, schedule, notify) |
| `logs` | 查看日志 (audit, entity) |

**主要命令示例**:
| 命令 | 描述 |
|------|------|
| `aiops get accounts` | 列出账户 (只有一个可激活) |
| `aiops get resources -t EC2` | 列出EC2资源 |
| `aiops describe anomaly 1` | 查看异常详情 |
| `aiops create account prod -a 123... -r arn:...` | 创建账户 |
| `aiops update account prod --enable` | 激活账户 (自动禁用其他) |
| `aiops run scan --services EC2,Lambda` | 执行扫描 |
| `aiops run detect` | 执行检测 |
| `aiops logs audit -e anomaly` | 查看审计日志 |

**账户约束**: 系统只允许一个账户处于激活状态。激活新账户会自动禁用其他账户。

**输出格式化**:

CLI使用 Rich 库提供友好的终端输出：

| 格式 | 命令参数 | 描述 |
|------|----------|------|
| Table | `-o table` | 默认表格视图，支持多种边框样式 |
| JSON | `-o json` | 语法高亮JSON输出 |
| Wide | `-o wide` | 扩展表格，显示更多列 |
| Tree | `aiops arch` | 树形结构视图 |
| Markdown | `aiops arch -o markdown` | Markdown表格渲染 |

**架构查看命令**:
```bash
aiops arch              # 树形视图 (默认)
aiops arch -o markdown  # Markdown表格
aiops arch -o json      # JSON格式
```

### 4.2 聊天斜杠命令 (Chat Slash Commands)

在 `aiops chat` 交互模式中，支持38个斜杠命令：

**思考过程显示** (Claude Code 风格):

聊天模式显示实时思考进度:
```
  ✓ Understanding request (245ms)
  ✓ Calling scan_resources (EC2, Lambda) (1.2s)
  ◐ Generating response...
```

| 图标 | 状态 |
|------|------|
| `◐` | 思考中 (动画旋转) |
| `⚙` | 工具调用中 |
| `⟳` | 处理中 |
| `✓` | 步骤完成 |
| `✗` | 错误 |

**终端键盘支持** (使用 prompt_toolkit):

| 快捷键 | 功能 |
|--------|------|
| ↑ / ↓ | 历史记录导航 |
| Ctrl+R | 反向搜索历史 |
| Tab | 斜杠命令自动补全 |
| Ctrl+A / Ctrl+E | 行首/行尾 |
| Ctrl+W | 删除单词 |
| Ctrl+U | 清除整行 |
| Ctrl+C | 取消输入 (按两次退出) |

**命令列表**:

| 类别 | 命令 | 描述 |
|------|------|------|
| **信息** | `/status`, `/arch`, `/help`, `/alias` | 系统状态与帮助 |
| **资源** | `/account list\|show\|activate\|delete` | 账户管理 |
| | `/resource list\|show` | 资源查询 |
| | `/anomaly list\|show` | 异常查询 |
| **操作** | `/scan`, `/detect`, `/analyze <id>` | 核心操作 |
| | `/acknowledge <id>`, `/resolve <id>` | 异常状态管理 |
| **工作流** | `/workflow full-scan\|daily\|incident\|health` | 多步骤管道 |
| **自动化** | `/schedule list\|run\|enable\|disable` | 调度管理 |
| | `/notify list\|test\|send` | 通知管理 |
| **会话** | `/session list\|save\|load\|delete` | 会话持久化 |
| | `/context account <name>\|reset` | 上下文切换 |
| **导出** | `/export resources\|anomalies\|accounts` | 数据导出 |
| **输出** | `/output json\|table\|wide\|yaml` | 输出格式 |
| **通知** | `/channel list\|show\|test\|set` | 通知渠道管理 (YAML-backed) |
| | `/send_to <target> <content>` | 发送内容到渠道或IM别名 |
| **输出** | `/detail [concise\|medium\|detailed]` | Agent 输出详细度控制 |
| **其他** | `/clear`, `/verbose` | 辅助命令 |

**会话持久化**:
- 历史记录: `~/.aiops/chat_history`
- 会话文件: `~/.aiops/sessions/`

### 4.3 Web API

**REST API端点 (81)**:

| 端点组 | 端点数 | 描述 |
|--------|--------|------|
| `/api/accounts` | 5 | 账户CRUD (列表/创建/详情/更新/删除) |
| `/api/resources` | 5 | 资源列表 (支持过滤) + 资源详情 |
| `/api/anomalies` | 5 | 异常列表/详情/状态更新/RCA结果 (legacy compat) |
| `/api/health-issues` | 7 | HealthIssue CRUD + 关联RCA/修复计划 |
| `/api/fix-plans` | 6 | 修复计划 CRUD + 审批 + 执行 |
| `/api/reports` | 5 | 报告CRUD + 生成 |
| `/api/schedules` | 7 | 调度 CRUD + 运行 + 执行历史 |
| `/api/notifications/channels` | 7 | 通知渠道 CRUD + 测试 (YAML-backed, string name 路由) |
| `/api/chat/sessions` | 5 | SSE 流式聊天 (创建/列表/消息/删除/历史) |
| `/api/topology` `/api/vpc-topology` | 6 | 网络拓扑 (VPC/区域/跨区域) |
| `/api/graph` | 12 | 图引擎 (VPC/区域/多区域 + enriched/SPOF/容量/依赖链/变更模拟) |
| `/api/audit-log` | 2 | 审计日志 |
| `/api/auth` | 3 | 认证 (登录/登出/当前用户) |
| `/api/im-aliases` | 3 | IM 别名管理 (列表/创建/删除) |
| `/api/im/bots` | 1 | IM Bot 状态 |
| `/api/local-docs` | 2 | Agent 生成文件追踪 (列表/详情) |
| `/api/stats` `/api/health` | 3 | 统计/健康检查 (DB/STS/磁盘) |
| `/api/webhooks` | 1 | 外部告警接入 (Prometheus/CloudWatch/Datadog/PagerDuty/Generic) |
| `/app/{path}` | 1 | SPA 静态文件 |

---

## 5. 配置管理

### 5.1 环境变量

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `AIOPS_DATABASE_URL` | 数据库连接 | `sqlite:///data/agenticops.db` |
| `AIOPS_BEDROCK_REGION` | Bedrock区域 | `us-east-1` |
| `AIOPS_BEDROCK_MODEL_ID` | 默认模型 (Sonnet 4.6) | `global.anthropic.claude-sonnet-4-6-v1` |
| `AIOPS_BEDROCK_MODEL_ID_CHEAP` | 经济模型 (Haiku 4.5) | `global.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `AIOPS_BEDROCK_MODEL_ID_STRONG` | 强模型 (Opus 4.6) | `global.anthropic.claude-opus-4-6-v1` |
| `AIOPS_BEDROCK_MAX_TOKENS` | 最大输出 token | `16384` |
| `AIOPS_BEDROCK_WINDOW_SIZE` | 滑窗对话管理大小 | `40` |
| `AIOPS_EXECUTOR_ENABLED` | 修复执行总开关 | `true` |
| `AIOPS_AUTO_RCA_ENABLED` | 自动触发RCA | `true` |
| `AIOPS_AUTO_FIX_ENABLED` | 自动修复管线总开关 | `true` |
| `AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1` | L0/L1 自动审批 | `true` |
| `AIOPS_NOTIFICATIONS_ENABLED` | 事件自动通知 | `true` |
| `AIOPS_SKILLS_ENABLED` | Agent 技能系统 | `true` |
| `AIOPS_AGENT_OUTPUT_DETAIL` | 输出详细度 | `medium` |
| `AIOPS_API_AUTH_ENABLED` | API Key 认证 | `false` |
| `AIOPS_CORS_ORIGINS` | CORS 允许源 | `""` (dev-mode) |
| `AIOPS_FEISHU_WS_ENABLED` | 飞书 WS 长连接 | `true` |
| `AIOPS_DEFAULT_METRICS_PERIOD` | 指标周期(秒) | `300` |
| `AIOPS_TABLE_STYLE` | 表格边框样式 | `default` |

**表格样式选项**: `default` (圆角), `simple`, `minimal`, `double`, `ascii`

**配置文件**:
- `config/channels.yaml` — 通知渠道配置 (**sole source of truth**, gitignored)
- `config/channels.yaml.example` — 渠道配置模板 (committed)
- `config/im-apps.yaml` — IM 应用凭证 (gitignored)
- `config/im-apps.yaml.example` — IM 凭证模板 (committed)

### 5.2 目录结构

```
data/
├── agenticops.db          # SQLite数据库
├── reports/               # 报告文件
└── knowledge_base/        # 知识库(预留)

~/.aiops/
├── chat_history           # 聊天历史记录
└── sessions/              # 保存的会话
    └── *.json
```

---

## 6. 安全设计

### 6.1 跨账户访问

```json
// IAM Trust Policy
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::MAIN_ACCOUNT:root"},
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": {"sts:ExternalId": "your-external-id"}
    }
  }]
}
```

### 6.2 最小权限原则

仅需只读权限:
- `ec2:Describe*`, `lambda:List*`, `lambda:Get*`
- `rds:Describe*`, `s3:List*`, `s3:GetBucket*`
- `cloudwatch:GetMetricData`, `logs:StartQuery`
- 等

---

## 7. 技术栈

### 7.1 依赖

| 类别 | 库 | 版本 |
|------|-----|------|
| AWS | boto3 | >=1.34.0 |
| ORM | sqlalchemy | >=2.0.0 |
| CLI | typer, rich, prompt_toolkit | >=0.12.0, >=13.0.0, >=3.0.0 |
| Web | fastapi, uvicorn | >=0.109.0, >=0.27.0 |
| LLM | strands-agents, strands-agents-tools | >=0.1.0 |
| 验证 | pydantic, pydantic-settings | >=2.0.0 |
| 数据 | pandas, numpy | >=2.0.0, >=1.26.0 |
| 调度 | croniter | >=1.3.0 |

### 7.2 开发依赖

- pytest >= 8.0.0
- pytest-asyncio >= 0.23.0
- ruff >= 0.2.0 (代码检查)
- mypy >= 1.8.0 (类型检查)

---

## 8. 扩展性设计

### 8.1 新增AWS服务

在 `scan/services.py` 中添加服务定义:

```python
SERVICE_DEFINITIONS["NewService"] = {
    "boto3_service": "newservice",
    "list_method": "list_resources",
    "list_key": "Resources",
    "id_field": "ResourceId",
    "cloudwatch_namespace": "AWS/NewService",
    "default_metrics": ["Metric1", "Metric2"],
}
```

### 8.2 新增检测规则

在 `detect/rules.py` 中添加规则:

```python
ThresholdRule(
    name="new_rule",
    metric_name="NewMetric",
    operator=RuleOperator.GT,
    threshold=100,
    severity=RuleSeverity.HIGH,
)
```

### 8.3 新增Agent工具

在 `tools/` 目录中添加工具模块，使用 Strands `@tool` 装饰器注册:

```python
from strands import tool

@tool
def new_tool(param: str) -> str:
    """工具描述"""
    return result
```

### 8.4 多监控源 — Monitoring Provider 架构

**背景**: 当前系统仅支持 CloudWatch 作为告警和指标数据源。实际客户环境中普遍使用多种可观测性工具 (Prometheus, Datadog, Grafana, ELK 等)，需要支持从多个数据源获取告警、指标和日志。

**架构决策 (ADR-001, 2026-02-24)**:

> 采用 **Provider 模式** (路线 A) — 为每个监控数据源实现独立的 Provider adapter。
> Agent 根据账户配置按需调用相应 Provider 的工具。
> 后续如需统一告警收敛 (路线 B — Webhook 聚合层)，可在 Provider 之上叠加，两者不冲突。

**Provider 接口定义**:

```
MonitoringProvider (抽象基类)
├── list_alarms(filters) → List[Alarm]          # 查询告警
├── get_metrics(query, time_range) → MetricData  # 查询指标
├── query_logs(query, time_range) → List[LogEntry] # 查询日志
└── get_provider_info() → ProviderInfo           # 提供者元信息
```

**Provider 实现优先级**:

| 优先级 | Provider | 数据源 | 状态 |
|--------|----------|--------|------|
| P0 | CloudWatch | AWS CloudWatch Alarms + Metrics + Logs | 已有 (待重构) |
| P1 | Prometheus | Prometheus API + Alertmanager | 待实现 |
| P2 | Datadog | Datadog Monitors + Metrics + Logs API | 待实现 |
| P3 | Grafana | Grafana Alerting + Loki + Mimir | 待评估 |

**数据流**:

```
账户配置: account.monitoring_providers = ["cloudwatch", "prometheus"]

告警触发阶段:
  Detect Agent
    → 遍历 account.monitoring_providers
    → cloudwatch_provider.list_alarms()  → [Alarm1, Alarm2]
    → prometheus_provider.list_alarms()  → [Alarm3]
    → 合并告警 → 创建 HealthIssue

调查阶段:
  RCA Agent
    → 根据 HealthIssue.source_provider 选择对应 Provider
    → provider.get_metrics(related_metrics)
    → provider.query_logs(error_patterns)
    → 综合分析 → RCAResult

修复阶段:
  SRE Agent (不依赖 Provider，直接操作基础设施)
    → kubectl / AWS API / Terraform
```

**对现有代码的影响**:
- `tools/aws_tools.py` 中的 `list_alarms`, `get_metrics`, `query_logs` 将重构为 CloudWatch Provider
- Agent 的 tool 注册将根据账户的 `monitoring_providers` 配置动态加载
- 新增 `providers/` 模块目录

**后续演进 — 路线 B (统一告警入口)**:

当多个 Provider 均已实现后，可增加 Webhook 聚合层作为补充:
```
Prometheus  ──→ Alertmanager ──→ Webhook ──→ AgenticOps (创建 HealthIssue)
Datadog     ──→ PagerDuty    ──→ Webhook ──→ AgenticOps
CloudWatch  ──→ SNS          ──→ Webhook ──→ AgenticOps
```
此时 Provider 仍用于调查阶段的深度查询，Webhook 仅用于被动接收告警事件。

---

## L4 Auto Operation (自动修复执行)

### 架构概览

L4 层补齐了 HealthIssue 生命周期中 `fix_approved → fix_executed → resolved` 的自动化闭环。
核心原则：**人工审批后自动执行，全程可审计**。

```
                          Human Approval (L2/L3)
                                  |
detect_agent --> rca_agent --> sre_agent --> approve --> executor_agent
  (L2)           (L3)          (L3)         (gateway)      (L4)
  |               |              |              |              |
  v               v              v              v              v
HealthIssue    RCAResult      FixPlan      FixPlan        FixExecution
 (open)     (investigating) (fix_planned)  (approved)    (fix_executed)
                                                              |
                                                              v
                                                         HealthIssue
                                                         (resolved)
```

### 新增组件

| 组件 | 文件 | 用途 |
|------|------|------|
| FixExecution 模型 | `models.py` | 记录每次执行的详细结果（步骤级追踪） |
| Executor Agent | `agents/executor_agent.py` | 读取已审批 FixPlan，多后端执行 (AWS CLI + SSM/SSH + kubectl) |
| Metadata Tools | `tools/metadata_tools.py` | `get_approved_fix_plan`, `save_execution_result`, `mark_fix_executed`, `mark_fix_failed` |
| 配置项 | `config.py` | `executor_enabled` (默认**开启**), `executor_step_timeout`, `executor_total_timeout` |
| API 端点 | `web/app.py` | 执行触发、执行记录查询、审批风险检查修复 |
| Auto-Fix Pipeline | `services/pipeline_service.py` | RCA → SRE → Approve(L0/L1) → Execute 自动化链 |
| Auto-RCA Trigger | `services/rca_service.py` | HealthIssue 创建后自动触发 RCA |
| Notification Service | `services/notification_service.py` | 7 个管线事件触发点的自动通知 |

### 执行协议（7 步）

1. **VERIFY** — `get_approved_fix_plan` 确认 status=approved
2. **GATE** — 检查 `executor_enabled` 配置
3. **PRE-CHECK** — 逐项验证前置条件（只读工具）
4. **EXECUTE** — 按 plan.steps 顺序执行（`run_aws_cli`）
5. **POST-CHECK** — 验证修复效果（只读工具）
6. **ROLLBACK** — 仅失败时按 rollback_plan 反向执行
7. **FINALIZE** — 记录结果，更新 HealthIssue 状态

### 安全规则

- 绝不执行未审批的计划
- 绝不跳过 pre-check
- 每步都记录结果（审计追踪）
- 失败必须尝试回滚
- L2/L3 审批端点拒绝 agent: 前缀的审批者
- 总开关 `AIOPS_EXECUTOR_ENABLED` 默认开启（可通过环境变量关闭）
- 三级安全分类: shell/kubectl 命令经 `skills/security.py` 分类为 readonly/write/blocked

### 风险分级审批策略

| 等级 | 审批方式 | 示例 |
|------|----------|------|
| L0 | 自动审批 | 只读验证（确认指标恢复） |
| L1 | 自动审批 | 低风险配置变更（调整告警阈值） |
| L2 | 人工审批 | 服务影响变更（调整实例大小） |
| L3 | 人工审批 | 高风险变更（重启服务、故障转移） |

---

## Agent Skills 系统

### 架构

Agent Skills 采用渐进式加载（Progressive Disclosure）模式:
1. **系统提示词** (~100 tokens/skill): 始终加载的 `<available_skills>` XML 摘要
2. **activate_skill()** (~3-5K tokens): 按需加载完整 SKILL.md (决策树 + 工具声明)
3. **read_skill_reference()** (~2-8K tokens): 深度参考资料 (references/*.md)

### 技能列表 (12 个)

| 技能 | 说明 | 动态工具 |
|------|------|----------|
| `linux-admin` | 进程/磁盘/内存/网络排查 | 无 |
| `network-engineer` | CCIE级路由/防火墙/TCP/VPN/MTU | 无 |
| `kubernetes-admin` | Pod/Node/CNI/CoreDNS/PVC/HPA + 8个修复决策树 | 无 |
| `database-admin` | RDS/DynamoDB/ElastiCache (慢查询/复制/死锁) | 无 |
| `elasticsearch` | ES/OpenSearch (集群健康/DSL/JVM/ILM/快照) | 无 |
| `monitoring` | CloudWatch/Prometheus/SLI/SLO/告警疲劳 | 无 |
| `log-analysis` | CloudWatch Insights/Pod logs/系统日志/错误模式 | 无 |
| `aws-compute` | EC2/ECS/EKS/Lambda 排查 | 无 |
| `aws-storage` | S3/EBS/EFS/FSx 排查 | 无 |
| `local-os-operator` | 本地文件操作 | 5 个动态工具 (read/tail/search/list/stat) |
| `distributed-tracing` | 分布式追踪分析 | 无 |
| `notification-operator` | 格式感知的批量报告分发 | 无 |

### 动态工具注册

Skills 可在 YAML frontmatter 中声明 `tools:` 字段（dotted path 列表）。`activate_skill()` 通过 Strands SDK 的 `agent.tool_registry.process_tools()` 在运行时注册工具，实现按需加载。

### 安全模型

`skills/security.py` 实现三级安全分类:
- **readonly**: 只读命令 (cat, kubectl get, df, etc.) — 直接执行
- **write**: 写操作 (kubectl delete, systemctl restart, etc.) — 需要确认
- **blocked**: 高危命令 (rm -rf, kubectl drain, etc.) — 拒绝执行

---

## 通知渠道系统

### YAML-Only 架构

`config/channels.yaml` 是通知渠道配置的**唯一数据源**（DB 表已废弃）。

```yaml
# config/channels.yaml 示例
feishu-ops:
  type: feishu
  enabled: true
  severity_filter: [critical, high]
  app_name: default
  chat_id: "oc_b972a0..."

slack-incidents:
  type: slack
  enabled: true
  webhook_url: "${SLACK_WEBHOOK_URL}"
```

### 通知类型

| 类型 | 说明 |
|------|------|
| `feishu` | 飞书群消息 (通过 IM App 凭证) |
| `dingtalk` | 钉钉群消息 (Webhook) |
| `wecom` | 企业微信群消息 (通过 IM App 凭证) |
| `slack` | Slack Webhook |
| `email` | AWS SES 邮件 |
| `sns` | AWS SNS Topic |
| `webhook` | 通用 HTTP Webhook |

### 自动通知 (7 个触发点)

通过 `services/notification_service.py` 的 daemon thread 异步发送:

1. `notify_issue_created` — HealthIssue 创建时
2. `notify_rca_completed` — RCA 完成时
3. `notify_fix_planned` — Fix Plan 生成时
4. `notify_fix_approved` — Fix Plan 审批通过时
5. `notify_execution_result` — 执行结果 (成功/失败)
6. `notify_report_saved` — 报告生成时
7. `notify_schedule_result` — 定时任务执行结果

---

## IM Bot 网关

### 支持的平台

| 平台 | 连接方式 | 文件 |
|------|----------|------|
| 飞书 | WebSocket 长连接 (outbound) | `im/feishu_ws.py` |
| 飞书 | HTTP 回调 | `im/feishu_gateway.py` |
| 钉钉 | HTTP 回调 | `im/dingtalk_gateway.py` |
| 企业微信 | HTTP 回调 | `im/wecom_gateway.py` |

### 架构

IM Bot 作为第三入口（与 CLI、Web 并列），共享完整的 Agent 层和预处理管线:

```
IM 消息 → Gateway → preprocess_message() → Main Agent → 回复
                                              ↓
                          /send_to 和 /channel 命令拦截
```

每个 chat_id 有独立 Agent 实例（通过 `IMChatSessionManager` 管理），保证会话隔离。飞书 WS 模式下 4-worker ThreadPoolExecutor 处理消息，同一会话串行处理（per-chat_id 锁）。

---

## 闭环验证结果 (Closed-Loop Validation)

### 验证环境

- **集群**: `agenticops-lab` — EKS 1.30, ap-southeast-1, 5 节点 (3 workload m5.large + 2 monitoring m5.large)
- **工作负载**: Google Online Boutique (12 微服务)
- **监控**: Prometheus + AlertManager → webhook → AgenticOps API
- **网络**: VPC 内网通信，EKS Private Endpoint Only

### 10 Case 验证结果 (2026-03-06)

| Case | 场景 | 得分 | MTTR | 修复方式 |
|------|------|------|------|----------|
| 1 | OOM Kill (adservice 64Mi) | **5/5** | 5m 34s | kubectl set resources (L1) |
| 2 | Bad Image (productcatalog) | **5/5** | 6m 38s | kubectl rollout undo (L1) |
| 3 | Redis Crash (redis-cart) | **5/5** | 7m 3s | kubectl rollout undo (L1) |
| 4 | Node DiskPressure (70G fill) | **5/5** | 8m 41s | kubectl delete pod + 清理 (L1) |
| 5 | Pod Pending (CPU 耗尽) | **5/5** | 7m 30s | kubectl delete stress pods (L1) |
| 6 | Unhealthy Targets (readiness) | **5/5** | 5m 24s | kubectl rollout undo (L1) |
| 7 | CoreDNS Down | **5/5** | 4m 42s | kubectl scale coredns (L1) |
| 8 | PVC Pending (错误 SC) | **5/5** | 6m 38s | kubectl delete + recreate PVC (L1) |
| 9 | HPA Maxed Out | **5/5** | 4m 7s | kubectl patch HPA maxReplicas (L1) |
| 10 | Service Crash (cartservice) | **5/5** | 6m 24s | kubectl rollout undo (L1) |

### 验收指标

| 指标 | 目标 | 实际 | 状态 |
|------|------|------|------|
| 闭环成功率 | ≥ 7/10 | **10/10** | ✅ |
| 平均检测延迟 | ≤ 3 min | **~2 min** | ✅ |
| 平均修复延迟 (MTTR) | ≤ 10 min | **~6.3 min** | ✅ |
| 单次成本 | ≤ $3/cycle | **~$2-3** | ✅ |

### 修复的关键 Bug

1. **`mark_fix_executed` 覆盖 `resolved` 状态** — Executor 的 `save_execution_result("succeeded")` 自动将 issue 解析为 `resolved`，但随后 `mark_fix_executed()` 又覆盖为 `fix_executed`。修复: 在 `mark_fix_executed()` 中增加 `resolved` 状态的 early return。
2. **AlertEvent 去重阻止新 HealthIssue 创建** — 两层去重 (AlertEvent + HealthIssue fingerprint) 中，AlertEvent 层在 linked issue 为终态时应放行创建新 issue。修复: 检查 linked HealthIssue 是否为终态 (`resolved`/`fix_executed`/`closed`)，如是则 unlink 并继续创建。

### 场景设计经验

- **OOM**: adservice 在 256Mi 下存活；需 64Mi + `-Xmx256m` 才能可靠触发 OOM
- **NetworkPolicy**: kubelet health check 绕过 Pod 级 NetworkPolicy → 改用 crash-loop 注入
- **Deployment Delete/Scale-to-0**: 删除 deployment 移除所有 metrics → 无 alert；scale to 0 → 0==0 无 mismatch → 改用 invalid command patch
- **LimitRange/ResourceQuota**: online-boutique 命名空间强制 CPU limits + 128Mi min memory，所有注入 Pod/Job 必须合规
- **Alert 时序**: `for:` duration + AlertManager `group_wait` = 3-6 min 检测延迟，verify timeout 需 ≥ 360s
