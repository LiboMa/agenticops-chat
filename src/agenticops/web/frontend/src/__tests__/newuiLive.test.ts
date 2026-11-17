import { describe, expect, it } from "vitest";
import type { Activity, ActivityLane, ActivityRecent } from "@/newui/lib/activity";
import { atWork, lanePath, laneViews, pickLane, recentCut, staleSince, type LaneView, stopState } from "@/newui/lib/live";

const running = (over: Partial<ActivityLane>): ActivityLane => ({
  id: "I12:diagnosis", kind: "diagnosis", agent: "rca", item: "I12", ref: "I#12", title: "disk full", account_id: 1,
  since: "2026-11-17T11:57:00Z", basis: "status", requested_by: null, overdue: false, route: "/app/issues/12", ...over,
});
const ended = (over: Partial<ActivityRecent>): ActivityRecent => ({
  id: "X41", kind: "run", agent: "executor", item: "I12", ref: "I#12", title: "disk full", account_id: 1,
  at: "2026-11-17T11:50:00Z", outcome: "done", route: "/app/issues/12", ...over,
});
const activity = (over: Partial<Activity>): Activity => ({ running: [], upcoming: [], recent: [], generated_at: "2026-11-17T12:00:00Z", ...over });

describe("laneViews — «现场»'s list: at work now, due next, ended lately", () => {
  const lanes = laneViews(activity({
    running: [running({}), running({ id: "S5", kind: "schedule", agent: "scheduler", item: null, ref: null, title: "patrol", basis: "schedule" })],
    upcoming: [{ id: "S5", kind: "schedule", agent: "scheduler", title: "patrol", at: "2026-11-17T13:00:00Z", route: "/app/schedules/5" }],
    recent: [ended({}), ended({ id: "R9", kind: "diagnosis", agent: "rca", at: "2026-11-17T11:40:00Z" })],
  }));

  it("keeps the three groups in that order", () => {
    expect(lanes.map((l) => l.group)).toEqual(["running", "running", "upcoming", "recent", "recent"]);
  });

  it("gives every lane an id of its own — a schedule that is running and due again is two lanes", () => {
    expect(lanes.map((l) => l.id)).toEqual(["I12:diagnosis", "S5", "next:S5", "X41", "R9"]);
    expect(new Set(lanes.map((l) => l.id)).size).toBe(lanes.length);
  });

  it("carries when: since when it runs, when it is due, when it ended", () => {
    expect(lanes.map((l) => l.at)).toEqual(["2026-11-17T11:57:00Z", "2026-11-17T11:57:00Z", "2026-11-17T13:00:00Z", "2026-11-17T11:50:00Z", "2026-11-17T11:40:00Z"]);
  });

  it("names the row that ended, so its result can be fetched", () => {
    expect(lanes.map((l) => l.row)).toEqual([null, null, null, 41, 9]);
  });

  it("colours a lane by what is true of it", () => {
    const tone = (a: Partial<Activity>) => laneViews(activity(a))[0].tone;
    expect(tone({ running: [running({})] })).toBe("run");
    expect(tone({ running: [running({ overdue: true })] })).toBe("late");           // it outlived its own time limit
    expect(tone({ upcoming: [{ id: "S1", kind: "schedule", agent: "scheduler", title: "t", at: "2026-11-17T13:00:00Z", route: null }] })).toBe("wait");
    expect(tone({ recent: [ended({ outcome: "done" })] })).toBe("done");
    expect(tone({ recent: [ended({ outcome: "failed" })] })).toBe("bad");
    expect(tone({ recent: [ended({ outcome: "needs_you" })] })).toBe("you");
  });

  it("marks a diagnosis that stopped: it is listed where a person will see it, but it is not at work", () => {
    const lanes2 = laneViews(activity({ running: [running({ id: "I1:diagnosis", item: "I1", basis: "stopped", overdue: true }), running({})],
                                        recent: [ended({})] }));
    expect(lanes2.map((l) => [l.id, l.group, l.stopped, l.tone])).toEqual([
      ["I12:diagnosis", "running", false, "run"],
      ["I1:diagnosis", "stalled", true, "late"],          // its own group, after what is really at work
      ["X41", "recent", false, "done"],
    ]);
    expect(atWork(activity({ running: [running({ basis: "stopped", overdue: true }), running({}), running({ id: "S5" })] }))).toBe(2);
    expect(atWork(undefined)).toBeUndefined();
  });

  it("is empty before the first answer", () => {
    expect(laneViews(undefined)).toEqual([]);
  });
});

