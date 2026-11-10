import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ApiKeyRow } from "@/api/types";

/** «My API keys» (MVP-2.8.0) — /api/api-keys, from a signed-in session only. A refusal throws ApiError with the
 *  server's code (scope_exceeds_role / invalid_scope / invalid_name / invalid_expiry / not_found / session_required). */
const KEY = ["api-keys"] as const;

export function useMyApiKeys() {
  return useQuery({ queryKey: KEY, queryFn: () => apiFetch<ApiKeyRow[]>("/api-keys") });
}

export function useCreateApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; permissions: string[]; expires_days: number | null }) =>
      apiFetch<ApiKeyRow & { key: string }>("/api-keys", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useRevokeApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/api-keys/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
