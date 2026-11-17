import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { useUpdateIssueStatus } from "@/hooks/useIssueActions";
import { useAddIssueNote } from "@/hooks/useIssueTimeline";
import { errorText } from "../decide/briefs/briefContext";

/** Dismiss an issue with its reason. The status endpoint keeps no reason, so the reason goes onto the issue's
 *  timeline as a note first; a retry after the second step failed does not write the note twice. */
export function useDismissIssue(issueId: number) {
  const note = useAddIssueNote(issueId);
  const status = useUpdateIssueStatus();
  const noted = useRef<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dismiss = async (reason: string, prefix: string): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      if (noted.current !== reason) { await note.mutateAsync(prefix + reason); noted.current = reason; }
      await status.mutateAsync({ id: issueId, status: "dismissed" });
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { dismiss, busy, error };
}

/** Ask the RCA agent to diagnose the issue again (POST /api/issues/{id}/rca starts it in the background). */
export function useTriggerRca(issueId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<unknown>(`/issues/${issueId}/rca`, { method: "POST" }),
    onSettled: () => {
      for (const key of [["anomaly", issueId], ["anomaly-rca", issueId], ["issue-timeline", issueId], ["ui-attention"]]) qc.invalidateQueries({ queryKey: key });
    },
  });
}
