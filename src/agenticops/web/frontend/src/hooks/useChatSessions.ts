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
