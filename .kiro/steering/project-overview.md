---
inclusion: auto
---

# AgenticOps 项目概览

## 项目定位
AgenticOps 是一个 Agent-First 云运维平台，使用 7 个专业 AI Agent（基于 Strands Agents SDK + AWS Bedrock Claude）实现 AWS 基础设施的扫描、监控、检测、分析和自动修复。

## 技术栈

### 后端
- Python 3.12+ / FastAPI（异步，~70 REST 端点）
- SQLAlchemy 2.0 ORM + SQLite（本地）/ PostgreSQL（云端）
- Strands Agents SDK（Agent 框架）
- AWS Bedrock（LLM 推理：Opus 4.6 / Sonnet 4.6 / Haiku 4.5）
- SSE（Server-Sent Events）用于 Chat 流式输出
- Pydantic Settings（配置管理，AIOPS_ 前缀环境变量）

### 前端
- React 18 + TypeScript 5.6
- Vite 6.0（构建工具）
- Tailwind CSS 3.4 + CSS Variables（shadcn 风格主题系统）
- Radix UI（无头组件库）
- TanStack Query 5.62（服务端状态管理）
- React Router 6.28（路由）
- i18n：自定义 LocaleContext（en/zh 双语）
- 字体：Outfit（Google Fonts）

## 核心架构

### 多 Agent 体系
| Agent | 模型层级 | 职责 |
|-------|---------|------|
| Main | Opus 4.6 | 纯路由器，分发到专业 Agent |
| Scan | Haiku 4.5 | 资源发现（20+ AWS 服务） |
| Detect | Haiku 4.5 | 健康监控（CloudWatch/Prometheus/Datadog） |
| RCA | Opus 4.6 | 根因分析 + Skills + KB |
| SRE | Opus 4.6 | 修复方案生成（只读，不执行） |
| Executor | Sonnet 4.6 | 多后端执行（AWS CLI/SSM/kubectl） |
| Reporter | Haiku 4.5 | 报告生成 + KB 蒸馏 |

### Auto-Fix Pipeline
```
Alert → HealthIssue → RCA Agent → SRE Agent → Auto-Approve(L0/L1) → Executor → Resolve
```
三个独立开关：`auto_fix_enabled`、`executor_auto_approve_l0_l1`、`executor_enabled`

### HealthIssue 生命周期
```
open → investigating → acknowledged → root_cause_identified → fix_planned
  → fix_approved → fix_executing → fix_executed → resolved
```

## 前端页面结构
| 页面 | 路由 | 功能 |
|------|------|------|
| Dashboard | `/app` | KPI 卡片、趋势图、最近 Issue、资源分布、活跃 Fix Plan、审计日志、定时任务 |
| Chat | `/app/chat/:sessionId` | SSE 流式聊天、文件上传、Session 管理、保存为报告 |
| Issues & Plans | `/app/issues` | Issue 列表（阶段过滤）+ 资源列表（分页/筛选） |
| Issue Detail | `/app/issues/:id` | Issue 详情 + RCA + Fix Plan + Timeline + 审批/执行工作流 |
| Reports | `/app/reports` | 报告列表 + 详情 + 发布/订阅 |
| Schedules | `/app/schedules` | 定时任务 CRUD + 执行历史 |
| Settings | `/app/settings` | 运行时配置（模型、通道、Skills、KB、审计、MCP、账户） |
| Resource Detail | `/app/resources/:id` | 资源元数据 + 关联 Issue + Fix Plan |

## 布局结构
- `AppShell`：52px 左侧图标导航栏 + 顶部栏 + 主内容区
- `IconSidebar`：固定左侧，Radix Tooltip，NavLink 高亮
- `MinimalTopBar`：顶部工具栏
- `CommandPalette`：Cmd+K 全局搜索

## 关键目录
```
src/agenticops/
├── agents/          # 7 个 Strands Agent
├── tools/           # Agent 工具（AWS CLI、文件、KB 搜索等）
├── services/        # Pipeline 服务（auto-fix、RCA、通知、事件）
├── graph/           # 基础设施拓扑图引擎
├── skills/          # Skill 加载器、安全、执行、演化
├── kb/              # 知识库（向量存储、搜索、案例研究）
├── web/
│   ├── app.py       # FastAPI 后端（~70 端点）
│   └── frontend/src/
│       ├── pages/       # 10 个主页面
│       ├── components/  # UI 组件 + 布局
│       ├── hooks/       # 33 个 React Query hooks
│       ├── api/         # API 客户端 + 类型定义
│       ├── i18n/        # 国际化
│       ├── theme/       # 颜色主题
│       └── lib/         # 工具函数
├── models.py        # SQLAlchemy ORM 模型
└── config.py        # Pydantic Settings
```
