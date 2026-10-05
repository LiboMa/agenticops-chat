import { describe, it, expect } from "vitest";
import type { PipelineEvent } from "@/api/types";
import { toActivity } from "@/lib/activity";

const ev = (event_type: string, detail: unknown, extra: Partial<PipelineEvent> = {}): PipelineEvent => ({
  id: 0, event_type, stage: "", status: "completed", detail: detail as Record<string, unknown> | null,
  actor: "system", duration_ms: null, created_at: "2026-10-03T03:39:00", trace_id: null, ...extra,
});

describe("toActivity (P4)", () => {
  it("a known event gets its label key and a summary from its detail; unknown keys stay out of the sentence", () => {
    const [a] = toActivity([ev("rca_needs_review", { confidence: 0.57, reason: "confidence 0.57 < 0.6", rca_id: 1 })]);
    expect(a.labelKey).toBe("activity.type.rca_needs_review");
    expect(a.summary).toBe("confidence 0.57 < 0.6");
    expect(a.tone).toBe("warn");
  });
  it("an unknown event type falls back to the generic label with the raw type; never throws", () => {
    const [a] = toActivity([ev("brand_new_thing", "not json")]);
    expect(a.labelKey).toBe("activity.type.unknown");
    expect(a.labelParams).toEqual({ type: "brand_new_thing" });
    expect(a.summary).toBe("");
  });
  it("authz denials read as rule + permission, shadow ones marked", () => {
    const [a, b] = toActivity([
      ev("authz.denied", { rule: "no-webhook-approve-or-execute", permission: "change.approve" }, { actor: "webhook:e2e" }),
      ev("authz.denied_shadow", { rule: "sod-change-approver-not-requester", permission: "change.approve" }, { created_at: "2026-10-03T03:40:00" }),
    ]);
    expect(a.labelKey).toBe("activity.type.authz_denied");
    expect(a.labelParams).toEqual({ rule: "no-webhook-approve-or-execute", permission: "change.approve" });
    expect(a.tone).toBe("bad");
    expect(b.labelKey).toBe("activity.type.authz_denied_shadow");
  });
  it("consecutive duplicates merge into one entry with a count; the raw events are kept", () => {
    const d = { rule: "no-webhook-approve-or-execute", permission: "change.execute" };
    const out = toActivity([ev("authz.denied", d), ev("authz.denied", d), ev("policy_decision", { action: "auto_approve" })]);
    expect(out.map((x) => [x.labelKey, x.count])).toEqual([["activity.type.authz_denied", 2], ["activity.type.policy_decision", 1]]);
    expect(out[0].raw).toHaveLength(2);
  });
  it("events come out oldest first whatever the input order; a JSON-string detail is parsed", () => {
    const out = toActivity([
      ev("rca_completed", JSON.stringify({ confidence: 0.95 }), { created_at: "2026-10-03T03:40:00" }),
      ev("issue_created", { severity: "high" }, { created_at: "2026-10-03T03:39:00" }),
    ]);
    expect(out.map((x) => x.labelKey)).toEqual(["activity.type.issue_created", "activity.type.rca_completed"]);
    expect(out[1].summary).toBe("95%");
  });
});
