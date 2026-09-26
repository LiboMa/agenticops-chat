import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ChangeTimelineEntry } from "@/api/types";
import { isTerminalChange } from "@/lib/plans";

/** The change request's merged event + audit timeline; polls until the request reaches a terminal status. */
export function useChangeTimeline(id: number, status?: string) {
  return useQuery({
    queryKey: ["change-timeline", id],
    queryFn: () => apiFetch<ChangeTimelineEntry[]>(`/changes/${id}/timeline`),
    enabled: id > 0,
    refetchInterval: isTerminalChange(status) ? false : 10_000,
  });
}
