import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { FixPlan, PlanKind } from "@/api/types";
import { toQuery } from "@/lib/plans";

// A type alias, not an interface: only an alias is assignable to toQuery's Record parameter.
export type FixPlanFilters = {
  status?: string;
  risk_level?: string;
  health_issue_id?: number;
  account_id?: number;
  kind?: PlanKind;
  limit?: number;
};

export function useFixPlans(filters: FixPlanFilters = {}) {
  return useQuery({
    queryKey: ["fix-plans", filters],
    queryFn: () => apiFetch<FixPlan[]>(`/fix-plans${toQuery(filters)}`),
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
    // approved_by is the legacy claimed name: the backend audits it but never trusts it
    mutationFn: ({ id, reason, approved_by }: { id: number; reason?: string; approved_by?: string }) =>
      apiFetch<FixPlan>(`/fix-plans/${id}/approve`, {
        method: "PUT",
        body: JSON.stringify({ reason, approved_by }),
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
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      apiFetch<FixPlan>(`/fix-plans/${id}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["fix-plans"] });
      qc.invalidateQueries({ queryKey: ["fix-plan", vars.id] });
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
