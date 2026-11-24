import { describe, expect, it } from "vitest";
import { canClarify, clarifyMessage, clarifyOverflow, CLARIFY_MAX, requestVm } from "@/newui/lib/briefs/change";
import type { ChangeRequest } from "@/api/types";

const cr = (over: Partial<ChangeRequest> = {}): ChangeRequest => ({
  id: 3, title: "Tag the web tier", description: "Add cost tags to every web instance.", justification: "Finance asked.", source: "web",
  requested_by: "user:alice", requester_user_id: 1, requested_at: "2026-11-17T00:00:00Z", account_id: 1, target_hints: ["web-01", "web-99"],
  target_resources: [{ resource_id: "i-0abc", resource_type: "EC2", db_id: 7, region: "us-east-1", evidence: "x", hint: "web-01" }],
  requested_change_type: "normal", effective_change_type: null, risk_level: "L1", action_type: null, status: "draft",
  review_verdict: null, review_reasons: [], reviewed_by: null, reviewed_at: null, policy_rule: null, policy_action: null,
  approved_by: null, approver_user_id: null, approved_at: null, approval_reason: null, rejected_by: null, rejected_at: null,
  rejection_reason: null, closed_at: null, trace_id: null, chat_session_id: null, created_at: null, updated_at: null,
  proposed_steps: [{ action: "tag", command: "aws ec2 create-tags --resources i-0abc --tags Key=cost,Value=web" }],
  external_ref: null, steps_diff: null, needs_review_reason: null, ...over,
});

describe("requestVm — what a change request asks for", () => {
  it("says what, why, who, the targets found and the hints that matched nothing", () => {
    expect(requestVm(cr())).toEqual({
      text: "Add cost tags to every web instance.", why: "Finance asked.", by: "user:alice", emergency: false,
      targets: [{ id: "i-0abc", type: "EC2", region: "us-east-1" }], unresolved: ["web-99"],
      proposed: [{ say: "tag", cmd: "aws ec2 create-tags --resources i-0abc --tags Key=cost,Value=web", tier: null }],
    });
  });
  it("has no steps when the requester wrote none, and marks an emergency", () => {
    expect(requestVm(cr({ proposed_steps: null, requested_change_type: "emergency" }))).toMatchObject({ proposed: [], emergency: true });
  });
});

describe("answering the reviewer — the server takes one message, the page asks one question at a time", () => {
  const qs = ["Which window?", "Who owns web-99?"];
  it("needs every question answered", () => {
    expect(canClarify(qs, ["tonight", ""])).toBe(false);
    expect(canClarify(qs, ["tonight", "  "])).toBe(false);
    expect(canClarify(qs, ["tonight", "nobody: drop it"])).toBe(true);
  });
  it("needs one answer when the reviewer asked nothing specific", () => {
    expect(canClarify([], [""])).toBe(false);
    expect(canClarify([], ["go ahead with web-01 only"])).toBe(true);
  });
  it("puts each answer under its question, numbered", () => {
    expect(clarifyMessage(qs, [" tonight ", "nobody: drop it"])).toBe("1. Which window?\n   tonight\n\n2. Who owns web-99?\n   nobody: drop it");
    expect(clarifyMessage([], ["  go ahead  "])).toBe("go ahead");
  });
  it("says by how much the answers are too long — it never cuts them and reports «sent»", () => {
    // final review: three long answers went over the server's limit, the tail was dropped and the toast said «answers sent»
    expect(clarifyOverflow(qs, ["tonight", "nobody"])).toBe(0);
    const fits = "x".repeat(CLARIFY_MAX - clarifyMessage(["q"], [""]).length);
    expect(clarifyOverflow(["q"], [fits])).toBe(0);
    expect(clarifyOverflow(["q"], [fits + "yyy"])).toBe(3);
    expect(clarifyMessage(["q"], [fits + "yyy"]).endsWith("yyy")).toBe(true);        // whole: the caller blocks the send
    expect(canClarify(["q"], [fits + "yyy"])).toBe(false);
  });
});
