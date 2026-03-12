import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { AgentModelConfig } from "@/api/types";

export interface AppSettings {
  scan_focus: string;
  executor_enabled: boolean;
  auto_fix_enabled: boolean;
  auto_rca_enabled: boolean;
  notifications_enabled: boolean;
  executor_auto_approve_l0_l1: boolean;
  notifications_consolidated: boolean;
  bedrock_cache_enabled: boolean;
  agent_models: Record<string, AgentModelConfig>;
}

type AgentModelPatch = { model_id?: string; max_tokens?: number };
type SettingsPatch = Partial<Omit<AppSettings, "agent_models">> & { agent_models?: Record<string, AgentModelPatch> };

export function useSettings() {
  return useQuery<AppSettings>({
    queryKey: ["settings"],
    queryFn: () => apiFetch("/api/settings"),
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: SettingsPatch) =>
      apiFetch("/api/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
  });
}
