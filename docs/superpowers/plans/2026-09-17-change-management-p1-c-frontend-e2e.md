# Change Management P1 — Plan C: 前端 + 文档 + Live E2E（S4 + S5 + S6）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Plan A/B 交付的变更闭环在 Web UI 上可达（新页 `/app/plans` 三 tab + `/app/changes/:id` 详情 + 既有页面的身份绑定修正），补齐文档（发布说明、工作流、双语 README、文档地图、CLAUDE.md、harness 附注），最后在真实账户上跑一遍 tag 变更的 live E2E 并出报告——E2E 通过且主人确认后才 push。

**Architecture:** React 18 + TanStack Query 5 + Radix Tabs + Recharts 3；新增 `components/plans/` 承载从 `IssueDetail.tsx` 抽出的 Runbook 组件与新的变更组件；所有弹层遵守 house rule（`animate-[slideInRight_0.2s_ease-out]` + ESC）；前端只依赖 Plan B 契约里的 URL 与 schema 名。

**Tech Stack:** TypeScript, React, TanStack Query, Radix UI Tabs, Recharts, Tailwind；验证手段 `npx tsc --noEmit` + `npm run build` + 浏览器走查（Playwright MCP 可用于截图）。

**Spec:** `docs/superpowers/specs/2026-09-16-change-management-p1-design.md`（§3.9、§5 Audit tab、§7 Live E2E、§8、§9 S4–S6）
**前置:** Plan A 与 Plan B 全部完成并提交；后端可在本机 `uvicorn agenticops.web.app:app --port 8000` 跑起。

## Global Constraints

- 前端目录 `src/agenticops/web/frontend/`；命令：`npx tsc --noEmit && npm run build`（每个 Task 结束都跑）；开发预览 `npm run dev`（代理到 8000）。
- 弹层 house rule：每个 overlay/dialog ① `animate-[slideInRight_0.2s_ease-out]` ② ESC 关闭（`window` keydown 监听或 Radix 原生）。参考 `components/chat/SaveReportDialog.tsx`。
- 文案一律走 `useLocale().t("key")`，`locales/en.json` 与 `locales/zh.json` **同一提交**同步加键。
- 不改后端契约；如需字段，回到 Plan B 加。
- README.md ↔ README_CN.md 段落一一对应、同一提交；文档地图 `docs/README.md` 的 living/历史划分不变。
- 提交纪律同 Plan A/B；**live E2E 在真实账户上会创建/删除一个 EC2 tag**——这是本 P1 唯一的写操作，写在报告里；push 只在 E2E 通过 + 主人确认之后（`git push --no-verify`）。

## File Structure

| 文件 | 责任 | Task |
|---|---|---|
| `src/api/types.ts` | `FixPlan` 扩展、`ChangeRequest*`、`PlanStats`、`CommandAudit`、`ChangeTimelineEntry` | 1 |
| `src/hooks/useChanges.ts`、`usePlanStats.ts`、`useCommandAudits.ts`（新）；`useFixPlans.ts` | 数据钩子 | 1 |
| `src/components/plans/RunbookStep.tsx`、`CheckItem.tsx`、`RollbackPlan.tsx`、`PipelineTimeline.tsx`（从 IssueDetail 抽出）；`ReasonDialog.tsx`、`ChangeStatusBadge.tsx`、`ChangeStepper.tsx`（新） | 共用组件 | 2 |
| `src/pages/PlansAndChanges.tsx`、`src/components/plans/NewChangeDialog.tsx`、`src/components/plans/FixPlansTab.tsx`、`ChangePlansTab.tsx` | 新页与两个 tab | 3 |
| `src/pages/ChangeDetail.tsx`、`src/lib/renderMarkdown.ts` | 详情页、`C#N` 链接 | 4 |
| `src/components/plans/AuditTab.tsx` | 统计与两本账 | 5 |
| `src/App.tsx`、`src/components/layout/NavItems.tsx`、`src/locales/*.json`、`src/pages/Dashboard.tsx`、`src/components/chat/ContextPanel.tsx`、`src/pages/IssueDetail.tsx`、`src/components/settings/AuditTab.tsx` | 路由、侧栏、既有页修正 | 3, 6 |
| `docs/MVP-2.6.0-RELEASE.md`（新）、`docs/WORKFLOW.md`、`README.md`、`README_CN.md`、`docs/README.md`、`CLAUDE.md`、`docs/superpowers/plans/2026-09-09-harness-engineering-architecture-update.md` | 文档 | 7 |
| `docs/MVP-2.6.0-E2E-REPORT.md`（新） | Live E2E 证据 | 8 |

---

### Task 1: 类型与数据钩子

**Files:**
- Modify: `src/api/types.ts`（`FixPlan` :147-164；`FixExecution.health_issue_id`；文件末尾追加 Change 类型）
- Create: `src/hooks/useChanges.ts`, `src/hooks/usePlanStats.ts`, `src/hooks/useCommandAudits.ts`
- Modify: `src/hooks/useFixPlans.ts`（approve 体、reject 端点）

**Interfaces:**
- Produces（TS）：`FixPlan` 新字段 `plan_kind: "fix" | "change"; change_request_id: number | null; rejected_by/rejected_at/rejection_reason: string | null; updated_at: string | null; health_issue_id/rca_result_id: number | null`；`ChangeStatus` 联合类型；`ChangeRequest`、`ChangeRequestDetail`、`ChangeTimelineEntry`、`PlanStats`、`CommandAudit`；hooks `useChanges(filters)`, `useChange(id, {poll})`, `useChangeTimeline(id)`, `useCreateChange()`, `useChangeAction()`（approve/reject/cancel/clarify/execute/review/resolve-review 统一 mutation：`{id, action, body}`），`usePlanStats({period, kind, bucket})`, `useCommandAudits(filters)`；`useApproveFixPlan` 体改 `{ id, reason? }`，`useRejectFixPlan` 改 `{ id, reason }` → `POST /fix-plans/:id/reject`。

- [ ] **Step 1: `types.ts`**

`FixPlan` 改为：

```ts
export type PlanKind = "fix" | "change";

export interface FixPlan {
  id: number;
  plan_kind: PlanKind;
  health_issue_id: number | null;
  rca_result_id: number | null;
  change_request_id: number | null;
  risk_level: RiskLevel;
  title: string;
  summary: string;
  steps: unknown[];
  rollback_plan: Record<string, unknown>;
  estimated_impact: string;
  pre_checks: unknown[];
  post_checks: unknown[];
  status: FixPlanStatus;
  approved_by: string | null;
  approved_at: string | null;
  rejected_by: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  created_at: string;
  updated_at: string | null;
  account_id: number | null;
}
```

`FixExecution.health_issue_id: number | null`；`IssueStatus` 联合类型补上后端已有的 `"fix_executing"`；`AuditLogEntry` 加 `actor: string | null`。文件末尾追加：

```ts
/* ------------------------------------------------------------------ */
/*  Change Management (MVP-2.6.0)                                      */
/* ------------------------------------------------------------------ */

export type ChangeStatus =
  | "draft" | "under_review" | "needs_clarification" | "planned" | "approved"
  | "executing" | "needs_review" | "completed" | "failed" | "rolled_back" | "rejected" | "cancelled";

export type ChangeType = "standard" | "normal" | "emergency";

export interface ChangeTarget {
  resource_id: string;
  resource_type: string;
  db_id: number | null;
  region: string | null;
  evidence: string | { command: string; excerpt: string };
  hint?: string;
}

export interface ChangeRequest {
  id: number;
  title: string;
  description: string;
  justification: string;
  source: string;
  requested_by: string;
  requester_user_id: number | null;
  requested_at: string | null;
  account_id: number | null;
  target_hints: string[];
  target_resources: ChangeTarget[];
  requested_change_type: "normal" | "emergency";
  effective_change_type: ChangeType | null;
  risk_level: RiskLevel | null;
  action_type: string | null;
  status: ChangeStatus;
  review_verdict: string | null;
  review_reasons: string[];
  reviewed_by: string | null;
  reviewed_at: string | null;
  policy_rule: string | null;
  policy_action: string | null;
  approved_by: string | null;
  approver_user_id: number | null;
  approved_at: string | null;
  approval_reason: string | null;
  rejected_by: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  closed_at: string | null;
  trace_id: string | null;
  chat_session_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ChangeRequestDetail extends ChangeRequest {
  plans: FixPlan[];
  executions: FixExecution[];
}

export interface ChangeTimelineEntry {
  ts: string | null;
  kind: "event" | "audit";
  type: string;
  actor: string | null;
  status: string | null;
  stage: string | null;
  detail: unknown;
}

export interface ChangeRequestCreate {
  title: string;
  description: string;
  account_name?: string;
  targets: string[];
  requested_change_type: "normal" | "emergency";
  justification?: string;
}

export interface PlanStats {
  period: { start: string; end: string; bucket: string };
  kind: string;
  totals: { by_kind_status: Record<string, Record<string, number>>; open: number };
  approvals: { auto: number; human: number; rejected: number; authz_denied: number; authz_denied_shadow: number };
  lead_time: {
    request_to_approve_p50_s: number | null; request_to_approve_p90_s: number | null;
    approve_to_start_p50_s: number | null; exec_duration_p50_s: number | null;
  };
  outcomes: { success_rate: number | null; rollbacks: number; needs_review: number };
  breakdown: {
    by_actor: { requesters: { actor: string; count: number }[]; approvers: { actor: string; count: number }[]; executors: { actor: string; count: number }[] };
    by_risk: Record<string, number>; by_change_type: Record<string, number>; by_action_type: Record<string, number>; by_account: Record<string, number>;
  };
  series: { bucket: string; created: number; completed: number; failed: number }[];
  commands: { by_outcome: Record<string, number>; by_tool: Record<string, number> };
}

export interface CommandAudit {
  id: number;
  created_at: string;
  actor: string;
  on_behalf_of: string | null;
  agent_name: string | null;
  tool: string;
  tier: string;
  account: string;
  region: string;
  target: string;
  command: string;
  outcome: "executed" | "refused" | "blocked" | "error";
  reason: string | null;
  exit_code: number | null;
  output_excerpt: string;
  duration_ms: number;
  trace_id: string | null;
  fix_plan_id: number | null;
  change_request_id: number | null;
}
```

- [ ] **Step 2: hooks**

`src/hooks/useChanges.ts`：

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ChangeRequest, ChangeRequestCreate, ChangeRequestDetail, ChangeTimelineEntry, FixExecution } from "@/api/types";

export interface ChangeFilters { status?: string; account_id?: number; requested_by?: string; period?: "7d" | "30d" | "90d"; limit?: number; offset?: number }

const TERMINAL = new Set(["completed", "failed", "rolled_back", "rejected", "cancelled"]);
export const isTerminalChange = (s: string) => TERMINAL.has(s);

