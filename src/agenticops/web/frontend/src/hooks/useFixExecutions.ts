import { useQuery } from "@tanstack/react-query";
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
