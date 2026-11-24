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

describe("toActivity hideText (spec §1-3: the status line's sentence is said once)", () => {
  const sentence = "Pre-check #1 FAILED: Deployment frontend reports 0 ready replicas (expected 3/3).";
  const events = [
    ev("execution_completed", { reason: sentence, execution_status: "aborted" }, { created_at: "2026-10-03T09:56:39", actor: "agent:executor" }),
    ev("change.failed", { reason: ` ${sentence} ` }, { created_at: "2026-10-03T09:56:40", actor: "agent:executor" }),
    ev("change_approved", { reason: "go for deployment." }, { created_at: "2026-10-03T09:55:56", actor: "user:admin" }),
  ];
  it("an entry whose summary IS the hidden text keeps its label, actor and time but no summary (both trimmed)", () => {
    const out = toActivity(events, { hideText: `${sentence}\n` });
    expect(out.map((x) => [x.labelKey, x.summary, x.actor, x.ts])).toEqual([
      ["activity.type.change_approved", "go for deployment.", "user:admin", "2026-10-03T09:55:56"],
      ["activity.type.execution_completed", "", "agent:executor", "2026-10-03T09:56:39"],
      ["activity.type.change_failed", "", "agent:executor", "2026-10-03T09:56:40"],
    ]);
    expect(out[1].raw[0].detail).toEqual({ reason: sentence, execution_status: "aborted" }); // the raw view keeps it
  });
  it("a different summary is kept; no opts, or a null / blank hideText, changes nothing", () => {
    expect(toActivity(events, { hideText: "something else" }).map((x) => x.summary))
      .toEqual(["go for deployment.", sentence, sentence]);
    expect(toActivity(events)).toEqual(toActivity(events, { hideText: null }));
    expect(toActivity(events, { hideText: "  " }).map((x) => x.summary)).toEqual(["go for deployment.", sentence, sentence]);
  });
});

describe("notes (MVP-2.7.0 S4)", () => {
  const note = (content: string, extra: Partial<PipelineEvent> = {}) =>
    ev("note_added", { content }, { status: "recorded", actor: "user:alice", ...extra });
  it("a note is its own entry: label, the text as written, who and when", () => {
    const [a] = toActivity([note("checked the LB\n  then the pool")]);
    expect(a.labelKey).toBe("activity.type.note_added");
    expect(a.note).toBe("checked the LB\n  then the pool");
    expect(a.summary).toBe("");
    expect(a.actor).toBe("user:alice");
    expect(a.ts).toBe("2026-10-03T03:39:00");
  });
  it("two identical notes in a row stay two entries (×N is for system events)", () => {
    expect(toActivity([note("same", { id: 1 }), note("same", { id: 2 })])).toHaveLength(2);
  });
  it("a note equal to the status line's sentence is still shown", () => {
    expect(toActivity([note("Waiting for an approver")], { hideText: "Waiting for an approver" })[0].note)
      .toBe("Waiting for an approver");
  });
  it("markup is kept as a plain string — the list renders text nodes, never HTML", () => {
    expect(toActivity([note("<script>alert(1)</script>")])[0].note).toBe("<script>alert(1)</script>");
  });
  it("a note whose detail is not an object reads as an empty note, never throws", () => {
    expect(toActivity([ev("note_added", "not json")])[0].note).toBe("");
  });
});

describe("a plan request that followed sending a plan back (MVP-2.9.0 N14)", () => {
  const ev = (id: number, detail: unknown) => ({ id, health_issue_id: 1, event_type: "fix_plan_requested", stage: "sre", status: "started",
                                                actor: "user:alice", created_at: `2026-11-18T08:0${id}:00Z`, detail }) as unknown as PipelineEvent;

  it("says which plan was sent back — the rejection itself is not a timeline event", () => {
    const [e] = toActivity([ev(1, { trigger: "manual", requested_by: "user:alice", after_plan: 160 })]);
    expect(e.labelKey).toBe("activity.type.fix_plan_requested_after");
    expect(e.labelParams).toEqual({ plan: "160" });
  });

  it("a plain request keeps its plain sentence, whatever else the detail holds", () => {
    expect(toActivity([ev(1, { trigger: "manual" })])[0].labelKey).toBe("activity.type.fix_plan_requested");
    expect(toActivity([ev(1, { trigger: "manual", after_plan: "160; drop" })])[0].labelKey).toBe("activity.type.fix_plan_requested");
    expect(toActivity([ev(1, JSON.stringify({ after_plan: 7 }))])[0].labelParams).toEqual({ plan: "7" });   // a detail stored as a JSON string
  });

  it("two requests about two plans are two entries, never ×2", () => {
    const out = toActivity([ev(1, { after_plan: 160 }), ev(2, { after_plan: 167 })]);
    expect(out.map((e) => [e.labelParams.plan, e.count])).toEqual([["160", 1], ["167", 1]]);
  });
});

describe("a plan written by the agent has a sentence of its own (MVP-2.9.0 N15)", () => {
  // the top bar's band says each event in the timeline's own words: «事件：fix_plan_created» is no sentence
  it("names a plan that was written and one that was rewritten", () => {
    const [made, redone] = toActivity([ev("fix_plan_created", { plan_id: 7, risk_level: "L2" }), ev("fix_plan_updated", { plan_id: 7, risk_level: "L1" }, { created_at: "2026-10-03T03:40:00" })]);
    expect([made.labelKey, made.summary]).toEqual(["activity.type.fix_plan_created", "L2"]);
    expect(redone.labelKey).toBe("activity.type.fix_plan_updated");
  });
});
