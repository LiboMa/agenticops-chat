import { describe, it, expect, vi } from "vitest";
import { MutationObserver, QueryClient } from "@tanstack/react-query";

vi.mock("@/api/client", () => ({
  apiFetch: vi.fn(async () => { throw Object.assign(new Error("Fix plan is already approved"), { status: 409 }); }),
}));
import { approveFixPlanMutation, executeFixPlanMutation, rejectFixPlanMutation } from "@/hooks/useFixPlans";

// final review I6: a losing approval (409: someone else moved the plan) must re-read the plan, or a stale Approve lingers
describe("fix-plan mutations refresh the plan even when the server refuses", () => {
  it.each([
    ["approve", (qc: QueryClient) => new MutationObserver(qc, approveFixPlanMutation(qc)).mutate({ id: 9, content_hash: "h" })],
    ["reject", (qc: QueryClient) => new MutationObserver(qc, rejectFixPlanMutation(qc)).mutate({ id: 9, reason: "r" })],
    ["execute", (qc: QueryClient) => new MutationObserver(qc, executeFixPlanMutation(qc)).mutate(9)],
  ])("%s → 409 → the plan, its list and the attention list are stale", async (_name, run) => {
    const qc = new QueryClient();
    for (const key of [["fix-plan", 9], ["fix-plans", {}], ["ui-attention"]]) qc.setQueryData(key, { cached: true });
    await (run(qc) as Promise<unknown>).catch(() => undefined);
    for (const key of [["fix-plan", 9], ["fix-plans", {}], ["ui-attention"]]) expect(qc.getQueryState(key)?.isInvalidated).toBe(true);
  });
});