describe("pickLane — which lane the address means", () => {
  const lanes: LaneView[] = laneViews(activity({
    running: [running({}), running({ id: "I7:run", kind: "run", agent: "executor", item: "I7", ref: "I#7" })],
    recent: [ended({ id: "X41", item: "I3", ref: "I#3" }), ended({ id: "R9", kind: "diagnosis", item: "I5", ref: "I#5" }),
             ended({ id: "R8", kind: "diagnosis", item: "I5", ref: "I#5", at: "2026-11-17T10:00:00Z" })],
  }));

  it("no lane in the address: the first one", () => {
    expect(pickLane(lanes, null)).toEqual({ state: "none", lane: lanes[0] });
    expect(pickLane([], null)).toEqual({ state: "none", lane: null });
  });

  it("finds the lane the address names", () => {
    expect(pickLane(lanes, "I7:run")).toEqual({ state: "found", lane: lanes[1] });
    expect(pickLane(lanes, "X41")).toEqual({ state: "found", lane: lanes[2] });
  });

  it("a lane that was being watched and ended is followed to what it left behind — a result made after it began", () => {
    // I5's diagnosis began at 09:50: the newest diagnosis of I5 made since then is what it left (R9, 11:50)
    expect(pickLane(lanes, "I5:diagnosis", "2026-11-17T09:50:00Z")).toEqual({ state: "moved", lane: lanes[3] });
    expect(pickLane(lanes, "I3:run", "2026-11-17T11:00:00Z")).toEqual({ state: "moved", lane: lanes[2] });
  });

  it("never presents an older result as what the watched run left: a run that failed left nothing", () => {
    // final review: yesterday's diagnosis was shown as «it has ended; this is what it left behind» for a run that
    // had just failed. The result must have been made at or after the lane's own start.
    expect(pickLane(lanes, "I5:diagnosis", "2026-11-17T11:55:00Z")).toEqual({ state: "ended", lane: null });   // R9 (11:50) is older than the run
    expect(pickLane(lanes, "I5:plan", "2026-11-17T09:00:00Z")).toEqual({ state: "ended", lane: null });       // another kind of work is not its result
  });

  it("an address opened on a lane that is no longer listed claims nothing about what it left", () => {
    // no start on record for it here (a bookmark, a link from earlier): which result would be «its» is not known
    expect(pickLane(lanes, "I5:diagnosis")).toEqual({ state: "gone", lane: null });
    expect(pickLane(lanes, "I5:diagnosis", null)).toEqual({ state: "gone", lane: null });
  });

  it("says it is gone when nothing of it is listed — never another lane in its place", () => {
    expect(pickLane(lanes, "I5:plan")).toEqual({ state: "gone", lane: null });          // another kind of work is not its result
    expect(pickLane(lanes, "C3:change_review")).toEqual({ state: "gone", lane: null });
    expect(pickLane(lanes, "X999")).toEqual({ state: "gone", lane: null });
  });
});

describe("lanePath — a lane's own address", () => {
  it("escapes the lane id", () => {
    expect(lanePath("I12:diagnosis")).toBe("/app/new/live/I12%3Adiagnosis");
    expect(lanePath(null)).toBe("/app/new/live");
  });
});

