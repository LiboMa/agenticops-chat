import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { FixExecution } from "@/api/types";

export function useIssueExecutions(issueId: number) {
  return useQuery({
    queryKey: ["issue-executions", issueId],
    queryFn: () =>
      apiFetch<FixExecution[]>(`/health-issues/${issueId}/executions`),
    enabled: issueId > 0,
    staleTime: 15_000,
  });
}
