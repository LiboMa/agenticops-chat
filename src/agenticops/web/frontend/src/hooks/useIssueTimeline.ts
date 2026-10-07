import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

/** Append a note (MVP-2.7.0 S4): POST /api/health-issues/{id}/notes as the session user; the activity refetches. */
export function useAddIssueNote(issueId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (content: string) =>
      apiFetch<{ event_id: number }>(`/health-issues/${issueId}/notes`, { method: "POST", body: JSON.stringify({ content }) }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["issue-timeline", issueId] }),
  });
}
