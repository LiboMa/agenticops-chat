import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { PipelineEvent } from "@/api/types";

export function useIssueTimeline(issueId: number) {
  return useQuery({
    queryKey: ["issue-timeline", issueId],
    queryFn: () =>
      apiFetch<PipelineEvent[]>(`/health-issues/${issueId}/timeline`),
    enabled: issueId > 0,
    staleTime: 10_000,
    refetchInterval: 15_000,
  });
}
