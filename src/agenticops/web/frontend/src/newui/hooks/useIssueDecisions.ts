import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { ACTIVITY_QUERY_KEY } from "./useActivity";

const refresh = (qc: QueryClient, issueId: number) => {
  for (const key of [["anomaly", issueId], ["anomalies"], ["anomaly-rca", issueId], ["issue-timeline", issueId], ["fix-plans"],
                     ["issue-executions", issueId], ["ui-attention"], [...ACTIVITY_QUERY_KEY]]) qc.invalidateQueries({ queryKey: key });
};

/** Dismiss an issue with its reason: the reason goes with the status change and stays on the timeline. */
export function useDismissIssue(issueId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (reason: string) =>
      apiFetch<unknown>(`/issues/${issueId}/status`, { method: "PUT", body: JSON.stringify({ status: "dismissed", note: reason }) }),
    onSettled: () => refresh(qc, issueId),
  });
}

/** Mark an issue resolved: its run ended and a person confirms the problem is gone. */
export function useResolveIssue(issueId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<unknown>(`/issues/${issueId}/status`, { method: "PUT", body: JSON.stringify({ status: "resolved" }) }),
    onSettled: () => refresh(qc, issueId),
  });
}

/** Reopen a dismissed issue: it goes back to «open», and its signals alert again. */
export function useReopenIssue(issueId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<unknown>(`/issues/${issueId}/status`, { method: "PUT", body: JSON.stringify({ status: "open" }) }),
    onSettled: () => refresh(qc, issueId),
  });
}

/** Ask the RCA agent to diagnose the issue (again). The server starts it in the background, records the request on
 *  the timeline and refuses a second one while an agent is still on this issue (409 agent_run_in_flight). */
export function useTriggerRca(issueId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<unknown>(`/issues/${issueId}/rca`, { method: "POST" }),
    onSettled: () => refresh(qc, issueId),
  });
}

/** Ask the SRE agent for a fix plan from the issue's diagnosis. Same guard as the diagnosis. */
export function useTriggerPlan(issueId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<unknown>(`/issues/${issueId}/generate-fix-plan`, { method: "POST" }),
    onSettled: () => refresh(qc, issueId),
  });
}
