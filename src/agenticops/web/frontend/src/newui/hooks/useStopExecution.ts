import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { FixExecution } from "@/api/types";
import { ACTIVITY_QUERY_KEY } from "./useActivity";

/** Ask a run in progress to stop (POST /api/fix-executions/{id}/stop, N9). The server writes the request on the run's
 *  record: the executor finishes the command it is on, is refused every further step of the plan, and may then run
 *  only the plan's own rollback steps and read-only checks. 409 `not_running` = it had ended already;
 *  409 `already_stopping` = somebody else asked first. */
export function useStopExecution() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason?: string }) =>
      apiFetch<FixExecution>(`/fix-executions/${id}/stop`, { method: "POST", body: JSON.stringify({ reason: reason ?? "" }) }),
    onSettled: () => {
      for (const key of [[...ACTIVITY_QUERY_KEY], ["issue-executions"], ["fix-executions"], ["issue-timeline"], ["change-timeline"], ["ui-attention"]]) {
        qc.invalidateQueries({ queryKey: key });
      }
    },
  });
}
