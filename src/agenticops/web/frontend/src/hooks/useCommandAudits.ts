import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { CommandAudit } from "@/api/types";
import { toQuery, type Period } from "@/lib/plans";

export type CommandAuditFilters = { actor?: string; tool?: string; outcome?: CommandAudit["outcome"]; fix_plan_id?: number; change_request_id?: number; period?: Period; limit?: number };

export function useCommandAudits(filters: CommandAuditFilters = {}) {
  return useQuery({ queryKey: ["command-audits", filters], queryFn: () => apiFetch<CommandAudit[]>(`/command-audits${toQuery(filters)}`), staleTime: 15_000 });
}
