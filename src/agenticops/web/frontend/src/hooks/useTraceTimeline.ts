import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { AgentLogTimeline } from "@/api/types";

export function useTraceTimeline(traceId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ["trace-timeline", traceId],
    queryFn: () => apiFetch<AgentLogTimeline>(`/api/agent-logs/timeline/${traceId}`),
    enabled: enabled && !!traceId,
    staleTime: 60_000,
  });
}
