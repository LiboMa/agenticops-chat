import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { HealthIssue } from "@/api/types";
import { ISSUE_IN_FLIGHT } from "@/lib/issueDetail";

// The health-issue endpoint (MVP-2.6.1): the legacy /issues/{id} shape drops trace_id, merged_alerts and the anchor
export function useAnomaly(id: number) {
  return useQuery({
    queryKey: ["anomaly", id],
    queryFn: () => apiFetch<HealthIssue>(`/health-issues/${id}`),
    staleTime: 5 * 60_000,
    // while a fix is in motion, so the page follows approve → execute → the run's verdict without a reload
    refetchInterval: (q) => (q.state.data && ISSUE_IN_FLIGHT.has(q.state.data.status) ? 5_000 : false),
  });
}
