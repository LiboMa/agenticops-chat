# Dashboard 2.0 — 统计页重设计 — Design Spec

> Status: approved design (brainstorm 2026-07-04) · Branch: `MVP-2.0.1`
> Sub-project D(统计页):simpler、real-time、interaction stats、agent logs、schedules、service status。

## 1. 用户确认的决策

| 决策 | 选择 |
|---|---|
| 页面归属 | **重做 Dashboard**(Dashboard 即统计页;AgentMetrics 不动) |
| 实时机制 | **统一轮询 10s**(四数据源 `refetchInterval: 10_000`,页面不可见自动暂停;不做 SSE,YAGNI) |
| 日志形态 | **精简流 + 链到详情**(最近 10 条一行一条,点击跳 AgentMetrics trace) |

## 2. 布局(六区块 → 五区块,一屏)

```
┌─ ServiceStatusBar(新) ──────────────────────────────────────┐
│ ● DB 3ms  ● AWS ok  ● Disk 52%  │  Executor On · 0 active   │
├─ KPI 行(保留) ───────────────────────────────────────────────┤
│ Resources │ Open Issues │ Critical │ Accounts                │
├─ InteractionStats(新,替换 Trends) ───────────────────────────┤
│ 24h: 47 calls · ↑1.2M ↓89K tok · $12.40 · 2 errors          │
│ per-agent 横条(main/scan/sre/…,CSS 宽度百分比)                │
├─ AgentActivityFeed(新) ─────────┬─ Issues + Schedules(精简) ─┤
│ 最近10条: 时间 agent·action 耗时 $ │ open issues 前5 + badge    │
│ 点击行 → AgentMetrics trace 详情  │ schedules 下次执行           │
└─────────────────────────────────┴────────────────────────────┘
```

**砍掉**:Trends 卡(7/30/90d)、Resources by Type 格子(Resources 页已有)、Active Fix Plans 卡、Recent Activity(audit log,被 AgentActivityFeed 替代)。Dashboard.tsx 456 → ~200 行(只做布局编排)。

## 3. 数据源(全部现成,零新后端)

| 区块 | 端点 | Hook |
|---|---|---|
| ServiceStatusBar | `GET /api/health`(checks: database/aws/disk + status/version)+ 现有 `useExecutorStatus` | 新 `useHealth`(10s) |
| KPI | `GET /api/stats` | 现有 `useStats`(refetchInterval 收敛为 10s) |
| InteractionStats | `GET /api/agent-logs/summary?hours=24`(per_agent: call_count/tokens/cost/error_count)+ `GET /api/cost/summary` | 新 `useAgentLogSummary`(10s) |
| AgentActivityFeed | `GET /api/agent-logs?limit=10` | 新/复用 `useAgentLogs`(10s) |
| Issues/Schedules | 现有 `useAnomalies`/`useSchedules` | 现有(不加轮询,staleTime 已够) |

## 4. 组件结构

```
pages/Dashboard.tsx              → 重写为布局编排(~200 行)
components/dashboard/            (新目录)
  ServiceStatusBar.tsx           灯带:每组件 status 点(ok=green/error=red)+ latency;整体不可达 → 红条 "API unreachable"
  InteractionStats.tsx           聚合行 + per-agent 横条;百分比计算抽纯函数 agentShare(summary) 便于 vitest
  AgentActivityFeed.tsx          10 行日志流;行点击 → navigate(`/app/agent-metrics?trace=${trace_id}`)(AgentMetrics 已支持 trace 查询参数则复用;否则仅跳页)
```

- 横条用纯 CSS 宽度百分比(`style={{width: pct+"%"}}` + primary 色阶),**不引图表库**。
- i18n:~8 个新 flat 键(dashboard.serviceStatus、dashboard.interactions、dashboard.activityFeed 等,en/zh)。

## 5. 实时策略

- 四个统计 hook `refetchInterval: 10_000`;TanStack 默认 `refetchIntervalInBackground: false`,标签页不可见自动停。
- 失败降级:单区块失败显示 muted "—",不阻塞其他区块;`/api/health` 请求本身失败 → 状态条整体红 "API unreachable"。

## 6. 测试

- vitest:`agentShare` 纯函数(空 summary/单 agent/多 agent 百分比和=100)。
- `npx tsc --noEmit` + `npm run build`。
- Playwright E2E:五区块渲染;服务状态灯全绿;交互统计有非零 calls;日志流 10 条且点击跳转;砍掉的区块(Trends/ByType/FixPlans)不再出现。

## 7. 不做(YAGNI)

- SSE / WebSocket
- 图表库引入 Dashboard(AgentMetrics 的 Recharts 不动)
- Trends 保留开关、自定义时间窗
- AgentMetrics 页任何改动
- 服务状态历史记录/告警

## 8. Brainstorm 留档

侦察:Dashboard 456 行 6 区块(stats/trends/byType/issues/fixplans/activity/schedules)、AgentMetrics 558 行;hooks 全靠 staleTime 15-60s,仅 useStats 有 60s 轮询;`/api/health` 返回 database/aws/disk 三组件 checks;`/api/agent-logs/summary` per-agent 聚合现成;`/api/cost/summary` 现成。三决策(重做 Dashboard/统一轮询 10s/精简日志流)经 AskUserQuestion 确认,布局设计经用户"继续"批准。
