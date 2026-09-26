import { describe, it, expect } from "vitest";
import { isHintResolved, toPipelineEvents, policySummary } from "@/lib/changeDetail";
import type { ChangeTarget, ChangeTimelineEntry } from "@/api/types";

type Tgt = Pick<ChangeTarget, "resource_id" | "hint">;

describe("isHintResolved (R2)", () => {
  const targets: Tgt[] = [{ resource_id: "i-0abc", hint: "web-server" }];
  it.each([
    ["exact resource_id match", "i-0abc", targets, true],
    ["exact hint match", "web-server", targets, true],
    ["strip + case-insensitive resource_id", " I-0ABC ", targets, true],
    ["a hint matching nothing", "nope", targets, false],
    ["an empty target list", "i-0abc", [] as Tgt[], false],
    ["a missing-hint target that matches on id", "i-0abc", [{ resource_id: "i-0abc" }] as Tgt[], true],
    ["a missing-hint target with no match (no throw)", "web-server", [{ resource_id: "i-0abc" }] as Tgt[], false],
  ] as [string, string, Tgt[], boolean][])("%s", (_label, hint, tgts, expected) => {
    expect(isHintResolved(hint, tgts)).toBe(expected);
  });
});

describe("toPipelineEvents (R2)", () => {
  it("maps an event row with all fields present", () => {
    const entries: ChangeTimelineEntry[] = [
      { ts: "2026-09-20T00:00:00", kind: "event", type: "change_requested", actor: "alice", status: "started", stage: "intake", detail: { note: "hi" } },
    ];
    expect(toPipelineEvents(entries)).toEqual([
      { id: 0, event_type: "change_requested", stage: "intake", status: "started", actor: "alice", duration_ms: null, created_at: "2026-09-20T00:00:00", trace_id: null, detail: { note: "hi" } },
    ]);
  });

  it("fills defaults: status null → '', actor null → 'system', ts null → '', stage null → ''", () => {
    const entries: ChangeTimelineEntry[] = [
      { ts: null, kind: "audit", type: "authz.denied", actor: null, status: null, stage: null, detail: null },
    ];
    expect(toPipelineEvents(entries)).toEqual([
      { id: 0, event_type: "authz.denied", stage: "", status: "", actor: "system", duration_ms: null, created_at: "", trace_id: null, detail: null },
    ]);
  });

  it("passes an audit stage through and stringifies nested object values", () => {
    const entries: ChangeTimelineEntry[] = [
      { ts: "t", kind: "audit", type: "policy", actor: "sys", status: "completed", stage: "audit", detail: { policy_decision: { a: 1 }, reason: "ok" } },
    ];
    const out = toPipelineEvents(entries);
    expect(out[0].stage).toBe("audit");
    expect(out[0].detail).toEqual({ policy_decision: JSON.stringify({ a: 1 }), reason: "ok" });
  });

  it("wraps a legacy string detail as { detail }", () => {
    const out = toPipelineEvents([{ ts: "t", kind: "event", type: "x", actor: "a", status: "s", stage: "st", detail: "legacy" }]);
    expect(out[0].detail).toEqual({ detail: "legacy" });
  });

  it("wraps an array detail and JSON-stringifies it", () => {
    const out = toPipelineEvents([{ ts: "t", kind: "event", type: "x", actor: "a", status: "s", stage: "st", detail: [1, 2, 3] }]);
    expect(out[0].detail).toEqual({ detail: JSON.stringify([1, 2, 3]) });
  });

  it("null detail → null", () => {
    const out = toPipelineEvents([{ ts: "t", kind: "event", type: "x", actor: "a", status: "s", stage: "st", detail: null }]);
    expect(out[0].detail).toBeNull();
  });

  it("ids equal the array indexes", () => {
    const rows: ChangeTimelineEntry[] = [0, 1, 2].map((n) => ({ ts: "t", kind: "event", type: `e${n}`, actor: "a", status: "s", stage: "st", detail: null }));
    expect(toPipelineEvents(rows).map((e) => e.id)).toEqual([0, 1, 2]);
  });
});

describe("policySummary (R2)", () => {
  it("reads a full payload", () => {
    expect(policySummary({ reasons: ["r1", "r2"], escalated_from: "L1", effective_risk_level: "L3" })).toEqual({
      reasons: ["r1", "r2"],
      escalatedFrom: "L1",
      effectiveRisk: "L3",
    });
  });

  it.each([
    ["null", null],
    ["undefined", undefined],
  ] as [string, Record<string, unknown> | null | undefined][])("%s → all empty", (_l, pd) => {
    expect(policySummary(pd)).toEqual({ reasons: [], escalatedFrom: null, effectiveRisk: null });
  });

  it("reasons that is not an array → []", () => {
    expect(policySummary({ reasons: "nope" }).reasons).toEqual([]);
  });

  it("keeps only string reasons, dropping non-strings", () => {
    expect(policySummary({ reasons: ["a", 1, "b", null] }).reasons).toEqual(["a", "b"]);
  });

  it("escalated_from empty string → null", () => {
    expect(policySummary({ escalated_from: "" }).escalatedFrom).toBeNull();
  });

  it("drops reasons already shown in review_reasons (no duplicated list)", () => {
    expect(policySummary({ reasons: ["risk_level=L1", "extra"] }, ["sre note", "risk_level=L1"]).reasons).toEqual([
      "extra",
    ]);
  });
});
