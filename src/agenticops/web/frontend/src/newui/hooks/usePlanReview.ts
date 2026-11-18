import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { PreviousPlanDiff } from "@/api/types";
import { fixPlanMutationKeys } from "@/hooks/useFixPlans";
import { ACTIVITY_QUERY_KEY } from "./useActivity";

/** «Request changes» (POST /api/fix-plans/{id}/request-changes, N14): the plan is sent back with the reason AND the
 *  plan agent is asked for the next one — both, or neither. 409 `agent_run_in_flight` = an agent is on the issue and
 *  the plan was NOT sent back. Settled, not succeeded: a refusal re-reads the plan too. */
export function useRequestChanges() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      apiFetch<{ health_issue_id: number; fix_plan_id: number }>(`/fix-plans/${id}/request-changes`, { method: "POST", body: JSON.stringify({ reason }) }),
    onSettled: (_data, _error, vars) => {
      for (const queryKey of [...fixPlanMutationKeys(vars.id), [...ACTIVITY_QUERY_KEY]]) qc.invalidateQueries({ queryKey });
    },
  });
}

/** What this plan changed relative to the plan before it on the same issue (GET …/previous-diff, N14). Keyed by the
 *  plan's content hash too: a draft rewritten in place is another comparison. */
export function usePreviousDiff(planId: number, contentHash: string | null) {
  return useQuery({
    queryKey: ["fix-plan", planId, "previous-diff", contentHash ?? ""],
    queryFn: () => apiFetch<PreviousPlanDiff>(`/fix-plans/${planId}/previous-diff`),
    enabled: planId > 0,
    staleTime: 60_000,
  });
}
