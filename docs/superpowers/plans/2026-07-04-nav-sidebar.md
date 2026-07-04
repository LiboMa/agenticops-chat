# Nav Sidebar 2.0(拖拽排序 + 展开/收起 + hover 预览)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 侧边导航支持展开(200px 图标+文字)/收起(52px 纯图标)切换、展开态拖拽排序(localStorage 持久化)、hover 预览卡片(页面名+实时数据摘要)。

**Architecture:** `IconSidebar.tsx` 拆为壳 + `NavItems.tsx`(排序 state + 原生 HTML5 DnD)+ `NavPreviewCard.tsx`(Tooltip 内容升级);排序算法 `reorderNavIds` 为纯函数(交集+append 自愈);展开态通过 `usePersistedState` 共享给 `AppShell`(内容区 padding 联动)。零新依赖、零新后端。

**Tech Stack:** React 18、Radix Tooltip(已有)、原生 HTML5 DnD、usePersistedState(已有)、vitest、Playwright。

**Spec:** `docs/superpowers/specs/2026-07-04-nav-sidebar-design.md`

## Global Constraints

- Branch:`MVP-2.0.1`。零新 npm 依赖(**禁止 dnd-kit**)。零新后端端点。
- localStorage 键:`aiops-nav-order`(string[] of nav ids)、`aiops-nav-expanded`(boolean,默认 false)。
- 拖拽仅展开态启用;Settings 固定底部不参与排序。
- 预览卡片数据**只读现有缓存**(useStats 已在 sidebar 订阅;其余用 `queryClient.getQueryData`),hover 绝不触发新请求;缓存为空只显示页面名。
- 提交 `--no-verify`;**不 push**;提交结尾 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。
- 前端验证:`cd src/agenticops/web/frontend && npx tsc --noEmit`;最终任务 `npm run build` + vitest。

---

### Task 1: 排序纯函数 + vitest

**Files:**
- Create: `src/agenticops/web/frontend/src/lib/navOrder.ts`
- Test: `src/agenticops/web/frontend/src/__tests__/navOrder.test.ts`

**Interfaces:**
- Produces: `reorderNavIds(stored: string[], current: string[]): string[]`(交集+append 自愈);`moveId(order: string[], sourceId: string, targetId: string): string[]`(把 source 移到 target 位置前)。Task 2 依赖。

- [ ] **Step 1: 写失败测试**

创建 `src/agenticops/web/frontend/src/__tests__/navOrder.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { reorderNavIds, moveId } from "@/lib/navOrder";

describe("reorderNavIds", () => {
  it("keeps stored order for known ids", () => {
    expect(reorderNavIds(["b", "a"], ["a", "b"])).toEqual(["b", "a"]);
  });
  it("drops ids no longer current", () => {
    expect(reorderNavIds(["x", "a"], ["a"])).toEqual(["a"]);
  });
  it("appends new current ids at the end", () => {
    expect(reorderNavIds(["b", "a"], ["a", "b", "c"])).toEqual(["b", "a", "c"]);
  });
  it("empty stored → current as-is", () => {
    expect(reorderNavIds([], ["a", "b"])).toEqual(["a", "b"]);
  });
});

describe("moveId", () => {
  it("moves source before target", () => {
    expect(moveId(["a", "b", "c"], "c", "a")).toEqual(["c", "a", "b"]);
  });
  it("no-op when source === target", () => {
    expect(moveId(["a", "b"], "a", "a")).toEqual(["a", "b"]);
  });
  it("unknown ids → unchanged", () => {
    expect(moveId(["a", "b"], "x", "a")).toEqual(["a", "b"]);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd src/agenticops/web/frontend && npx vitest run src/__tests__/navOrder.test.ts 2>&1 | tail -3`
Expected: FAIL — Cannot find module `@/lib/navOrder`。

- [ ] **Step 3: 实现**

创建 `src/agenticops/web/frontend/src/lib/navOrder.ts`:

