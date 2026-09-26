import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ChangeTimelineEntry } from "@/api/types";
import { isTerminalChange } from "@/lib/plans";

/** The change request's merged event + audit timeline. Polls until the request is terminal, then refetches
 *  once on the non-terminal -> terminal flip so the closing rows the executor wrote in the background arrive. */
export function useChangeTimeline(id: number, status: string | undefined) {
  const terminal = isTerminalChange(status);
  const q = useQuery({
    queryKey: ["change-timeline", id],
    queryFn: () => apiFetch<ChangeTimelineEntry[]>(`/changes/${id}/timeline`),
    enabled: id > 0,
    refetchInterval: terminal ? false : 10_000,
  });
  const wasTerminal = useRef(terminal);
  useEffect(() => {
    if (terminal && !wasTerminal.current) void q.refetch();
    wasTerminal.current = terminal;
  }, [terminal, q.refetch]);
  return q;
}
