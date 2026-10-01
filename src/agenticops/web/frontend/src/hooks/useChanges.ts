import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ChangeRequest, ChangeRequestCreate, ChangeRequestDetail, ChangeStatus, FixExecution } from "@/api/types";
import { isTerminalChange, toQuery, type Period } from "@/lib/plans";

export type ChangeFilters = { status?: ChangeStatus; account_id?: number; requested_by?: string; period?: Period; limit?: number; offset?: number };

/** Every query a change mutation must refresh — including plan-stats, which the Audit tab's KPIs read. */
export const changeMutationKeys = (id: number): QueryKey[] =>
  [["changes"], ["change", id], ["change-timeline", id], ["fix-plans"], ["plan-stats"]];

export function useChanges(filters: ChangeFilters = {}) {
  return useQuery({
    queryKey: ["changes", filters],
    queryFn: () => apiFetch<ChangeRequest[]>(`/changes${toQuery(filters)}`),
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
    onSuccess: () => [["changes"], ["plan-stats"]].forEach((queryKey) => qc.invalidateQueries({ queryKey })),
  });
}

// Each action carries exactly the body the backend expects; review/execute take none.
// An approve names the implementation plan content it approves (409 if that plan changed since); a
// resolve-review is the change's acceptance, and the API requires its reason.
export type ChangeActionArgs =
  | { id: number; action: "approve"; body: { reason: string; content_hash: string } }
  | { id: number; action: "reject" | "cancel"; body: { reason: string } }
  | { id: number; action: "clarify"; body: { message: string } }
  | { id: number; action: "resolve-review"; body: { outcome: "completed" | "failed"; reason: string } }
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
    onSuccess: (_d, vars) => changeMutationKeys(vars.id).forEach((queryKey) => qc.invalidateQueries({ queryKey })),
  });
}