```typescript
/** Nav 排序自愈:stored ∩ current 保序,current 新增项 append(版本升级安全)。 */
export function reorderNavIds(stored: string[], current: string[]): string[] {
  const currentSet = new Set(current);
  const kept = stored.filter((id) => currentSet.has(id));
  const keptSet = new Set(kept);
  return [...kept, ...current.filter((id) => !keptSet.has(id))];
}

/** 把 sourceId 移到 targetId 之前;任一 id 不存在或相同则原样返回。 */
export function moveId(order: string[], sourceId: string, targetId: string): string[] {
  if (sourceId === targetId) return order;
  const si = order.indexOf(sourceId);
  const ti = order.indexOf(targetId);
  if (si === -1 || ti === -1) return order;
  const next = order.filter((id) => id !== sourceId);
  next.splice(next.indexOf(targetId), 0, sourceId);
  return next;
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd src/agenticops/web/frontend && npx vitest run src/__tests__/navOrder.test.ts 2>&1 | tail -3`
Expected: 7 passed。

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/web/frontend/src/lib/navOrder.ts src/agenticops/web/frontend/src/__tests__/navOrder.test.ts
git commit --no-verify -m "feat(nav): self-healing nav order pure functions

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: NavItems 组件(排序 + DnD)+ NavPreviewCard + IconSidebar 壳重构

**Files:**
- Create: `src/agenticops/web/frontend/src/components/layout/NavItems.tsx`
- Create: `src/agenticops/web/frontend/src/components/layout/NavPreviewCard.tsx`
- Modify: `src/agenticops/web/frontend/src/components/layout/IconSidebar.tsx`(全量重写,117 行 → 壳)
- Modify: `src/agenticops/web/frontend/src/locales/en.json`、`zh.json`

**Interfaces:**
- Consumes: Task 1 的 `reorderNavIds`/`moveId`;现有 `usePersistedState`、`useStats`、`useChatSessions`、Radix Tooltip。
- Produces: `<NavItems expanded={boolean} />`;`<NavPreviewCard id={string} labelKey={string} />`;`IconSidebar` 导出不变(AppShell 无需改 import)。NAV_ITEMS 各项新增 `id: string` 字段(dashboard/chat/issues/schedules/reports/agent-metrics/skills)。

- [ ] **Step 1: NavPreviewCard.tsx**

```tsx
import { useQueryClient } from "@tanstack/react-query";
import { useStats } from "@/hooks/useStats";
import { useLocale } from "@/i18n/LocaleContext";
import type { ChatSession } from "@/api/types";

/** hover 预览卡片:页面名 + 一行实时摘要。数据只读现有缓存,绝不发新请求。 */
export function NavPreviewCard({ id, labelKey }: { id: string; labelKey: string }) {
  const { t } = useLocale();
  const qc = useQueryClient();
  const stats = useStats(); // sidebar 本就订阅(badge),非新请求

  let summary = "";
  if (id === "dashboard" && stats.data) {
    summary = `${stats.data.total_resources} resources · ${stats.data.total_accounts} accounts`;
  } else if (id === "issues" && stats.data) {
    summary = `${stats.data.open_anomalies} open · ${stats.data.critical_anomalies} critical`;
  } else if (id === "chat") {
    const sessions = qc.getQueryData<ChatSession[]>(["chat-sessions"]);
    if (sessions) summary = `${sessions.length} sessions`;
  } else if (id === "schedules") {
    const rows = qc.getQueryData<unknown[]>(["schedules"]);
    if (Array.isArray(rows)) summary = `${rows.length} jobs`;
  } else if (id === "reports") {
    const rows = qc.getQueryData<unknown[]>(["reports"]);
    if (Array.isArray(rows)) summary = `${rows.length} reports`;
  } else if (id === "skills") {
    const rows = qc.getQueryData<unknown[]>(["skills"]);
    if (Array.isArray(rows)) summary = `${rows.length} skills`;
  }

  return (
    <div className="w-44">
      <div className="text-xs font-medium text-foreground">{t(labelKey)}</div>
      {summary && <div className="text-[11px] text-muted-foreground mt-0.5">{summary}</div>}
    </div>
  );
}
```

