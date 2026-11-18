import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { StepRow } from "../lib/steps";

/** Say a word to an agent while it works (POST /api/ui/activity/note, N12). The note is a step of the run (kind
 *  «you») and reaches the agent before its next model call; the answer is that step, and the step list is asked
 *  again so it shows at once. 409 `not_running` = the run had ended: the note was not delivered. */
export function useSteer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ lane, text }: { lane: string; text: string }) =>
      apiFetch<StepRow>("/ui/activity/note", { method: "POST", body: JSON.stringify({ lane, text }) }),
    onSettled: () => { void qc.invalidateQueries({ queryKey: ["ui-activity-steps"] }); },
  });
}
