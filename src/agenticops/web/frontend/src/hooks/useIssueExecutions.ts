import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { FixExecution } from "@/api/types";
import { hasRunInFlight } from "@/lib/issueDetail";

export function useIssueExecutions(issueId: number) {
  return useQuery({
    queryKey: ["issue-executions", issueId],
    queryFn: () =>
      apiFetch<FixExecution[]>(`/health-issues/${issueId}/executions`),
    enabled: issueId > 0,
    staleTime: 15_000,
    refetchInterval: (q) => (hasRunInFlight(q.state.data) ? 5_000 : false),
  });
}
