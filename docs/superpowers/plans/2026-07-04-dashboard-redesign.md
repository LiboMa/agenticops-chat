# Dashboard 2.0(服务状态 + 交互统计 + 活动流)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dashboard 重做为一屏五区块实时统计页:服务状态灯带、KPI、24h 交互统计(per-agent 横条)、agent 活动流(最近 10 条)、精简 Issues+Schedules;10s 统一轮询。

**Architecture:** 三个新展示组件(`components/dashboard/`)+ 一个新 hook(`useHealth`);`Dashboard.tsx` 重写为纯布局编排(~200 行);砍掉 Trends/ByType/FixPlans/RecentActivity 四区块。数据源全部现成端点,零后端改动。

**Tech Stack:** React 18 + TanStack Query(refetchInterval)、纯 CSS 横条(无图表库)、vitest、Playwright。

**Spec:** `docs/superpowers/specs/2026-07-04-dashboard-redesign-design.md`

## Global Constraints

- Branch:`MVP-2.0.1`。零新 npm 依赖、零新后端端点。
- 实时:统计四源(health/stats/summary/logs)`refetchInterval: 10_000`;Issues/Schedules 不加轮询。
- 失败降级:单区块失败显示 muted "—" 不阻塞;`/api/health` 请求失败 → 状态条整体红 "API unreachable"。
- AgentMetrics 页零改动;Feed 行点击 → `navigate("/app/agent-metrics")`(不带参)。
- 提交 `--no-verify`;**不 push**;结尾 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。
- 前端验证:`cd src/agenticops/web/frontend && npx tsc --noEmit`;最终 `npm run build` + vitest 全量。

---

### Task 1: agentShare 纯函数 + useHealth hook

**Files:**
- Create: `src/agenticops/web/frontend/src/lib/agentShare.ts`
- Create: `src/agenticops/web/frontend/src/hooks/useHealth.ts`
- Test: `src/agenticops/web/frontend/src/__tests__/agentShare.test.ts`

**Interfaces:**
- Consumes: `AgentLogSummary.per_agent`(types.ts:552,`Record<string, {calls, cost_usd?, ...}>`)。
- Produces: `agentShare(perAgent: Record<string, {calls: number}>): {name: string; calls: number; pct: number}[]`(按 calls 降序,pct 相对总 calls,0 总数 → 空数组);`useHealth()` → `useQuery<HealthData>`,10s 轮询。Task 2 依赖两者。

- [ ] **Step 1: 写失败测试**

创建 `src/agenticops/web/frontend/src/__tests__/agentShare.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { agentShare } from "@/lib/agentShare";

describe("agentShare", () => {
  it("empty input → empty array", () => {
    expect(agentShare({})).toEqual([]);
  });
  it("single agent → 100%", () => {
    expect(agentShare({ main: { calls: 5 } })).toEqual([{ name: "main", calls: 5, pct: 100 }]);
  });
  it("multi agents sorted desc, pcts sum ~100", () => {
    const out = agentShare({ main: { calls: 6 }, scan: { calls: 3 }, sre: { calls: 1 } });
    expect(out.map((o) => o.name)).toEqual(["main", "scan", "sre"]);
    expect(out[0].pct).toBe(60);
    expect(out.reduce((s, o) => s + o.pct, 0)).toBeCloseTo(100, 0);
  });
  it("zero total calls → empty array", () => {
    expect(agentShare({ main: { calls: 0 } })).toEqual([]);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd src/agenticops/web/frontend && npx vitest run src/__tests__/agentShare.test.ts 2>&1 | tail -3`
Expected: FAIL — Cannot find module `@/lib/agentShare`。

- [ ] **Step 3: 实现两个文件**

创建 `src/agenticops/web/frontend/src/lib/agentShare.ts`:

```typescript
/** per-agent 调用占比(按 calls 降序;总数 0 → 空)。 */
export function agentShare(
  perAgent: Record<string, { calls: number }>,
): { name: string; calls: number; pct: number }[] {
  const entries = Object.entries(perAgent).filter(([, v]) => v.calls > 0);
  const total = entries.reduce((s, [, v]) => s + v.calls, 0);
  if (total === 0) return [];
  return entries
    .map(([name, v]) => ({ name, calls: v.calls, pct: Math.round((v.calls / total) * 100) }))
    .sort((a, b) => b.calls - a.calls);
}
```