export function useChanges(filters: ChangeFilters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => { if (v !== undefined && v !== "") params.set(k, String(v)); });
  const qs = params.toString();
  return useQuery({
    queryKey: ["changes", filters],
    queryFn: () => apiFetch<ChangeRequest[]>(`/changes${qs ? `?${qs}` : ""}`),
    staleTime: 10_000,
    refetchInterval: 15_000,
  });
}

export function useChange(id: number) {
  return useQuery({
    queryKey: ["change", id],
    queryFn: () => apiFetch<ChangeRequestDetail>(`/changes/${id}`),
    enabled: id > 0,
    // poll while the request is still moving (review / execution run in the background)
    refetchInterval: (q) => (q.state.data && !isTerminalChange(q.state.data.status) ? 5_000 : false),
  });
}

export function useChangeTimeline(id: number) {
  return useQuery({
    queryKey: ["change-timeline", id],
    queryFn: () => apiFetch<ChangeTimelineEntry[]>(`/changes/${id}/timeline`),
    enabled: id > 0,
    refetchInterval: 10_000,
  });
}

export function useCreateChange() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ChangeRequestCreate) => apiFetch<ChangeRequest>("/changes", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["changes"] }),
  });
}

export type ChangeAction = "approve" | "reject" | "cancel" | "clarify" | "execute" | "review" | "resolve-review";

export function useChangeAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action, body }: { id: number; action: ChangeAction; body?: Record<string, unknown> }) =>
      apiFetch<ChangeRequest | FixExecution>(`/changes/${id}/${action}`, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ["changes"] });
      qc.invalidateQueries({ queryKey: ["change", vars.id] });
      qc.invalidateQueries({ queryKey: ["change-timeline", vars.id] });
      qc.invalidateQueries({ queryKey: ["fix-plans"] });
    },
  });
}
```

`src/hooks/usePlanStats.ts`：

```ts
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { PlanStats } from "@/api/types";

export function usePlanStats(opts: { period: "7d" | "30d" | "90d"; kind: "all" | "fix" | "change"; bucket?: "day" | "week" }) {
  const qs = `period=${opts.period}&kind=${opts.kind}&bucket=${opts.bucket ?? "day"}`;
  return useQuery({ queryKey: ["plan-stats", opts], queryFn: () => apiFetch<PlanStats>(`/plans/stats?${qs}`), staleTime: 30_000 });
}
```

`src/hooks/useCommandAudits.ts`：

```ts
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { CommandAudit } from "@/api/types";

export interface CommandAuditFilters { actor?: string; tool?: string; outcome?: string; fix_plan_id?: number; change_request_id?: number; period?: "7d" | "30d" | "90d"; limit?: number }

export function useCommandAudits(filters: CommandAuditFilters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => { if (v !== undefined && v !== "") params.set(k, String(v)); });
  const qs = params.toString();
  return useQuery({ queryKey: ["command-audits", filters], queryFn: () => apiFetch<CommandAudit[]>(`/command-audits${qs ? `?${qs}` : ""}`), staleTime: 15_000 });
}
```

`useFixPlans.ts`：`FixPlanFilters` 加 `kind?: "fix" | "change"`（`params.set("kind", ...)`）；

```ts
export function useApproveFixPlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason?: string }) =>
      apiFetch<FixPlan>(`/fix-plans/${id}/approve`, { method: "PUT", body: JSON.stringify({ reason }) }),
    onSuccess: (_data, vars) => { qc.invalidateQueries({ queryKey: ["fix-plans"] }); qc.invalidateQueries({ queryKey: ["fix-plan", vars.id] }); },
  });
}

export function useRejectFixPlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      apiFetch<FixPlan>(`/fix-plans/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) }),
    onSuccess: (_data, vars) => { qc.invalidateQueries({ queryKey: ["fix-plans"] }); qc.invalidateQueries({ queryKey: ["fix-plan", vars.id] }); },
  });
}
```

- [ ] **Step 3: 编译（此时 IssueDetail / ContextPanel 对旧 mutation 签名的调用会报错——这是预期，Task 6 修）**

Run: `cd src/agenticops/web/frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: 只有 `IssueDetail.tsx` / `ContextPanel.tsx` 关于 `approved_by` / `rejectMut.mutate(fp.id)` 的类型错误。为了让本 Task 独立可提交，**临时**在这两处改成新签名的最小调用：`approveMut.mutate({ id: fp.id })`、`rejectMut.mutate({ id: fp.id, reason: "rejected from UI" })`（Task 6 会换成 ReasonDialog）。再跑 `npx tsc --noEmit && npm run build` 应通过。

- [ ] **Step 4: Commit**

```bash
git add src/agenticops/web/frontend/src/api/types.ts src/agenticops/web/frontend/src/hooks/useChanges.ts src/agenticops/web/frontend/src/hooks/usePlanStats.ts src/agenticops/web/frontend/src/hooks/useCommandAudits.ts src/agenticops/web/frontend/src/hooks/useFixPlans.ts src/agenticops/web/frontend/src/pages/IssueDetail.tsx src/agenticops/web/frontend/src/components/chat/ContextPanel.tsx
git commit -m "feat(web): change-management types and hooks; plan approve/reject hooks match the hardened API"
```

---

### Task 2: 共用组件 `components/plans/`（抽取 + 新增）

**Files:**
- Create: `src/components/plans/RunbookStep.tsx`（含 `CommandBlock`）, `CheckItem.tsx`, `RollbackPlan.tsx`, `PipelineTimeline.tsx`（从 `pages/IssueDetail.tsx:997-1200` 原样搬出并 `export`）；`ReasonDialog.tsx`, `ChangeStatusBadge.tsx`, `ChangeStepper.tsx`（新）
- Modify: `src/pages/IssueDetail.tsx`（删除本地定义，改 import）

**Interfaces:**
- Produces: `RunbookStep({index, step})`, `CheckItem({item})`, `RollbackPlan({plan})`, `PipelineTimeline({events})`（形状不变）；`ReasonDialog({ title, description?, confirmText, variant?: "default"|"destructive", required?: boolean, onConfirm(reason: string), onClose })`（textarea，`required` 默认 true，空理由禁用确认；slideInRight + ESC）；`ChangeStatusBadge({status})`；`ChangeStepper({status})`（Requested → Reviewed → Planned → Approved → Executed → Completed；rejected/failed/rolled_back/cancelled 红标，needs_review 琥珀，needs_clarification 显示在 Reviewed 位）。

- [ ] **Step 1: 抽取**

把 `IssueDetail.tsx` 中 `STAGE_COLORS`、`STATUS_ICONS`、`PipelineTimeline`、`RunbookStep`、`CommandBlock`、`CheckItem`、`RollbackPlan` 六段**原样**移到对应新文件，每个加 `export`，补各自的 import（`useState`, `useLocale`, `renderMarkdown`, `formatFullDate`, `PipelineEvent` 类型）。`IssueDetail.tsx` 顶部加：

```ts
import { RunbookStep } from "@/components/plans/RunbookStep";
import { CheckItem } from "@/components/plans/CheckItem";
import { RollbackPlan } from "@/components/plans/RollbackPlan";
import { PipelineTimeline } from "@/components/plans/PipelineTimeline";
```

- [ ] **Step 2: `ReasonDialog.tsx`**

```tsx
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocale } from "@/i18n/LocaleContext";

interface Props {
  title: string;
  description?: string;
  confirmText: string;
  variant?: "default" | "destructive";
  required?: boolean;
  busy?: boolean;
  onConfirm: (reason: string) => void;
  onClose: () => void;
}

/** House-rule overlay: slideInRight + ESC. Captures a mandatory reason for approve / reject / cancel. */
export function ReasonDialog({ title, description, confirmText, variant = "default", required = true, busy = false, onConfirm, onClose }: Props) {
  const { t } = useLocale();
  const [reason, setReason] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { ref.current?.focus(); }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const disabled = busy || (required && !reason.trim());
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-card border border-border rounded-xl shadow-2xl w-full max-w-md mx-4 animate-[slideInRight_0.2s_ease-out]">
        <div className="px-6 py-4 border-b border-border">
          <h3 className="text-base font-semibold text-foreground">{title}</h3>
          {description && <p className="text-sm text-muted-foreground mt-1">{description}</p>}
        </div>
        <div className="px-6 py-4">
          <label className="block text-xs font-medium uppercase tracking-wider text-muted-foreground mb-1">
            {t("plans.reason")}{required && " *"}
          </label>
          <textarea ref={ref} value={reason} onChange={(e) => setReason(e.target.value)} rows={3}
            placeholder={t("plans.reasonPlaceholder")}
            className="w-full border border-border bg-background text-foreground rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50" />
        </div>
        <div className="px-6 py-4 border-t border-border flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-sm font-medium rounded-lg border border-border text-muted-foreground hover:bg-secondary transition-colors">{t("common.cancel")}</button>
          <button onClick={() => onConfirm(reason.trim())} disabled={disabled}
            className={`px-4 py-2 text-sm font-medium rounded-lg text-white disabled:opacity-50 transition-colors ${variant === "destructive" ? "bg-red-600 hover:bg-red-700" : "bg-emerald-600 hover:bg-emerald-700"}`}>
            {busy ? "…" : confirmText}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
```

- [ ] **Step 3: `ChangeStatusBadge.tsx` 与 `ChangeStepper.tsx`**

```tsx
// ChangeStatusBadge.tsx
import React from "react";
import { cn } from "@/lib/cn";
import type { ChangeStatus } from "@/api/types";

const STYLES: Record<ChangeStatus, { dot: string; text: string }> = {
  draft: { dot: "bg-muted-foreground", text: "text-muted-foreground" },
  under_review: { dot: "bg-blue-500 animate-pulse", text: "text-blue-600 dark:text-blue-400" },
  needs_clarification: { dot: "bg-amber-500", text: "text-amber-600 dark:text-amber-400" },
  planned: { dot: "bg-violet-500", text: "text-violet-600 dark:text-violet-400" },
  approved: { dot: "bg-green-500", text: "text-green-600 dark:text-green-400" },
  executing: { dot: "bg-blue-500 animate-pulse", text: "text-blue-600 dark:text-blue-400" },
  needs_review: { dot: "bg-amber-500", text: "text-amber-600 dark:text-amber-400" },
  completed: { dot: "bg-emerald-500", text: "text-emerald-600 dark:text-emerald-400" },
  failed: { dot: "bg-red-500", text: "text-red-500 dark:text-red-400" },
  rolled_back: { dot: "bg-red-400", text: "text-red-500 dark:text-red-400" },
  rejected: { dot: "bg-red-400", text: "text-red-500 dark:text-red-400" },
  cancelled: { dot: "bg-muted-foreground", text: "text-muted-foreground" },
};

export const ChangeStatusBadge = React.memo(function ChangeStatusBadge({ status }: { status: ChangeStatus }) {
  const s = STYLES[status] ?? STYLES.draft;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn("h-2 w-2 rounded-full", s.dot)} />
      <span className={cn("text-xs font-medium", s.text)}>{status.replace(/_/g, " ")}</span>
    </span>
  );
});
```

```tsx
// ChangeStepper.tsx
import React from "react";
import type { ChangeStatus } from "@/api/types";

