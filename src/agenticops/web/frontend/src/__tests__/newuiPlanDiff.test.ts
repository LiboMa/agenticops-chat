import { describe, expect, it } from "vitest";
import type { PreviousPlanDiff } from "@/api/types";
import { OPEN_UP_TO, partOf, prevDiffVm, tallyOf } from "@/newui/lib/briefs/diff";

const NONE = { added: [], removed: [], modified: [], unchanged: 0 };
const answer = (over: Partial<PreviousPlanDiff> = {}, prev: Partial<NonNullable<PreviousPlanDiff["previous"]>> = {}): PreviousPlanDiff => ({
  plan_id: 12,
  previous: { id: 9, status: "rejected", plan_version: 1, risk_level: "L2", created_at: "2026-11-18T08:00:00Z",
              rejected_by: "user:alice", rejected_at: "2026-11-18T08:05:00Z", rejection_reason: "restart only the web tier",
              rejection_is_feedback: true, same_diagnosis: true, ...prev },
  same_content: false,
  steps: { ...NONE, unchanged: 2 },
  rollback: { ...NONE },
  ...over,
});

describe("partOf — one list's changes as lines in reading order", () => {
  it("is empty for no answer", () => {
    expect(partOf(null)).toEqual({ lines: [], unchanged: 0 });
  });

  it("puts a removed step where it was, before what took its number", () => {
    const part = partOf({
      added: [{ step: 3, text: "kubectl get endpoints web" }],
      removed: [{ previous_step: 2, text: "kubectl delete pod web-0" }],
      modified: [{ previous_step: 1, step: 1, previous: "kubectl rollout restart deploy", now: "kubectl rollout restart deploy/web" }],
      unchanged: 1,
    });
    expect(part.unchanged).toBe(1);
    expect(part.lines).toEqual([
      { kind: "chg", n: 1, text: "kubectl rollout restart deploy/web", was: "kubectl rollout restart deploy", wasN: 1 },
      { kind: "del", n: 2, text: "kubectl delete pod web-0" },
      { kind: "add", n: 3, text: "kubectl get endpoints web" },
    ]);
  });

  it("keeps a modified step's old number when it moved", () => {
    const part = partOf({ added: [], removed: [], modified: [{ previous_step: 2, step: 4, previous: "a", now: "b" }], unchanged: 0 });
    expect(part.lines).toEqual([{ kind: "chg", n: 4, text: "b", was: "a", wasN: 2 }]);
  });
});

describe("prevDiffVm — what the approver is told about the plan before this one", () => {
  it("is nothing for an issue's first plan, or before the answer is here", () => {
    expect(prevDiffVm(undefined, "L1")).toBeNull();
    expect(prevDiffVm(answer({ previous: null, steps: null, rollback: null, same_content: null }), "L1")).toBeNull();
  });

  it("quotes a person's reason, and only a person's", () => {
    const vm = prevDiffVm(answer(), "L2")!;
    expect([vm.previousId, vm.ended, vm.by, vm.at, vm.reason]).toEqual([9, "feedback", "user:alice", "2026-11-18T08:05:00Z", "restart only the web tier"]);
    const code = prevDiffVm(answer({}, { rejection_is_feedback: false, rejection_reason: "content changed after approval" }), "L2")!;
    expect([code.ended, code.reason]).toEqual(["byCode", "content changed after approval"]);
    const bare = prevDiffVm(answer({}, { rejection_is_feedback: false, rejection_reason: "  " }), "L2")!;
    expect([bare.ended, bare.reason]).toEqual(["rejected", ""]);
  });

  it("says what became of a plan that was not sent back", () => {
    const failed = prevDiffVm(answer({}, { status: "failed", rejected_by: null, rejected_at: null, rejection_reason: null, rejection_is_feedback: false }), "L2")!;
    expect(failed.ended).toBe("failed");
    expect(prevDiffVm(answer({}, { status: "executed", rejection_is_feedback: false }), "L2")!.ended).toBe("ran");
    expect(prevDiffVm(answer({}, { status: "approved", rejection_is_feedback: false }), "L2")!.ended).toBe("other");
  });

  it("a plan redone word for word is said to be identical", () => {
    expect(prevDiffVm(answer({ same_content: true }), "L2")!.verdict).toBe("identical");
  });

  it("no changed line is not «nothing changed»: the content differs, or it is not known", () => {
    expect(prevDiffVm(answer({ same_content: false }), "L2")!.verdict).toBe("sameCommands");
    expect(prevDiffVm(answer({ same_content: null }), "L2")!.verdict).toBe("sameCommandsUnknown");
  });

  it("any changed step or rollback line is a change", () => {
    const steps = { ...NONE, added: [{ step: 1, text: "x" }] };
    expect(prevDiffVm(answer({ steps }), "L2")!.verdict).toBe("changed");
    const rollback = { ...NONE, removed: [{ previous_step: 1, text: "y" }] };
    const vm = prevDiffVm(answer({ rollback }), "L2")!;
    expect(vm.verdict).toBe("changed");
    expect(vm.rollback.lines).toEqual([{ kind: "del", n: 1, text: "y" }]);
  });

  it("names a changed risk level and a different diagnosis, and nothing when they are the same or unknown", () => {
    expect(prevDiffVm(answer(), "L1")!.risk).toEqual({ from: "L2", to: "L1" });
    expect(prevDiffVm(answer(), "L2")!.risk).toBeNull();
    expect(prevDiffVm(answer(), null)!.risk).toBeNull();
    expect(prevDiffVm(answer({}, { same_diagnosis: false }), "L2")!.otherDiagnosis).toBe(true);
    expect(prevDiffVm(answer({}, { same_diagnosis: null }), "L2")!.otherDiagnosis).toBe(false);
  });
});

describe("tallyOf — one list's changes in one sentence's worth of numbers", () => {
  const part = partOf({
    added: [{ step: 3, text: "c" }],
    removed: [{ previous_step: 2, text: "b" }, { previous_step: 4, text: "d" }],
    modified: [{ previous_step: 1, step: 1, previous: "a", now: "a2" }],
    unchanged: 5,
  });

  it("counts each kind and what did not change", () => {
    expect(tallyOf(part)).toEqual({ chg: 1, add: 1, del: 2, same: 5, open: true, comparable: true });
  });

  it("a long list starts folded: the numbers are read first", () => {
    const many = partOf({ added: [], removed: [], unchanged: 0,
                          modified: Array.from({ length: OPEN_UP_TO + 1 }, (_x, i) => ({ previous_step: i + 1, step: i + 1, previous: "a", now: "b" })) });
    expect(tallyOf(many).open).toBe(false);
    const few = partOf({ added: [], removed: [], unchanged: 0,
                         modified: Array.from({ length: OPEN_UP_TO }, (_x, i) => ({ previous_step: i + 1, step: i + 1, previous: "a", now: "b" })) });
    expect(tallyOf(few).open).toBe(true);
  });

  it("two lists with nothing in them cannot be compared — that is not «unchanged»", () => {
    expect(tallyOf(partOf({ added: [], removed: [], modified: [], unchanged: 0 })).comparable).toBe(false);
    expect(tallyOf(partOf({ added: [], removed: [], modified: [], unchanged: 2 })).comparable).toBe(true);
    expect(tallyOf(partOf(null)).comparable).toBe(false);
  });
});
