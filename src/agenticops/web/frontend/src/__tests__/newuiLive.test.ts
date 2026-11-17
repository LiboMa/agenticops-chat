import { describe, expect, it } from "vitest";
import type { Activity, ActivityLane, ActivityRecent } from "@/newui/lib/activity";
import { atWork, lanePath, laneViews, pickLane, staleSince, type LaneView } from "@/newui/lib/live";

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

  it("a running lane that ended is followed to what it left behind — the newest of that kind on that item", () => {
    expect(pickLane(lanes, "I5:diagnosis")).toEqual({ state: "moved", lane: lanes[3] });
    expect(pickLane(lanes, "I3:run")).toEqual({ state: "moved", lane: lanes[2] });
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