const STEPS = ["Requested", "Reviewed", "Planned", "Approved", "Executed", "Completed"] as const;
const INDEX: Record<ChangeStatus, number> = {
  draft: 0, under_review: 1, needs_clarification: 1, planned: 2, approved: 3, executing: 4, needs_review: 4,
  completed: 5, failed: 4, rolled_back: 4, rejected: 2, cancelled: 0,
};
const TERMINAL_BAD = new Set<ChangeStatus>(["failed", "rolled_back", "rejected", "cancelled"]);

export const ChangeStepper = React.memo(function ChangeStepper({ status }: { status: ChangeStatus }) {
  const current = INDEX[status] ?? 0;
  const bad = TERMINAL_BAD.has(status);
  const warn = status === "needs_review" || status === "needs_clarification";
  return (
    <ol className="flex items-center gap-2 text-xs">
      {STEPS.map((label, i) => {
        const done = i < current || (i === current && status === "completed");
        const active = i === current && status !== "completed";
        const color = active && bad ? "bg-red-500 text-white" : active && warn ? "bg-amber-500 text-white"
          : done ? "bg-emerald-500 text-white" : active ? "bg-primary text-primary-foreground" : "bg-secondary text-muted-foreground";
        return (
          <li key={label} className="flex items-center gap-2">
            <span className={`w-6 h-6 rounded-full flex items-center justify-center font-semibold ${color}`}>{done ? "✓" : i + 1}</span>
            <span className={active || done ? "text-foreground font-medium" : "text-muted-foreground"}>
              {active && bad ? status.replace(/_/g, " ") : active && warn ? status.replace(/_/g, " ") : label}
            </span>
            {i < STEPS.length - 1 && <span className="w-6 h-px bg-border" />}
          </li>
        );
      })}
    </ol>
  );
});
```

- [ ] **Step 4: 编译 + Commit**

```bash
cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build
cd /Users/malibo/MyDev/AgenticOps && git add src/agenticops/web/frontend/src/components/plans src/agenticops/web/frontend/src/pages/IssueDetail.tsx
git commit -m "refactor(web): extract runbook/timeline components into components/plans; add ReasonDialog, ChangeStatusBadge, ChangeStepper"
```

---

### Task 3: `/app/plans` 页（Fix Plans / Change Plans 两个 tab）+ New change 表单 + 路由 / 侧栏 / 文案

**Files:**
- Create: `src/pages/PlansAndChanges.tsx`, `src/components/plans/FixPlansTab.tsx`, `src/components/plans/ChangePlansTab.tsx`, `src/components/plans/NewChangeDialog.tsx`
- Modify: `src/App.tsx`（lazy import + 两条路由）、`src/components/layout/NavItems.tsx`（`plans` 项 + `clipboard` 图标）、`src/locales/en.json`、`src/locales/zh.json`

**Interfaces:**
- Produces: 页面 `/app/plans?tab=fix|changes|audit`（Radix Tabs，`tab` 同步到 URL）；`FixPlansTab`（`useFixPlans({kind:"fix", status?, risk_level?})` → DataTable：I#、标题、风险、状态、审批人/时间、操作 approve/reject（ReasonDialog）/execute）；`ChangePlansTab`（`useChanges({status?, period})` → DataTable：C#、标题、`ChangeStepper` 迷你态、风险、类型、申请人、更新时间；行点击 → `/app/changes/:id`；「New change request」按钮）；`NewChangeDialog({onClose, onCreated(id)})`（标题、描述、账户下拉 `useAccounts()`、目标资源多选（库存搜索 `useResources({search, account_id, limit: 20})` + 手输 id 回车追加）、类型 normal/emergency、理由；提交 `useCreateChange()` → 跳详情）。locale 键前缀 `plans.*`。

- [ ] **Step 1: 文案（两份 locale 同步）**

`en.json` 加（`nav.plans` 放 nav 段；其余放新段）：

```json
  "nav.plans": "Plans & Changes",
  "nav.issues": "Issues",
  "plans.title": "Plans & Changes",
  "plans.tab.fix": "Fix Plans",
  "plans.tab.changes": "Change Plans",
  "plans.tab.audit": "Audit",
  "plans.newChange": "New change request",
  "plans.reason": "Reason",
  "plans.reasonPlaceholder": "Why? This is written to the audit ledger.",
  "plans.approveTitle": "Approve",
  "plans.rejectTitle": "Reject",
  "plans.cancelTitle": "Cancel change",
  "plans.executeConfirm": "Queue execution now? The Executor will run the approved plan.",
  "plans.noPlans": "No plans yet.",
  "plans.noChanges": "No change requests yet.",
  "plans.status": "Status",
  "plans.risk": "Risk",
  "plans.type": "Type",
  "plans.requestedBy": "Requested by",
  "plans.approvedBy": "Approved by",
  "plans.updated": "Updated",
  "plans.actions": "Actions",
  "plans.allStatuses": "All statuses",
  "plans.form.title": "Title",
  "plans.form.description": "What should change, and why?",
  "plans.form.account": "Account",
  "plans.form.targets": "Target resources",
  "plans.form.targetsHint": "Search the inventory or type an id / ARN and press Enter",
  "plans.form.type": "Change type",
  "plans.form.justification": "Justification (optional)",
  "plans.form.submit": "Submit for review",
  "changes.detail": "Change request",
  "changes.request": "Request",
  "changes.review": "Review",
  "changes.plan": "Plan",
  "changes.approval": "Approval",
  "changes.execution": "Execution",
  "changes.timeline": "Timeline",
  "changes.startReview": "Start review",
  "changes.clarify": "Send clarification",
  "changes.markCompleted": "Mark completed",
  "changes.markFailed": "Mark failed",
  "changes.copyAsNew": "Copy as new change",
  "changes.targets": "Targets",
  "changes.verdict": "Verdict",
  "changes.policy": "Policy",
  "changes.reasons": "Reasons",
  "audit.kpi.total": "Changes",
  "audit.kpi.success": "Success rate",
  "audit.kpi.leadTime": "Median approval time",
  "audit.kpi.rollbacks": "Rollbacks",
  "audit.kpi.refused": "Refused write commands",
  "audit.decisions": "Decision ledger",
  "audit.commands": "Command ledger"
```

`zh.json` 同键中文（`nav.plans`: "计划与变更"、`nav.issues`: "问题"、`plans.tab.fix`: "修复计划"、`plans.tab.changes`: "变更计划"、`plans.tab.audit`: "审计"、`plans.newChange`: "新建变更"、`plans.reason`: "理由"、`plans.reasonPlaceholder`: "为什么？会写入审计账本。"、`plans.form.submit`: "提交审核"、`changes.startReview`: "发起审核"、`changes.markCompleted`: "标记完成"、`changes.markFailed`: "标记失败"、`changes.copyAsNew`: "复制为新变更"、`audit.kpi.total`: "变更总数"、`audit.kpi.success`: "成功率"、`audit.kpi.leadTime`: "中位审批时长"、`audit.kpi.rollbacks`: "回滚数"、`audit.kpi.refused`: "被拒写命令"、`audit.decisions`: "决策账本"、`audit.commands`: "命令账本"……其余逐键翻译）。键集合必须与 en 完全一致，用下面这条命令校验（输出为空才算过）：

```bash
cd src/agenticops/web/frontend && diff <(python -c "import json;print('\n'.join(sorted(json.load(open('src/locales/en.json')))))") <(python -c "import json;print('\n'.join(sorted(json.load(open('src/locales/zh.json')))))")
```

- [ ] **Step 2: 路由与侧栏**

`App.tsx`：`const PlansAndChanges = lazy(() => import("@/pages/PlansAndChanges")); const ChangeDetail = lazy(() => import("@/pages/ChangeDetail"));` 在 `issues/:id` 路由后加 `plans` 与 `changes/:id` 两条（同 Suspense 形状）。`NavItems.tsx`：`NAV_ITEMS` 在 `issues` 之后插入 `{ id: "plans", to: "/app/plans", icon: "clipboard", labelKey: "nav.plans", end: false }`，`ICON_PATHS.clipboard = "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"`。（Task 4 才建 `ChangeDetail.tsx`——先建一个只渲染 `<Spinner />` 的占位文件让 tsc 通过，Task 4 替换。）

- [ ] **Step 3: `PlansAndChanges.tsx`**

```tsx
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import * as Tabs from "@radix-ui/react-tabs";
import { useLocale } from "@/i18n/LocaleContext";
import { FixPlansTab } from "@/components/plans/FixPlansTab";
import { ChangePlansTab } from "@/components/plans/ChangePlansTab";
import { AuditTab } from "@/components/plans/AuditTab";
import { NewChangeDialog } from "@/components/plans/NewChangeDialog";

const tabTriggerClass =
  "px-4 py-2 text-sm font-medium text-muted-foreground border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:text-foreground transition-colors";

export default function PlansAndChanges() {
  const { t } = useLocale();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "changes";
  const [showNew, setShowNew] = useState(false);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-foreground">{t("plans.title")}</h1>
        <button onClick={() => setShowNew(true)}
          className="px-4 py-2 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors">
          + {t("plans.newChange")}
        </button>
      </div>
      <Tabs.Root value={tab} onValueChange={(v) => setParams({ tab: v })}>
        <Tabs.List className="flex border-b border-border mb-6 gap-0 overflow-x-auto">
          <Tabs.Trigger value="fix" className={tabTriggerClass}>{t("plans.tab.fix")}</Tabs.Trigger>
          <Tabs.Trigger value="changes" className={tabTriggerClass}>{t("plans.tab.changes")}</Tabs.Trigger>
          <Tabs.Trigger value="audit" className={tabTriggerClass}>{t("plans.tab.audit")}</Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="fix"><FixPlansTab /></Tabs.Content>
        <Tabs.Content value="changes"><ChangePlansTab /></Tabs.Content>
        <Tabs.Content value="audit"><AuditTab /></Tabs.Content>
      </Tabs.Root>
      {showNew && <NewChangeDialog onClose={() => setShowNew(false)} onCreated={(id) => { setShowNew(false); navigate(`/app/changes/${id}`); }} />}
    </div>
  );
}
```

（`AuditTab` 在 Task 5 实现；本 Task 先建导出 `<div />` 的占位以通过编译。）

- [ ] **Step 4: `FixPlansTab.tsx`**

```tsx
import { useState } from "react";
import { Link } from "react-router-dom";
import { useApproveFixPlan, useExecuteFixPlan, useFixPlans, useRejectFixPlan } from "@/hooks/useFixPlans";
import { useLocale } from "@/i18n/LocaleContext";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { FixPlanStatusBadge } from "@/components/ui/FixPlanStatusBadge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { ReasonDialog } from "@/components/plans/ReasonDialog";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { formatShortDate } from "@/lib/formatDate";
import type { FixPlan } from "@/api/types";

