import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ChangeRequest, ChangeRequestCreate, ChangeRequestDetail, FixExecution } from "@/api/types";
import { isTerminalChange, toQuery, type Period } from "@/lib/plans";

// A type alias, not an interface: only an alias is assignable to toQuery's Record parameter.
export type ChangeFilters = { status?: string; account_id?: number; requested_by?: string; period?: Period; limit?: number; offset?: number };

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
    onSuccess: () => qc.invalidateQueries({ queryKey: ["changes"] }),
  });
}

export type ChangeAction = "approve" | "reject" | "cancel" | "clarify" | "execute" | "review" | "resolve-review";

export function useChangeAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action, body }: { id: number; action: ChangeAction; body?: Record<string, unknown> }) =>
      apiFetch<ChangeRequest | FixExecution>(`/changes/${id}/${action}`, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ["changes"] });
      qc.invalidateQueries({ queryKey: ["change", vars.id] });
      qc.invalidateQueries({ queryKey: ["change-timeline", vars.id] });
      qc.invalidateQueries({ queryKey: ["fix-plans"] });
    },
  });
}