创建 `src/agenticops/web/frontend/src/hooks/useHealth.ts`:

```typescript
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";

export interface HealthCheck {
  status: string; // "ok" | "error" | "warning"
  latency_ms?: number | null;
  error?: string | null;
  details?: Record<string, unknown> | null;
}

export interface HealthData {
  status: string; // "healthy" | "degraded" | "unhealthy"
  version: string;
  timestamp: string;
  checks: Record<string, HealthCheck>;
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => apiFetch<HealthData>("/health"),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}
```

- [ ] **Step 4: 跑测试确认通过 + tsc**

Run: `cd src/agenticops/web/frontend && npx vitest run src/__tests__/agentShare.test.ts 2>&1 | grep "Tests " && npx tsc --noEmit 2>&1 | tail -1`
Expected: 4 passed;tsc 干净。

- [ ] **Step 5: Commit**

```bash
git add -f src/agenticops/web/frontend/src/lib/agentShare.ts
git add src/agenticops/web/frontend/src/hooks/useHealth.ts src/agenticops/web/frontend/src/__tests__/agentShare.test.ts
git commit --no-verify -m "feat(dashboard): agentShare pure fn + useHealth 10s polling hook

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

(注意根 .gitignore 的 `lib/` 规则——`src/lib/` 下新文件必须 `git add -f`,与 navOrder.ts 相同。)

---

### Task 2: 三个展示组件

**Files:**
- Create: `src/agenticops/web/frontend/src/components/dashboard/ServiceStatusBar.tsx`
- Create: `src/agenticops/web/frontend/src/components/dashboard/InteractionStats.tsx`
- Create: `src/agenticops/web/frontend/src/components/dashboard/AgentActivityFeed.tsx`
- Modify: `src/agenticops/web/frontend/src/locales/en.json`、`zh.json`

**Interfaces:**
- Consumes: Task 1 的 `useHealth`/`agentShare`;现有 `useExecutorStatus`、`useAgentLogSummary`(useAgentLogs.ts,签名 `useAgentLogSummary(hours: number)`)、`useAgentLogs({limit})`、`AgentLogEntry`(types.ts:505)。
- Produces: `<ServiceStatusBar />`、`<InteractionStats />`、`<AgentActivityFeed />` 自足组件(内部各自取数)。Task 3 只做摆放。

- [ ] **Step 1: ServiceStatusBar.tsx**

```tsx
import { useHealth } from "@/hooks/useHealth";
import { useExecutorStatus } from "@/hooks/useExecutorStatus";
import { useLocale } from "@/i18n/LocaleContext";

const DOT: Record<string, string> = {
  ok: "bg-green-500",
  warning: "bg-amber-400",
  error: "bg-red-500",
};

/** 服务状态灯带:/api/health 组件灯 + executor 状态,10s 轮询。 */
export function ServiceStatusBar() {
  const { t } = useLocale();
  const health = useHealth();
  const executor = useExecutorStatus();

  if (health.isError) {
    return (
      <div className="flex items-center gap-2 px-4 py-2.5 mb-6 bg-red-500/10 border border-red-500/20 rounded-lg text-sm text-red-500">
        <span className="w-2 h-2 rounded-full bg-red-500" />
        {t("dashboard.apiUnreachable")}
      </div>
    );
  }

  const checks = health.data?.checks ?? {};
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5 mb-6 bg-card border rounded-lg duo-fade">
      {Object.entries(checks).map(([name, c]) => (
        <span key={name} className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <span className={`w-2 h-2 rounded-full ${DOT[c.status] ?? "bg-muted-foreground/40"}`} />
          <span className="capitalize">{name}</span>
          {typeof c.latency_ms === "number" && (
            <span className="text-xs font-mono text-muted-foreground/60">{c.latency_ms}ms</span>
          )}
        </span>
      ))}
      {executor.data && (
        <>
          <span className="w-px h-3 bg-border" />
          <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <span className={`w-2 h-2 rounded-full ${executor.data.running ? "bg-primary duo-pulse" : "bg-muted-foreground/30"}`} />
            {t("dashboard.executor")} {executor.data.enabled ? t("common.on") : t("common.off")}
            <span className="font-mono text-foreground ml-1">{executor.data.active_executions}</span>
          </span>
        </>
      )}
      {health.data && (
        <span className="ml-auto text-[10px] font-mono text-muted-foreground/50">v{health.data.version}</span>
      )}
    </div>
  );
}
```

- [ ] **Step 2: InteractionStats.tsx**

```tsx
import { useAgentLogSummary } from "@/hooks/useAgentLogs";
import { agentShare } from "@/lib/agentShare";
import { useLocale } from "@/i18n/LocaleContext";

