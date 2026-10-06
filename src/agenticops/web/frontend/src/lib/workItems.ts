import type { Anomaly, ChangeRequest, FixPlan } from "@/api/types";
import { isBlank } from "@/lib/issueDetail";
import { issuePhases, type PhaseState, type PhaseView } from "@/lib/issuePhases";
import { PLAN_TERMINAL_STATUSES, planRef } from "@/lib/plans";
import { changePhases } from "@/lib/changePhases";

/** "critical": an open critical issue (tinted); "closed": a resolved / dismissed issue or a closed change (dimmed). */
export type RowEmphasis = "critical" | "closed" | null;

export interface WorkItemRow {
  key: string; ref: string; href: string; title: string;
  subtitle: string | null; subtitleFull: string | null; // shortened for the row / untruncated for its tooltip
  statusKey: string; dots: PhaseView[]; waitKey: string | null; level: string | null;
  typeKey: string | null; // a change's type (standard / normal / emergency), shown with its risk
  recurrence: number;     // signals the Signal Gate merged into the issue; 1 = it happened once
  emphasis: RowEmphasis;
  account: string | null; time: string | null;
}

/** An ARN's tail is the resource's own name; a long id keeps its last 28 characters (the end carries the signal). */
export function shortId(id: string): string {
  const rid = id.startsWith("arn:") ? id.split(/[/:]/).filter(Boolean).pop() ?? id : id;
  return rid.length > 28 ? "…" + rid.slice(-28) : rid;
}

/** An issue list row. The list has no RCA or runs, so the wait comes from list-mode issuePhases (R2). */
export function issueRow(a: Anomaly): WorkItemRow {
  const p = issuePhases({ status: a.status });
  const [type, id, region] = [a.resource_type, a.resource_id, a.region].map((x) => (isBlank(x) ? null : x));
  const closed = a.status === "resolved" || a.status === "dismissed";
  return { key: `I${a.id}`, ref: `I#${a.id}`, href: `/app/issues/${a.id}`, title: a.title,
           subtitle: [type, id && shortId(id), region].filter(Boolean).join(" · ") || null,
           subtitleFull: [type, id, region].filter(Boolean).join(" · ") || null,
           statusKey: `issues.status.${a.status}`, dots: p.phases, waitKey: p.waitingFor ? `workitem.wait.${p.waitingFor}` : null,
           level: a.severity, typeKey: null, recurrence: a.occurrence_count ?? 1,
           emphasis: closed ? "closed" : a.severity === "critical" ? "critical" : null,
           account: a.account_name, time: a.detected_at };
}

/** A change list row; a closed change's "wait" column says its next step (copy as new) instead. */
export function changeRow(cr: ChangeRequest, accountName?: string | null): WorkItemRow {
  const p = changePhases(cr);
  const ext = cr.external_ref ? `${cr.external_ref.system} ${cr.external_ref.ticket_id}` : null;
  const sub = [cr.requested_by, ext].filter(Boolean).join(" · ") || null;
  const type = cr.effective_change_type ?? cr.requested_change_type;
  return { key: `C${cr.id}`, ref: `C#${cr.id}`, href: `/app/changes/${cr.id}`, title: cr.title,
           subtitle: sub, subtitleFull: sub,
           statusKey: `changes.status.${cr.status}`, dots: p.phases,
           waitKey: p.waitingFor ? `workitem.wait.${p.waitingFor}` : p.primary === "copyAsNew" ? "workitem.primary.copyAsNew" : null,
           level: cr.risk_level, typeKey: type ? `plans.changeType.${type}` : null, recurrence: 1,
           emphasis: p.terminal ? "closed" : null,
           account: accountName ?? null, time: cr.updated_at ?? cr.created_at };
}

const planDots = (status: string): PhaseView[] => {
  const two = (approve: PhaseState, run: PhaseState): PhaseView[] => [{ id: "approve", state: approve }, { id: "run", state: run }];
  switch (status) {
    case "draft": case "pending_approval": return two("current", "future");
    case "approved": case "executing": return two("done", "current");
    case "executed": return two("done", "done");
    case "failed": return two("done", "failed");
    case "rejected": return two("failed", "future");
    default: return two("future", "future");
  }
};

/** A fix-plan row of the hub (MVP-2.7.0 S3): ① approval ② run; who waits only where the list can tell. */
export function fixPlanRow(p: FixPlan, accountName?: string | null): WorkItemRow {
  const rid = p.target?.resource_id ?? null;
  const wait = p.status === "draft" || p.status === "pending_approval" ? "workitem.wait.approver"
    : p.status === "executing" ? "workitem.wait.executor" : null;
  return { key: `P${p.id}`, ref: `${planRef(p)} v${p.plan_version || 1}`, href: `/app/plans/${p.id}`, title: p.title,
           subtitle: [p.issue_title, rid && shortId(rid)].filter(Boolean).join(" · ") || null,
           subtitleFull: [p.issue_title, rid].filter(Boolean).join(" · ") || null,
           statusKey: `plans.planStatus.${p.status}`, dots: planDots(p.status), waitKey: wait,
           level: p.risk_level, typeKey: null, recurrence: 1,
           emphasis: PLAN_TERMINAL_STATUSES.has(p.status) ? "closed" : null,
           account: accountName ?? null, time: p.updated_at ?? p.created_at };
}
