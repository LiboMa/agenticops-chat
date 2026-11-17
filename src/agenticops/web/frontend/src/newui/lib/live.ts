import { parseApiDate } from "@/lib/formatDate";
import type { Activity } from "./activity";

/** «现场»: everything on GET /api/ui/activity as one list of lanes — what is at work now, what is due next, what ended
 *  lately. The server builds it only from state it can check; nothing here adds to that. */

/** running = at work now · stalled = listed by the server among the running ones, yet nothing is at work (a diagnosis
 *  that ended while its status stayed) · upcoming = due next · recent = ended in the last day */
export type LaneGroup = "running" | "stalled" | "upcoming" | "recent";
export const LANE_GROUPS: readonly LaneGroup[] = ["running", "stalled", "upcoming", "recent"];

export interface LaneView {
  /** unique across the three groups (a schedule that is running and due again is two lanes) */
  id: string;
  group: LaneGroup;
  kind: string;
  agent: string;
  /** the work item it belongs to ("I12" / "C3"); null for a job that belongs to none */
  item: string | null;
  ref: string | null;
  title: string;
  /** running: since when · upcoming: when it is due · recent: when it ended; null = nothing on record says */
  at: string | null;
  /** the lane's edge: at work · outlived its own limit · scheduled · ended well · failed, or a run a person
   *  stopped (the design's red: stop and roll back) · ended and waits on a person */
  tone: "run" | "late" | "wait" | "done" | "bad" | "you";
  /** how the server knows a running lane is running */
  basis: string | null;
  requestedBy: string | null;
  overdue: boolean;
  /** listed among the running ones, but nothing is at work: a diagnosis that ended while its status stayed */
  stopped: boolean;
  outcome: "done" | "failed" | "needs_you" | null;
  /** the classic page of the thing */
  route: string | null;
  /** the row that ended (a run, a diagnosis, a plan, a schedule run) — what a recent lane's result is fetched by */
  row: number | null;
  /** a run in flight: its run record — what «stop» names, and who already asked it to stop (N9) */
  execution: { id: number; status: string; stopRequestedAt: string | null; stopRequestedBy: string | null } | null;
}

const OUTCOME_TONE = { done: "done", failed: "bad", needs_you: "you" } as const;
const rowOf = (id: string): number | null => {
  const m = /^(?:X|R|P|SE)(\d+)$/.exec(id);
  return m ? Number(m[1]) : null;
};

export function laneViews(activity: Activity | undefined): LaneView[] {
  if (!activity) return [];
  const stopped = (l: { basis: string }) => l.basis === "stopped";
  const live = [...activity.running.filter((l) => !stopped(l)), ...activity.running.filter(stopped)];
  return [
    ...live.map((l): LaneView => ({
      id: l.id, group: stopped(l) ? "stalled" : "running", kind: l.kind, agent: l.agent, item: l.item, ref: l.ref, title: l.title, at: l.since,
      tone: l.execution?.stop_requested_at ? "bad" : l.overdue ? "late" : "run", basis: l.basis, requestedBy: l.requested_by,
      overdue: l.overdue, stopped: stopped(l),
      outcome: null, route: l.route, row: null,
      execution: l.execution ? { id: l.execution.id, status: l.execution.status, stopRequestedAt: l.execution.stop_requested_at,
                                 stopRequestedBy: l.execution.stop_requested_by } : null,
    })),
    ...activity.upcoming.map((l): LaneView => ({
      id: `next:${l.id}`, group: "upcoming", kind: l.kind, agent: l.agent, item: null, ref: null, title: l.title, at: l.at,
      tone: "wait", basis: null, requestedBy: null, overdue: false, stopped: false, outcome: null, route: l.route, row: null,
      execution: null,
    })),
    ...activity.recent.map((l): LaneView => ({
      id: l.id, group: "recent", kind: l.kind, agent: l.agent, item: l.item, ref: l.ref, title: l.title, at: l.at,
      tone: OUTCOME_TONE[l.outcome] ?? "done", basis: null, requestedBy: null, overdue: false, stopped: false, outcome: l.outcome, route: l.route,
      row: rowOf(l.id), execution: null,
    })),
  ];
}

