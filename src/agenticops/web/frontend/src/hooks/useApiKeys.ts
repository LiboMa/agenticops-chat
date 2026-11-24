import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ApiKeyRow } from "@/api/types";

/** «My API keys» (MVP-2.8.0) — /api/api-keys, from a signed-in session only. A refusal throws ApiError with the
 *  server's code (scope_exceeds_role / invalid_scope / invalid_name / invalid_expiry / not_found / session_required). */
const KEY = ["api-keys"] as const;

export function useMyApiKeys() {
  return useQuery({ queryKey: KEY, queryFn: () => apiFetch<ApiKeyRow[]>("/api-keys") });
}

export function createApiKeyOptions(qc: QueryClient) {
  return {
    // a secret shown once: dropped from the mutation cache as soon as the page resets it (closing its dialog)
    gcTime: 0,
    mutationFn: (body: { name: string; permissions: string[]; expires_days: number | null }) =>
      apiFetch<ApiKeyRow & { key: string }>("/api-keys", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  };
}

export function useCreateApiKey() {
  return useMutation(createApiKeyOptions(useQueryClient()));
}

export function useRevokeApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/api-keys/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

/** «更新密钥»: a new key under the same name, the old one dead at once; the new key is shown once (gcTime 0). */
export function rotateApiKeyOptions(qc: QueryClient) {
  return {
    // a secret shown once: dropped from the mutation cache as soon as the page resets it (closing its dialog)
    gcTime: 0,
    mutationFn: ({ id, ...body }: { id: number; permissions: string[]; expires_days: number | null }) =>
      apiFetch<ApiKeyRow & { key: string }>(`/api-keys/${id}/rotate`, { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  };
}

export function useRotateApiKey() {
  return useMutation(rotateApiKeyOptions(useQueryClient()));
}
