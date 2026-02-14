# AgenticAIOps - 系统设计文档

## 概述

AgenticAIOps 是一个 Agent-First 的 AWS 云可观测性平台，通过 LLM 智能分析实现自动化的异常检测和根因分析。

**版本**: 0.1.0
**技术栈**: Python 3.11+, SQLAlchemy, FastAPI, LangChain, AWS Bedrock

---

## 1. 系统架构

### 1.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           AgenticAIOps                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐         │
│   │   CLI    │    │   Web    │    │  Agent   │    │   API    │         │
│   │ (Typer)  │    │(FastAPI) │    │(LangChain│    │Endpoints │         │
│   └────┬─────┘    └────┬─────┘    └────┬─────┘    └────┬─────┘         │
│        │               │               │               │                │
│        └───────────────┴───────────────┴───────────────┘                │
│                              │                                           │
│   ┌──────────────────────────┴───────────────────────────┐              │
│   │                    Core Services                      │              │
│   ├──────────┬──────────┬──────────┬──────────┬─────────┤              │
│   │  SCAN    │ MONITOR  │  DETECT  │ ANALYZE  │ REPORT  │              │
│   │ 资源扫描 │ 指标监控 │ 异常检测 │ 根因分析 │ 报告生成│              │
│   └────┬─────┴────┬─────┴────┬─────┴────┬─────┴────┬────┘              │
│        │          │          │          │          │                    │
│   ┌────┴──────────┴──────────┴──────────┴──────────┴────┐              │
│   │                    Data Layer                        │              │
│   │              SQLAlchemy + SQLite                     │              │
│   └─────────────────────────┬────────────────────────────┘              │
│                             │                                            │
└─────────────────────────────┼────────────────────────────────────────────┘
                              │
┌─────────────────────────────┴────────────────────────────────────────────┐
│                         External Services                                 │
├──────────────────┬──────────────────┬────────────────────────────────────┤
│   AWS Services   │  AWS CloudWatch  │         AWS Bedrock                │
│ (EC2,Lambda,RDS  │  (Metrics/Logs)  │        (Claude LLM)                │
│  S3,ECS,EKS...) │                  │                                    │
└──────────────────┴──────────────────┴────────────────────────────────────┘
```

### 1.2 模块结构

```
src/agenticops/
├── __init__.py              # 版本定义 (0.1.0)
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
├── agent/                   # AGENT - AI代理模块
│   └── ops_agent.py        # LangChain Agent编排 (13个工具)
│
├── pipeline/                # PIPELINE - 管道编排模块 (新)
│   └── orchestrator.py     # 多步骤管道编排器
│
├── scheduler/               # SCHEDULER - 调度模块 (新)
│   └── scheduler.py        # Cron调度器
│
├── notify/                  # NOTIFY - 通知模块 (新)
│   └── notifier.py         # 多渠道通知 (Slack/Email/SNS/Webhook)
│
├── auth/                    # AUTH - 认证模块 (新)
│   ├── models.py           # User, APIKey, Session模型
│   └── service.py          # 认证服务
│
├── audit/                   # AUDIT - 审计模块 (新)
│   ├── models.py           # AuditLog模型
│   └── service.py          # 审计日志服务
│
├── cli/                     # CLI - 命令行接口
│   └── main.py             # kubectl风格命令 + 33个聊天斜杠命令
│
└── web/                     # WEB - Web仪表板
    └── app.py              # FastAPI + 30+ REST API端点
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
│    Anomaly      │──1:N──│   RCAResult     │       │     Report      │
├─────────────────┤       ├─────────────────┤       ├─────────────────┤
│ id (PK)         │       │ id (PK)         │       │ id (PK)         │
│ resource_id     │       │ anomaly_id (FK) │       │ report_type     │
│ resource_type   │       │ analysis_type   │       │ title           │
│ region          │       │ root_cause      │       │ summary         │
│ anomaly_type    │       │ confidence_score│       │ content_markdown│
│ severity        │       │ contributing_   │       │ content_html    │
│ title           │       │   factors[]     │       │ file_path       │
│ description     │       │ recommendations│       │ report_metadata │
│ metric_name     │       │ related_        │       │ created_at      │
│ expected_value  │       │   resources[]   │       └─────────────────┘
│ actual_value    │       │ llm_model       │
│ deviation_%     │       │ llm_prompt      │
│ raw_data        │       │ llm_response    │
│ status          │       │ created_at      │
│ detected_at     │       └─────────────────┘
│ resolved_at     │
└─────────────────┘
```

### 2.2 枚举类型

| 枚举 | 值 |
|------|-----|
| `ResourceStatus` | running, stopped, terminated, available, unknown |
| `AnomalySeverity` | low, medium, high, critical |
| `AnomalyStatus` | open, acknowledged, resolved |
| `RuleOperator` | >, >=, <, <=, ==, != |

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
- 使用 AWS Bedrock Claude 模型
- 默认模型: `anthropic.claude-3-sonnet-20240229-v1:0`

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

### 3.6 AGENT - AI代理

**工具列表** (8个):
1. `scan_resources` - 扫描资源
2. `get_metrics` - 获取指标
3. `detect_anomalies` - 检测异常
4. `analyze_anomaly` - 分析异常
5. `generate_report` - 生成报告
6. `list_resources` - 列出资源
7. `list_anomalies` - 列出异常
8. `collect_metrics` - 采集指标

**Agent循环**: 最多5次迭代

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

在 `aiops chat` 交互模式中，支持35个斜杠命令：

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
| **其他** | `/clear`, `/verbose` | 辅助命令 |

**会话持久化**:
- 历史记录: `~/.aiops/chat_history`
- 会话文件: `~/.aiops/sessions/`

### 4.3 Web API

**REST API端点 (30+)**:

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/accounts` | GET/POST | 账户列表/创建 |
| `/api/accounts/{id}` | GET/PUT/DELETE | 账户CRUD |
| `/api/resources` | GET | 资源列表 (支持过滤) |
| `/api/resources/{id}` | GET | 资源详情 |
| `/api/anomalies` | GET | 异常列表 |
| `/api/anomalies/{id}` | GET | 异常详情 |
| `/api/anomalies/{id}/status` | PUT | 更新异常状态 |
| `/api/anomalies/{id}/rca` | GET | 获取RCA结果 |
| `/api/reports` | GET | 报告列表 |
| `/api/reports/generate` | POST | 生成报告 |
| `/api/schedules` | GET/POST | 调度管理 |
| `/api/channels` | GET/POST | 通知渠道 |
| `/api/audit` | GET | 审计日志 |
| `/api/auth/login` | POST | 用户登录 |
| `/api/health` | GET | 健康检查 |

---

## 5. 配置管理

### 5.1 环境变量

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `AIOPS_DATABASE_URL` | 数据库连接 | `sqlite:///data/agenticops.db` |
| `AIOPS_BEDROCK_REGION` | Bedrock区域 | `us-east-1` |
| `AIOPS_BEDROCK_MODEL_ID` | LLM模型 | `anthropic.claude-3-sonnet-20240229-v1:0` |
| `AIOPS_DEFAULT_METRICS_PERIOD` | 指标周期(秒) | `300` |
| `AIOPS_ANOMALY_DETECTION_WINDOW` | 检测窗口(秒) | `3600` |
| `AIOPS_TABLE_STYLE` | 表格边框样式 | `default` |
| `FORCE_COLOR` | 强制彩色输出 | - |

**表格样式选项**: `default` (圆角), `simple`, `minimal`, `double`, `ascii`

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
| CLI | typer, rich | >=0.12.0, >=13.0.0 |
| Web | fastapi, uvicorn | >=0.109.0, >=0.27.0 |
| LLM | langchain, langchain-aws | >=0.1.0 |
| 验证 | pydantic, pydantic-settings | >=2.0.0 |
| 数据 | pandas, numpy | >=2.0.0, >=1.26.0 |

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

在 `agent/ops_agent.py` 中注册工具:

```python
@tool
def new_tool(param: str) -> str:
    """工具描述"""
    return result
```
