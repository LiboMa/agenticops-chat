import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { ATTENTION_QUERY_KEY } from "@/lib/attention";

/** «Later» (N14): put one of my waiting items at the end of its group for a while (`on`), or take that back.
 *  It changes nothing about the item and nothing for anyone else; the list is read again either way. */
export function useSnooze() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ item, on }: { item: string; on: boolean }) => on
      ? apiFetch<{ item: string; snoozed_until: string }>("/ui/attention/snooze", { method: "POST", body: JSON.stringify({ item }) })
      : apiFetch<null>(`/ui/attention/snooze?item=${encodeURIComponent(item)}`, { method: "DELETE" }).then(() => null),
    onSettled: () => { qc.invalidateQueries({ queryKey: [...ATTENTION_QUERY_KEY] }); },
  });
}
