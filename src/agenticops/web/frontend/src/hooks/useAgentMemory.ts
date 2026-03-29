import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";

/* ── Types ─────────────────────────────────────────────────────────── */

export interface AgentMemory {
  agent: string;
  filename: string;
  type: string;
  status: string;
  confidence: number;
  source: string;
  resource_pattern: string;
  related_issue_id: number | null;
  summary: string;
  created_at: string;
  last_confirmed: string;
}

export interface AgentMemoryDetail {
  agent: string;
  filename: string;
  frontmatter: Record<string, unknown>;
  body: string;
}

export interface AgentMemoryUpdate {
  confidence?: number;
  status?: string;
  body?: string;
}

export interface IssueFeedback {
  type: "false_positive" | "confirmed";
  note?: string;
  confidence?: number;
}

/* ── List memories ─────────────────────────────────────────────────── */

export function useAgentMemories(agent = "", status = "active") {
  return useQuery<AgentMemory[]>({
    queryKey: ["agent-memory", agent, status],
    queryFn: () => {
      const params = new URLSearchParams();
      if (agent) params.set("agent", agent);
      if (status) params.set("status", status);
      const qs = params.toString();
      return apiFetch<AgentMemory[]>(`/agent-memory${qs ? `?${qs}` : ""}`);
    },
  });
}

/* ── Get single memory ─────────────────────────────────────────────── */

export function useAgentMemoryDetail(agent: string, filename: string) {
  return useQuery<AgentMemoryDetail>({
    queryKey: ["agent-memory", agent, filename],
    queryFn: () => apiFetch<AgentMemoryDetail>(`/agent-memory/${agent}/${filename}`),
    enabled: !!agent && !!filename,
  });
}

/* ── Update memory ─────────────────────────────────────────────────── */

export function useUpdateAgentMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ agent, filename, data }: { agent: string; filename: string; data: AgentMemoryUpdate }) =>
      apiFetch<unknown>(`/agent-memory/${agent}/${filename}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent-memory"] });
    },
  });
}

/* ── Delete (archive) memory ───────────────────────────────────────── */

export function useDeleteAgentMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ agent, filename }: { agent: string; filename: string }) =>
      apiFetch<unknown>(`/agent-memory/${agent}/${filename}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent-memory"] });
    },
  });
}

/* ── Issue feedback (false positive / confirmed) ───────────────────── */

export function useIssueFeedback() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ issueId, feedback }: { issueId: number; feedback: IssueFeedback }) =>
      apiFetch<unknown>(`/health-issues/${issueId}/feedback`, {
        method: "POST",
        body: JSON.stringify(feedback),
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["anomaly", vars.issueId] });
      qc.invalidateQueries({ queryKey: ["anomalies"] });
      qc.invalidateQueries({ queryKey: ["agent-memory"] });
    },
  });
}