(agent-metrics 无稳定 list 缓存 → 走默认"只显示页面名"分支,不特判。)

- [ ] **Step 2: NavItems.tsx(核心:排序 + 原生 DnD + 两种渲染态)**

```tsx
import { useState } from "react";
import { NavLink } from "react-router-dom";
import * as Tooltip from "@radix-ui/react-tooltip";
import { usePersistedState } from "@/hooks/usePersistedState";
import { useStats } from "@/hooks/useStats";
import { useLocale } from "@/i18n/LocaleContext";
import { reorderNavIds, moveId } from "@/lib/navOrder";
import { NavPreviewCard } from "./NavPreviewCard";

export const NAV_ITEMS = [
  { id: "dashboard", to: "/app", icon: "grid", labelKey: "nav.dashboard", end: true },
  { id: "chat", to: "/app/chat", icon: "chat", labelKey: "nav.chat", end: false },
  { id: "issues", to: "/app/issues", icon: "clock", labelKey: "nav.issues", end: false, badge: true },
  { id: "schedules", to: "/app/schedules", icon: "calendar", labelKey: "nav.schedules", end: false },
  { id: "reports", to: "/app/reports", icon: "file", labelKey: "nav.reports", end: false },
  { id: "agent-metrics", to: "/app/agent-metrics", icon: "barchart", labelKey: "nav.agentMetrics", end: false },
  { id: "skills", to: "/app/skills", icon: "puzzle", labelKey: "nav.skills", end: false },
] as const;

export const ICON_PATHS: Record<string, string> = {
  grid: "M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z",
  chat: "M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z",
  clock: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z",
  calendar: "M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z",
  file: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z",
  barchart: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z",
  puzzle: "M11 4a2 2 0 114 0v1a1 1 0 001 1h3a2 2 0 012 2v3a1 1 0 01-1 1 2 2 0 100 4 1 1 0 011 1v3a2 2 0 01-2 2h-3a1 1 0 01-1-1 2 2 0 10-4 0 1 1 0 01-1 1H7a2 2 0 01-2-2v-3a1 1 0 011-1 2 2 0 100-4 1 1 0 01-1-1V7a2 2 0 012-2h3a1 1 0 001-1V4z",
  cog: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.573-1.066z",
};

export function SvgIcon({ d }: { d: string }) {
  return (
    <svg className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d={d} />
    </svg>
  );
}

export function NavItems({ expanded }: { expanded: boolean }) {
  const { t } = useLocale();
  const stats = useStats();
  const hasOpenIssues = (stats.data?.open_anomalies ?? 0) > 0;

  const currentIds = NAV_ITEMS.map((i) => i.id);
  const [storedOrder, setStoredOrder] = usePersistedState<string[]>("aiops-nav-order", currentIds);
  const order = reorderNavIds(storedOrder, currentIds);
  const items = order.map((id) => NAV_ITEMS.find((i) => i.id === id)!);

  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);

  const onDrop = (targetId: string) => {
    if (dragId) setStoredOrder(moveId(order, dragId, targetId));
    setDragId(null);
    setOverId(null);
  };

  return (
    <nav className={`flex-1 flex flex-col py-3 gap-1 ${expanded ? "px-2" : "items-center"}`}>
      {items.map((item) => (
        <Tooltip.Root key={item.id}>
          <Tooltip.Trigger asChild>
            <div
              draggable={expanded}
              onDragStart={() => setDragId(item.id)}
              onDragOver={(e) => { if (dragId) { e.preventDefault(); setOverId(item.id); } }}
              onDragLeave={() => setOverId((cur) => (cur === item.id ? null : cur))}
              onDrop={() => onDrop(item.id)}
              onDragEnd={() => { setDragId(null); setOverId(null); }}
              className={overId === item.id && dragId !== item.id ? "border-t-2 border-primary" : "border-t-2 border-transparent"}
            >
              <NavLink
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `relative flex items-center rounded-lg transition-colors ${
                    expanded ? "gap-3 px-3 h-10 w-full" : "w-10 h-10 justify-center"
                  } ${
                    isActive
                      ? "bg-primary/10 text-primary border-l-2 border-primary"
                      : "text-muted-foreground hover:text-foreground hover:bg-accent"
                  }`
                }
              >
                <SvgIcon d={ICON_PATHS[item.icon]} />
                {expanded && <span className="text-sm truncate">{t(item.labelKey)}</span>}
                {"badge" in item && item.badge && hasOpenIssues && (
                  <span className={`absolute w-2 h-2 rounded-full bg-red-500 ${expanded ? "top-2 left-7" : "top-1.5 right-1.5"}`} />
                )}
              </NavLink>
            </div>
          </Tooltip.Trigger>
          <Tooltip.Portal>
            <Tooltip.Content
              side="right"
              sideOffset={8}
              className="px-2.5 py-1.5 bg-card border border-border rounded-md shadow-lg z-50"
            >
              <NavPreviewCard id={item.id} labelKey={item.labelKey} />
              <Tooltip.Arrow className="fill-card" />
            </Tooltip.Content>
          </Tooltip.Portal>
        </Tooltip.Root>
      ))}
    </nav>
  );
}
```

