import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ApiKeyRow, UserRole, UserRow } from "@/api/types";

/** /api/users (MVP-2.8.0 S2 rework): admins manage web accounts. A refusal throws ApiError with the server's code
 *  (not_found / email_taken / self_change / last_admin / invalid_email / invalid_role). */
const KEY = ["users"] as const;

export function useUsers() {
  return useQuery({ queryKey: KEY, queryFn: () => apiFetch<UserRow[]>("/users") });
}

function useInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: KEY });
}

export function createUserOptions(qc: QueryClient) {
  return {
    // a secret shown once: dropped from the mutation cache as soon as the page resets it (closing its dialog)
    gcTime: 0,
    mutationFn: (body: { email: string; name: string | null; role: UserRole; settings_view: boolean }) =>
      apiFetch<{ user: UserRow; password: string }>("/users", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  };
}

export function useCreateUser() {
  return useMutation(createUserOptions(useQueryClient()));
}

export function useUpdateUser() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; role?: UserRole; settings_view?: boolean; is_active?: boolean }) =>
      apiFetch<UserRow>(`/users/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: invalidate,
  });
}

export function resetPasswordOptions(qc: QueryClient) {
  return {
    // a secret shown once: dropped from the mutation cache as soon as the page resets it (closing its dialog)
    gcTime: 0,
    mutationFn: (id: number) => apiFetch<{ password: string }>(`/users/${id}/reset-password`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  };
}

export function useResetPassword() {
  return useMutation(resetPasswordOptions(useQueryClient()));
}

/** An admin's view of someone's API keys (MVP-2.8.0): GET /api/users/{id}/api-keys — never the full key. Under the
 *  users key, so a disable (which revokes the keys) refreshes it too. */
export function useUserKeys(userId: number) {
  return useQuery({
    queryKey: [...KEY, userId, "api-keys"],
    queryFn: () => apiFetch<ApiKeyRow[]>(`/users/${userId}/api-keys`),
  });
}

export function useRevokeUserKey() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ userId, keyId }: { userId: number; keyId: number }) =>
      apiFetch<void>(`/users/${userId}/api-keys/${keyId}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

/** An admin issues a key for someone (MVP-2.8.0): the key is shown to the admin once (gcTime 0). */
export function createUserKeyOptions(qc: QueryClient) {
  return {
    // a secret shown once: dropped from the mutation cache as soon as the page resets it (closing its dialog)
    gcTime: 0,
    mutationFn: ({ userId, ...body }: { userId: number; name: string; permissions: string[]; expires_days: number | null }) =>
      apiFetch<ApiKeyRow & { key: string }>(`/users/${userId}/api-keys`, { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  };
}

/** An admin updates someone's key: a new key under the same name, the old one dead at once (gcTime 0). */
export function rotateUserKeyOptions(qc: QueryClient) {
  return {
    gcTime: 0,
    mutationFn: ({ userId, keyId, ...body }: { userId: number; keyId: number; permissions: string[]; expires_days: number | null }) =>
      apiFetch<ApiKeyRow & { key: string }>(`/users/${userId}/api-keys/${keyId}/rotate`, { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  };
}

export function useCreateUserKey() {
  return useMutation(createUserKeyOptions(useQueryClient()));
}

export function useRotateUserKey() {
  return useMutation(rotateUserKeyOptions(useQueryClient()));
}

/** Delete a user (soft; services/user_admin.delete_user) — 409 self_change / last_admin / has_open_requests. */
export function useDeleteUser() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/users/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}