describe("staleSince — the list on the page is older than the last attempt", () => {
  it("is the time of the last good answer while the newest attempt failed", () => {
    expect(staleSince({ isError: true, hasData: true, dataUpdatedAt: 1_700_000_000_000 })).toBe(1_700_000_000_000);
  });
  it("is nothing while the list is current, or when there never was one", () => {
    expect(staleSince({ isError: false, hasData: true, dataUpdatedAt: 1 })).toBeNull();
    expect(staleSince({ isError: true, hasData: false, dataUpdatedAt: 0 })).toBeNull();
  });
});

describe("atWork — the number beside «现场»", () => {
  it("counts what is at work within its own time limit: not a stopped diagnosis, not work that outlived its limit", () => {
    expect(atWork(activity({ running: [running({}), running({ id: "I7:run", kind: "run", item: "I7" }),
                                       running({ id: "I9:diagnosis", item: "I9", overdue: true }),
                                       running({ id: "I4:diagnosis", item: "I4", basis: "stopped", overdue: true })] }))).toBe(2);
    expect(atWork(undefined)).toBeUndefined();
  });
});

describe("recentCut — «ended in the last day» says when it shows only some", () => {
  const some = [ended({}), ended({ id: "R9", kind: "diagnosis" }), ended({ id: "SE3", kind: "schedule", item: null, ref: null })];
  it("is nothing when everything that ended is listed, or the server did not count", () => {
    expect(recentCut(activity({ recent: some, recent_total: { work: 2, schedules: 1 } }))).toBeNull();
    expect(recentCut(activity({ recent: some }))).toBeNull();
    expect(recentCut(undefined)).toBeNull();
  });
  it("says how many of each there were when the list is the newest few", () => {
    expect(recentCut(activity({ recent: some, recent_total: { work: 39, schedules: 30 } })))
      .toEqual({ work: { shown: 2, total: 39 }, schedules: { shown: 1, total: 30 } });
    expect(recentCut(activity({ recent: some, recent_total: { work: 2, schedules: 30 } })))
      .toEqual({ work: null, schedules: { shown: 1, total: 30 } });
  });
});


describe("stopState — whether the opened lane's run can be stopped (N9)", () => {
  const run = (over: Partial<Activity["running"][number]> = {}) => laneViews({
    running: [{ id: "I5:run", kind: "run", agent: "executor", item: "I5", ref: "I#5", title: "t", account_id: 1, since: "2026-11-17T11:58:00Z",
                basis: "run", requested_by: null, overdue: false, route: "/app/issues/5",
                execution: { id: 41, status: "running", stop_requested_at: null, stop_requested_by: null }, ...over }],
    upcoming: [], recent: [], generated_at: "2026-11-17T12:00:00Z",
  })[0];

  it("a run in progress that has its record can be stopped", () => {
    expect(run().execution).toEqual({ id: 41, status: "running", stopRequestedAt: null, stopRequestedBy: null });
    expect(stopState(run())).toBe("can");
    expect(stopState(run({ id: "C3:change_run", kind: "change_run", item: "C3" }))).toBe("can");
  });

  it("one a person already asked to stop is stopping — it cannot be asked again", () => {
    const lane = run({ execution: { id: 41, status: "running", stop_requested_at: "2026-11-17T11:59:30Z", stop_requested_by: "user:alice" } });
    expect(stopState(lane)).toBe("stopping");
    expect(lane.execution?.stopRequestedBy).toBe("user:alice");
    expect([run().tone, lane.tone]).toEqual(["run", "bad"]);                   // the red edge: a person stopped it
  });

  it("a run the page cannot name, or one that has not started, offers no stop", () => {
    expect(stopState(run({ execution: undefined, basis: "status" }))).toBeNull();           // a status alone: no record to stop
    expect(stopState(run({ execution: { id: 41, status: "pending", stop_requested_at: null, stop_requested_by: null } }))).toBeNull();
  });

  it("nothing but a run in progress is stopped: not a diagnosis, not a lane that ended, not no lane", () => {
    expect(stopState(run({ kind: "diagnosis", execution: undefined }))).toBeNull();
    expect(stopState({ ...run(), group: "recent" })).toBeNull();
    expect(stopState(null)).toBeNull();
  });
});