const STATUSES = ["", "draft", "pending_approval", "approved", "executing", "executed", "failed", "rejected"];

export function FixPlansTab() {
  const { t } = useLocale();
  const [status, setStatus] = useState("");
  const plans = useFixPlans({ kind: "fix", status: status || undefined });
  const approve = useApproveFixPlan();
  const reject = useRejectFixPlan();
  const execute = useExecuteFixPlan();
  const { confirm, dialog } = useConfirm();
  const [pending, setPending] = useState<{ plan: FixPlan; action: "approve" | "reject" } | null>(null);

  if (plans.isLoading) return <Spinner />;
  if (plans.error) return <ErrorBanner message={(plans.error as Error).message} onRetry={() => plans.refetch()} />;

  const columns: Column<FixPlan>[] = [
    { key: "id", header: "#", render: (p) => <span className="font-mono text-xs">#{p.id}</span>, sortable: true, sortValue: (p) => p.id },
    { key: "issue", header: "Issue", render: (p) => p.health_issue_id ? <Link className="text-primary font-mono text-xs" to={`/app/issues/${p.health_issue_id}`}>I#{p.health_issue_id}</Link> : "-" },
    { key: "title", header: "Title", render: (p) => <span className="text-sm text-foreground">{p.title}</span> },
    { key: "risk", header: t("plans.risk"), render: (p) => <RiskLevelBadge level={p.risk_level} />, sortable: true, sortValue: (p) => p.risk_level },
    { key: "status", header: t("plans.status"), render: (p) => <FixPlanStatusBadge status={p.status} />, sortable: true, sortValue: (p) => p.status },
    { key: "approved", header: t("plans.approvedBy"), render: (p) => <span className="text-xs text-muted-foreground">{p.approved_by ?? "-"}{p.approved_at ? ` · ${formatShortDate(p.approved_at)}` : ""}</span> },
    { key: "actions", header: t("plans.actions"), render: (p) => (
      <div className="flex gap-2">
        {(p.status === "draft" || p.status === "pending_approval") && (
          <>
            <button onClick={(e) => { e.stopPropagation(); setPending({ plan: p, action: "approve" }); }} className="px-2 py-1 text-xs rounded bg-emerald-600 text-white">{t("issues.approve")}</button>
            <button onClick={(e) => { e.stopPropagation(); setPending({ plan: p, action: "reject" }); }} className="px-2 py-1 text-xs rounded border border-red-500/40 text-red-500">{t("issues.reject")}</button>
          </>
        )}
        {p.status === "approved" && (
          <button onClick={async (e) => { e.stopPropagation(); if (await confirm(t("plans.executeConfirm"), { confirmText: t("issues.execute") })) execute.mutate(p.id); }}
            className="px-2 py-1 text-xs rounded bg-primary text-primary-foreground">{t("issues.execute")}</button>
        )}
      </div>
    ) },
  ];

  return (
    <div className="space-y-4">
      <select value={status} onChange={(e) => setStatus(e.target.value)} className="border border-border bg-background text-sm rounded-lg px-3 py-1.5">
        {STATUSES.map((s) => <option key={s} value={s}>{s ? s.replace(/_/g, " ") : t("plans.allStatuses")}</option>)}
      </select>
      <DataTable columns={columns} data={plans.data ?? []} rowKey={(p) => p.id} emptyMessage={t("plans.noPlans")} />
      {pending && (
        <ReasonDialog
          title={pending.action === "approve" ? `${t("plans.approveTitle")} #${pending.plan.id}` : `${t("plans.rejectTitle")} #${pending.plan.id}`}
          description={pending.plan.title}
          confirmText={pending.action === "approve" ? t("issues.approve") : t("issues.reject")}
          variant={pending.action === "reject" ? "destructive" : "default"}
          required={pending.action === "reject"}
          busy={approve.isPending || reject.isPending}
          onConfirm={(reason) => {
            const done = { onSuccess: () => { setPending(null); plans.refetch(); } };
            if (pending.action === "approve") approve.mutate({ id: pending.plan.id, reason: reason || undefined }, done);
            else reject.mutate({ id: pending.plan.id, reason }, done);
          }}
          onClose={() => setPending(null)}
        />
      )}
      {dialog}
    </div>
  );
}
```

- [ ] **Step 5: `ChangePlansTab.tsx` 与 `NewChangeDialog.tsx`**

```tsx
// ChangePlansTab.tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useChanges } from "@/hooks/useChanges";
import { useLocale } from "@/i18n/LocaleContext";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { ChangeStatusBadge } from "@/components/plans/ChangeStatusBadge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatShortDate } from "@/lib/formatDate";
import type { ChangeRequest } from "@/api/types";

const STATUSES = ["", "draft", "under_review", "needs_clarification", "planned", "approved", "executing", "needs_review", "completed", "failed", "rolled_back", "rejected", "cancelled"];

export function ChangePlansTab() {
  const { t } = useLocale();
  const navigate = useNavigate();
  const [status, setStatus] = useState("");
  const [period, setPeriod] = useState<"7d" | "30d" | "90d">("30d");
  const changes = useChanges({ status: status || undefined, period, limit: 200 });

  if (changes.isLoading) return <Spinner />;
  if (changes.error) return <ErrorBanner message={(changes.error as Error).message} onRetry={() => changes.refetch()} />;

  const columns: Column<ChangeRequest>[] = [
    { key: "id", header: "C#", render: (c) => <span className="font-mono text-xs text-primary">C#{c.id}</span>, sortable: true, sortValue: (c) => c.id },
    { key: "title", header: "Title", render: (c) => <span className="text-sm text-foreground">{c.title}</span> },
    { key: "status", header: t("plans.status"), render: (c) => <ChangeStatusBadge status={c.status} />, sortable: true, sortValue: (c) => c.status },
    { key: "risk", header: t("plans.risk"), render: (c) => c.risk_level ? <RiskLevelBadge level={c.risk_level} /> : <span className="text-xs text-muted-foreground">-</span> },
    { key: "type", header: t("plans.type"), render: (c) => <span className="text-xs">{c.effective_change_type ?? c.requested_change_type}</span> },
    { key: "by", header: t("plans.requestedBy"), render: (c) => <span className="text-xs font-mono text-muted-foreground">{c.requested_by}</span> },
    { key: "updated", header: t("plans.updated"), render: (c) => <span className="text-xs text-muted-foreground">{formatShortDate(c.updated_at ?? c.created_at ?? "")}</span>, sortable: true, sortValue: (c) => c.updated_at ?? c.created_at ?? "" },
  ];

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="border border-border bg-background text-sm rounded-lg px-3 py-1.5">
          {STATUSES.map((s) => <option key={s} value={s}>{s ? s.replace(/_/g, " ") : t("plans.allStatuses")}</option>)}
        </select>
        <div className="flex gap-1 bg-secondary rounded-lg p-1">
          {(["7d", "30d", "90d"] as const).map((p) => (
            <button key={p} onClick={() => setPeriod(p)} className={`px-2 py-1 text-xs rounded ${period === p ? "bg-background shadow text-foreground" : "text-muted-foreground"}`}>{p}</button>
          ))}
        </div>
      </div>
      <DataTable columns={columns} data={changes.data ?? []} rowKey={(c) => c.id} onRowClick={(c) => navigate(`/app/changes/${c.id}`)} emptyMessage={t("plans.noChanges")} />
    </div>
  );
}
```

```tsx
// NewChangeDialog.tsx
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useAccounts } from "@/hooks/useAccounts";
import { useResources } from "@/hooks/useResources";
import { useCreateChange } from "@/hooks/useChanges";
import { useLocale } from "@/i18n/LocaleContext";

interface Props { onClose: () => void; onCreated: (id: number) => void; initial?: Partial<{ title: string; description: string; account_name: string; targets: string[] }> }

export function NewChangeDialog({ onClose, onCreated, initial }: Props) {
  const { t } = useLocale();
  const accounts = useAccounts();
  const create = useCreateChange();
  const [title, setTitle] = useState(initial?.title ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [accountName, setAccountName] = useState(initial?.account_name ?? "");
  const [targets, setTargets] = useState<string[]>(initial?.targets ?? []);
  const [search, setSearch] = useState("");
  const [type, setType] = useState<"normal" | "emergency">("normal");
  const [justification, setJustification] = useState("");
  const accountId = accounts.data?.find((a) => a.name === accountName)?.id;
  const matches = useResources({ search: search.length >= 2 ? search : undefined, account_id: accountId, limit: 10 });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const addTarget = (v: string) => { const x = v.trim(); if (x && !targets.includes(x)) setTargets([...targets, x]); setSearch(""); };
  const canSubmit = title.trim() && description.trim() && !create.isPending;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <form className="relative bg-card border border-border rounded-xl shadow-2xl w-full max-w-lg mx-4 animate-[slideInRight_0.2s_ease-out]"
        onSubmit={(e) => { e.preventDefault(); if (!canSubmit) return;
          create.mutate({ title: title.trim(), description: description.trim(), account_name: accountName || undefined, targets, requested_change_type: type, justification: justification || undefined },
            { onSuccess: (cr) => onCreated(cr.id) }); }}>
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <h2 className="text-lg font-semibold text-foreground">{t("plans.newChange")}</h2>
          <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground">✕</button>
        </div>
        <div className="px-6 py-4 space-y-3 max-h-[70vh] overflow-y-auto">
          <label className="block text-sm"><span className="text-muted-foreground">{t("plans.form.title")}</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} className="mt-1 w-full border border-border bg-background rounded-lg px-3 py-2 text-sm" /></label>
          <label className="block text-sm"><span className="text-muted-foreground">{t("plans.form.description")}</span>
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={4} className="mt-1 w-full border border-border bg-background rounded-lg px-3 py-2 text-sm" /></label>
          <label className="block text-sm"><span className="text-muted-foreground">{t("plans.form.account")}</span>
            <select value={accountName} onChange={(e) => setAccountName(e.target.value)} className="mt-1 w-full border border-border bg-background rounded-lg px-3 py-2 text-sm">
              <option value="">—</option>
              {(accounts.data ?? []).filter((a) => a.is_enabled).map((a) => <option key={a.id} value={a.name}>{a.name} ({a.provider})</option>)}
            </select></label>
          <div className="text-sm">
            <span className="text-muted-foreground">{t("plans.form.targets")}</span>
            <div className="mt-1 flex flex-wrap gap-1">
              {targets.map((x) => <span key={x} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-secondary text-xs font-mono">{x}<button type="button" onClick={() => setTargets(targets.filter((y) => y !== x))}>✕</button></span>)}
            </div>
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t("plans.form.targetsHint")}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTarget(search); } }}
              className="mt-1 w-full border border-border bg-background rounded-lg px-3 py-2 text-sm font-mono" />
            {search.length >= 2 && (matches.data?.items.length ?? 0) > 0 && (
              <ul className="mt-1 border border-border rounded-lg divide-y divide-border max-h-40 overflow-y-auto">
                {matches.data!.items.map((r) => (
                  <li key={r.id}><button type="button" onClick={() => addTarget(r.resource_id)} className="w-full text-left px-3 py-1.5 text-xs hover:bg-secondary">
                    <span className="font-mono">{r.resource_id}</span> <span className="text-muted-foreground">{r.resource_type} · {r.resource_name ?? ""} · {r.region}</span></button></li>
                ))}
              </ul>
            )}
          </div>
          <label className="block text-sm"><span className="text-muted-foreground">{t("plans.form.type")}</span>
            <select value={type} onChange={(e) => setType(e.target.value as "normal" | "emergency")} className="mt-1 w-full border border-border bg-background rounded-lg px-3 py-2 text-sm">
              <option value="normal">normal</option><option value="emergency">emergency</option></select></label>
          <label className="block text-sm"><span className="text-muted-foreground">{t("plans.form.justification")}</span>
            <input value={justification} onChange={(e) => setJustification(e.target.value)} className="mt-1 w-full border border-border bg-background rounded-lg px-3 py-2 text-sm" /></label>
          {create.error && <div className="text-sm text-red-500">{(create.error as Error).message}</div>}
        </div>
        <div className="px-6 py-4 border-t border-border flex justify-end gap-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm rounded-lg border border-border text-muted-foreground">{t("common.cancel")}</button>
          <button type="submit" disabled={!canSubmit} className="px-4 py-2 text-sm font-medium rounded-lg bg-primary text-primary-foreground disabled:opacity-50">{t("plans.form.submit")}</button>
        </div>
      </form>
    </div>,
    document.body,
  );
}
```

- [ ] **Step 6: 编译 + 浏览器走查 + Commit**

```bash
cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build
```
后端跑着（`uvicorn agenticops.web.app:app --port 8000`），`npm run dev` 打开 `/app/plans`：三个 tab 可切换、URL `?tab=` 同步、New change 表单能提交并跳到详情（Task 4 前详情是占位 Spinner）。

```bash
cd /Users/malibo/MyDev/AgenticOps && git add src/agenticops/web/frontend/src/pages/PlansAndChanges.tsx src/agenticops/web/frontend/src/pages/ChangeDetail.tsx src/agenticops/web/frontend/src/components/plans src/agenticops/web/frontend/src/App.tsx src/agenticops/web/frontend/src/components/layout/NavItems.tsx src/agenticops/web/frontend/src/locales
git commit -m "feat(web): Plans & Changes page (fix plans + change plans tabs), new change dialog, nav entry, locales"
```

---

### Task 4: `/app/changes/:id` 详情页 + `C#N` 自动链接

