import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

export function useCreateUser() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { email: string; name: string | null; role: UserRole; settings_view: boolean }) =>
      apiFetch<{ user: UserRow; password: string }>("/users", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: invalidate,
  });
}

export function useUpdateUser() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; role?: UserRole; settings_view?: boolean; is_active?: boolean }) =>
      apiFetch<UserRow>(`/users/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: invalidate,
  });
}

export function useResetPassword() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: number) => apiFetch<{ password: string }>(`/users/${id}/reset-password`, { method: "POST" }),
    onSuccess: invalidate,
  });
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
