---
inclusion: auto
---

# 后端 API 开发规范

## 架构概览
- 框架：FastAPI（异步）
- 主文件：`src/agenticops/web/app.py`（~70 REST 端点）
- ORM：SQLAlchemy 2.0（声明式映射）
- 数据库：SQLite（本地）/ PostgreSQL（云端）
- 配置：Pydantic Settings（`src/agenticops/config.py`）

## API 端点分类

| 路径前缀 | 功能 | 端点数 |
|----------|------|--------|
| `/api/health-issues` | Issue CRUD + RCA + Fix Plan 触发 | ~8 |
| `/api/fix-plans` | Plan 管理 + 审批 + 执行 | ~6 |
| `/api/chat/sessions` | Chat Session 管理 + SSE 流式 | ~5 |
| `/api/resources` | 资源清单 + 详情 + 关联资源 | ~5 |
| `/api/schedules` | 定时任务 CRUD + 执行历史 | ~7 |
| `/api/notifications` | 通道管理 + 测试发送 + 日志 | ~7 |
| `/api/graph` / `/api/network` | 拓扑 + SRE 分析 | ~18 |
| `/api/accounts` | 云账户 CRUD | ~5 |
| `/api/auth` | 登录/登出/用户 | ~3 |
| `/api/audit` | 审计日志查询 | ~3 |
| `/api/stats` / `/api/health` | 系统健康 + 趋势 | ~3 |
| `/api/memory` | 跨会话记忆（事实 + 经验） | ~3 |
| `/api/im` | IM Bot Webhook + 别名管理 | ~8 |

## 数据模型（`models.py`）

### 核心表
- `cloud_accounts`：多云账户配置
- `cloud_resources`：扫描的资源清单
- `health_issues`：检测到的问题（含生命周期状态机）
- `rca_results`：根因分析结果
- `fix_plans`：修复方案（draft → pending_approval → approved → executing → executed）
- `fix_executions`：执行记录（含步骤结果）
- `pipeline_events`：Issue 生命周期时间线事件
- `chat_sessions` / `chat_messages`：聊天历史
- `session_summaries`：对话摘要
- `agent_memory_facts`：跨会话结构化事实记忆
- `agent_memories`：跨会话向量化经验记忆
- `alert_events`：入站告警
- `sop_records`：标准操作流程
- `notification_logs`：通知审计日志
- `graph_nodes` / `graph_edges`：基础设施拓扑图

### 数据库会话管理
```python
from agenticops.models import get_db_session

with get_db_session() as session:
    # 自动 commit/rollback
    result = session.query(HealthIssue).filter_by(id=issue_id).first()
```

## 服务层（`services/`）
| 服务 | 职责 |
|------|------|
| `pipeline_service.py` | Auto-Fix Pipeline（RCA → SRE → Approve → Execute） |
| `rca_service.py` | RCA 触发与结果保存 |
| `executor_service.py` | Fix Plan 执行管理 |
| `notification_service.py` | 多通道通知发送 |
| `pipeline_events.py` | Pipeline 事件记录 |
| `resolution_service.py` | Issue 自动解决 |
| `graph_sync_service.py` | 拓扑图同步 |
| `summary_service.py` | 对话摘要生成（Haiku） |
| `memory_service.py` | 跨会话记忆（事实 + 向量化经验） |

## 配置管理（`config.py`）
- 优先级：环境变量 > `.env` > `config/settings.yaml` > 默认值
- 环境变量前缀：`AIOPS_`
- 关键配置项：
  - `database_url`：数据库连接
  - `bedrock_region` / `bedrock_model_id`：模型配置
  - `auto_fix_enabled`：Auto-Fix 主开关
  - `executor_auto_approve_l0_l1`：L0/L1 自动审批
  - `executor_enabled`：执行开关
  - `notifications_enabled`：通知开关

## API 开发规范

### 新增端点
1. 在 `web/app.py` 中定义路由
2. 使用 Pydantic BaseModel 定义请求/响应 Schema
3. 使用 `get_db_session()` 上下文管理器操作数据库
4. 敏感字段（密钥等）在响应中脱敏（`REDACTED_KEYS`）
5. 前端对应更新 `api/types.ts` 类型定义

### 错误处理
- 使用 `HTTPException` 返回错误
- 状态机违规返回 409（`InvalidSOPTransition`）
- 资源不存在返回 404

### SSE 流式响应
- Chat 使用 `sse-starlette` 的 `EventSourceResponse`
- 事件类型：`token`（流式内容）、`tool_call`（工具调用）、`done`（完成）、`error`（错误）

## 前后端联调
- 前端 Vite 开发服务器代理 `/api` 到后端
- 后端静态文件服务：`/app` 路由返回 React SPA 的 `index.html`
- 生产构建：`cd src/agenticops/web/frontend && npm run build`
