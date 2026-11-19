import { keepPreviousData, useInfiniteQuery, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { patchSessionPages, sessionsRequest, type SessionListData, type SessionView } from "@/lib/sessionList";
import type { ChatSession, ChatSessionPage } from "@/api/types";

/** One view of the conversation list — all / starred / archived — searched, ordered and cut by the server
 *  (MVP-2.9.0 N22), a page at a time. Every view and search is its own query under ["chat-sessions", "list", …],
 *  so `invalidateQueries({ queryKey: ["chat-sessions"] })` refreshes them all. */
export function useChatSessionList(view: SessionView, q: string) {
  return useInfiniteQuery({
    queryKey: ["chat-sessions", "list", view, q.trim()],
    queryFn: ({ pageParam }) => apiFetch<ChatSessionPage>(sessionsRequest(view, q, pageParam)),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    staleTime: 10_000,
    placeholderData: keepPreviousData,
  });
}

/** A conversation changed: the lists and its own record are read again. */
export function refreshSession(qc: QueryClient, sessionId?: string | null) {
  qc.invalidateQueries({ queryKey: ["chat-sessions"] });
  if (sessionId) qc.invalidateQueries({ queryKey: ["chat-session", sessionId] });
}

/** …and a change that is already known (the server's new title) shows at once in every loaded list and on the
 *  conversation's own record. */
export function patchSessionEverywhere(qc: QueryClient, sessionId: string, patch: Partial<ChatSession>) {
  qc.setQueriesData<SessionListData>({ queryKey: ["chat-sessions", "list"] }, (old) => patchSessionPages(old, sessionId, patch));
  qc.setQueryData<ChatSession>(["chat-session", sessionId], (old) => (old ? { ...old, ...patch } : old));
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
    onSuccess: (_data, sessionId) => {
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
      qc.removeQueries({ queryKey: ["chat-session", sessionId] });
    },
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
    onSuccess: (_data, vars) => refreshSession(qc, vars.sessionId),
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
      /** "" = Auto; else off|standard|deep; omit = don't change */
      effort?: string;
      /** who sees it — only its owner (or an admin) may change this */
      visibility?: "private" | "workspace";
    }) =>
      apiFetch<ChatSession>(`/chat/sessions/${sessionId}`, {
        method: "PATCH",
        body: JSON.stringify(fields),
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
      qc.invalidateQueries({ queryKey: ["chat-session", vars.sessionId] });
    },
  });
}
