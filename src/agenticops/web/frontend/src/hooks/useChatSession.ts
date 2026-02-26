import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ChatSessionDetail } from "@/api/types";

export function useChatSession(sessionId: string | null) {
  return useQuery({
    queryKey: ["chat-session", sessionId],
    queryFn: () => apiFetch<ChatSessionDetail>(`/chat/sessions/${sessionId}`),
    enabled: !!sessionId,
    staleTime: 5_000,
  });
}
