import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type {
  Schedule,
  ScheduleCreate,
  ScheduleUpdate,
  ScheduleExecution,
} from "@/api/types";

export function useSchedules() {
  return useQuery({
    queryKey: ["schedules"],
    queryFn: () => apiFetch<Schedule[]>("/schedules"),
  });
}

export function useSchedule(id: number) {
  return useQuery({
    queryKey: ["schedule", id],
    queryFn: () => apiFetch<Schedule>(`/schedules/${id}`),
    enabled: id > 0,
  });
}

export function useScheduleExecutions(id: number) {
  return useQuery({
    queryKey: ["schedule-executions", id],
    queryFn: () => apiFetch<ScheduleExecution[]>(`/schedules/${id}/executions`),
    enabled: id > 0,
  });
}

export function useCreateSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ScheduleCreate) =>
      apiFetch<Schedule>("/schedules", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });
}

export function useUpdateSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: ScheduleUpdate }) =>
      apiFetch<Schedule>(`/schedules/${id}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["schedules"] });
      qc.invalidateQueries({ queryKey: ["schedule", vars.id] });
    },
  });
}

export function useDeleteSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<void>(`/schedules/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });
}

export function useRunSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<unknown>(`/schedules/${id}/run`, { method: "POST" }),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["schedules"] });
      qc.invalidateQueries({ queryKey: ["schedule", id] });
      qc.invalidateQueries({ queryKey: ["schedule-executions", id] });
    },
  });
}
