import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type {
  NotificationChannel,
  NotificationChannelCreate,
  NotificationChannelUpdate,
  NotificationLog,
} from "@/api/types";

export function useNotificationChannels() {
  return useQuery({
    queryKey: ["notification-channels"],
    queryFn: () => apiFetch<NotificationChannel[]>("/notifications/channels"),
  });
}

export function useNotificationChannel(name: string) {
  return useQuery({
    queryKey: ["notification-channel", name],
    queryFn: () => apiFetch<NotificationChannel>(`/notifications/channels/${name}`),
    enabled: !!name,
  });
}

interface LogFilters {
  channel_name?: string;
  status?: string;
}

export function useNotificationLogs(filters: LogFilters = {}) {
  const params = new URLSearchParams();
  if (filters.channel_name) params.set("channel_name", filters.channel_name);
  if (filters.status) params.set("status", filters.status);
  const qs = params.toString();

  return useQuery({
    queryKey: ["notification-logs", filters],
    queryFn: () =>
      apiFetch<NotificationLog[]>(
        `/notifications/logs${qs ? `?${qs}` : ""}`,
      ),
  });
}

export function useCreateChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: NotificationChannelCreate) =>
      apiFetch<NotificationChannel>("/notifications/channels", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["notification-channels"] }),
  });
}

export function useUpdateChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      name,
      data,
    }: {
      name: string;
      data: NotificationChannelUpdate;
    }) =>
      apiFetch<NotificationChannel>(`/notifications/channels/${name}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["notification-channels"] }),
  });
}

export function useDeleteChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch<void>(`/notifications/channels/${name}`, { method: "DELETE" }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["notification-channels"] }),
  });
}

export function useTestChannel() {
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch<unknown>(`/notifications/channels/${name}/test`, {
        method: "POST",
        body: JSON.stringify({
          subject: "Test notification from AgenticOps",
          body: "This is a test notification.",
          severity: "low",
        }),
      }),
  });
}
