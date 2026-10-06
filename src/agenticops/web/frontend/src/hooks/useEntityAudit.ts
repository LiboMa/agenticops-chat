import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";

export interface EntityAuditRow { action: string; actor: string; details: Record<string, unknown> | null; created_at: string }

/** An entity's audit trail (GET /api/audit/entity/{type}/{id}); fail-soft — PlanDetail shows the plan's own fields
 *  when it cannot be read. */
export function useEntityAudit(entityType: string, entityId: number) {
  return useQuery({
    queryKey: ["entity-audit", entityType, entityId],
    queryFn: () => apiFetch<EntityAuditRow[]>(`/audit/entity/${entityType}/${entityId}`),
    enabled: entityId > 0,
    retry: false,
  });
}
