import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { AgentLogEntry, AgentLogTimeline, AgentLogSummary } from "@/api/types";

interface AgentLogParams {
  agent_name?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

export function useAgentLogs(params?: AgentLogParams) {
  const qs = new URLSearchParams();
  if (params?.agent_name) qs.set("agent_name", params.agent_name);
  if (params?.status) qs.set("status", params.status);
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  const query = qs.toString();

  return useQuery({
    queryKey: ["agent-logs", params],
    queryFn: () =>
      apiFetch<AgentLogEntry[]>(`/agent-logs${query ? `?${query}` : ""}`),
  });
}

export function useAgentTimeline(traceId: string | null) {
  return useQuery({
    queryKey: ["agent-timeline", traceId],
    queryFn: () =>
      apiFetch<AgentLogTimeline>(`/agent-logs/timeline/${traceId}`),
    enabled: !!traceId,
  });
}

export function useAgentLogSummary(hours: number) {
  return useQuery({
    queryKey: ["agent-log-summary", hours],
    queryFn: () =>
      apiFetch<AgentLogSummary>(`/agent-logs/summary?hours=${hours}`),
  });
}
