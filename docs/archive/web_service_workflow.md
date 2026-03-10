# AgenticOps Web Service — 技术工作流与进程模型

## 一句话总结

**一个 `uvicorn` 进程搞定一切** — REST API、SSE 流式 Chat、IM Bot（飞书/钉钉/企业微信）、Webhook 告警接入、后台自动修复管线全部内嵌，不需要额外进程。

---

## 进程架构

```
uvicorn agenticops.web.app:app --host 0.0.0.0 --port 8000
   │
   ├── [主线程] FastAPI HTTP 服务器
   │     ├── REST API (81 endpoints)
   │     ├── SSE Streaming Chat  POST /api/chat/sessions/{id}/messages
   │     ├── Webhook 接收器       POST /api/webhooks/{source}
   │     ├── IM HTTP 回调         POST /api/im/{platform}/callback
   │     └── SPA 静态文件         GET /app/*  (React build output)
   │
   ├── [daemon thread] Feishu WebSocket 长连接
   │     ├── outbound WS → Feishu 服务器 (无需公网 IP / callback URL)
   │     ├── 4-worker ThreadPoolExecutor 处理消息
   │     └── REST API 发送回复
   │
   ├── [daemon thread] Auto-Fix Pipeline (按需触发)
   │     ├── trigger_auto_rca() — HealthIssue 创建后
   │     ├── trigger_auto_sre() — RCA 完成后
   │     ├── trigger_auto_approve() — Fix Plan 生成后 (L0/L1 sync)
   │     └── trigger_auto_execute() — Plan 审批后
   │
   ├── [daemon thread] Notification Service (按需触发)
   │     └── 7 个管线事件触发点的异步通知发送
   │
   ├── [daemon thread] Executor Service 后台轮询
   │     └── 每 30s 检查 pending FixExecution 记录
   │
   └── [daemon thread] ChatSession Cleanup
         └── 每 5min 清理 30min 无活动的 Agent 实例
```

---

## 两套实时通信机制

项目中有两个容易混淆的实时通信通道，它们的技术实现完全不同：

### 1. Web Chat — SSE (Server-Sent Events)

用于 React 前端与后端的流式对话，**不是 WebSocket**。

```
React 前端 (useChat.ts)                          FastAPI 后端 (app.py)
┌─────────────────────┐                    ┌──────────────────────────┐
│ fetch() + ReadStream │ ── POST ──────►  │ EventSourceResponse(SSE) │
│                      │ ◄── text/event  │                          │
│ 逐 token 渲染        │    -stream ──── │ Strands Agent → Bedrock  │
└─────────────────────┘                    └──────────────────────────┘
```

**SSE 事件类型**:

| Event | Payload | 说明 |
|-------|---------|------|
| `text` | `{"token": "..."}` | 逐 token 流式输出 |
| `tool_start` | `{"name": "describe_ec2"}` | Agent 开始调用工具 |
| `tool_end` | `{"name": "describe_ec2"}` | 工具调用完成 |
| `done` | `{"input_tokens": N, "output_tokens": M}` | 对话结束 + token 用量 |
| `error` | `{"message": "..."}` | 错误信息 |

**关键代码路径**:

| 层 | 文件 | 说明 |
|----|------|------|
| 前端 Hook | `frontend/src/hooks/useChat.ts` | `fetch` + `ReadableStream` 解析 SSE |
| 后端 Endpoint | `web/app.py` → `api_send_chat_message()` | 返回 `EventSourceResponse` |
| SSE 库 | `sse-starlette` | FastAPI SSE 支持 |

**为什么用 SSE 不用 WebSocket**:
- Chat 是单向流（服务器 → 客户端），SSE 天然适合
- 原生 HTTP，不需要协议升级，对负载均衡友好
- 自动重连、更简单的错误处理

### 2. IM Bot — 多平台即时通讯

支持飞书、钉钉、企业微信三个 IM 平台，每个平台有独立的 Gateway 实现。

#### 2a. 飞书 — WebSocket 长连接 (推荐)

出站连接模式（bot 主动连飞书服务器），**无需公网 IP**。

```
AgenticOps 进程                              飞书服务器
┌─────────────────────────┐            ┌──────────────────┐
│ FeishuWSService          │            │                  │
│ ├── WSClient (daemon)    │ ─── WS ──►│ 推送消息事件      │
│ ├── ThreadPoolExecutor   │            │                  │
│ │   └── Agent → Bedrock  │            │                  │
│ └── REST Client          │ ─── HTTP ─►│ 接收回复         │
└─────────────────────────┘            └──────────────────┘
```

**工作流**:

1. 启动时 `FeishuWSService` 在 daemon thread 中建立 outbound WebSocket 连接
2. 飞书推送 `im.message.receive_v1` 事件（用户发消息）
3. 消息分发到 ThreadPoolExecutor（4 workers），不阻塞 WS 事件循环
4. 每个 chat_id 有独立锁，保证同一会话消息串行处理
5. 消息经过 `preprocess_message()` 处理（I#/R# 引用、/send_to 和 /channel 命令拦截）
6. Agent 处理完毕后通过 REST API 发送回复

#### 2b. 飞书/钉钉/企业微信 — HTTP 回调网关

需要公网可访问的回调 URL，由各平台推送 HTTP 请求。

```
IM 平台                                  AgenticOps 进程
┌──────────────┐                   ┌──────────────────────────┐
│ 飞书/钉钉/    │ ─── HTTP POST ──►│ FeishuGateway            │
│ 企业微信      │                   │ DingTalkGateway          │
│              │ ◄── HTTP 回复 ──  │ WeComGateway             │
└──────────────┘                   │   └── IMChatSessionManager│
                                   └──────────────────────────┘
```

| 平台 | Gateway 文件 | 连接方式 |
|------|-------------|----------|
| 飞书 | `im/feishu_ws.py` | WebSocket 长连接 (outbound, 免公网) |
| 飞书 | `im/feishu_gateway.py` | HTTP 回调 (需公网回调 URL) |
| 钉钉 | `im/dingtalk_gateway.py` | HTTP 回调 (需公网回调 URL) |
| 企业微信 | `im/wecom_gateway.py` | HTTP 回调 (需公网回调 URL) |

**运行方式**:

| 方式 | 命令 | 场景 |
|------|------|------|
| 嵌入模式 (默认) | `uvicorn agenticops.web.app:app` | Web + IM Bot 一起运行 |
| 独立模式 (飞书 WS) | `python -m agenticops.im.feishu_ws` | 只跑飞书 Bot，不需要 Web |

**会话管理**: `IMChatSessionManager` 为每个 chat_id 维护独立的 Agent 实例，保证会话隔离。凭证配置在 `config/im-apps.yaml`。

---

## 启动生命周期

```python
# app.py startup event

@app.on_event("startup")
async def startup():
    init_db()                        # 1. 初始化 SQLite 数据库 + 自动迁移 (含 channel_name backfill)
    start_scheduler()                # 2. 启动 Cron 调度器
    _chat_sessions.start_cleanup()   # 3. 启动 ChatSession 清理线程
    _executor_service.start()        # 4. 启动 Executor 后台轮询线程
    if settings.feishu_ws_enabled:   # 5. 启动 Feishu WS (如果启用)
        start_feishu_ws()

@app.on_event("shutdown")
async def shutdown():
    _chat_sessions.stop_cleanup()    # 清理 ChatSession
    _executor_service.stop()         # 停止 Executor
    stop_feishu_ws()                 # 断开 Feishu WS
    stop_scheduler()                 # 停止 Cron 调度器
```

---

## 自动修复管线 (Auto-Fix Pipeline)

当 Prometheus 告警通过 webhook 到达时，整条管线在后台 daemon thread 中自动运行：

```
POST /api/webhooks/prometheus  (也支持 /cloudwatch, /datadog, /pagerduty, /generic)
  │
  ▼
_process_webhook_alert()
  ├── parse_prometheus()           # 解析 AlertManager payload (6种源格式)
  ├── create_health_issue()        # 创建 HealthIssue (SHA-256 指纹去重, 5分钟窗口)
  ├── 📢 notify_issue_created()    # 自动通知 ①
  │
  ▼ [daemon thread 1]
trigger_auto_rca()                 # gate: AIOPS_AUTO_RCA_ENABLED
  ├── rca_agent(issue_id)          # Bedrock Sonnet 4.6
  ├── save_rca_result()
  ├── 📢 notify_rca_completed()    # 自动通知 ②
  │
  ▼ [daemon thread 2]
trigger_auto_sre()                 # gate: AIOPS_AUTO_FIX_ENABLED
  ├── sre_agent(issue_id)          # Bedrock Sonnet 4.6
  ├── save_fix_plan()
  ├── 📢 notify_fix_planned()      # 自动通知 ③
  │
  ▼ [sync]
trigger_auto_approve()             # gate: AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1
  ├── L0/L1 → 自动审批
  │     └── 📢 notify_fix_approved()  # 自动通知 ④
  ├── L2/L3 → 暂停，等待人工审批 (API/Chat)
  │
  ▼ [daemon thread 3]
trigger_auto_execute()             # gate: AIOPS_EXECUTOR_ENABLED
  ├── executor_agent(plan_id)      # Bedrock Opus 4.6 (多后端: AWS CLI + SSM/SSH + kubectl)
  ├── save_execution_result()
  ├── 📢 notify_execution_result() # 自动通知 ⑤
  ├── resolution_service           # RAG 管线 + case 蒸馏
  └── auto-resolve HealthIssue → resolved
```

