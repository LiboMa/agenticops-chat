import { describe, expect, it } from "vitest";
import { agentOn, railRows, requestedRun, whoText, type Activity, type ActivityLane } from "@/newui/lib/activity";
import { humanVerdict } from "@/newui/lib/briefs/verdict";
import type { PipelineEvent } from "@/api/types";

const lane = (over: Partial<ActivityLane>): ActivityLane => ({
  id: "I12:diagnosis", kind: "diagnosis", agent: "rca", item: "I12", ref: "I#12", title: "disk full", account_id: 1,
  since: "2026-11-17T11:57:00Z", basis: "status", requested_by: null, overdue: false, route: "/app/issues/12", ...over,
});
const activity = (running: ActivityLane[], recent: Activity["recent"] = []): Activity =>
  ({ running, upcoming: [], recent, generated_at: "2026-11-17T12:00:00Z" });

describe("agents at work on an item — the server's record, not this browser's memory", () => {
  const asked = lane({ id: "I12:plan", kind: "plan", agent: "sre", basis: "requested", requested_by: "user:alice" });
  it("finds the run a person asked for", () => {
    expect(requestedRun(activity([lane({}), asked]), "I12")).toBe(asked);
    expect(requestedRun(activity([lane({})]), "I12")).toBeNull();              // a status alone is not a request
    expect(requestedRun(activity([asked]), "I13")).toBeNull();
    expect(requestedRun(undefined, "I12")).toBeNull();
  });
  it("finds any agent on the item, the requested run first", () => {
    expect(agentOn(activity([lane({}), asked]), "I12")).toBe(asked);
    expect(agentOn(activity([lane({ item: "C3", id: "C3:change_review", kind: "change_review" })]), "C3")?.kind).toBe("change_review");
    expect(agentOn(activity([]), "I12")).toBeNull();
  });
});

describe("railRows — what the rail beside the brief lists", () => {
  it("is everything running, then the few newest that ended", () => {
    const recent = [1, 2, 3, 4, 5, 6].map((n) => ({ id: `X${n}`, kind: "run", agent: "executor", item: "I1", ref: "I#1", title: "t",
      account_id: null, at: `2026-11-17T11:0${n}:00Z`, outcome: "done" as const, route: null }));
    const rows = railRows(activity([lane({}), lane({ id: "S1", item: null })], recent), 4);
    expect(rows.running.map((l) => l.id)).toEqual(["I12:diagnosis", "S1"]);
    expect(rows.recent.map((l) => l.id)).toEqual(["X1", "X2", "X3", "X4"]);
    expect(railRows(undefined)).toEqual({ running: [], recent: [] });
  });
});

describe("whoText — an actor as a person reads it", () => {
  const t = (k: string) => (k === "who.you" ? "你" : k);
  it("says «you» for the signed-in person, and drops the kind prefix otherwise", () => {
    expect(whoText("user:alice", "alice", t)).toBe("你");
    expect(whoText("user:bob", "alice", t)).toBe("bob");
    expect(whoText("cli:malibo", "alice", t)).toBe("malibo");
    expect(whoText("agent:executor", "alice", t)).toBe("agent:executor");
    expect(whoText(null, "alice", t)).toBe("");
  });
});

describe("humanVerdict — what a person made of a diagnosis, from the timeline", () => {
  const ev = (id: number, type: string, detail: unknown, at: string): PipelineEvent =>
    ({ id, event_type: type, stage: "rca", status: "completed", detail: detail as Record<string, unknown>, actor: "user:alice", duration_ms: null, created_at: at, trace_id: null });
  const events = [
    ev(1, "rca_human_feedback", { rca_id: 5, verdict: "correct", by: "user:bob", note: "" }, "2026-11-16T08:00:00Z"),
    ev(2, "status_changed", { from: "a", to: "b" }, "2026-11-16T09:00:00Z"),
    ev(3, "rca_human_feedback", { rca_id: 5, verdict: "incorrect", by: "user:alice", note: "wrong layer" }, "2026-11-17T08:00:00Z"),
    ev(4, "rca_human_feedback", { rca_id: 6, verdict: "correct", by: "user:carol" }, "2026-11-17T09:00:00Z"),
    ev(5, "rca_human_feedback", { rca_id: 5, verdict: null, location_verdict: "partial", by: "user:dave" }, "2026-11-17T10:00:00Z"),
  ];
  it("is the newest verdict on THIS diagnosis — a location-only judgement is not one", () => {
    expect(humanVerdict(events, 5)).toEqual({ verdict: "incorrect", by: "user:alice", note: "wrong layer", at: "2026-11-17T08:00:00Z" });
    expect(humanVerdict(events, 6)).toEqual({ verdict: "correct", by: "user:carol", note: "", at: "2026-11-17T09:00:00Z" });
  });
  it("reads a detail stored as JSON text, and is null when there is none", () => {
    expect(humanVerdict([ev(1, "rca_human_feedback", JSON.stringify({ rca_id: 5, verdict: "correct", by: "user:bob" }), "2026-11-16T08:00:00Z")], 5)?.by).toBe("user:bob");
    expect(humanVerdict(events, 99)).toBeNull();
    expect(humanVerdict(undefined, 5)).toBeNull();
  });
});