- [ ] **Step 3: IconSidebar.tsx 重写为壳**

全量替换为:

```tsx
import { NavLink } from "react-router-dom";
import * as Tooltip from "@radix-ui/react-tooltip";
import { usePersistedState } from "@/hooks/usePersistedState";
import { useLocale } from "@/i18n/LocaleContext";
import { NavItems, ICON_PATHS, SvgIcon } from "./NavItems";

export function IconSidebar() {
  const { t } = useLocale();
  const [expanded, setExpanded] = usePersistedState<boolean>("aiops-nav-expanded", false);

  return (
    <Tooltip.Provider delayDuration={200}>
      <aside
        className={`fixed inset-y-0 left-0 bg-card border-r border-border flex flex-col z-30 transition-[width] duration-200 ${
          expanded ? "w-[200px]" : "w-[52px]"
        }`}
      >
        {/* Logo */}
        <div className={`h-[52px] flex items-center border-b border-border ${expanded ? "px-3 gap-2" : "justify-center"}`}>
          <img src={`${import.meta.env.BASE_URL}logo-icon.svg`} alt="AgenticOps" className="w-8 h-8 drop-shadow-md shrink-0" />
          {expanded && <span className="text-sm font-semibold text-foreground truncate">AgenticOps</span>}
        </div>

        {/* Sortable nav */}
        <NavItems expanded={expanded} />

        {/* Bottom: settings + collapse toggle */}
        <div className={`flex flex-col pb-3 gap-1 border-t border-border pt-3 ${expanded ? "px-2" : "items-center"}`}>
          <NavLink
            to="/app/settings"
            className={({ isActive }) =>
              `flex items-center rounded-lg transition-colors ${
                expanded ? "gap-3 px-3 h-10 w-full" : "w-10 h-10 justify-center"
              } ${
                isActive
                  ? "bg-primary/10 text-primary border-l-2 border-primary"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent"
              }`
            }
          >
            <SvgIcon d={ICON_PATHS.cog} />
            {expanded && <span className="text-sm truncate">{t("nav.settings")}</span>}
          </NavLink>
          <button
            onClick={() => setExpanded(!expanded)}
            className={`flex items-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors ${
              expanded ? "gap-3 px-3 h-10 w-full" : "w-10 h-10 justify-center"
            }`}
            title={expanded ? t("nav.collapse") : t("nav.expand")}
          >
            <svg className={`h-5 w-5 shrink-0 transition-transform ${expanded ? "" : "rotate-180"}`} fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
            </svg>
            {expanded && <span className="text-sm truncate">{t("nav.collapse")}</span>}
          </button>
          {!expanded && <span className="text-[8px] text-muted-foreground/50 font-mono">v1.0</span>}
        </div>
      </aside>
    </Tooltip.Provider>
  );
}
```

- [ ] **Step 4: i18n(chat.contextPanel.* 块后追加)**

en.json:

```json
  "nav.expand": "Expand sidebar",
  "nav.collapse": "Collapse",
```

