import type { Anomaly, ChangeRequest } from "@/api/types";
import { isBlank } from "@/lib/issueDetail";
import { issuePhases, type PhaseView } from "@/lib/issuePhases";
import { changePhases } from "@/lib/changePhases";

export interface WorkItemRow {
  key: string; ref: string; href: string; title: string; subtitle: string | null;
  statusKey: string; dots: PhaseView[]; waitKey: string | null; level: string | null; account: string | null; updated: string | null;
}

/** An issue list row. The list has no RCA or runs, so the wait comes from list-mode issuePhases (R2). */
export function issueRow(a: Anomaly): WorkItemRow {
  const p = issuePhases({ status: a.status });
  const sub = [a.resource_type, a.resource_id].filter((x) => !isBlank(x)).join(" · ");
  return { key: `I${a.id}`, ref: `I#${a.id}`, href: `/app/issues/${a.id}`, title: a.title, subtitle: sub || null,
           statusKey: `issues.status.${a.status}`, dots: p.phases, waitKey: p.waitingFor ? `workitem.wait.${p.waitingFor}` : null,
           level: a.severity, account: a.account_name, updated: a.resolved_at ?? a.detected_at };
}

/** A change list row; a closed change's "wait" column says its next step (copy as new) instead. */
export function changeRow(cr: ChangeRequest, accountName?: string | null): WorkItemRow {
  const p = changePhases(cr);
  const ext = cr.external_ref ? `${cr.external_ref.system} ${cr.external_ref.ticket_id}` : null;
  return { key: `C${cr.id}`, ref: `C#${cr.id}`, href: `/app/changes/${cr.id}`, title: cr.title,
           subtitle: [cr.requested_by, ext].filter(Boolean).join(" · ") || null,
           statusKey: `changes.status.${cr.status}`, dots: p.phases,
           waitKey: p.waitingFor ? `workitem.wait.${p.waitingFor}` : p.primary === "copyAsNew" ? "workitem.primary.copyAsNew" : null,
           level: cr.risk_level, account: accountName ?? null, updated: cr.updated_at ?? cr.created_at };
}
