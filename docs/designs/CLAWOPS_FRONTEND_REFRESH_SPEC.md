# ClawOps Frontend Refresh Spec v1.0

> **Author**: Architect  
> **Date**: 2026-03-10  
> **Status**: DRAFT  
> **Priority**: P0 (Ma Ronnie directive)

## 1. 现状分析

### 1.1 技术栈
- React 18 + Vite 6 + TypeScript 5.6
- **Tailwind CSS** (保留，不引入 Antd/MUI)
- TanStack Query (数据层)
- ReactFlow / xyflow (拓扑图)
- 无 UI 组件库 — 全部手写 Tailwind 组件

### 1.2 现有页面 (18 pages, 5,243 LOC)
| 页面 | LOC | 功能 |
|------|-----|------|
| Dashboard | 197 | 概览 |
| Anomalies | 144 | 异常列表 |
| AnomalyDetail | 571 | 异常详情 + RCA |
| KnowledgeBase | 547 | 知识库搜索 |
| Network | 489 | 网络拓扑 |
| FixPlans | 138 | 修复计划 |
| FixPlanDetail | 510 | 修复详情 |
| Notifications | 498 | 通知配置 |
| NotificationLogs | 150 | 通知日志 |
| Schedules | 343 | 定时扫描 |
| ScheduleDetail | 182 | 定时详情 |
| Settings | 426 | 系统设置 |
| Accounts | 358 | AWS 账户 |
| Resources | 133 | 资源列表 |
| Reports | 112 | 报告列表 |
| ReportDetail | 243 | 报告详情 |
| AuditLog | 141 | 审计日志 |
| Chat | 61 | 对话界面 |

### 1.3 后端 API
- **137 个 API 端点** (120 in app.py + 17 graph API)
- 前端已对接: ~60% (基础 CRUD)
- **今天新增模块 0% 对接** — Memory / Deep RCA / Proactive / @secure_tool / SOP

### 1.4 核心问题
1. 18 个页面太多，导航混乱
2. 今日新增 6 个核心模块无前端界面
3. Dashboard 只有基础统计，缺乏运维洞察
4. Chat 页面功能薄弱 (61 LOC)

## 2. 设计目标

> **Ma Ronnie**: "Frontend 像 Apple 产品 — 简约、克制、功能 Solid"

### 2.1 原则
- **Less is More**: 减少页面数量，增加信息密度
- **Data-Driven**: 每个组件都由真实数据驱动
- **L5 可视化**: 让 Memory / Prediction / Self-improvement 可观测

### 2.2 目标架构: 5 视图

```
┌─────────────────────────────────────────────┐
│  Sidebar                                     │
│  ┌───────┐                                   │
│  │ 🏠 Hub │  ← 运维中心 (Dashboard + Alerts)  │
│  │ 🔍 RCA │  ← 诊断中心 (Anomaly + Deep RCA)  │
│  │ 🧠 AI  │  ← 智能中心 (Memory + Proactive)  │
│  │ 📚 KB  │  ← 知识中心 (KB + SOP + Skills)   │
│  │ ⚙️ Sys │  ← 系统管理 (Settings + Accounts) │
│  └───────┘                                   │
└─────────────────────────────────────────────┘
```

## 3. 视图设计

### 3.1 🏠 OpsHub (运维中心) — `/`
合并: Dashboard + Anomalies + Notifications

**布局**: 
```
┌──────────────────────────────────────────┐
│  Summary Cards (4)                        │
│  [Active Alerts] [Open RCA] [Memory] [SOP]│
├──────────────┬───────────────────────────┤
│  Alert Feed  │  Quick Actions             │
│  (realtime)  │  • Trigger Scan            │
│              │  • View Proactive Alerts    │
│              │  • Recent RCA              │
├──────────────┴───────────────────────────┤
│  Timeline (last 24h anomalies + alerts)   │
└──────────────────────────────────────────┘
```

**新增 API 对接**:
- `GET /api/memory/stats` — Agent memory 统计
- `GET /api/proactive/alerts` — 预测告警列表
- `GET /api/sop/drafts` — 待审 SOP 列表

