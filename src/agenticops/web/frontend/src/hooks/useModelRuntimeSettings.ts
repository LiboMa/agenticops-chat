// GET / PATCH / DELETE /api/settings/model-runtime (2026-11-08): the model stream's read timeout, changed by admins.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, getAuthToken } from "@/api/client";

export interface ModelRuntimeValues {
  stream_read_timeout_seconds: number;
}

export interface ModelRuntimeSettings {
  effective: ModelRuntimeValues;
  defaults: ModelRuntimeValues;
  overridden: (keyof ModelRuntimeValues)[];
  ranges: Partial<Record<keyof ModelRuntimeValues, [number, number]>>;
  updated_by: string | null;
  updated_at: string | null;
  can_edit: boolean;
}

export class ModelRuntimeError extends Error {
  constructor(message: string, public field: string) { super(message); }
}

export const modelRuntimeKey = ["model-runtime-settings"] as const;

async function send(method: "PATCH" | "DELETE", body?: unknown): Promise<ModelRuntimeSettings> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch("/api/settings/model-runtime", { method, headers, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : data?.detail?.detail ?? res.statusText;
    throw new ModelRuntimeError(detail, data?.field ?? "");
  }
  return data as ModelRuntimeSettings;
}

export function useModelRuntimeSettings() {
  return useQuery({ queryKey: modelRuntimeKey, queryFn: () => apiFetch<ModelRuntimeSettings>("/settings/model-runtime") });
}

export function usePatchModelRuntime() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<ModelRuntimeValues>) => send("PATCH", patch),
    onSuccess: (data) => qc.setQueryData(modelRuntimeKey, data),
  });
}

export function useResetModelRuntime() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: () => send("DELETE"), onSuccess: (data) => qc.setQueryData(modelRuntimeKey, data) });
}
