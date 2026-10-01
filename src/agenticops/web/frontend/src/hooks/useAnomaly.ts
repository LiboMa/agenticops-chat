import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { HealthIssue } from "@/api/types";

// The health-issue endpoint (MVP-2.6.1): the legacy /issues/{id} shape drops trace_id, merged_alerts and the anchor
export function useAnomaly(id: number) {
  return useQuery({
    queryKey: ["anomaly", id],
    queryFn: () => apiFetch<HealthIssue>(`/health-issues/${id}`),
    staleTime: 5 * 60_000,
  });
}
