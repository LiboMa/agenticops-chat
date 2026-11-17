import { describe, expect, it } from "vitest";
import { approveState, approvedToastKey, checksVm, planHead, postChecksVm, rollbackVm, stepsVm } from "@/newui/lib/briefs/plan";
import type { FixPlan } from "@/api/types";

const plan = (over: Partial<FixPlan> = {}): FixPlan => ({
  id: 10, plan_kind: "fix", health_issue_id: 12, rca_result_id: 1, change_request_id: null, risk_level: "L2", title: "Close it",
  summary: "", steps: [], rollback_plan: {}, estimated_impact: "", pre_checks: [], post_checks: [], status: "pending_approval",
  approved_by: null, approved_at: null, rejected_by: null, rejected_at: null, rejection_reason: null, created_at: "2026-11-01T00:00:00Z",
  updated_at: null, account_id: 1, plan_version: 2, content_hash: "0123456789abcdef", approved_hash: null, approved_version: null, ...over,
} as FixPlan);

describe("stepsVm — a plan's steps as the page lists them", () => {
  it("reads what a step says and its command from every shape the column holds", () => {
    const steps = stepsVm(plan({
      steps: [{ action: "Revoke the rule", command: "aws ec2 revoke-security-group-ingress --group-id sg-1" }, { description: "Look", command: "aws ec2 describe-security-groups" },
              { step: "By hand" }, "Just text", { command: "kubectl get pods" }, 42],
      step_tiers: ["write", "readonly", "unknown", "unknown", "readonly", "unknown"],
    }));
    expect(steps.map((s) => s.say)).toEqual(["Revoke the rule", "Look", "By hand", "Just text", "", "42"]);
    expect(steps.map((s) => s.cmd)).toEqual(["aws ec2 revoke-security-group-ingress --group-id sg-1", "aws ec2 describe-security-groups", null, null, "kubectl get pods", null]);
    expect(steps.map((s) => s.tier)).toEqual(["write", "readonly", "unknown", "unknown", "readonly", "unknown"]);
  });

  it("claims no tier when the server sent none, or a list of another length", () => {
    const steps = [{ action: "a", command: "aws s3 ls" }, { action: "b", command: "rm -rf /" }];
    expect(stepsVm(plan({ steps })).map((s) => s.tier)).toEqual([null, null]);
    expect(stepsVm(plan({ steps, step_tiers: ["readonly"] })).map((s) => s.tier)).toEqual([null, null]);
    expect(stepsVm(plan({ steps, step_tiers: ["readonly", "odd"] })).map((s) => s.tier)).toEqual(["readonly", null]);
  });

  it("is empty for a column that is not a list", () => {
    expect(stepsVm(plan({ steps: "broken" as unknown as unknown[] }))).toEqual([]);
  });
});

describe("postChecksVm — the declared checks, named by position as the executor reports them", () => {
  it("numbers them pc-1 … pc-n", () => {
    expect(postChecksVm(plan({ post_checks: ["No 0.0.0.0/0 rule left", { check: "Port 22 closed", command: "nc -z" }, { description: "Alarm clear" }] })))
      .toEqual([{ id: "pc-1", text: "No 0.0.0.0/0 rule left" }, { id: "pc-2", text: "Port 22 closed" }, { id: "pc-3", text: "Alarm clear" }]);
  });
});

describe("rollbackVm", () => {
  it("lists the rollback's steps and its trigger", () => {
    expect(rollbackVm(plan({ rollback_plan: { trigger: "errors rise", steps: [{ action: "Put the rule back", command: "aws ec2 authorize-security-group-ingress" }] } })))
      .toEqual({ trigger: "errors rise", steps: [{ say: "Put the rule back", cmd: "aws ec2 authorize-security-group-ingress", tier: null }], notes: [] });
  });
  it("keeps whatever else a free-form rollback says, key by key — a described rollback never reads as none", () => {
    expect(rollbackVm(plan({ rollback_plan: { trigger: "if 5xx rise", preferred_rollback_before_step_6: "Swap the group back", verification_after_rollback: ["a", "b"], empty: "" } })))
      .toEqual({ trigger: "if 5xx rise", steps: [], notes: [
        { label: "preferred rollback before step 6", text: "Swap the group back" },
        { label: "verification after rollback", text: '["a","b"]' },
      ] });
    expect(rollbackVm(plan({ rollback_plan: { description: "Re-add the rule by hand" } })).notes).toEqual([{ label: "description", text: "Re-add the rule by hand" }]);
  });
  it("says nothing when there is none", () => {
    expect(rollbackVm(plan({ rollback_plan: {} }))).toEqual({ trigger: null, steps: [], notes: [] });
  });
});

