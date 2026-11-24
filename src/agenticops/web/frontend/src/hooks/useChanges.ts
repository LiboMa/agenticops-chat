import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ChangeRequest, ChangeRequestCreate, ChangeRequestDetail, ChangeRequestPage, ChangeStatus, FixExecution } from "@/api/types";
import { isTerminalChange, toQuery, type Period } from "@/lib/plans";

/** GET /api/changes filters. `status`: one status; `statuses`: several (sent as the comma list the server takes).
 *  MVP-2.9.0 N18: `q` (title / account / C#n), `sort`, `view=mine` (what waits on the caller); the answer is
 *  `{items, total}`. */
export type ChangeFilters = {
  status?: ChangeStatus; statuses?: ChangeStatus[]; account_id?: number; requested_by?: string; period?: Period; q?: string;
  sort?: "newest" | "oldest"; view?: "all" | "mine"; limit?: number; offset?: number;
};

/** The query string of a change list request. */
export function changesQuery({ statuses, ...rest }: ChangeFilters): string {
  return toQuery({ ...rest, status: statuses?.length ? statuses.join(",") : rest.status });
}

/** Every query a change mutation must refresh — including plan-stats, which the Audit tab's KPIs read. */
export const changeMutationKeys = (id: number): QueryKey[] =>
  [["changes"], ["change", id], ["change-timeline", id], ["fix-plans"], ["plan-stats"], ["ui-attention"]];

export function useChanges(filters: ChangeFilters = {}) {
  return useQuery({
    queryKey: ["changes", filters],
    queryFn: () => apiFetch<ChangeRequestPage>(`/changes${changesQuery(filters)}`),
    staleTime: 10_000,
    refetchInterval: 15_000,
  });
}

export function useChange(id: number) {
  return useQuery({
    queryKey: ["change", id],
    queryFn: () => apiFetch<ChangeRequestDetail>(`/changes/${id}`),
    enabled: id > 0,
    // poll while the request is still moving (review / execution run in the background)
    refetchInterval: (q) => (q.state.data && !isTerminalChange(q.state.data.status) ? 5_000 : false),
  });
}

export function useCreateChange() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ChangeRequestCreate) => apiFetch<ChangeRequest>("/changes", { method: "POST", body: JSON.stringify(body) }),
    // a create changes the list and the counts
    onSuccess: () => [["changes"], ["plan-stats"], ["ui-attention"]].forEach((queryKey) => qc.invalidateQueries({ queryKey })),
  });
}

// Each action carries exactly the body the backend expects; review/execute take none.
// An approve names the implementation plan content it approves (409 if that plan changed since); a
// resolve-review is the change's acceptance, and the API requires its reason.
export type ChangeActionArgs =
  | { id: number; action: "approve"; body: { reason: string; content_hash: string } }
  | { id: number; action: "reject" | "cancel"; body: { reason: string } }
  | { id: number; action: "clarify"; body: { message: string } }
  | { id: number; action: "resolve-review"; body: { outcome: "completed" | "failed"; reason: string; confirmed_checks?: string[] } }
  | { id: number; action: "review" }
  | { id: number; action: "execute" };

export function useChangeAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: ChangeActionArgs) =>
      apiFetch<ChangeRequest | FixExecution>(`/changes/${args.id}/${args.action}`, {
        method: "POST",
        body: "body" in args ? JSON.stringify(args.body) : undefined,
      }),
    // settled, not succeeded: a refusal (409 — someone else moved the change) must re-read it too, as a fix plan's does
    onSettled: (_d, _e, vars) => changeMutationKeys(vars.id).forEach((queryKey) => qc.invalidateQueries({ queryKey })),
  });
}
