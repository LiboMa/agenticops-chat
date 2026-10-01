import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { FixExecution } from "@/api/types";

export function useFixExecutions(planId: number) {
  return useQuery({
    queryKey: ["fix-executions", planId],
    queryFn: () =>
      apiFetch<FixExecution[]>(`/fix-plans/${planId}/executions`),
    enabled: planId > 0,
    staleTime: 15_000,
  });
}

export function useCancelExecution() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (executionId: number) =>
      apiFetch<unknown>(`/fix-executions/${executionId}/cancel`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["fix-executions"] });
      qc.invalidateQueries({ queryKey: ["issue-executions"] });
      qc.invalidateQueries({ queryKey: ["fix-plans"] });
    },
  });
}

/** A human's verdict on a run pending acceptance; the identity is the session's, the reason is required. */
export function useAcceptExecution() {
  const qc = useQueryClient();
  return useMutation({
    // the response is the updated execution row; callers rely on the invalidation below, not on it
    mutationFn: ({ id, decision, reason }: { id: number; decision: "accepted" | "rejected"; reason: string }) =>
      apiFetch<FixExecution>(
        `/fix-executions/${id}/accept`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision, reason }) },
      ),
    onSuccess: () => {
      // accepted resolves the issue; rejected returns it to root_cause_identified and disputes the RCA
      for (const key of ["issue-executions", "fix-executions", "anomaly", "anomaly-rca", "issue-timeline", "fix-plans"]) {
        qc.invalidateQueries({ queryKey: [key] });
      }
    },
  });
}
