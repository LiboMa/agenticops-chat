import { describe, it, expect } from "vitest";
import type { FixPlan } from "@/api/types";
import { currentFixPlan, issuePhases, type IssuePhaseInput } from "@/lib/issuePhases";

const gateFail = { confidence: 0.57, evidence_verified: false, critic_verdict: "weak", human_verdict: null } as const;
const gatePass = { confidence: 0.9, evidence_verified: true, critic_verdict: "supported", human_verdict: null } as const;
const P = (x: Partial<IssuePhaseInput>): IssuePhaseInput => ({ status: "open", threshold: 0.6, ...x });
const pick = (r: ReturnType<typeof issuePhases>) => [r.current, r.sub, r.waitingFor, r.primary];
const states = (r: ReturnType<typeof issuePhases>) => r.phases.map((p) => p.state);

describe("issuePhases — spec §4 issue table, one case per row", () => {
  it("open / investigating / acknowledged → ① running, the RCA agent, no primary", () => {
    for (const status of ["open", "investigating", "acknowledged"] as const)
      expect(pick(issuePhases(P({ status, rca: null }))), status).toEqual(["diagnose", "running", "rca_agent", null]);
    expect(states(issuePhases(P({ status: "open" })))).toEqual(["current", "future", "future", "future"]);
  });
  it("root_cause_identified, RCA below the gate → ① needs review, you, 'review root cause' (I#1)", () => {
    expect(pick(issuePhases(P({ status: "root_cause_identified", rca: gateFail })))).toEqual(["diagnose", "needsReview", "you", "reviewRca"]);
  });
  it("…a person said the root cause is wrong → ① rejected, you, rerun RCA", () => {
    expect(pick(issuePhases(P({ status: "root_cause_identified", rca: { ...gateFail, human_verdict: "incorrect" } }))))
      .toEqual(["diagnose", "rcaRejected", "you", "rerunRca"]);
  });
  it("root_cause_identified, gate passed → ② to generate, the SRE agent; or a person said correct → you", () => {
    expect(pick(issuePhases(P({ status: "root_cause_identified", rca: gatePass })))).toEqual(["plan", "toGenerate", "sre_agent", "generatePlan"]);
    expect(pick(issuePhases(P({ status: "root_cause_identified", rca: { ...gateFail, human_verdict: "correct" } }))))
      .toEqual(["plan", "toGenerate", "you", "generatePlan"]);
    expect(states(issuePhases(P({ status: "root_cause_identified", rca: gatePass })))).toEqual(["done", "current", "future", "future"]);
  });
  it("root_cause_identified after a failed run → ② needs a new plan; ③ shows the failed run", () => {
    const r = issuePhases(P({ status: "root_cause_identified", rca: gatePass, latestRun: { status: "failed", verification_status: "failed" } }));
    expect(pick(r)).toEqual(["plan", "needsNewPlan", "you", "generatePlan"]);
    expect(states(r)).toEqual(["done", "current", "failed", "future"]);
  });
  it("fix_planned → ③ awaiting approval, the approver, 'approve & run'", () => {
    expect(pick(issuePhases(P({ status: "fix_planned", plan: { status: "pending_approval" } })))).toEqual(["run", "awaitingApproval", "approver", "approveAndRun"]);
    expect(pick(issuePhases(P({ status: "fix_planned", plan: null })))).toEqual(["run", "awaitingApproval", "approver", null]);
  });
  it("fix_approved and no run queued → ③ not queued, you, retry; a queued run → executing", () => {
    expect(pick(issuePhases(P({ status: "fix_approved", plan: { status: "approved" }, latestRun: null })))).toEqual(["run", "notQueued", "you", "retryExecution"]);
    expect(pick(issuePhases(P({ status: "fix_approved", latestRun: { status: "pending", verification_status: null } })))).toEqual(["run", "executing", "executor", null]);
  });
  it("fix_executing → ③ executing, the executor, no primary", () => {
    expect(pick(issuePhases(P({ status: "fix_executing" })))).toEqual(["run", "executing", "executor", null]);
  });
  it("fix_executed: pending acceptance → ④ you accept; passed (auto-resolve off) → ④ mark resolved; no verdict → unverified", () => {
    expect(pick(issuePhases(P({ status: "fix_executed", latestRun: { status: "succeeded", verification_status: "pending_acceptance" } }))))
      .toEqual(["accept", "awaitingAcceptance", "acceptor", "acceptResult"]);
    expect(pick(issuePhases(P({ status: "fix_executed", latestRun: { status: "succeeded", verification_status: "passed" } }))))
      .toEqual(["accept", "passed", "you", "markResolved"]);
    expect(pick(issuePhases(P({ status: "fix_executed", latestRun: { status: "succeeded", verification_status: null } }))))
      .toEqual(["accept", "unverified", "you", "markResolved"]);
  });
  it("resolved / dismissed → terminal: no current phase, no primary", () => {
    const r = issuePhases(P({ status: "resolved", rca: gatePass, plan: { status: "executed" }, latestRun: { status: "succeeded", verification_status: "passed" } }));
    expect(pick(r)).toEqual([null, "resolved", null, null]);
    expect(states(r)).toEqual(["done", "done", "done", "done"]);
    expect(states(issuePhases(P({ status: "dismissed", rca: null })))).toEqual(["future", "future", "future", "future"]);
  });
});

