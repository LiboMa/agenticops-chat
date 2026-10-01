import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { GraphFocus } from "@/api/types";
import { focusPath, type FocusSubject } from "@/lib/localGraph";

/** The local graph around an issue's anchor, a resource or a change request's targets (spec §3.E.3). */
export function useGraphFocus(subject: FocusSubject, includeLlm = false) {
  const path = focusPath(subject, { includeLlm });
  const id = Object.values(subject)[0];
  return useQuery({
    queryKey: ["graph-focus", path],
    queryFn: () => apiFetch<GraphFocus>(path),
    enabled: Number.isInteger(id) && id > 0, // a route's Number(id) can be NaN or 0, which the API answers 422
    staleTime: 30_000,
    placeholderData: keepPreviousData, // toggling the llm relations keeps the drawing until the answer lands
  });
}