const BAR_COLORS = ["bg-primary-600", "bg-primary-400", "bg-primary-300", "bg-primary-200", "bg-primary-100"];

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

/** 24h 交互统计:聚合行 + per-agent CSS 横条。 */
export function InteractionStats() {
  const { t } = useLocale();
  const summary = useAgentLogSummary(24);

  const per = summary.data?.per_agent ?? {};
  const rows = Object.values(per) as Array<{ calls: number; input_tokens: number; output_tokens: number; errors: number; cost_usd?: number }>;
  const totals = rows.reduce(
    (a, v) => ({
      calls: a.calls + v.calls,
      input: a.input + v.input_tokens,
      output: a.output + v.output_tokens,
      errors: a.errors + v.errors,
      cost: a.cost + (v.cost_usd ?? 0),
    }),
    { calls: 0, input: 0, output: 0, errors: 0, cost: 0 },
  );
  const shares = agentShare(per);

  return (
    <div className="mb-8 duo-fade">
      <div className="text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground mb-3">
        {t("dashboard.interactions")}
      </div>
      <div className="bg-card border rounded-lg px-5 py-4">
        {summary.isError || totals.calls === 0 ? (
          <div className="text-sm text-muted-foreground">—</div>
        ) : (
          <>
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 mb-3 text-sm">
              <span className="font-mono text-2xl font-light">{totals.calls}</span>
              <span className="text-muted-foreground">{t("dashboard.calls24h")}</span>
              <span className="font-mono text-muted-foreground">↑{fmtTokens(totals.input)} ↓{fmtTokens(totals.output)}</span>
              <span className="font-mono text-foreground">${totals.cost.toFixed(2)}</span>
              {totals.errors > 0 && (
                <span className="text-red-500 text-xs">{totals.errors} {t("dashboard.errors")}</span>
              )}
            </div>
            <div className="space-y-1.5">
              {shares.slice(0, 5).map((s, i) => (
                <div key={s.name} className="flex items-center gap-2 text-xs">
                  <span className="w-16 text-muted-foreground truncate">{s.name}</span>
                  <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                    <div className={`h-full rounded-full ${BAR_COLORS[i] ?? "bg-primary-100"}`} style={{ width: `${s.pct}%` }} />
                  </div>
                  <span className="w-14 text-right font-mono text-muted-foreground">{s.calls} · {s.pct}%</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: AgentActivityFeed.tsx**

```tsx
import { useNavigate } from "react-router-dom";
import { useAgentLogs } from "@/hooks/useAgentLogs";
import { formatShortDate } from "@/lib/formatDate";
import { useLocale } from "@/i18n/LocaleContext";

/** 最近 10 条 agent 调用流;点击行 → AgentMetrics 页。 */
export function AgentActivityFeed() {
  const { t } = useLocale();
  const navigate = useNavigate();
  const logs = useAgentLogs({ limit: 10 });

  return (
    <div className="duo-fade">
      <div className="text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground mb-3">
        {t("dashboard.activityFeed")}
      </div>
      {logs.data && logs.data.length > 0 ? (
        <div className="bg-card border rounded-lg overflow-hidden divide-y divide-border/50">
          {logs.data.map((e) => (
            <div
              key={e.id}
              onClick={() => navigate("/app/agent-metrics")}
              className="flex items-center gap-3 px-4 py-2 cursor-pointer hover:bg-accent transition-colors"
            >
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${e.status === "success" ? "bg-green-500" : "bg-red-500"}`} />
              <span className="text-xs font-medium text-foreground w-16 truncate">{e.agent_name}</span>
              <span className="text-xs text-muted-foreground flex-1 truncate">{e.action}</span>
              <span className="text-[10px] font-mono text-muted-foreground/60 whitespace-nowrap">
                {(e.duration_ms / 1000).toFixed(1)}s
              </span>
              <span className="text-[10px] text-muted-foreground/60 whitespace-nowrap hidden sm:inline">
                {formatShortDate(e.created_at)}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div className="border border-dashed rounded-lg py-12 text-center text-sm text-muted-foreground">
          {t("common.noData")}
        </div>
      )}
    </div>
  );
}
```

(已验证:`AgentLogEntry.created_at: string` 存在于 types.ts:521,上面代码直接可用。)

- [ ] **Step 4: i18n(dashboard.* 块内追加,en/zh)**

en.json:

```json
  "dashboard.serviceStatus": "Service Status",
  "dashboard.apiUnreachable": "API unreachable",
  "dashboard.interactions": "Interactions (24h)",
  "dashboard.calls24h": "agent calls",
  "dashboard.errors": "errors",
  "dashboard.activityFeed": "Agent Activity",
```

zh.json:

```json
  "dashboard.serviceStatus": "服务状态",
  "dashboard.apiUnreachable": "API 不可达",
  "dashboard.interactions": "交互统计(24h)",
  "dashboard.calls24h": "次 agent 调用",
  "dashboard.errors": "错误",
  "dashboard.activityFeed": "Agent 活动",
```

- [ ] **Step 5: tsc + Commit**

Run: `cd src/agenticops/web/frontend && npx tsc --noEmit 2>&1 | tail -2`
Expected: 干净(组件尚未被引用,tsc 仍会检查)。

```bash
git add src/agenticops/web/frontend/src
git commit --no-verify -m "feat(dashboard): ServiceStatusBar + InteractionStats + AgentActivityFeed components

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Dashboard.tsx 重写(布局编排)

**Files:**
- Modify: `src/agenticops/web/frontend/src/pages/Dashboard.tsx`(456 行全量重写为 ~200 行)

**Interfaces:**
- Consumes: Task 2 三组件;现有 `useStats`/`useAnomalies`/`useSchedules`/`SEV_DOT`/`CLOSED_STATUSES` 逻辑(KPI 行与 Issues 表、Schedules 卡从旧文件保留)。
- Produces: 新五区块布局;`useStats` 加 `refetchInterval: 10_000`(在 hooks/useStats.ts 已有 60_000 → 收敛为 10_000)。

- [ ] **Step 1: useStats 轮询收敛**

`src/agenticops/web/frontend/src/hooks/useStats.ts` 的 `refetchInterval: 60_000` 改为 `refetchInterval: 10_000`。

- [ ] **Step 2: Dashboard.tsx 全量重写**

保留:import 中的 useStats/useAnomalies/useSchedules/Spinner/ErrorBanner/formatShortDate/useNavigate/useLocale、`SEV_DOT`、`CLOSED_STATUSES`、KPI 行 JSX(:78-104 原样)、Open Issues 表 JSX(:190-240 原样,含 SeverityDot/行点击 navigate)、Scheduled Jobs 卡 JSX(:361-400 原样)。

删除:useResourceTypeCounts/useFixPlans/useAuditLog/useDashboardTrends/useExecutorStatus(挪进 ServiceStatusBar)及其区块 JSX、RiskLevelBadge/FixPlanStatusBadge import、trendDays state。

新结构:

```tsx
import { useStats } from "@/hooks/useStats";
import { useAnomalies } from "@/hooks/useAnomalies";
import { useSchedules } from "@/hooks/useSchedules";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { ServiceStatusBar } from "@/components/dashboard/ServiceStatusBar";
import { InteractionStats } from "@/components/dashboard/InteractionStats";
import { AgentActivityFeed } from "@/components/dashboard/AgentActivityFeed";
import { formatShortDate } from "@/lib/formatDate";
import { useNavigate } from "react-router-dom";
import { useMemo } from "react";
import { useLocale } from "@/i18n/LocaleContext";

const SEV_DOT: Record<string, string> = {
  critical: "bg-red-500",
  high: "bg-orange-500",
  medium: "bg-amber-400",
  low: "bg-blue-500 dark:bg-green-500",
};

const CLOSED_STATUSES = new Set(["resolved", "dismissed"]);

export default function Dashboard() {
  const { t } = useLocale();
  const stats = useStats();
  const anomalies = useAnomalies();
  const schedules = useSchedules();
  const navigate = useNavigate();

  const activeSchedules = useMemo(
    () => (schedules.data ?? []).filter((s) => s.is_enabled),
    [schedules.data],
  );

  if (stats.isLoading) return <Spinner label={t("common.loading")} />;
  if (stats.error)
    return <ErrorBanner message={stats.error.message} onRetry={() => stats.refetch()} />;

  const s = stats.data!;
  const kpis = [
    { label: t("dashboard.resources"), value: s.total_resources, hot: false, link: "/app/issues?view=resources" },
    { label: t("dashboard.openIssues"), value: s.open_anomalies, hot: s.open_anomalies > 0 },
    { label: t("dashboard.critical"), value: s.critical_anomalies, hot: s.critical_anomalies > 0 },
    { label: t("dashboard.accounts"), value: s.total_accounts, hot: false },
  ];

  return (
    <div>
      {/* 1. Service status bar */}
      <ServiceStatusBar />

      {/* 2. KPI strip — 保留原 :88-104 的 JSX 原样贴入 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {kpis.map((k, i) => (
          <div
            key={k.label}
            className={`bg-card border rounded-lg px-5 py-4 duo-fade${k.link ? " cursor-pointer hover:border-primary/50 transition-colors" : ""}`}
            style={{ animationDelay: `${i * 70}ms` }}
            onClick={k.link ? () => navigate(k.link!) : undefined}
          >
            <div className="text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground mb-1.5">
              {k.label}
            </div>
            <div className={`text-3xl font-light tracking-tight font-mono ${k.hot ? "text-primary" : ""}`}>
              {k.value}
            </div>
          </div>
        ))}
      </div>

      {/* 3. Interaction stats */}
      <InteractionStats />

      {/* 4+5. Activity feed | Issues + Schedules */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <AgentActivityFeed />
        <div className="space-y-6">
          {/* Open Issues — 原 :190-240 的表格 JSX 原样贴入(slice(0, 5)) */}
          {/* Scheduled Jobs — 原 :361-400 的卡片 JSX 原样贴入 */}
        </div>
      </div>
    </div>
  );
}
```

(标注"原样贴入"的两处:从旧文件复制对应 JSX 块,Issues 表 `slice(0, 8)` 改 `slice(0, 5)`;执行者从 git 历史 `git show HEAD:src/agenticops/web/frontend/src/pages/Dashboard.tsx` 取原文。)

- [ ] **Step 3: tsc + vitest 全量**

Run: `cd src/agenticops/web/frontend && npx tsc --noEmit && npx vitest run 2>&1 | grep -E "Test Files|Tests "`
Expected: tsc 干净;全 passed(navOrder 7 + agentShare 4 + 既有)。

- [ ] **Step 4: Commit**

```bash
git add src/agenticops/web/frontend/src
git commit --no-verify -m "feat(dashboard): rewrite as 5-block realtime stats page

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: build + live E2E → STOP 等 owner

**Files:** 无新增。

- [ ] **Step 1: build**

Run: `cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build 2>&1 | tail -3`
Expected: 干净。

- [ ] **Step 2: live E2E(Playwright,重启 server)**

```bash
pkill -f "uvicorn agenticops" 2>/dev/null; sleep 1
nohup .venv/bin/uvicorn agenticops.web.app:app --host 0.0.0.0 --port 8000 > /tmp/aiops-e2e.log 2>&1 &
sleep 6
```

浏览器验证 `http://localhost:8000/app`:
1. 服务状态条:database/aws/disk 灯 + latency + Executor 状态 + 版本号。
2. KPI 四格照旧。
3. 交互统计:非零 calls、↑↓ tokens、$ 成本、per-agent 横条(main 最长)。
4. Agent 活动流:10 条,点击一行 → 跳 AgentMetrics。
5. Issues 前 5 条 + Schedules 保留;**Trends/Resources by Type/Active Fix Plans/Recent Activity 四区块消失**。
6. 等 ~12s 观察 Network:health/stats/summary/agent-logs 均有第二次请求(10s 轮询生效)。

- [ ] **Step 3: STOP — 汇报 owner**

汇报 E2E 截图、提交清单。**不 push** —— owner 确认后决定(A/B/C 已推,D 是增量)。