每个阶段独立的 daemon thread，互不阻塞。主 HTTP 线程不受影响。

**另外 2 个通知触发点**:
- 📢 `notify_report_saved()` — 报告生成时 (report_tools.py)
- 📢 `notify_schedule_result()` — 定时任务完成时 (scheduler.py, 成功/失败各一次)

---

## 前端部署模式

### 开发模式

```bash
# Terminal 1: 后端
uvicorn agenticops.web.app:app --reload --port 8000

# Terminal 2: 前端 dev server (HMR)
cd src/agenticops/web/frontend
npm run dev    # Vite dev server, proxy → localhost:8000
```

### 生产模式

```bash
# 1. 构建前端静态文件
cd src/agenticops/web/frontend
npm run build  # → dist/ 目录

# 2. 只启动后端 (FastAPI serve 静态文件)
uvicorn agenticops.web.app:app --host 0.0.0.0 --port 8000
# /app/* 路由 serve React SPA
# /api/* 路由处理 API 请求
```

**不需要 nginx / 单独的前端服务器** — FastAPI 直接 serve 构建产物。

---

## 相关配置

| Setting | Default | Env Var | 说明 |
|---------|---------|---------|------|
| `feishu_ws_enabled` | `true` | `AIOPS_FEISHU_WS_ENABLED` | 启用 Feishu WS 长连接 |
| `executor_enabled` | `true` | `AIOPS_EXECUTOR_ENABLED` | 启用修复执行 |
| `auto_rca_enabled` | `true` | `AIOPS_AUTO_RCA_ENABLED` | 自动触发 RCA |
| `auto_fix_enabled` | `true` | `AIOPS_AUTO_FIX_ENABLED` | 自动修复管线总开关 |
| `executor_auto_approve_l0_l1` | `true` | `AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1` | L0/L1 自动审批 |
| `notifications_enabled` | `true` | `AIOPS_NOTIFICATIONS_ENABLED` | 事件自动通知 (7 触发点) |
| `executor_poll_interval` | `30` | `AIOPS_EXECUTOR_POLL_INTERVAL` | Executor 轮询间隔 (秒) |
| `cors_origins` | `""` | `AIOPS_CORS_ORIGINS` | CORS 允许的源 (空 = dev only) |
| `api_auth_enabled` | `false` | `AIOPS_API_AUTH_ENABLED` | 启用 API Key 认证 |
| `channels_config` | `config/channels.yaml` | - | 通知渠道 YAML 配置路径 |

---

## 关键文件索引

| 文件 | 职责 |
|------|------|
| `web/app.py` | FastAPI 主入口 — 启动/关闭、81 路由、SSE chat、webhook、IM 回调 |
| `web/session_manager.py` | ChatSessionManager — per-session Agent 实例管理 (TTL 清理) |
| `im/feishu_ws.py` | Feishu WebSocket 服务 — 消息接收、Agent 调度、REST 回复 |
| `im/feishu_gateway.py` | Feishu HTTP 回调网关 |
| `im/dingtalk_gateway.py` | 钉钉 HTTP 回调网关 |
| `im/wecom_gateway.py` | 企业微信 HTTP 回调网关 |
| `im/gateway.py` | IM 网关抽象基类 |
| `im/session_manager.py` | IMChatSessionManager — IM 会话的 Agent 实例管理 |
| `services/pipeline_service.py` | 自动修复管线 — RCA → SRE → Approve → Execute 触发链 |
| `services/rca_service.py` | 自动 RCA 触发器 — HealthIssue 创建后自动分析 |
| `services/executor_service.py` | Executor 后台轮询服务 — 处理 pending FixExecution |
| `services/notification_service.py` | 事件自动通知 — 7 个管线触发点的异步通知发送 |
| `services/resolution_service.py` | 后处理服务 — RAG 管线 + case 蒸馏 |
| `notify/notifier.py` | NotificationManager — 多渠道通知发送 (Feishu/Slack/Email/DingTalk/WeCom/SNS/Webhook) |
| `notify/im_config.py` | YAML-only 频道配置 — load_channels(), save_channel(), mtime 缓存 |
| `chat/send_to.py` | /send_to 命令处理器 — CLI/Web/IM 共享 |
| `chat/channel.py` | /channel 命令处理器 — CLI/Web/IM 共享 |
| `frontend/src/hooks/useChat.ts` | React SSE 流式 chat hook |
| `config.py` | 所有 `AIOPS_*` 环境变量的集中配置 |
| `config/channels.yaml` | 通知渠道配置 (**sole source of truth**, gitignored) |
| `config/im-apps.yaml` | IM 应用凭证配置 (gitignored) |
