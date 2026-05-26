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
  skills_auto_improve_enabled: boolean;
  skills_post_resolution_review: boolean;
  skills_improvement_notify: boolean;
  agent_models: Record<string, AgentModelConfig>;
  model_presets: { label: string; value: string; context_window?: number }[];
  // IM WebSocket status (read-only, auto-detected from channels.yaml)
  feishu_ws_active: boolean;
  slack_ws_active: boolean;
  // Report S3 storage config
  report_storage: string;
  report_s3_bucket: string;
  report_s3_prefix: string;
  report_s3_region: string;
  report_presigned_url_expiry: number;
}

type AgentModelPatch = { model_id?: string; max_tokens?: number; window_size?: number };
type SettingsPatch = Partial<Omit<AppSettings, "agent_models">> & { agent_models?: Record<string, AgentModelPatch> };

export function useSettings() {
  return useQuery<AppSettings>({
    queryKey: ["settings"],
    queryFn: () => apiFetch("/settings"),
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: SettingsPatch) =>
      apiFetch("/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
  });
}
