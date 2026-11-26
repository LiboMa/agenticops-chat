// The model providers (MVP-2.9.0 N35): /api/model-providers — the providers beyond Bedrock, their models, the
// Bedrock switch — and /api/kb/embedding (the knowledge base's embedding model). Every write refreshes the list,
// the settings (their model list and model issues) and the setup page's readiness.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { PresetLike, ProviderKind, ProviderRowLike } from "@/lib/providerForm";

export interface ProbeStep {
  ok: boolean;
  ms: number | null;
  error: string | null;
  count?: number | null;
}

export interface ProbeResult {
  model_id: string | null;
  at: string;
  list: ProbeStep;
  chat: ProbeStep;
  tools: ProbeStep;
}

export interface ProviderRow extends ProviderRowLike {
  enabled: boolean;
  models_count: number;
  last_test: ProbeResult | null;
  references: string[];
  updated_at: string | null;
  updated_by: string | null;
}

export interface PlatformPreset extends PresetLike {
  label: string;
  notes: string;
}

export interface ProvidersPage {
  bedrock: { enabled: boolean; region: string; references: string[] };
  providers: ProviderRow[];
  presets: PlatformPreset[];
  credential_backend: string;
  can_edit: boolean;
}

export type Reasoning = "none" | "openai_effort" | "anthropic_thinking";
export type Purpose = "chat" | "embedding";

export interface ProviderModel {
  provider: string;
  model_id: string;
  label: string;
  purpose: Purpose;
  context_window: number | null;
  max_output_tokens: number | null;
  supports_tools: boolean | null;
  tools_probe: "passed" | "failed" | null;
  tools_probe_at: string | null;
  supports_images: boolean;
  supports_documents: boolean;
  reasoning: Reasoning;
  price_input: number | null;
  price_output: number | null;
  price_cache_read: number | null;
  price_cache_write: number | null;
  source: "discovered" | "manual";
  enabled: boolean;
  manual_fields: string[];
  /** the server's answer to «does it call tools»: an admin's value, else the connection test's, else null */
  tools: boolean | null;
}

export interface RefreshResult {
  added: number;
  updated: number;
  unchanged: number;
  error: string | null;
}

export const providersKey = ["model-providers"] as const;
const modelsKey = (name: string) => ["model-providers", name, "models"] as const;
const enc = encodeURIComponent;

/** `/model-providers/<name>/<what>` — refused for an empty name: the server would answer a different route (404),
 *  as «Save and test» did when it read the list of a provider not yet named (N35 E2E). */
export function modelsPath(name: string, what: "models" | "refresh-models"): string {
  if (!name.trim()) throw new Error("no provider name");
  return `/model-providers/${enc(name)}/${what}`;
}

function useRefresh() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: providersKey });
    qc.invalidateQueries({ queryKey: ["settings"] });
    qc.invalidateQueries({ queryKey: ["kb-embedding"] });
    qc.invalidateQueries({ queryKey: ["setup-readiness"] });
  };
}

export function useModelProviders() {
  return useQuery({ queryKey: providersKey, queryFn: () => apiFetch<ProvidersPage>("/model-providers") });
}

export function useCreateProvider() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiFetch<ProviderRow>("/model-providers", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: refresh,
  });
}

export function useUpdateProvider() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ name, body }: { name: string; body: Record<string, unknown> }) =>
      apiFetch<ProviderRow>(`/model-providers/${enc(name)}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: refresh,
  });
}

export function useDeleteProvider() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (name: string) => apiFetch<void>(`/model-providers/${enc(name)}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
}

export function useSetBedrock() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (enabled: boolean) =>
      apiFetch<{ enabled: boolean; references: string[] }>("/model-providers/bedrock",
        { method: "PUT", body: JSON.stringify({ enabled }) }),
    onSuccess: refresh,
  });
}

export function useTestProvider() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ name, modelId }: { name: string; modelId?: string }) =>
      apiFetch<ProbeResult>(`/model-providers/${enc(name)}/test`,
        { method: "POST", body: JSON.stringify(modelId ? { model_id: modelId } : {}) }),
    onSuccess: refresh,
  });
}

/** The connection test of what the form holds, before it is saved — the server writes nothing (MVP-2.9.0 review). */
export function useTestDraft() {
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiFetch<ProbeResult>("/model-providers/test-draft", { method: "POST", body: JSON.stringify(body) }),
  });
}

export function useProviderModels(name: string | null) {
  return useQuery({
    queryKey: modelsKey(name ?? ""),
    queryFn: () => apiFetch<ProviderModel[]>(modelsPath(name ?? "", "models")),
    enabled: !!name,
  });
}

/** Read a provider's model list again. `mutate(name)` names the provider at the call (a provider saved a moment ago
 *  has no name yet when the dialog renders); without one, the provider the hook was made for. */
export function useRefreshModels(name: string) {
  const qc = useQueryClient();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (which?: string) => apiFetch<RefreshResult>(modelsPath(which ?? name, "refresh-models"), { method: "POST" }),
    onSuccess: (_r, which) => { qc.invalidateQueries({ queryKey: modelsKey(which ?? name) }); refresh(); },
  });
}

export function useAddModel(name: string) {
  const qc = useQueryClient();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiFetch<ProviderModel>(`/model-providers/${enc(name)}/models`, { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: modelsKey(name) }); refresh(); },
  });
}

export function usePatchModel(name: string) {
  const qc = useQueryClient();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ modelId, body }: { modelId: string; body: Record<string, unknown> }) =>
      // the model id goes in the path as it is (it may hold «/»: OpenRouter's «vendor/model»); each segment encoded
      apiFetch<ProviderModel>(`/model-providers/${enc(name)}/models/${modelId.split("/").map(enc).join("/")}`,
        { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: modelsKey(name) }); refresh(); },
  });
}

export type { ProviderKind };

// ── the knowledge base's embedding model (GET / PUT /api/kb/embedding, POST /api/kb/reembed) ─────────────────────

export interface KbEmbedding {
  model_ref: string;
  model: string;
  source: "provider" | "bedrock" | "none";
  dimension: number | null;
  vectors: number | null;
  indexed_with: string;
  needs_reembed: boolean;
  store: string;
  can_reembed: boolean;
  presets: import("@/lib/modelRefs").ModelPreset[];
}

const kbKey = ["kb-embedding"] as const;

export function useKbEmbedding() {
  return useQuery({ queryKey: kbKey, queryFn: () => apiFetch<KbEmbedding>("/kb/embedding") });
}

export function useSetKbEmbedding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (modelRef: string) =>
      apiFetch<KbEmbedding>("/kb/embedding", { method: "PUT", body: JSON.stringify({ model_ref: modelRef }) }),
    onSuccess: (data) => { qc.setQueryData(kbKey, data); qc.invalidateQueries({ queryKey: providersKey }); },
  });
}

export function useReembed() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<{ cases: number; vectors: number; failed: number }>("/kb/reembed", { method: "POST" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: kbKey }); qc.invalidateQueries({ queryKey: ["kb-stats"] }); },
  });
}
