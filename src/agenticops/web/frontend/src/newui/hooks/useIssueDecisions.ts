import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { ACTIVITY_QUERY_KEY } from "./useActivity";

const refresh = (qc: QueryClient, issueId: number) => {
  // «galaxy-health»: a dismissed, resolved or reopened issue changes its resource's ring on the map
  for (const key of [["anomaly", issueId], ["anomalies"], ["anomaly-rca", issueId], ["issue-timeline", issueId], ["fix-plans"],
                     ["issue-executions", issueId], ["ui-attention"], [...ACTIVITY_QUERY_KEY], ["galaxy-health"]]) qc.invalidateQueries({ queryKey: key });
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

/** Mark an issue resolved: its run ended and a person confirms the problem is gone. Final — a resolved issue cannot
 *  be reopened — so the request names the status the page showed (`expected`), and the server refuses it (409
 *  `status_moved`) when the issue has left that status meanwhile. */
export function useResolveIssue(issueId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (expected: string) =>
      apiFetch<unknown>(`/issues/${issueId}/status`, { method: "PUT", body: JSON.stringify({ status: "resolved", expected_status: expected }) }),
    onSettled: () => refresh(qc, issueId),
  });
}

/** A verdict on the diagnosis the person was shown. `rca_id` names it: when a newer diagnosis exists the server
 *  refuses the verdict (409 `rca_changed`) instead of recording it against one nobody read. */
export function useRcaVerdict(issueId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { verdict?: "correct" | "incorrect"; location_verdict?: "correct" | "partial" | "incorrect"; note?: string; rca_id: number }) =>
      apiFetch<{ rca_id: number }>(`/health-issues/${issueId}/rca-feedback`, { method: "POST", body: JSON.stringify(payload) }),
    onSettled: () => refresh(qc, issueId),          // a refusal re-reads the diagnosis too
  });
}

/** «Confirmed» / «false alarm» on the issue itself. A false alarm dismisses it, so the queue is re-read as well. */
export function useIssueVerdict(issueId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (feedback: { type: "confirmed" | "false_positive"; note?: string; confidence: number }) =>
      apiFetch<unknown>(`/health-issues/${issueId}/feedback`, { method: "POST", body: JSON.stringify(feedback) }),
    onSettled: () => { refresh(qc, issueId); qc.invalidateQueries({ queryKey: ["agent-memory"] }); },
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
