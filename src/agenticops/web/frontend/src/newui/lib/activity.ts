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
  /** how the server knows: a person asked and this process is on it ("requested"), a run row, a status, an event… —
   *  or "stopped": the status says «investigating» but the timeline says the diagnosis ended */
  basis: string;
  requested_by: string | null;
  /** N26: false = a person asked for this run, and it is not this person (nor are they an administrator) — it takes
   *  no word from them. Absent on lanes that take notes from anyone who may write them (and on an older server). */
  notes_from_you?: boolean;
  /** it outlived its own watchdog */
  overdue: boolean;
  route: string | null;
  /** a run lane's run record (N9): what a stop names — and who already asked it to stop. Absent when the server
   *  knows of the run by a status or an event alone. */
  execution?: { id: number; status: string; stop_requested_at: string | null; stop_requested_by: string | null };
}
export interface ActivityUpcoming { id: string; kind: string; agent: string; title: string; at: string; route: string | null }
export interface ActivityRecent {
  id: string; kind: string; agent: string; item: string | null; ref: string | null; title: string; account_id: number | null;
  at: string | null; outcome: "done" | "failed" | "needs_you"; route: string | null;
}
export interface Activity {
  running: ActivityLane[]; upcoming: ActivityUpcoming[]; recent: ActivityRecent[]; generated_at: string;
  /** how many ended in the last day — `recent` is the newest few of each: the agents' work on items, and schedule runs */
  recent_total?: { work: number; schedules: number };
}

/** The agent run a person asked for on this item that is still in flight — the server's record, so a reload or
 *  another browser sees it too. */
export function requestedRun(activity: Activity | undefined, item: string): ActivityLane | null {
  return activity?.running.find((l) => l.item === item && l.basis === "requested") ?? null;
}

/** Any agent at work on this item; a run a person asked for comes first, then the plan run the pipeline started
 *  (both are claims this process holds). A diagnosis the server lists as `stopped` (its end is on the timeline, the
 *  status stayed «investigating») is nobody at work. */
export function agentOn(activity: Activity | undefined, item: string): ActivityLane | null {
  return requestedRun(activity, item) ?? activity?.running.find((l) => l.item === item && l.basis === "pipeline")
    ?? activity?.running.find((l) => l.item === item && l.basis !== "stopped") ?? null;
}

/** The diagnosis of this item that ended while its status stayed «investigating»: nothing is working on it. */
export function stoppedOn(activity: Activity | undefined, item: string): ActivityLane | null {
  return activity?.running.find((l) => l.item === item && l.basis === "stopped") ?? null;
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
