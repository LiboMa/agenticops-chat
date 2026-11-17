/** GET /api/ui/activity (services/activity): what agents are doing now, what is scheduled next, what ended lately —
 *  each from state the server can check. */

export interface ActivityLane {
  id: string;
  kind: "diagnosis" | "plan" | "run" | "change_review" | "change_run" | "schedule" | "graph_build" | string;
  agent: string;
  /** the work item it belongs to ("I12" / "C3"); null for a job that belongs to none */
  item: string | null;
  ref: string | null;
  title: string;
  account_id: number | null;
  /** when it started; null = nothing on record says */
  since: string | null;
  /** how the server knows: a person asked and this process is on it ("requested"), a run row, a status, an event… */
  basis: string;
  requested_by: string | null;
  /** it outlived its own watchdog */
  overdue: boolean;
  route: string | null;
}
export interface ActivityUpcoming { id: string; kind: string; agent: string; title: string; at: string; route: string | null }
export interface ActivityRecent {
  id: string; kind: string; agent: string; item: string | null; ref: string | null; title: string; account_id: number | null;
  at: string | null; outcome: "done" | "failed" | "needs_you"; route: string | null;
}
export interface Activity { running: ActivityLane[]; upcoming: ActivityUpcoming[]; recent: ActivityRecent[]; generated_at: string }

/** The agent run a person asked for on this item that is still in flight — the server's record, so a reload or
 *  another browser sees it too. */
export function requestedRun(activity: Activity | undefined, item: string): ActivityLane | null {
  return activity?.running.find((l) => l.item === item && l.basis === "requested") ?? null;
}

/** Any agent at work on this item; a run a person asked for comes first. */
export function agentOn(activity: Activity | undefined, item: string): ActivityLane | null {
  return requestedRun(activity, item) ?? activity?.running.find((l) => l.item === item) ?? null;
}

/** The rail beside the brief: everything running, then the newest few that ended. */
export function railRows(activity: Activity | undefined, recentMax = 4): { running: ActivityLane[]; recent: ActivityRecent[] } {
  return { running: activity?.running ?? [], recent: (activity?.recent ?? []).slice(0, recentMax) };
}

/** An actor key as a person reads it: «you» for the signed-in person, the name without its kind otherwise; an
 *  agent keeps its kind (agent:executor is not a person called «executor»). */
export function whoText(actor: string | null | undefined, me: string | null | undefined, t: (key: string) => string): string {
  if (!actor) return "";
  if (me && actor === `user:${me}`) return t("who.you");
  return /^(user|cli|web|im):/.test(actor) ? actor.slice(actor.indexOf(":") + 1) : actor;
}
