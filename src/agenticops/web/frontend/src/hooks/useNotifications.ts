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

export function useNotificationChannel(id: number) {
  return useQuery({
    queryKey: ["notification-channel", id],
    queryFn: () => apiFetch<NotificationChannel>(`/notifications/channels/${id}`),
    enabled: id > 0,
  });
}

interface LogFilters {
  channel_id?: number;
  status?: string;
}

export function useNotificationLogs(filters: LogFilters = {}) {
  const params = new URLSearchParams();
  if (filters.channel_id) params.set("channel_id", String(filters.channel_id));
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
      id,
      data,
    }: {
      id: number;
      data: NotificationChannelUpdate;
    }) =>
      apiFetch<NotificationChannel>(`/notifications/channels/${id}`, {
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
    mutationFn: (id: number) =>
      apiFetch<void>(`/notifications/channels/${id}`, { method: "DELETE" }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["notification-channels"] }),
  });
}

export function useTestChannel() {
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<unknown>(`/notifications/channels/${id}/test`, {
        method: "POST",
        body: JSON.stringify({
          subject: "Test notification from AgenticOps",
          body: "This is a test notification.",
          severity: "low",
        }),
      }),
  });
}
