import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { MessagingSchema } from "@/lib/messagingFields";

export type AppsMap = Record<string, Record<string, Record<string, string>>>;

export interface ChannelInfo {
  name: string;
  type: string;
  enabled: boolean;
  role: string;
  severity_filter: string[];
  preferred_format: string;
  config: Record<string, unknown>;
}

export interface DeliveryLog {
  id: number;
  channel_name: string;
  subject: string;
  body: string;
  severity?: string | null;
  status: string;
  error?: string | null;
  sent_at: string;
}

export function useMessagingSchema() {
  return useQuery<MessagingSchema>({
    queryKey: ["messaging-schema"],
    queryFn: () => apiFetch("/messaging/schema"),
    staleTime: Infinity,
  });
}

export function useMessagingApps() {
  return useQuery<AppsMap>({ queryKey: ["messaging-apps"], queryFn: () => apiFetch("/messaging/apps") });
}

export function useUpsertApp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ platform, name, config }: { platform: string; name: string; config: Record<string, unknown> }) =>
      apiFetch(`/messaging/apps/${platform}/${name}`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["messaging-apps"] }),
  });
}

export function useDeleteApp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ platform, name }: { platform: string; name: string }) =>
      apiFetch(`/messaging/apps/${platform}/${name}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["messaging-apps"] }),
  });
}

export function useMessagingChannels() {
  return useQuery<ChannelInfo[]>({ queryKey: ["messaging-channels"], queryFn: () => apiFetch("/messaging/channels") });
}

export function useUpsertChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, data }: { name: string; data: Record<string, unknown> }) =>
      apiFetch(`/messaging/channels/${name}`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["messaging-channels"] }),
  });
}

export function useDeleteChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => apiFetch(`/messaging/channels/${name}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["messaging-channels"] }),
  });
}

export function useToggleChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) =>
      apiFetch(`/messaging/channels/${name}/toggle`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["messaging-channels"] }),
  });
}

export function useTestChannel() {
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch(`/messaging/channels/${name}/test`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subject: "Test from AgenticOps", body: "This is a test message.", severity: "low" }),
      }),
  });
}

export function useMessagingLogs(channelName?: string) {
  const qs = channelName ? `?channel_name=${encodeURIComponent(channelName)}` : "";
  return useQuery<DeliveryLog[]>({
    queryKey: ["messaging-logs", channelName ?? null],
    queryFn: () => apiFetch(`/messaging/logs${qs}`),
  });
}
