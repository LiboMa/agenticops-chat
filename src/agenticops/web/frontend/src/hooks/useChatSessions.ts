import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ChatSession } from "@/api/types";

export function useChatSessions() {
  return useQuery({
    queryKey: ["chat-sessions"],
    queryFn: () => apiFetch<ChatSession[]>("/chat/sessions"),
    staleTime: 10_000,
  });
}

export function useCreateChatSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name?: string) =>
      apiFetch<ChatSession>("/chat/sessions", {
        method: "POST",
        body: JSON.stringify({ name: name || undefined }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["chat-sessions"] }),
  });
}

export function useDeleteChatSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) =>
      apiFetch<void>(`/chat/sessions/${sessionId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["chat-sessions"] }),
  });
}

export function useRenameChatSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, name }: { sessionId: string; name: string }) =>
      apiFetch<ChatSession>(`/chat/sessions/${sessionId}`, {
        method: "PATCH",
        body: JSON.stringify({ name }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["chat-sessions"] }),
  });
}

export function useUpdateChatSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      sessionId,
      ...fields
    }: {
      sessionId: string;
      pinned?: boolean;
      starred?: boolean;
      archived?: boolean;
      /** "" = Auto (follow global); non-empty = model id; omit = don't change */
      model_id?: string;
    }) =>
      apiFetch<ChatSession>(`/chat/sessions/${sessionId}`, {
        method: "PATCH",
        body: JSON.stringify(fields),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["chat-sessions"] }),
  });
}
