import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { AuditLogEntry, AuditStats } from "@/api/types";

interface AuditLogParams {
  action?: string;
  entity_type?: string;
  hours?: number;
}

export function useAuditLog(params: AuditLogParams) {
  const qs = new URLSearchParams();
  if (params.action) qs.set("action", params.action);
  if (params.entity_type) qs.set("entity_type", params.entity_type);
  if (params.hours) qs.set("hours", String(params.hours));
  const query = qs.toString();

  return useQuery({
    queryKey: ["audit", params],
    queryFn: () =>
      apiFetch<AuditLogEntry[]>(`/audit${query ? `?${query}` : ""}`),
  });
}

export function useAuditStats(hours = 24) {
  return useQuery({
    queryKey: ["audit-stats", hours],
    queryFn: () => apiFetch<AuditStats>(`/audit/stats?hours=${hours}`),
  });
}