describe("issuePhases — list mode (R2) and missing data (Review Focus 1)", () => {
  it("rca undefined (the list has no RCA): root_cause_identified waits for you to review or plan", () => {
    expect(pick(issuePhases({ status: "root_cause_identified" }))).toEqual(["diagnose", "reviewOrPlan", "you", null]);
  });
  it("threshold unknown (settings not loaded) with an RCA → also review-or-plan, never a guessed gate", () => {
    expect(pick(issuePhases({ status: "root_cause_identified", rca: gateFail, threshold: null }))).toEqual(["diagnose", "reviewOrPlan", "you", null]);
  });
  it("root_cause_identified with rca null (the RCA row is gone) → rerun RCA", () => {
    expect(pick(issuePhases(P({ status: "root_cause_identified", rca: null })))).toEqual(["diagnose", "needsReview", "you", "rerunRca"]);
  });
  it("fix_executed in list mode (no run known) → unverified, you", () => {
    expect(pick(issuePhases({ status: "fix_executed" }))).toEqual(["accept", "unverified", "you", null]);
  });
});

describe("currentFixPlan (Review Focus 2)", () => {
  const plan = (id: number, status: FixPlan["status"], created_at: string) => ({ id, status, created_at }) as FixPlan;
  it("the newest plan not executed / failed / rejected; else the newest; null with none", () => {
    expect(currentFixPlan([plan(2, "pending_approval", "2026-10-03T02"), plan(1, "rejected", "2026-10-03T01")])?.id).toBe(2);
    expect(currentFixPlan([plan(1, "rejected", "2026-10-03T01"), plan(2, "pending_approval", "2026-10-03T02")])?.id).toBe(2);
    expect(currentFixPlan([plan(3, "executed", "2026-10-03T03"), plan(2, "failed", "2026-10-03T02")])?.id).toBe(3);
    expect(currentFixPlan([])).toBeNull();
    expect(currentFixPlan(undefined)).toBeNull();
  });
});

describe("issuePhases — a status outside the union (a newer backend) degrades, never throws", () => {
  it("no current phase, no button, nobody waited on; the phases it has data for read done", () => {
    const r = issuePhases(P({ status: "quarantined" as IssuePhaseInput["status"], rca: gatePass }));
    expect(pick(r)).toEqual([null, "unknown", null, null]);
    expect(states(r)).toEqual(["done", "future", "future", "future"]);
  });
});
