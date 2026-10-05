import { useQuery, useMutation, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { FixPlan, PlanKind } from "@/api/types";
import { toQuery } from "@/lib/plans";

/** Every query a fix-plan mutation must refresh — including plan-stats, which the Audit tab's KPIs read, the
 *  issue and its runs, which approve and execute move on the backend, and the issue timeline, where IssueDetail
 *  reads the approval's move and its auto-run's start (C1(c)). */
export const fixPlanMutationKeys = (id: number): QueryKey[] =>
  [["fix-plans"], ["fix-plan", id], ["plan-stats"], ["anomaly"], ["anomalies"], ["issue-executions"], ["issue-timeline"]];

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
    // approved_by is the legacy claimed name: the backend audits it but never trusts it.
    // content_hash is the plan content the approver was shown; the backend refuses (409) if it changed since.
    mutationFn: ({ id, content_hash, reason, approved_by }:
      { id: number; content_hash: string; reason?: string; approved_by?: string }) =>
      apiFetch<FixPlan>(`/fix-plans/${id}/approve`, {
        method: "PUT",
        body: JSON.stringify({ content_hash, reason, approved_by }),
      }),
    onSuccess: (_data, vars) => fixPlanMutationKeys(vars.id).forEach((queryKey) => qc.invalidateQueries({ queryKey })),
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
    onSuccess: (_data, vars) => fixPlanMutationKeys(vars.id).forEach((queryKey) => qc.invalidateQueries({ queryKey })),
  });
}

export function useExecuteFixPlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<unknown>(`/fix-plans/${id}/execute`, { method: "POST" }),
    onSuccess: (_data, id) =>
      [...fixPlanMutationKeys(id), ["fix-executions", id]].forEach((queryKey) => qc.invalidateQueries({ queryKey })),
  });
}
