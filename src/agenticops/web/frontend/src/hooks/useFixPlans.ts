import { useQuery, useMutation, useQueryClient, type QueryClient, type QueryKey, type UseMutationOptions } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { FixPlan, PlanKind } from "@/api/types";
import { toQuery } from "@/lib/plans";

/** Every query a fix-plan mutation must refresh — including plan-stats, which the Audit tab's KPIs read, the
 *  issue and its runs, which approve and execute move on the backend, and the issue timeline, where IssueDetail
 *  reads the approval's move and its auto-run's start (C1(c)). */
export const fixPlanMutationKeys = (id: number): QueryKey[] =>
  [["fix-plans"], ["fix-plan", id], ["plan-stats"], ["anomaly"], ["anomalies"], ["issue-executions"], ["issue-timeline"], ["ui-attention"]];

export type FixPlanFilters = {
  status?: string;
  risk_level?: string;
  health_issue_id?: number;
  account_id?: number;
  kind?: PlanKind;
  q?: string;
  limit?: number;
};

export function useFixPlans(filters: FixPlanFilters = {}) {
  return useQuery({
    queryKey: ["fix-plans", filters],
    queryFn: () => apiFetch<FixPlan[]>(`/fix-plans${toQuery(filters)}`),
    staleTime: 30_000,
  });
}

export function useFixPlan(id: number, refetchInterval: number | false = false) {
  return useQuery({
    queryKey: ["fix-plan", id],
    queryFn: () => apiFetch<FixPlan>(`/fix-plans/${id}`),
    enabled: id > 0,
    refetchInterval,
  });
}

/** The approve / reject / execute mutations as options (useMutation and node tests share them). */
type ApproveVars = { id: number; content_hash: string; reason?: string; approved_by?: string };
export const approveFixPlanMutation = (qc: QueryClient): UseMutationOptions<FixPlan, Error, ApproveVars> => ({
  // approved_by is the legacy claimed name: the backend audits it but never trusts it.
  // content_hash is the plan content the approver was shown; the backend refuses (409) if it changed since.
  mutationFn: ({ id, content_hash, reason, approved_by }: ApproveVars) =>
    apiFetch<FixPlan>(`/fix-plans/${id}/approve`, {
      method: "PUT",
      body: JSON.stringify({ content_hash, reason, approved_by }),
    }),
  // settled, not succeeded: a refusal (409 — someone else moved the plan) must re-read it too (final review I6)
  onSettled: (_data: unknown, _error: unknown, vars: { id: number }) => fixPlanMutationKeys(vars.id).forEach((queryKey) => qc.invalidateQueries({ queryKey })),
});

export const rejectFixPlanMutation = (qc: QueryClient): UseMutationOptions<FixPlan, Error, { id: number; reason: string }> => ({
  mutationFn: ({ id, reason }: { id: number; reason: string }) =>
    apiFetch<FixPlan>(`/fix-plans/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  // settled, not succeeded: a refusal (409 — someone else moved the plan) must re-read it too (final review I6)
  onSettled: (_data: unknown, _error: unknown, vars: { id: number }) => fixPlanMutationKeys(vars.id).forEach((queryKey) => qc.invalidateQueries({ queryKey })),
});

export const executeFixPlanMutation = (qc: QueryClient): UseMutationOptions<unknown, Error, number> => ({
  mutationFn: (id: number) =>
    apiFetch<unknown>(`/fix-plans/${id}/execute`, { method: "POST" }),
  onSettled: (_data: unknown, _error: unknown, id: number) =>
    [...fixPlanMutationKeys(id), ["fix-executions", id]].forEach((queryKey) => qc.invalidateQueries({ queryKey })),
});

export function useApproveFixPlan() {
  const qc = useQueryClient();
  return useMutation(approveFixPlanMutation(qc));
}

export function useRejectFixPlan() {
  const qc = useQueryClient();
  return useMutation(rejectFixPlanMutation(qc));
}

export function useExecuteFixPlan() {
  const qc = useQueryClient();
  return useMutation(executeFixPlanMutation(qc));
}
