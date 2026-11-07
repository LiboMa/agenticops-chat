// GET / PATCH / DELETE /api/settings/chat-upload (2026-11-07): the chat attachment limits, changed by admins.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, getAuthToken } from "@/api/client";

export interface ChatUploadValues {
  max_files: number;
  max_file_mb: number;
  max_total_mb: number;
  allowed_extensions: string[] | null;
  text_max_chars: number;
  turn_text_max_chars: number;
  history_text_max_chars: number;
  history_images_max: number;
  image_max_edge_px: number;
  pdf_render_pages_max: number;
  native_media_max_mb: number;
  staged_ttl_hours: number;
}

export interface ChatUploadSettings {
  effective: ChatUploadValues;
  defaults: ChatUploadValues;
  overridden: (keyof ChatUploadValues)[];
  supported: Record<"image" | "pdf" | "office" | "text", string[]>;
  ranges: Partial<Record<keyof ChatUploadValues, [number, number]>>;
  updated_by: string | null;
  updated_at: string | null;
  can_edit: boolean;
}

/** A refused change: the field it names is marked on the card. */
export class UploadConfigError extends Error {
  constructor(message: string, public field: string) { super(message); }
}

export const chatUploadKey = ["chat-upload-settings"] as const;

async function send(method: "PATCH" | "DELETE", body?: unknown): Promise<ChatUploadSettings> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch("/api/settings/chat-upload", { method, headers, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : data?.detail?.detail ?? res.statusText;
    throw new UploadConfigError(detail, data?.field ?? "");
  }
  return data as ChatUploadSettings;
}

export function useChatUploadSettings() {
  return useQuery({ queryKey: chatUploadKey, queryFn: () => apiFetch<ChatUploadSettings>("/settings/chat-upload") });
}

function useSaved() {
  const qc = useQueryClient();
  return (data: ChatUploadSettings) => {
    qc.setQueryData(chatUploadKey, data);
    void qc.invalidateQueries({ queryKey: ["ui-bootstrap"] });   // the composer's upload_policy changes at once
  };
}

export function usePatchChatUpload() {
  const saved = useSaved();
  return useMutation({ mutationFn: (patch: Partial<ChatUploadValues>) => send("PATCH", patch), onSuccess: saved });
}

export function useResetChatUpload() {
  const saved = useSaved();
  return useMutation({ mutationFn: () => send("DELETE"), onSuccess: saved });
}