zh.json:

```json
  "nav.expand": "展开侧边栏",
  "nav.collapse": "收起",
```

- [ ] **Step 5: tsc 验证 + Commit**

Run: `cd src/agenticops/web/frontend && npx tsc --noEmit 2>&1 | tail -2`
Expected: 干净。

```bash
git add src/agenticops/web/frontend/src
git commit --no-verify -m "feat(nav): sortable NavItems + preview cards + expandable IconSidebar shell

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: AppShell padding 联动

**Files:**
- Modify: `src/agenticops/web/frontend/src/components/layout/AppShell.tsx`

**Interfaces:**
- Consumes: `usePersistedState<boolean>("aiops-nav-expanded", false)`(与 IconSidebar 同 key,同 tab 内两个 hook 实例各自 setState——IconSidebar 写入时 AppShell 不会自动感知,因此 **AppShell 也用同一 hook 读取**;usePersistedState 的 storage 事件只跨 tab,同 tab 需要状态提升)。
- Produces: 内容区 padding 随展开态 52↔200px。

**实现注意(同 tab 同步问题的正解)**:两个组件各持一个 `usePersistedState("aiops-nav-expanded")` 实例在同一 tab 内不同步(storage 事件不触发于本 tab)。**状态提升到 AppShell**:AppShell 持有 state,传 `expanded`/`onToggle` 给 IconSidebar。Task 2 的 IconSidebar 签名相应调整。

- [ ] **Step 1: AppShell 持有状态并传递**

`AppShell.tsx` 改为:

```tsx
import { useState, useEffect, useCallback } from "react";
import { Outlet } from "react-router-dom";
import { IconSidebar } from "./IconSidebar";
import { MinimalTopBar } from "./MinimalTopBar";
import { CommandPalette } from "../CommandPalette";
import { usePersistedState } from "@/hooks/usePersistedState";

export function AppShell() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [navExpanded, setNavExpanded] = usePersistedState<boolean>("aiops-nav-expanded", false);

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault();
      setPaletteOpen((prev) => !prev);
    }
  }, []);

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <IconSidebar expanded={navExpanded} onToggle={() => setNavExpanded(!navExpanded)} />
      <div className={`transition-[padding] duration-200 ${navExpanded ? "pl-[200px]" : "pl-[52px]"}`}>
        <MinimalTopBar />
        <main className="p-6">
          <Outlet />
        </main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
```

- [ ] **Step 2: IconSidebar 改为受控**

`IconSidebar.tsx` 签名与内部改为(替换 Task 2 版本的 state 持有):

```tsx
export function IconSidebar({ expanded, onToggle }: { expanded: boolean; onToggle: () => void }) {
  const { t } = useLocale();
  // 删除 usePersistedState 行;折叠按钮 onClick={onToggle}
```

(其余 JSX 不变;`usePersistedState` import 移除。)

- [ ] **Step 3: tsc + vitest + Commit**

Run: `cd src/agenticops/web/frontend && npx tsc --noEmit && npx vitest run 2>&1 | tail -3`
Expected: 干净 + 全 passed。

```bash
git add src/agenticops/web/frontend/src
git commit --no-verify -m "feat(nav): AppShell owns nav-expanded state, content padding follows

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
1. 默认收起 52px 纯图标;点底部折叠按钮 → 展开 200px,图标+文字,内容区 padding 平滑联动。
2. 展开态拖 Issues 到列表顶部 → 顺序变化;刷新页面 → 顺序保持(localStorage)。
3. hover Issues 项 → 预览卡片显示 "N open · M critical"(来自 stats 缓存);hover 无缓存页(如 Reports 未访问过)→ 只显示页面名。
4. 收起 → 恢复 52px;再刷新 → 收起态保持。
5. 回归确认:Chat 页三栏布局在展开态不破版(挤压可接受,无横向滚动条)。

- [ ] **Step 3: STOP — 汇报 owner**

汇报 E2E 截图、提交清单。**不 push、不 merge** —— owner 确认后连同 A/B 一起决定推送。
