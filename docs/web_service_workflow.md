# AgenticOps Web Service — 技术工作流与进程模型

## 一句话总结

**一个 `uvicorn` 进程搞定一切** — REST API、SSE 流式 Chat、Feishu Bot、后台任务全部内嵌，不需要额外进程。

---

## 进程架构

```
uvicorn agenticops.web.app:app --host 0.0.0.0 --port 8000
   │
   ├── [主线程] FastAPI HTTP 服务器
   │     ├── REST API (80+ endpoints)
   │     ├── SSE Streaming Chat  POST /api/chat/sessions/{id}/messages
   │     ├── Webhook 接收器       POST /api/webhooks/{source}
   │     └── SPA 静态文件         GET /app/*  (React build output)
   │
   ├── [daemon thread] Feishu WebSocket 长连接
   │     ├── outbound WS → Feishu 服务器 (无需公网 IP / callback URL)
   │     ├── 4-worker ThreadPoolExecutor 处理消息
   │     └── REST API 发送回复
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

### 2. Feishu Bot — WebSocket 长连接

用于飞书 IM 双向对话，是真正的 WebSocket，但是**出站连接**（bot 主动连飞书服务器）。

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
5. Agent 处理完毕后通过 REST API 发送回复

**两种运行方式**:

| 方式 | 命令 | 场景 |
|------|------|------|
| 嵌入模式 (默认) | `uvicorn agenticops.web.app:app` | Web + Feishu Bot 一起运行 |
| 独立模式 | `python -m agenticops.im.feishu_ws` | 只跑 Feishu Bot，不需要 Web |

---

## 启动生命周期

```python
# app.py startup event (line 615)

@app.on_event("startup")
async def startup():
    init_db()                        # 1. 初始化 SQLite 数据库 + 自动迁移
    _chat_sessions.start_cleanup()   # 2. 启动 ChatSession 清理线程
    _executor_service.start()        # 3. 启动 Executor 后台轮询线程
    if settings.feishu_ws_enabled:   # 4. 启动 Feishu WS (如果启用)
        start_feishu_ws()

@app.on_event("shutdown")
async def shutdown():
    _chat_sessions.stop_cleanup()    # 清理 ChatSession
    _executor_service.stop()         # 停止 Executor
    stop_feishu_ws()                 # 断开 Feishu WS
```

---

## 自动修复管线 (Auto-Fix Pipeline)

当 Prometheus 告警通过 webhook 到达时，整条管线在后台 daemon thread 中自动运行：

```
POST /api/webhooks/prometheus
  │
  ▼
_process_webhook_alert()
  ├── parse_prometheus()           # 解析 AlertManager payload
  ├── create_health_issue()        # 创建 HealthIssue (指纹去重)
  │
  ▼ [daemon thread 1]
trigger_auto_rca()
  ├── rca_agent(issue_id)          # Bedrock Sonnet 4.6
  ├── save_rca_result()
  │
  ▼ [daemon thread 2]
trigger_auto_sre()
  ├── sre_agent(issue_id)          # Bedrock Sonnet 4.6
  ├── save_fix_plan()
  │
  ▼ [sync]
trigger_auto_approve()
  ├── L0/L1 → 自动审批
  ├── L2/L3 → 暂停，等待人工审批
  │
  ▼ [daemon thread 3]
trigger_auto_execute()
  ├── executor_agent(plan_id)      # Bedrock Opus 4.6
  ├── save_execution_result()
  └── resolution_service           # RAG 管线 + 通知
```

每个阶段独立的 daemon thread，互不阻塞。主 HTTP 线程不受影响。

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
| `executor_poll_interval` | `30` | `AIOPS_EXECUTOR_POLL_INTERVAL` | Executor 轮询间隔 (秒) |
| `cors_origins` | `""` | `AIOPS_CORS_ORIGINS` | CORS 允许的源 (空 = dev only) |
| `api_auth_enabled` | `false` | `AIOPS_API_AUTH_ENABLED` | 启用 API Key 认证 |

---

## 关键文件索引

| 文件 | 职责 |
|------|------|
| `web/app.py` | FastAPI 主入口 — 启动/关闭、80+ 路由、SSE chat、webhook |
| `web/session_manager.py` | ChatSessionManager — per-session Agent 实例管理 (TTL 清理) |
| `im/feishu_ws.py` | Feishu WebSocket 服务 — 消息接收、Agent 调度、REST 回复 |
| `im/session_manager.py` | IMChatSessionManager — IM 会话的 Agent 实例管理 |
| `services/pipeline_service.py` | 自动修复管线 — RCA → SRE → Approve → Execute 触发链 |
| `services/executor_service.py` | Executor 后台轮询服务 — 处理 pending FixExecution |
| `frontend/src/hooks/useChat.ts` | React SSE 流式 chat hook |
| `config.py` | 所有 `AIOPS_*` 环境变量的集中配置 |
