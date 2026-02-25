import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { FixPlan } from "@/api/types";

interface FixPlanFilters {
  status?: string;
  risk_level?: string;
  health_issue_id?: number;
}

export function useFixPlans(filters: FixPlanFilters = {}) {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.risk_level) params.set("risk_level", filters.risk_level);
  if (filters.health_issue_id)
    params.set("health_issue_id", String(filters.health_issue_id));
  const qs = params.toString();

  return useQuery({
    queryKey: ["fix-plans", filters],
    queryFn: () => apiFetch<FixPlan[]>(`/fix-plans${qs ? `?${qs}` : ""}`),
    staleTime: 30_000,
  });
}

export function useFixPlan(id: number) {
  return useQuery({
    queryKey: ["fix-plan", id],
    queryFn: () => apiFetch<FixPlan>(`/fix-plans/${id}`),
    enabled: id > 0,
  });
}

export function useApproveFixPlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, approved_by }: { id: number; approved_by: string }) =>
      apiFetch<FixPlan>(`/fix-plans/${id}/approve`, {
        method: "PUT",
        body: JSON.stringify({ approved_by }),
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["fix-plans"] });
      qc.invalidateQueries({ queryKey: ["fix-plan", vars.id] });
    },
  });
}

export function useRejectFixPlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<FixPlan>(`/fix-plans/${id}`, {
        method: "PUT",
        body: JSON.stringify({ status: "rejected" }),
      }),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["fix-plans"] });
      qc.invalidateQueries({ queryKey: ["fix-plan", id] });
    },
  });
}

export function useExecuteFixPlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<unknown>(`/fix-plans/${id}/execute`, { method: "POST" }),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["fix-plans"] });
      qc.invalidateQueries({ queryKey: ["fix-plan", id] });
      qc.invalidateQueries({ queryKey: ["fix-executions", id] });
    },
  });
}