/** Whether the opened lane's run can be stopped (N9). "can": a run in progress whose record the page can name and
 *  nobody has stopped yet. "stopping": a person already asked — the executor finishes the command it is on and may
 *  then only roll back. null: anything else — a diagnosis, a run known by its status alone or not started yet, a
 *  lane that ended. Who MAY stop is the server's answer (plan.execute); a read-only account is not offered it. */
export type StopState = "can" | "stopping" | null;
export function stopState(lane: LaneView | null): StopState {
  if (!lane || lane.group !== "running" || (lane.kind !== "run" && lane.kind !== "change_run")) return null;
  const x = lane.execution;
  if (!x || x.status !== "running") return null;
  return x.stopRequestedAt ? "stopping" : "can";
}

/** How many lanes are at work within their own time limit — the number beside the «现场» tab. A diagnosis that
 *  stopped is not at work; work that outlived its limit is listed and flagged, but not counted as going on.
 *  undefined = not known yet. */
export function atWork(activity: Activity | undefined): number | undefined {
  return activity?.running.filter((l) => l.basis !== "stopped" && !l.overdue).length;
}

/** When «ended in the last day» shows only the newest of what ended: how many are shown and how many there were, for
 *  the agents' work on items and for schedule runs. null = everything is listed, or the server did not count. */
export function recentCut(activity: Activity | undefined):
    { work: { shown: number; total: number } | null; schedules: { shown: number; total: number } | null } | null {
  const total = activity?.recent_total;
  if (!activity || !total) return null;
  const schedules = activity.recent.filter((l) => l.kind === "schedule").length, work = activity.recent.length - schedules;
  const cut = (shown: number, all: number) => (all > shown ? { shown, total: all } : null);
  const out = { work: cut(work, total.work), schedules: cut(schedules, total.schedules) };
  return out.work || out.schedules ? out : null;
}

export interface LanePick {
  /** none = the address names no lane (the first one is shown) · found · moved = the lane that was being watched
   *  ended and this is what it left behind · ended = it ended and nothing made since it began is listed · gone =
   *  nothing of it is listed and nothing is known about it (never another lane in its place) */
  state: "none" | "found" | "moved" | "ended" | "gone";
  lane: LaneView | null;
}

/** Which lane the address means. A running lane's id says its item and its kind ("I12:diagnosis"); once it ends it
 *  is listed under what it produced ("R9"). `since` = when the running lane began, as the page saw it while it was
 *  listed: only a result made at or after that is «what it left behind» — a run that failed left nothing, and an
 *  older result of the same kind is not its result. Without `since` (the address was opened on a lane that is no
 *  longer listed) nothing is claimed about what it left. */
export function pickLane(lanes: LaneView[], id: string | null, since?: string | null): LanePick {
  if (!id) return { state: "none", lane: lanes[0] ?? null };
  const found = lanes.find((l) => l.id === id);
  if (found) return { state: "found", lane: found };
  const m = /^([IC][1-9]\d*):(\w+)$/.exec(id);
  const began = since ? parseApiDate(since)?.getTime() : undefined;
  if (!m || began === undefined || Number.isNaN(began)) return { state: "gone", lane: null };
  const after = lanes.find((l) => {                                                      // recent is newest first
    if (l.group !== "recent" || l.item !== m[1] || l.kind !== m[2]) return false;
    const at = parseApiDate(l.at)?.getTime();
    return at !== undefined && at >= began;
  });
  return after ? { state: "moved", lane: after } : { state: "ended", lane: null };
}

/** A lane's own address. */
export const lanePath = (id: string | null): string => (id ? `/app/new/live/${encodeURIComponent(id)}` : "/app/new/live");

/** When the newest attempt to fetch the list failed but an older answer is on the page: the time of that answer
 *  (epoch ms), so the page can say how old what it shows is. null = current, or there never was an answer. */
export function staleSince(q: { isError: boolean; hasData: boolean; dataUpdatedAt: number }): number | null {
  return q.isError && q.hasData ? q.dataUpdatedAt : null;
}