**Files:**
- Create/replace: `src/pages/ChangeDetail.tsx`
- Modify: `src/lib/renderMarkdown.ts:52-56`（`C#N` 自动链接）
- Modify: `src/components/chat/MessageList.tsx:39-50`（`/app/changes/N` 走 `navigate`——已是默认分支，确认即可）

**Interfaces:**
- Produces: 详情页区块顺序 = stepper → 请求卡 → 审核卡 → 计划卡 → 审批/操作卡 → 执行卡 → 时间线；操作按状态显示：`draft`→Start review；`needs_clarification`→补充输入框（clarify）；`planned`→Approve/Reject（ReasonDialog）+ Cancel；`approved`→Execute（confirm）+ Cancel；`needs_review`→Mark completed / Mark failed（ReasonDialog）+ Copy as new；终态→Copy as new。

- [ ] **Step 1: `renderMarkdown.ts`**

R# 之后加：

```ts
    // Auto-link C#N → /app/changes/N
    s = s.replace(/\bC#(\d+)\b/g,
      '<a href="/app/changes/$1" class="md-link md-ref" title="Change #$1">C#$1</a>');
```

- [ ] **Step 2: `ChangeDetail.tsx`**

```tsx
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useChange, useChangeAction, useChangeTimeline } from "@/hooks/useChanges";
import { useCancelExecution } from "@/hooks/useFixExecutions";
import { useLocale } from "@/i18n/LocaleContext";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { FixPlanStatusBadge } from "@/components/ui/FixPlanStatusBadge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { ChangeStepper } from "@/components/plans/ChangeStepper";
import { ChangeStatusBadge } from "@/components/plans/ChangeStatusBadge";
import { ReasonDialog } from "@/components/plans/ReasonDialog";
import { NewChangeDialog } from "@/components/plans/NewChangeDialog";
import { RunbookStep } from "@/components/plans/RunbookStep";
import { CheckItem } from "@/components/plans/CheckItem";
import { RollbackPlan } from "@/components/plans/RollbackPlan";
import { formatFullDate } from "@/lib/formatDate";
import { renderMarkdown } from "@/lib/renderMarkdown";
import type { ChangeAction } from "@/hooks/useChanges";

type Pending = { action: ChangeAction; title: string; confirmText: string; variant?: "default" | "destructive"; extra?: Record<string, unknown> };

export default function ChangeDetail() {
  const { id } = useParams<{ id: string }>();
  const crId = Number(id);
  const { t } = useLocale();
  const q = useChange(crId);
  const tl = useChangeTimeline(crId);
  const act = useChangeAction();
  const cancelExec = useCancelExecution();
  const { confirm, dialog } = useConfirm();
  const [pending, setPending] = useState<Pending | null>(null);
  const [clarify, setClarify] = useState("");
  const [copy, setCopy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  if (q.isLoading) return <Spinner />;
  if (q.error || !q.data) return <ErrorBanner message={(q.error as Error)?.message ?? "Not found"} onRetry={() => q.refetch()} />;
  const cr = q.data;
  const plan = cr.plans[0];
  const run = (action: ChangeAction, body?: Record<string, unknown>) =>
    act.mutate({ id: crId, action, body }, { onSuccess: () => setPending(null), onError: (e) => setMsg(e.message) });

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-3 flex-wrap">
        <Link to="/app/plans?tab=changes" className="text-sm text-muted-foreground hover:text-foreground">← {t("plans.title")}</Link>
        <h1 className="text-2xl font-semibold text-foreground">C#{cr.id} · {cr.title}</h1>
        <ChangeStatusBadge status={cr.status} />
        {cr.risk_level && <RiskLevelBadge level={cr.risk_level} />}
      </div>
      <ChangeStepper status={cr.status} />
      {msg && <ErrorBanner message={msg} onRetry={() => setMsg(null)} />}

      <Card><CardHeader><h2 className="font-semibold">{t("changes.request")}</h2><span className="text-xs text-muted-foreground">{cr.source} · {cr.trace_id}</span></CardHeader>
        <CardBody className="space-y-3">
          <div className="text-sm report-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(cr.description) }} />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div><span className="text-muted-foreground block">{t("plans.requestedBy")}</span><span className="font-mono">{cr.requested_by}</span></div>
            <div><span className="text-muted-foreground block">{t("plans.type")}</span>{cr.effective_change_type ?? cr.requested_change_type}</div>
            <div><span className="text-muted-foreground block">{t("issues.created")}</span>{cr.created_at ? formatFullDate(cr.created_at) : "-"}</div>
            <div><span className="text-muted-foreground block">{t("changes.targets")}</span>
              <div className="flex flex-wrap gap-1">{cr.target_resources.map((x) => <span key={x.resource_id} className="px-1.5 py-0.5 rounded bg-secondary text-xs font-mono" title={typeof x.evidence === "string" ? x.evidence : x.evidence.command}>{x.resource_id}</span>)}
                {cr.target_hints.filter((h) => !cr.target_resources.some((x) => x.resource_id === h || x.hint === h)).map((h) => <span key={h} className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 text-xs font-mono" title="unresolved">{h}?</span>)}</div></div>
          </div>
          {cr.justification && <p className="text-sm text-muted-foreground">{cr.justification}</p>}
        </CardBody></Card>

      {(cr.review_verdict || cr.review_reasons.length > 0) && (
        <Card><CardHeader><h2 className="font-semibold">{t("changes.review")}</h2><span className="text-xs text-muted-foreground">{cr.reviewed_by} · {cr.reviewed_at ? formatFullDate(cr.reviewed_at) : ""}</span></CardHeader>
          <CardBody className="space-y-2 text-sm">
            <div><span className="text-muted-foreground">{t("changes.verdict")}: </span>{cr.review_verdict ?? "-"}{cr.action_type ? ` · ${cr.action_type}` : ""}</div>
            {cr.policy_rule && <div><span className="text-muted-foreground">{t("changes.policy")}: </span><span className="font-mono">{cr.policy_rule} → {cr.policy_action}</span></div>}
            <ul className="list-disc list-inside text-muted-foreground">{cr.review_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
          </CardBody></Card>
      )}

      {plan && (
        <Card><CardHeader><h2 className="font-semibold">{t("changes.plan")} #{plan.id}</h2><FixPlanStatusBadge status={plan.status} /></CardHeader>
          <CardBody>
            <div className="text-muted-foreground mb-4 report-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(plan.summary) }} />
            <ol className="space-y-4">{plan.steps.map((s, i) => <RunbookStep key={i} index={i + 1} step={s} />)}</ol>
            {plan.pre_checks.length > 0 && <div className="mt-6"><h4 className="font-semibold mb-2">{t("issues.preChecks")}</h4><ul className="space-y-1.5">{plan.pre_checks.map((c, i) => <CheckItem key={i} item={c} />)}</ul></div>}
            {plan.post_checks.length > 0 && <div className="mt-6"><h4 className="font-semibold mb-2">{t("issues.postChecks")}</h4><ul className="space-y-1.5">{plan.post_checks.map((c, i) => <CheckItem key={i} item={c} />)}</ul></div>}
            {Object.keys(plan.rollback_plan).length > 0 && <RollbackPlan plan={plan.rollback_plan} />}
          </CardBody></Card>
      )}

      <Card><CardHeader><h2 className="font-semibold">{t("changes.approval")}</h2>
          {cr.approved_by && <span className="text-xs text-muted-foreground">{t("plans.approvedBy")} {cr.approved_by} · {cr.approved_at ? formatFullDate(cr.approved_at) : ""} · {cr.approval_reason}</span>}
          {cr.rejected_by && <span className="text-xs text-red-500">{cr.rejected_by}: {cr.rejection_reason}</span>}
        </CardHeader>
        <CardBody className="flex flex-wrap gap-2">
          {cr.status === "draft" && <button onClick={() => run("review")} className="px-4 py-2 text-sm rounded-lg bg-primary text-primary-foreground">{t("changes.startReview")}</button>}
          {cr.status === "needs_clarification" && (
            <div className="flex gap-2 w-full">
              <input value={clarify} onChange={(e) => setClarify(e.target.value)} className="flex-1 border border-border bg-background rounded-lg px-3 py-2 text-sm" placeholder={cr.review_reasons.join("; ")} />
              <button disabled={!clarify.trim()} onClick={() => { run("clarify", { message: clarify.trim() }); setClarify(""); }} className="px-4 py-2 text-sm rounded-lg bg-primary text-primary-foreground disabled:opacity-50">{t("changes.clarify")}</button>
            </div>
          )}
          {cr.status === "planned" && (<>
            <button onClick={() => setPending({ action: "approve", title: `${t("plans.approveTitle")} C#${cr.id}`, confirmText: t("issues.approve") })} className="px-4 py-2 text-sm rounded-lg bg-emerald-600 text-white">{t("issues.approve")}</button>
            <button onClick={() => setPending({ action: "reject", title: `${t("plans.rejectTitle")} C#${cr.id}`, confirmText: t("issues.reject"), variant: "destructive" })} className="px-4 py-2 text-sm rounded-lg border border-red-500/40 text-red-500">{t("issues.reject")}</button>
          </>)}
          {cr.status === "approved" && (
            <button onClick={async () => { if (await confirm(t("plans.executeConfirm"), { confirmText: t("issues.execute") })) run("execute"); }} className="px-4 py-2 text-sm rounded-lg bg-primary text-primary-foreground">{t("issues.execute")}</button>
          )}
          {["draft", "needs_clarification", "planned", "approved"].includes(cr.status) && (
            <button onClick={() => setPending({ action: "cancel", title: `${t("plans.cancelTitle")} C#${cr.id}`, confirmText: t("common.confirm"), variant: "destructive" })} className="px-4 py-2 text-sm rounded-lg border border-border text-muted-foreground">{t("common.cancel")}</button>
          )}
          {cr.status === "needs_review" && (<>
            <button onClick={() => setPending({ action: "resolve-review", title: t("changes.markCompleted"), confirmText: t("changes.markCompleted"), extra: { outcome: "completed" } })} className="px-4 py-2 text-sm rounded-lg bg-emerald-600 text-white">{t("changes.markCompleted")}</button>
            <button onClick={() => setPending({ action: "resolve-review", title: t("changes.markFailed"), confirmText: t("changes.markFailed"), variant: "destructive", extra: { outcome: "failed" } })} className="px-4 py-2 text-sm rounded-lg border border-red-500/40 text-red-500">{t("changes.markFailed")}</button>
          </>)}
          {["needs_review", "completed", "failed", "rolled_back", "rejected", "cancelled"].includes(cr.status) && (
            <button onClick={() => setCopy(true)} className="px-4 py-2 text-sm rounded-lg border border-border">{t("changes.copyAsNew")}</button>
          )}
        </CardBody></Card>

      {cr.executions.length > 0 && (
        <Card><CardHeader><h2 className="font-semibold">{t("changes.execution")}</h2></CardHeader>
          <CardBody><table className="w-full text-sm"><thead><tr className="border-b border-border text-left text-xs uppercase text-muted-foreground"><th className="py-2">#</th><th>{t("plans.status")}</th><th>{t("issues.executedBy")}</th><th>{t("issues.duration")}</th><th>{t("issues.started")}</th><th></th></tr></thead>
            <tbody className="divide-y divide-border">{cr.executions.map((ex) => (
              <tr key={ex.id}><td className="py-2 font-mono text-muted-foreground">#{ex.id}</td><td>{ex.status}</td><td className="font-mono text-xs">{ex.executed_by}</td>
                <td>{ex.duration_ms > 0 ? `${(ex.duration_ms / 1000).toFixed(1)}s` : "-"}</td><td>{ex.started_at ? formatFullDate(ex.started_at) : "-"}</td>
                <td>{(ex.status === "pending" || ex.status === "running") && <button onClick={() => cancelExec.mutate(ex.id)} className="text-xs text-red-500">{t("common.cancel")}</button>}</td></tr>
            ))}</tbody></table>
            {cr.executions.filter((e) => e.error_message).map((e) => <div key={e.id} className="mt-3 p-3 rounded-lg bg-red-500/10 text-sm text-red-400">#{e.id}: {e.error_message}</div>)}
          </CardBody></Card>
      )}

      <Card><CardHeader><h2 className="font-semibold">{t("changes.timeline")}</h2></CardHeader>
        <CardBody>{tl.isLoading ? <Spinner /> : (
          <ol className="relative border-l border-border ml-3 space-y-4">
            {(tl.data ?? []).map((e, i) => (
              <li key={i} className="ml-4">
                <span className={`absolute -left-[7px] mt-1.5 w-3 h-3 rounded-full ${e.kind === "audit" ? "bg-violet-500" : e.status === "failed" ? "bg-red-500" : "bg-emerald-500"}`} />
                <div className="text-sm"><span className="font-medium">{e.type.replace(/_/g, " ")}</span>{e.status && <span className="ml-2 text-xs text-muted-foreground uppercase">{e.status}</span>}<span className="ml-2 text-xs font-mono text-muted-foreground">{e.actor}</span></div>
                <div className="text-[11px] text-muted-foreground">{e.ts ? formatFullDate(e.ts) : ""}{e.detail && typeof e.detail === "object" && "reason" in (e.detail as Record<string, unknown>) ? ` · ${String((e.detail as Record<string, unknown>).reason)}` : ""}</div>
              </li>
            ))}
          </ol>
        )}</CardBody></Card>

      {pending && <ReasonDialog title={pending.title} confirmText={pending.confirmText} variant={pending.variant} busy={act.isPending}
        onConfirm={(reason) => run(pending.action, { reason, ...(pending.extra ?? {}) })} onClose={() => setPending(null)} />}
      {copy && <NewChangeDialog onClose={() => setCopy(false)} onCreated={() => setCopy(false)}
        initial={{ title: cr.title, description: cr.description, targets: cr.target_hints }} />}
      {dialog}
    </div>
  );
}
```

（`NewChangeDialog.onCreated` 在复制场景里应导航到新单：用 `useNavigate` 并 `navigate(`/app/changes/${id}`)`。`useCancelExecution` 来自 `hooks/useFixExecutions.ts`，已存在。）

- [ ] **Step 3: 编译 + 浏览器走查 + Commit**

```bash
cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build
```
走查：从 Chat 发一条 `/change`… 或用 New change 建单，详情页 5 秒轮询看到 under_review → planned；Approve 弹 ReasonDialog（空理由按钮禁用；ESC 关闭）；Execute 后执行卡出现；时间线含紫色 audit 点。Chat 消息里 `C#N` 可点击跳详情。

