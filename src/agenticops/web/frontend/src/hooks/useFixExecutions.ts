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
