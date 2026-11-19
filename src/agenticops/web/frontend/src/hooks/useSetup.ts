import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ModelVerification, Readiness } from "@/api/types";

const KEY = ["setup-readiness"] as const;

/** How far the installation is set up (MVP-2.9.0 N23). Asked only of a signed-in person; it never runs a check. */
export function useReadiness(enabled: boolean) {
  return useQuery({ queryKey: KEY, queryFn: () => apiFetch<Readiness>("/setup/readiness"), enabled, staleTime: 15_000 });
}

/** One tiny call to the main model (administrators); the overview is read again after it. */
export function useVerifyModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<ModelVerification>("/setup/verify-model", { method: "POST" }),
    onSettled: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