```bash
cd /Users/malibo/MyDev/AgenticOps && git add src/agenticops/web/frontend/src/pages/ChangeDetail.tsx src/agenticops/web/frontend/src/lib/renderMarkdown.ts src/agenticops/web/frontend/src/components/plans
git commit -m "feat(web): change request detail page (stepper, review, plan, approval actions, executions, timeline); C#N autolink"
```

---

### Task 5: Audit tab（KPI + Recharts + 两本账）

**Files:**
- Replace: `src/components/plans/AuditTab.tsx`

**Interfaces:**
- Produces: `AuditTab()`：筛选 period（7d/30d/90d）、kind（all/fix/change）；KPI 行 5 张 `StatCard`（变更总数 = change 各状态之和、成功率、中位审批时长、回滚数、被拒写命令数）；Recharts `ComposedChart`（按日 created / completed / failed 堆叠柱）+ `PieChart`（by_risk）；两张 DataTable：决策账本（`useAuditLog({hours})` 过滤 `action` 以 `change.`/`plan.`/`authz.` 开头）与命令账本（`useCommandAudits({period})`）。

- [ ] **Step 1: 实现**

```tsx
import { useState } from "react";
import { Bar, CartesianGrid, Cell, ComposedChart, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { usePlanStats } from "@/hooks/usePlanStats";
import { useAuditLog } from "@/hooks/useAuditLog";
import { useCommandAudits } from "@/hooks/useCommandAudits";
import { useLocale } from "@/i18n/LocaleContext";
import { StatCard } from "@/components/ui/StatCard";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatFullDate } from "@/lib/formatDate";
import type { AuditLogEntry, CommandAudit } from "@/api/types";

const COLORS = ["#3b82f6", "#8b5cf6", "#f59e0b", "#10b981", "#ef4444"];
const HOURS = { "7d": 168, "30d": 720, "90d": 720 } as const;  // /api/audit caps hours at 720

function fmtSecs(s: number | null) { if (s == null) return "-"; if (s < 90) return `${Math.round(s)}s`; if (s < 5400) return `${Math.round(s / 60)}m`; return `${(s / 3600).toFixed(1)}h`; }

export function AuditTab() {
  const { t } = useLocale();
  const [period, setPeriod] = useState<"7d" | "30d" | "90d">("30d");
  const [kind, setKind] = useState<"all" | "fix" | "change">("all");
  const stats = usePlanStats({ period, kind });
  const decisions = useAuditLog({ hours: HOURS[period] });
  const commands = useCommandAudits({ period, limit: 200 });

  if (stats.isLoading) return <Spinner />;
  if (stats.error || !stats.data) return <ErrorBanner message={(stats.error as Error)?.message ?? "no data"} onRetry={() => stats.refetch()} />;
  const s = stats.data;
  const changeTotal = Object.values(s.totals.by_kind_status.change ?? {}).reduce((a, b) => a + b, 0);
  const riskData = Object.entries(s.breakdown.by_risk).map(([name, value]) => ({ name, value }));
  const decisionRows = (decisions.data ?? []).filter((a) => /^(change|plan|authz)\./.test(a.action));

  const dcols: Column<AuditLogEntry & { actor?: string | null }>[] = [
    { key: "ts", header: "Time", render: (a) => <span className="text-xs text-muted-foreground">{formatFullDate(a.timestamp)}</span>, sortable: true, sortValue: (a) => a.timestamp },
    { key: "actor", header: "Actor", render: (a) => <span className="text-xs font-mono">{a.actor ?? a.user_email ?? "system"}</span> },
    { key: "action", header: "Action", render: (a) => <span className="text-xs">{a.action}</span>, sortable: true, sortValue: (a) => a.action },
    { key: "entity", header: "Entity", render: (a) => <span className="text-xs font-mono">{a.entity_type}#{a.entity_id}</span> },
    { key: "reason", header: t("plans.reason"), render: (a) => <span className="text-xs text-muted-foreground">{(a.details as Record<string, unknown> | null)?.reason ? String((a.details as Record<string, unknown>).reason) : "-"}</span> },
  ];
  const ccols: Column<CommandAudit>[] = [
    { key: "ts", header: "Time", render: (c) => <span className="text-xs text-muted-foreground">{formatFullDate(c.created_at)}</span>, sortable: true, sortValue: (c) => c.created_at },
    { key: "actor", header: "Actor", render: (c) => <span className="text-xs font-mono">{c.actor}{c.on_behalf_of ? ` (for ${c.on_behalf_of})` : ""}</span> },
    { key: "tool", header: "Tool", render: (c) => <span className="text-xs">{c.tool}</span> },
    { key: "outcome", header: "Outcome", render: (c) => <span className={`text-xs font-medium ${c.outcome === "executed" ? "text-emerald-500" : c.outcome === "refused" || c.outcome === "blocked" ? "text-amber-500" : "text-red-500"}`}>{c.outcome}{c.reason ? ` · ${c.reason}` : ""}</span>, sortable: true, sortValue: (c) => c.outcome },
    { key: "cmd", header: "Command", render: (c) => <code className="text-[11px] break-all">{c.command.slice(0, 120)}</code> },
    { key: "ref", header: "Ref", render: (c) => <span className="text-xs font-mono text-primary">{c.change_request_id ? `C#${c.change_request_id}` : c.fix_plan_id ? `plan #${c.fix_plan_id}` : "-"}</span> },
  ];

  return (
    <div className="space-y-6">
      <div className="flex gap-2">
        <div className="flex gap-1 bg-secondary rounded-lg p-1">{(["7d", "30d", "90d"] as const).map((p) => <button key={p} onClick={() => setPeriod(p)} className={`px-2 py-1 text-xs rounded ${period === p ? "bg-background shadow" : "text-muted-foreground"}`}>{p}</button>)}</div>
        <div className="flex gap-1 bg-secondary rounded-lg p-1">{(["all", "fix", "change"] as const).map((k) => <button key={k} onClick={() => setKind(k)} className={`px-2 py-1 text-xs rounded ${kind === k ? "bg-background shadow" : "text-muted-foreground"}`}>{k}</button>)}</div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <StatCard label={t("audit.kpi.total")} value={changeTotal} />
        <StatCard label={t("audit.kpi.success")} value={s.outcomes.success_rate == null ? "-" : `${Math.round(s.outcomes.success_rate * 100)}%`} colorClass="text-emerald-500" />
        <StatCard label={t("audit.kpi.leadTime")} value={fmtSecs(s.lead_time.request_to_approve_p50_s)} />
        <StatCard label={t("audit.kpi.rollbacks")} value={s.outcomes.rollbacks} colorClass={s.outcomes.rollbacks ? "text-red-500" : "text-foreground"} />
        <StatCard label={t("audit.kpi.refused")} value={(s.commands.by_outcome.refused ?? 0) + (s.commands.by_outcome.blocked ?? 0)} colorClass="text-amber-500" />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2"><CardHeader><h3 className="font-semibold text-sm">Created / completed / failed per day</h3></CardHeader>
          <CardBody><ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={s.series}><CartesianGrid strokeDasharray="3 3" opacity={0.2} /><XAxis dataKey="bucket" tick={{ fontSize: 10 }} /><YAxis tick={{ fontSize: 10 }} allowDecimals={false} /><Tooltip /><Legend />
              <Bar dataKey="created" stackId="a" fill={COLORS[0]} /><Bar dataKey="completed" stackId="a" fill={COLORS[3]} /><Bar dataKey="failed" stackId="a" fill={COLORS[4]} /></ComposedChart>
          </ResponsiveContainer></CardBody></Card>
        <Card><CardHeader><h3 className="font-semibold text-sm">By risk</h3></CardHeader>
          <CardBody><ResponsiveContainer width="100%" height={240}>
            <PieChart><Pie data={riskData} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80} label>{riskData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}</Pie><Tooltip /></PieChart>
          </ResponsiveContainer></CardBody></Card>
      </div>
      <Card><CardHeader><h3 className="font-semibold text-sm">{t("audit.decisions")}</h3><span className="text-xs text-muted-foreground">auto {s.approvals.auto} · human {s.approvals.human} · denied {s.approvals.authz_denied} (+{s.approvals.authz_denied_shadow} shadow)</span></CardHeader>
        <CardBody>{decisions.isLoading ? <Spinner /> : <DataTable columns={dcols} data={decisionRows} rowKey={(a) => a.id} emptyMessage={t("common.noData")} />}</CardBody></Card>
      <Card><CardHeader><h3 className="font-semibold text-sm">{t("audit.commands")}</h3></CardHeader>
        <CardBody>{commands.isLoading ? <Spinner /> : <DataTable columns={ccols} data={commands.data ?? []} rowKey={(c) => c.id} emptyMessage={t("common.noData")} />}</CardBody></Card>
    </div>
  );
}
```

`hooks/useAuditLog.ts` 的 `AuditLogEntry` 需含 `actor?: string | null`（Plan A 已让 `/api/audit` 返回 `actor`）——在 `types.ts` 的 `AuditLogEntry` 加 `actor: string | null`。`GET /api/audit` 在 Plan B Task 11 已改为 `current_actor` + `authz.check("audit.read")`（认证关闭时影子模式放行），所以这里直接用 `useAuditLog`。

- [ ] **Step 2: 编译 + 走查 + Commit**

```bash
cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build
cd /Users/malibo/MyDev/AgenticOps && git add src/agenticops/web/frontend/src/components/plans/AuditTab.tsx src/agenticops/web/frontend/src/api/types.ts
git commit -m "feat(web): Audit tab — plan/change KPIs, charts, decision and command ledgers"
```

---

### Task 6: 既有页面修正 — Dashboard「Active Plans」、ContextPanel 审批卡、IssueDetail 审批卡、Settings→Audit 的 actor 列

**Files:**
- Modify: `src/pages/Dashboard.tsx:165-200`、`src/components/chat/ContextPanel.tsx:324-411`、`src/pages/IssueDetail.tsx`（`FixPlanTab` 审批卡 :692-745 与 `approverName` 状态）、`src/components/settings/AuditTab.tsx`（列表加 Actor 列）、`src/locales/*.json`（`dashboard.activePlans`）

**Interfaces:** 无新符号。行为契约：不再有任何地方把审批人名字从客户端发给后端；approve 可选理由、reject 必填理由，都走 `ReasonDialog`；Dashboard 卡同时展示 fix 与 change 两类未完成计划并按 kind 跳转。

- [ ] **Step 1: Dashboard**

`Dashboard.tsx`：`useFixPlans()` 保持（现在返回两种 kind）；卡标题键改 `dashboard.activePlans`（en "Active Plans" / zh "进行中的计划"）；每张卡加 kind 徽标：`<span className="text-[10px] uppercase tracking-wider text-muted-foreground">{fp.plan_kind}</span>`；点击 `fp.plan_kind === "change" ? navigate(`/app/changes/${fp.change_request_id}`) : navigate(`/app/issues/${fp.health_issue_id}`)`；引用文本 `fp.plan_kind === "change" ? `C#${fp.change_request_id}` : `I#${fp.health_issue_id}``。

- [ ] **Step 2: ContextPanel `FixPlanCard`**

删掉 `approved_by: "web-user"`：Approve 按钮打开 `ReasonDialog`（`required={false}`）→ `approveMut.mutate({ id: fp.id, reason })`；Reject 打开 `ReasonDialog`（`variant="destructive"`）→ `rejectMut.mutate({ id: fp.id, reason })`。在 `FixPlanCard` 内用 `useState<"approve"|"reject"|null>` 管理弹窗。"Approved by X" 行保留（现在显示 actor key）。

- [ ] **Step 3: IssueDetail 审批卡**

删除 `approverName` / `setApproverName` / `showApproveForm` 三个 state 与相关 props（`FixPlanTab` 签名同步瘦身）；审批卡改为两个按钮 + `ReasonDialog`（approve 理由可选、reject 必填）；`handleReject` 不再用 `confirm`。`issues.approverPlaceholder` 键可删除（两份 locale 同步删）。

- [ ] **Step 4a: Settings → General 的两个新开关**

`pages/Settings.tsx` 里 `executor_auto_approve_l0_l1` 的开关（:1247 附近）之后，照同样的 `<Toggle enabled={s.change_auto_approve_standard} onChange={(v) => patchSetting("change_auto_approve_standard", v)} />` 与 `rbac_enforce` 各加一条（标题/说明键：`settings.changeAutoApprove` "Auto-approve standard changes" / "Policy-approved L0/L1 changes run without a human approver"；`settings.rbacEnforce` "Enforce RBAC" / "Turn shadow mode into 403 + separation of duties"；zh 同步）。`GET /api/settings` 已在 Plan B Task 11 返回这两个键；`api/types.ts` 的 Settings 类型加两个 boolean。

- [ ] **Step 4: Settings → Audit tab**

`components/settings/AuditTab.tsx` 的列定义在 `user_email` 前加 `{ key: "actor", header: "Actor", render: (a) => <span className="text-xs font-mono">{a.actor ?? a.user_email ?? "system"}</span> }`。

- [ ] **Step 5: 编译 + 走查 + Commit**

```bash
cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build
```
走查：IssueDetail 的 fix plan 审批（无名字输入框，弹理由框）、Chat 右侧 ContextPanel 审批、Dashboard 卡跳转两种详情。

```bash
cd /Users/malibo/MyDev/AgenticOps && git add src/agenticops/web/frontend/src/pages/Dashboard.tsx src/agenticops/web/frontend/src/components/chat/ContextPanel.tsx src/agenticops/web/frontend/src/pages/IssueDetail.tsx src/agenticops/web/frontend/src/components/settings/AuditTab.tsx src/agenticops/web/frontend/src/locales
git commit -m "fix(web): identity-bound approvals everywhere (reason dialogs, no client-supplied approver); Active Plans shows both kinds"
```

---

### Task 7: 文档 — 发布说明、WORKFLOW、双语 README、文档地图、CLAUDE.md、harness 附注

**Files:**
- Create: `docs/MVP-2.6.0-RELEASE.md`
- Modify: `docs/WORKFLOW.md`（在 `## Cloud Security Review (MVP-2.5.0)` 之后加 `## Change Management (MVP-2.6.0)`；`## CLI Slash Command Quick Reference` 加 5 条；`## API Quick Reference (curl)` 加 changes 段；Tutorials 加 `### Tutorial 13: Request and Approve a Change`）
- Modify: `README.md` 与 `README_CN.md`（版本行 :9-11、历史表 :336 之前加 2.6.0 行、功能列表加一条）
- Modify: `docs/README.md`（§2 发布表加 2.6.0 行）
- Modify: `CLAUDE.md`（Project Overview 的文档指针加 2.6.0；Architecture 段加 Change 流一句；Key Modules 表加 `services/change_service.py`、`auth/actor.py`+`authz.py`、`run_context.py`、`tools/change_tools.py`、`web/routers/{changes,plans}.py` 行；`## HealthIssue State Machine` 后加 `## Plan & ChangeRequest State Machines` 小节；配置表已在 Plan A/B 加行——核对）
- Modify: `docs/superpowers/plans/2026-09-09-harness-engineering-architecture-update.md`（§二 循环状态机末尾加 “Change Loop（第三种 loop，MVP-2.6.0 已落地）” 附注，5-8 行）

- [ ] **Step 1: `docs/MVP-2.6.0-RELEASE.md`**

按 `MVP-2.5.0-RELEASE.md` 的体例写（顶部引用块 → 一句话 → 定位 → 研发宪法（本方向三条不变量：终态只由代码写 / 目标不可实证不出计划 / 自动审批双开关）→ 架构（复用 spec §2 图）→ 数据模型概览（`change_requests`、`plan_kind`、`command_audits`、`audit_logs.actor`）→ 新增配置（七项，表格）→ 六个可达面表（做/非目标，含 P2/P3 去向）→ 明确不做 → 验收纲要（spec §8 八条）→ P1 交付状态（S0–S6，执行时填 ✅ 与 commit 范围）→ Roadmap：P2 Runbook 模板库 + GitHub Webhook 部署变更、P3 逐步交互执行 + IM 审批卡片、Harness Phase 1 收编 `on_execution_result` 为 VerifyGate）。状态行写 "P1 已实现，live E2E 见 `docs/MVP-2.6.0-E2E-REPORT.md`，push 待主人确认"——Task 8 完成后再改为已 push。

- [ ] **Step 2: `docs/WORKFLOW.md`**

新节包含：一段说明（Incident 流 vs Change 流的区别：无 HealthIssue、SRE 审核合法性、人工审批默认必需）、一张 Mermaid `stateDiagram-v2`（CR 12 个状态与转换，直接照 `CHANGE_TRANSITIONS`）、一张 Mermaid `sequenceDiagram`（User → Main → request_change/review_change → SRE Mode C（ground / policy / save plan / verdict）→ change_service → 通知审批人 → Web approve → request_execution → ExecutorService → executor_agent → on_execution_result）、两本账说明（`audit_logs` 决策 / `command_audits` 命令；`change_required` 拒绝）、RBAC 影子模式说明（`rbac_enforce`、SoD、`config/rbac.yaml`）。Slash 参考加 `/change` `/changes` `/approve C<id>` `/reject C<id>` `/execute C<id>`；API 参考加 `POST /api/changes`、`GET /api/changes/{id}`、`POST /api/changes/{id}/approve`、`GET /api/plans/stats`、`GET /api/command-audits` 的 curl 例。Tutorial 13：从 Chat 输入 → 看 C# → Web 审批 → 执行 → Audit tab 六步。

- [ ] **Step 3: README 双语同步**

`README.md` :9 版本行改为 `**Version**: 2.6.0 · **Latest release**: [Change Management — ITSM change flow (request → SRE review → approval → Executor), audit ledgers and an RBAC seam](docs/MVP-2.6.0-RELEASE.md)`；:11 成熟度段加一句 "Change Management P1 was validated with a live tag change on a real account ([E2E](docs/MVP-2.6.0-E2E-REPORT.md))."；历史表 2.5.0 行之前插入：

```
| **[2.6.0](docs/MVP-2.6.0-RELEASE.md)** | 2026-09-XX | **Change Management** — ITSM change requests separate from incidents: `request_change`/`review_change` (SRE Mode C: grounding fail-closed, policy engine, mandatory rollback + post-checks), identity-bound approvals with mandatory reasons, separation of duties behind `rbac_enforce` (shadow mode by default), **two audit ledgers** (`audit_logs` decisions, `command_audits` write-tier commands incl. refused `change_required` attempts), `/app/plans` (Fix Plans · Change Plans · Audit) + `/app/changes/:id`, `/api/changes/*`, `/api/plans/stats` — validated with a live EC2 tag change ([E2E](docs/MVP-2.6.0-E2E-REPORT.md)) |
```

`README_CN.md` 对应行中文（段落一一对应）。功能列表段（搜索 "Cloud Security Review" 所在的 features 列表）各加一条 Change Management。

- [ ] **Step 4: `docs/README.md`、`CLAUDE.md`、harness 附注**

`docs/README.md` §2 表加 `| 2.6.0 | 2026-09-XX | [MVP-2.6.0-RELEASE.md] | [MVP-2.6.0-E2E-REPORT.md] |`（日期在 Task 8 后填）。CLAUDE.md 按上面 Files 列表逐项加；`## Plan & ChangeRequest State Machines` 小节写两组转换（照 `PLAN_TRANSITIONS` / `CHANGE_TRANSITIONS`），并注明 "终态只由 `change_service.on_execution_result` / `resolve_review` 写"。harness 计划附注：Change Loop 状态列表、复用 Remediation 尾段、`on_execution_result` 是 VerifyGate 雏形、Phase 1 收编。

- [ ] **Step 5: Commit**

```bash
git add docs/MVP-2.6.0-RELEASE.md docs/WORKFLOW.md README.md README_CN.md docs/README.md CLAUDE.md docs/superpowers/plans/2026-09-09-harness-engineering-architecture-update.md
git commit -m "docs: MVP-2.6.0 change management — release notes, workflow (state + sequence diagrams), bilingual README, docs map, CLAUDE.md, harness addendum"
```

---

### Task 8: Live E2E（真实账户，tag 变更）→ `docs/MVP-2.6.0-E2E-REPORT.md` → 主人确认 → push

**Files:**
- Create: `docs/MVP-2.6.0-E2E-REPORT.md`
- Modify: `docs/MVP-2.6.0-RELEASE.md`、`docs/README.md`、`README.md`、`README_CN.md`（填日期、状态改为已 push——push 之后再改并追加一个 commit）

**Interfaces:** 无。**前置条件（人工确认后再跑）**：在 dev 账户里选定一台低风险 EC2 实例（如 opsagent 或 EKS lab 节点）作为 tag 目标；确认 `settings.yaml` 的 `executor_enabled: true`、`change_management_enabled: true`、`change_auto_approve_standard: false`、`rbac_enforce: false`；后端与前端在本机跑（`uvicorn … --port 8000` + `npm run dev`），或使用 dev 部署（`iac/deploy-sg/deploy.sh redeploy MVP-2.5.0`）——报告里写清用了哪一个。

- [ ] **Step 1: 全量回归 + 构建（报告 Test 1/2）**

```bash
python -m pytest tests/ -q > /tmp/e2e-full.log 2>&1; tail -5 /tmp/e2e-full.log
cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build; cd -
```
记录 passed/failed 数字与构建产物（`Plans*.js`/`ChangeDetail*.js` chunk）。

- [ ] **Step 2: Chat 建单 + 审核（Test 3）**

Web Chat 输入：`给 EC2 实例 <i-xxxxxxxx> 加一个 tag ChangeTest=2026-09-17`。期望：Main 调 `request_change` → `review_change`；回复含 `C#N`、风险 L1、verdict approved_for_planning、计划含 `aws ec2 create-tags` 步骤、`describe-tags` post_check、`delete-tags` rollback。记录 trace_id。用 `sqlite3`/API 核对：`GET /api/changes/N` status=planned、`effective_change_type=standard`、`policy_rule=change-standard-low-risk`；`GET /api/command-audits?change_request_id=N` **无** `outcome=executed` 行。

- [ ] **Step 3: Web 审批 + 执行（Test 4）**

`/app/changes/N`：Approve → ReasonDialog 填 "E2E approval" → status approved；Execute → 确认 → executing；等待 ExecutorService（≤30s 轮询）→ 详情页轮询到 completed。核对：`aws ec2 describe-tags --filters Name=resource-id,Values=<i-xxx> Name=key,Values=ChangeTest`（经 CLI 或 Chat 只读查询）返回该 tag；`GET /api/changes/N/timeline` 含 `change.requested / change.reviewed / change.approved / change.execution_started / change.completed`；`GET /api/command-audits?change_request_id=N` 有 `create-tags` 行 `outcome=executed`、`actor=agent:executor`、`on_behalf_of=web:anonymous`（或登录用户）。

- [ ] **Step 4: Audit tab（Test 5）**

`/app/plans?tab=audit`：KPI 变更总数 ≥1、成功率 100%、中位审批时长 > 0；决策账本出现 5 条 change.* 行；命令账本出现 create-tags 行。截图（Playwright MCP `browser_take_screenshot`）存 `docs/assets/`（若该目录存在；否则只贴文字）。

- [ ] **Step 5: 第二个变更删除 tag（Test 6）**

同路径提交 "删除 <i-xxx> 的 tag ChangeTest"，审批 → 执行 → completed；`describe-tags` 确认 tag 消失；stats `totals.by_kind_status.change.completed == 2`。

- [ ] **Step 6: RBAC 强制模式抽查（Test 7）**

SoD 只在有身份的 actor 之间生效（匿名 Web 主体豁免——Plan A 裁决），所以用 CLI 身份演示：在 REPL 用 `/change …` 建一个变更并让它到 planned（不执行）；临时 `AIOPS_RBAC_ENFORCE=true` 重启后端与 REPL；同一 OS 用户 `/approve C<id> 理由` → 红色 403 文案（申请人=审批人）；`GET /api/audit?action=authz.denied` 有一行；恢复 `false` 重启；把该变更 cancel（理由 "E2E cleanup"）。

- [ ] **Step 7: Chat 直接写路径（Test 8）**

Chat：`用 aws cli 给 <i-xxx> 加 tag Direct=1`（不说"变更"）→ 若 Main 走 sre_query 直接写并确认，则 `command_audits` 出现 `executed` 行且**无** change_request_id（直接写被记账）；随后 Chat：`aws ec2 modify-security-group-rules --group-id <sg-xxx> …`（任选一条不会真正生效的命令，如指向不存在的 rule id）→ 期望被 `change_required` 拒绝并提示 `/change`，账本 `outcome=refused reason=change_required`。清理：删掉 `Direct=1` tag（Chat 只读查询确认）。

- [ ] **Step 8: 写报告**

`docs/MVP-2.6.0-E2E-REPORT.md` 按 2.5.0 报告体例：Environment 表（账户、目标实例、DB、模型、Python、运行方式）→ Test 1–8 各一节（命令 + 关键输出摘录 + ✅/❌）→ Observations（发现的非阻断问题）→ Conclusion（八条验收标准逐条对照 spec §8）。**写操作清单**单独一节：create-tags ×2（ChangeTest、Direct）、delete-tags ×2，全部已清理。

```bash
git add docs/MVP-2.6.0-E2E-REPORT.md
git commit -m "docs(e2e): MVP-2.6.0 change management live E2E report (real account, tag change round-trip)"
```

- [ ] **Step 9: 主人确认 → push → 收尾**

向主人汇报：全量测试数字、E2E 八步结果、写操作清单、未解决观察项。**等主人明确确认后**：

```bash
git push --no-verify origin MVP-2.5.0   # 或主人指定的分支
```
push 后把 `docs/MVP-2.6.0-RELEASE.md` 状态行改为 "已于 <日期> 经主人确认 push"、`docs/README.md`/`README.md`/`README_CN.md` 的 2.6.0 日期填实，再提交一次并 push。

## 执行记录

（执行时追加：日期 · tsc/build 结果 · 走查结论 · E2E 报告链接 · push 时间与主人确认记录）
