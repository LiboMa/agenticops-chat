import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { Account, AccountCreate, AccountUpdate, AvailableProfiles, EnvironmentInfo, ConnectionTestResult } from "@/api/types";

export function useAccounts(provider?: string) {
  return useQuery({
    queryKey: ["accounts", provider],
    queryFn: () => apiFetch<Account[]>(provider ? `/accounts?provider=${provider}` : "/accounts"),
  });
}

export function useCreateAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: AccountCreate) =>
      apiFetch<Account>("/accounts", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounts"] }),
  });
}

export function useUpdateAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: AccountUpdate }) =>
      apiFetch<Account>(`/accounts/${id}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounts"] }),
  });
}

export function useDeleteAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<void>(`/accounts/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounts"] }),
  });
}

export function useAvailableProfiles() {
  return useQuery({
    queryKey: ["available-profiles"],
    queryFn: () => apiFetch<AvailableProfiles>("/settings/available-profiles"),
    staleTime: 60_000,
  });
}

export function useEnvironmentInfo() {
  return useQuery({
    queryKey: ["environment-info"],
    queryFn: () => apiFetch<EnvironmentInfo>("/settings/environment"),
    staleTime: 300_000,
  });
}

export function useTestConnection() {
  return useMutation({
    mutationFn: (accountId: number) =>
      apiFetch<ConnectionTestResult>(`/accounts/${accountId}/test`, { method: "POST" }),
  });
}