### 3.2 🔍 Diagnose (诊断中心) — `/diagnose`
合并: AnomalyDetail + FixPlans + FixPlanDetail

**布局**:
```
┌────────────────────────────────────────────┐
│  Anomaly List (left panel, collapsible)     │
├────────────────────────────────────────────┤
│  RCA Detail                                 │
│  ┌────────────────────────────────────┐    │
│  │  Evidence Chain (8-level hierarchy) │    │
│  │  CloudTrail > Traces > Metrics > ...│    │
│  ├────────────────────────────────────┤    │
│  │  Deep RCA Flow (7-step visual)      │    │
│  │  Memory→Graph→KB→LLM→Verify→WAL    │    │
│  ├────────────────────────────────────┤    │
│  │  Fix Plan + Execution History       │    │
│  └────────────────────────────────────┘    │
└────────────────────────────────────────────┘
```

**新增 API 对接**:
- `GET /api/rca/{id}/deep` — Deep RCA 结果 (7-step)
- `GET /api/rca/{id}/evidence` — Evidence chain with weights
- `GET /api/rca/{id}/iterations` — Self-verify iteration log

### 3.3 🧠 AI Center (智能中心) — `/ai`
**全新页面** — 展示 L5 自主能力

**布局**:
```
┌────────────────────────────────────────────┐
│  Agent Memory Dashboard                     │
│  ┌──────────┬──────────┬──────────┐        │
│  │ Episodic │Procedural│Reflection│        │
│  │   142    │    38    │    12    │        │
│  └──────────┴──────────┴──────────┘        │
├────────────────────────────────────────────┤
│  Proactive Predictions                      │
│  [Pattern] [Confidence] [Action] [Time]    │
│  OOM-pod    0.87/ESC    RCA-123  2m ago    │
│  CPU-spike  0.42/NOTIFY  —       15m ago   │
├────────────────────────────────────────────┤
│  Learning Timeline                          │
│  • Learned: "OOM → scale memory limit"     │
│  • Created: Skill "k8s-oom-handler"        │
│  • Generated: SOP "high-cpu-rds.md"        │
└────────────────────────────────────────────┘
```

**新增后端 API (需 Developer 创建)**:
```python
# Memory APIs
GET  /api/memory/agents                  # 各 agent 记忆统计
GET  /api/memory/{agent}/entries         # 查询记忆条目
GET  /api/memory/{agent}/reflections     # 反思日志

# Proactive APIs  
GET  /api/proactive/alerts               # 预测告警列表
GET  /api/proactive/patterns             # 检测到的 patterns
GET  /api/proactive/stats                # 预测统计 (hit rate)

# Learning APIs
GET  /api/learning/timeline              # 学习时间线
GET  /api/learning/skills                # 自动创建的 skills
GET  /api/learning/sops                  # 自动生成的 SOPs
```

### 3.4 📚 Knowledge (知识中心) — `/knowledge`
合并: KnowledgeBase + SOP 管理

**布局**:
```
┌──────────────────────────────────────────┐
│  Tabs: [KB Search] [SOPs] [Skills]        │
├──────────────────────────────────────────┤
│  KB Search (现有)                         │
│  ─ 或 ─                                  │
│  SOP 列表 (新增: auto-generated SOPs)     │
│  [Status: draft/active/stable]            │
│  [Trigger: new_pattern/better_fix/esc]    │
│  ─ 或 ─                                  │
│  Skill Gap Report (自动检测的技能缺口)    │
└──────────────────────────────────────────┘
```

### 3.5 ⚙️ System (系统管理) — `/system`
合并: Settings + Accounts + Schedules + AuditLog

保留现有功能，新增:
- **@secure_tool Dashboard**: T0-T3 统计，审批队列 (T2/T3)
- **WAL Log Viewer**: Write-Ahead Log 查看

## 4. 后端 API 新增清单

Developer 需要新增 **12 个 API 端点**:

| # | Method | Path | 模块 | 优先级 |
|---|--------|------|------|--------|
| 1 | GET | `/api/memory/agents` | Memory | P0 |
| 2 | GET | `/api/memory/{agent}/entries` | Memory | P0 |
| 3 | GET | `/api/memory/{agent}/reflections` | Memory | P1 |
| 4 | GET | `/api/proactive/alerts` | Proactive | P0 |
| 5 | GET | `/api/proactive/patterns` | Proactive | P1 |
| 6 | GET | `/api/proactive/stats` | Proactive | P2 |
| 7 | GET | `/api/rca/{id}/deep` | Deep RCA | P0 |
| 8 | GET | `/api/rca/{id}/evidence` | Evidence | P0 |
| 9 | GET | `/api/rca/{id}/iterations` | Deep RCA | P1 |
| 10 | GET | `/api/learning/timeline` | Learning | P1 |
| 11 | GET | `/api/learning/skills` | SkillGap | P1 |
| 12 | GET | `/api/learning/sops` | SOP | P1 |

## 5. 页面精简计划

### 5.1 删除 (合并到新视图)
- `NotificationLogs.tsx` → OpsHub timeline
- `ScheduleDetail.tsx` → System 内联展开
- `ReportDetail.tsx` → Modal/Drawer in Reports

### 5.2 重构 (保留但移入新视图)
- `Dashboard.tsx` → OpsHub
- `AnomalyDetail.tsx` → Diagnose  
- `KnowledgeBase.tsx` → Knowledge
- `Settings.tsx` → System

### 5.3 新增
- `AICenter.tsx` — 全新，展示 Memory + Proactive + Learning + Agent Console
- `AgentConsole.tsx` — 现有 Chat.tsx 升级，合并为 AI Center 的 tab
- 更新 `Sidebar.tsx` — 5 视图导航

### 5.4 Researcher 建议 (已采纳)
1. **Learning Timeline 数据源**: Developer 在 SkillGapDetector + SOPAutoWriter 加 `event_log` 表 (timestamp + type + detail)，作为 `/api/learning/timeline` 数据源
2. **Chat → Agent Console**: Chat.tsx 合并到 AI Center 作为 "Agent Console" tab，和 Agent 对话是核心交互

### 5.4 预期结果
| 指标 | Before | After |
|------|--------|-------|
| 页面数 | 18 | ~10 (-44%) |
| 视图 | 18 散装 | 5 结构化 |
| 新模块覆盖 | 0% | 100% |
| API 对接 | ~60% | ~85% |

## 6. 实施顺序

**Phase 1 (P0, ~2h)**: Sidebar + OpsHub + API routes
- 新 Sidebar (5 视图导航)
- OpsHub 基础版 (Summary Cards + Alert Feed)
- 4 个 P0 API endpoints

**Phase 2 (P0, ~2h)**: Diagnose + AI Center
- Diagnose 视图 (Deep RCA 可视化)
- AI Center 基础版 (Memory stats + Proactive alerts)

**Phase 3 (P1, ~1.5h)**: Knowledge + System + Polish
- Knowledge 3-tab 视图
- System 合并
- 页面精简 (删除冗余)

**Total**: ~5.5h 估算

## 7. 技术约束

1. **保留 Tailwind CSS** — 不引入新 UI 框架
2. **保留 TanStack Query** — 数据获取层已有，直接复用
3. **保留 ReactFlow** — 拓扑图保留在 Network 或 Diagnose
4. **TypeScript strict** — 所有新组件 TypeScript
5. **响应式** — 最小宽度 1024px (运维终端)

## 8. 设计风格

> Apple 风格: 大量留白 + 清晰层次 + 深色主题

- 深色背景 (`bg-gray-900`)
- 卡片式布局 (`bg-gray-800 rounded-xl shadow-lg`)
- 数据高亮用品牌色 (蓝/绿/橙)
- 状态色: 红=critical, 橙=warning, 绿=healthy, 蓝=info
- 字体: System UI (SF Pro 风格)
- 动画: 过渡 150ms ease-in-out (克制)