describe("planHead", () => {
  it("is the version, the first 8 of the hash and the risk level", () => {
    expect(planHead(plan())).toEqual({ version: 2, hash8: "01234567", risk: "L2" });
    expect(planHead(plan({ content_hash: null, plan_version: 0 }))).toEqual({ version: 1, hash8: null, risk: "L2" });
  });
});

describe("approveState — what «approve» does here, as the server says", () => {
  const act = (over: object) => [{ action: "approve", allowed: true, reason_code: null, effect: "approve_and_queue_execution", ...over }];
  it("approves and runs when the server will queue the run", () => {
    expect(approveState(plan({ available_actions: act({}) }))).toEqual({ can: true, runs: true, effect: "run", why: null, shadow: false });
  });
  it("only approves when the executor or auto-fix is off", () => {
    expect(approveState(plan({ available_actions: act({ effect: "approve_only" }) }))).toEqual({ can: true, runs: false, effect: "only", why: null, shadow: false });
  });
  it("says so when only the policy's shadow mode lets it through", () => {
    expect(approveState(plan({ available_actions: act({ reason_code: "policy_shadow" }) }))).toEqual({ can: true, runs: true, effect: "run", why: null, shadow: true });
  });
  it("cannot approve when the server refuses, and says why", () => {
    expect(approveState(plan({ available_actions: act({ allowed: false, reason_code: "forbidden" }) }))).toEqual({ can: false, runs: true, effect: "run", why: "forbidden", shadow: false });
  });
  it("cannot approve a plan without a content hash, or one that offers no approval", () => {
    expect(approveState(plan({ content_hash: null, available_actions: act({}) }))).toEqual({ can: false, runs: true, effect: "run", why: "no_hash", shadow: false });
    expect(approveState(plan({ available_actions: [] }))).toEqual({ can: false, runs: false, effect: "unknown", why: "state", shadow: false });
    expect(approveState(plan({}))).toEqual({ can: false, runs: false, effect: "unknown", why: "state", shadow: false });
  });
});

describe("the page shows everything the approval's hash covers", () => {
  // final review: the hash binds steps, rollback, pre-checks and post-checks — the brief showed no pre-check, no
  // check's command, and «—» for a step written with keys it did not know
  it("lists the pre-checks too, each with its command", () => {
    const p = plan({ pre_checks: [{ check: "replica lag < 5s", command: "aws rds describe-db-instances --query x" }, "nobody is deploying"],
                     post_checks: [{ description: "port closed", command: "nc -z host 22" }, { check: "no alarm" }] });
    expect(checksVm(p, "pre")).toEqual([
      { id: "pre-1", text: "replica lag < 5s", cmd: "aws rds describe-db-instances --query x" },
      { id: "pre-2", text: "nobody is deploying", cmd: null },
    ]);
    expect(checksVm(p, "post")).toEqual([
      { id: "pc-1", text: "port closed", cmd: "nc -z host 22" },
      { id: "pc-2", text: "no alarm", cmd: null },
    ]);
    expect(postChecksVm(p).map((c) => c.id)).toEqual(["pc-1", "pc-2"]);                // the old reader, same ids
    expect(checksVm(plan({ pre_checks: "nothing" as unknown as unknown[] }), "pre")).toEqual([]);
  });

  it("prints a step it cannot read as it is, never as «—»", () => {
    const [odd, plain] = stepsVm(plan({ steps: [{ title: "drain", run: "kubectl drain node-1" }, { action: "look" }] }));
    expect(odd).toEqual({ say: "", cmd: null, tier: null, raw: '{"title":"drain","run":"kubectl drain node-1"}' });
    expect(plain.raw).toBeUndefined();
  });
});

describe("approveState.effect — what the page may say approving does", () => {
  const act = (effect: string | undefined) => plan({ available_actions: [{ action: "approve", allowed: true, reason_code: null, effect } as never] });
  it("runs, only approves, or is not known — an effect the client does not know is never «does not run»", () => {
    expect(approveState(act("approve_and_queue_execution")).effect).toBe("run");
    expect(approveState(act("approve_only")).effect).toBe("only");
    expect(approveState(act("something_new")).effect).toBe("unknown");
    expect(approveState(act(undefined)).effect).toBe("unknown");
    expect(approveState(plan({ available_actions: [] })).effect).toBe("unknown");
  });

  it("the toast says what happened: the server's answer first, the page's belief only when it said nothing", () => {
    expect(approvedToastKey(true, "only")).toBe("toast.approved.run");            // the executor was switched on meanwhile
    expect(approvedToastKey(false, "run")).toBe("toast.approved.only");           // … or off
    expect(approvedToastKey(undefined, "run")).toBe("toast.approved.run");
    expect(approvedToastKey(undefined, "only")).toBe("toast.approved.only");
    expect(approvedToastKey(undefined, "unknown")).toBe("toast.approved.unknown");
  });
});

