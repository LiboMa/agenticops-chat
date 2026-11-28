import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { AgentModelConfig } from "@/api/types";
import type { ModelIssue, ModelPreset } from "@/lib/modelRefs";

/** The model settings beside the agents' own (MVP-2.9.0 N35): the setting's own value, the model in force, and
 *  what an empty value means (null: it cannot be empty — a tier). */
export interface ModelSettingView {
  value: string;
  effective: string;
  default: string | null;
}

export interface AppSettings {
  scan_focus: string;
  executor_enabled: boolean;
  auto_fix_enabled: boolean;
  auto_rca_enabled: boolean;
  notifications_enabled: boolean;
  executor_auto_approve_l0_l1: boolean;
  executor_hitl_enabled: boolean;
  /** MVP-2.9.0 N25: which of the four stored switches are an administrator's values, the settings file's
   *  defaults, and who last changed them (read-only) */
  execution_switches?: { overridden: string[]; defaults: Record<string, boolean>; locked?: Record<string, boolean>; updated_by: string | null; updated_at: string | null };
  notifications_consolidated: boolean;
  bedrock_cache_enabled: boolean;
  skills_auto_improve_enabled: boolean;
  skills_post_resolution_review: boolean;
  skills_improvement_notify: boolean;
  agent_models: Record<string, AgentModelConfig>;
  /** Bedrock's models (while Bedrock is on) and every enabled chat model of an enabled provider (N35) */
  model_presets: ModelPreset[];
  model_settings?: Record<string, ModelSettingView>;
  /** the settings in force whose model cannot be used, and why (N35) */
  model_issues?: ModelIssue[];
  // Galaxy build model override — "" = use cheap tier (bedrock_model_id_cheap)
  galaxy_model_id: string;
  // IM WebSocket status (read-only, auto-detected from channels.yaml)
  feishu_ws_active: boolean;
  slack_ws_active: boolean;
  // Report S3 storage config
  report_storage: string;
  report_s3_bucket: string;
  report_s3_prefix: string;
  report_s3_region: string;
  report_presigned_url_expiry: number;
  // ACP enhanced backend (optional task delegation)
  acp_enhanced_enabled: boolean;
  acp_enhanced_backend: string;
  acp_available_backends: string[];
  acp_enhanced_blocked?: "bedrock_off" | null;  // read-only: switched on, but Claude Code runs on Bedrock and it is off
  // Change management
  change_management_enabled: boolean; // read-only: PATCH /api/settings rejects it as an unknown key (400)
  change_auto_approve_standard: boolean;
  rbac_enforce: boolean;
  policy_graph_impact_enforce: boolean; // read-only: false = the graph's impact count is shadow-recorded
  rca_min_confidence_for_autofix: number; // read-only: the post-RCA auto-fix gate
  executor_total_timeout: number;         // read-only: seconds a fix plan's auto-run counts as under way
}

type AgentModelPatch = { model_id?: string; max_tokens?: number; window_size?: number };
// change_management_enabled, policy_graph_impact_enforce, rca_min_confidence_for_autofix, executor_total_timeout and
// acp_available_backends are read-only: PATCH /api/settings rejects them as unknown keys (400), so they are
// dropped from the patch shape (they stay readable on AppSettings).
type SettingsPatch = Partial<Omit<AppSettings, "agent_models" | "change_management_enabled" | "execution_switches"
  | "policy_graph_impact_enforce" | "rca_min_confidence_for_autofix" | "executor_total_timeout" | "acp_available_backends"
  | "acp_enhanced_blocked" | "model_presets" | "model_settings" | "model_issues">>
  & { agent_models?: Record<string, AgentModelPatch>; model_settings?: Record<string, string> };

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
      qc.invalidateQueries({ queryKey: ["ui-attention"] });  // auto-fix / executor switches change what approving does
    },
  });
}
