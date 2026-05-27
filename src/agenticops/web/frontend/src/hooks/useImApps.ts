import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";

export type ImAppsMap = Record<string, Record<string, Record<string, string>>>;

export interface ChannelInfo {
  name: string;
  type: string;
  enabled: boolean;
  role: string;
  preferred_format: string;
  config: Record<string, unknown>;
}

export function useImApps() {
  return useQuery<ImAppsMap>({
    queryKey: ["im-apps"],
    queryFn: () => apiFetch("/settings/im-apps"),
  });
}

export function useUpsertImApp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ platform, name, config }: { platform: string; name: string; config: Record<string, string> }) =>
      apiFetch(`/settings/im-apps/${platform}/${name}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["im-apps"] }),
  });
}

export function useDeleteImApp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ platform, name }: { platform: string; name: string }) =>
      apiFetch(`/settings/im-apps/${platform}/${name}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["im-apps"] }),
  });
}

export function useChannels() {
  return useQuery<ChannelInfo[]>({
    queryKey: ["channels"],
    queryFn: () => apiFetch("/settings/channels"),
  });
}

export function useUpsertChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, data }: { name: string; data: Record<string, unknown> }) =>
      apiFetch(`/settings/channels/${name}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["channels"] }),
  });
}

export function useDeleteChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch(`/settings/channels/${name}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["channels"] }),
  });
}

export function useToggleChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) =>
      apiFetch(`/settings/channels/${name}/toggle`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["channels"] }),
  });
}
