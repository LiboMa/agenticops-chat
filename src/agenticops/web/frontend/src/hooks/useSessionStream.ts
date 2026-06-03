import { useSyncExternalStore, useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { chatStream } from "@/lib/chatStream";
import { appendMessageToCache, nextTempId } from "@/hooks/useChatMessages";
import type { ChatSession, ChatMessage } from "@/api/types";

/**
 * React adapter over the chatStream store for a single session. Returns the
 * same shape the old useChat() exposed, but the underlying SSE loop lives in
 * the store, so it survives navigation and runs concurrently per session.
 */
export function useSessionStream(sessionId: string | null) {
  const qc = useQueryClient();

  // Wire store lifecycle callbacks to the TanStack cache. The module-level
  // store keeps the last callbacks; re-registering with a stable qc is fine.
  useEffect(() => {
    chatStream.setCallbacks({
      onDone: (sid, payload) => {
        const assistantMsg: ChatMessage = {
          id: nextTempId(), // optimistic temp id (negative, unique); reconciled below
          role: "assistant",
          content: payload.content,
          tool_calls: payload.toolCalls,
          token_usage: payload.tokenMetrics ?? undefined,
          created_at: new Date().toISOString(),
        };
        appendMessageToCache(qc, sid, assistantMsg);
        // Refresh the session list (name/last_activity/order may change).
        qc.invalidateQueries({ queryKey: ["chat-sessions"] });
        // Reconcile optimistic temp ids -> real server ids by refetching the
        // newest page in the background (keeps markdown-memo/React keys correct).
        qc.invalidateQueries({ queryKey: ["chat-messages", sid] });
      },
      onRenamed: (sid, name) => {
        qc.setQueryData<ChatSession[]>(["chat-sessions"], (old) =>
          old?.map((s) => (s.session_id === sid ? { ...s, name } : s)));
      },
    });
  }, [qc]);

  const subscribe = useCallback(
    (cb: () => void) => (sessionId ? chatStream.subscribe(sessionId, cb) : () => {}),
    [sessionId],
  );
  const getSnapshot = useCallback(() => chatStream.getSnapshot(sessionId), [sessionId]);
  const state = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const send = useCallback(
    (content: string, files?: File[], detailLevel?: string) => {
      if (!sessionId) return;
      // Optimistically append the user's message so it shows immediately.
      const userMsg: ChatMessage = {
        id: nextTempId(),
        role: "user",
        content,
        attachments: files && files.length > 0
          ? files.map((f) => ({ filename: f.name, size: f.size }))
          : undefined,
        created_at: new Date().toISOString(),
      };
      appendMessageToCache(qc, sessionId, userMsg);
      void chatStream.send(sessionId, content, files, detailLevel);
    },
    [sessionId, qc],
  );

  const cancel = useCallback(() => {
    if (sessionId) chatStream.cancel(sessionId);
  }, [sessionId]);

  return {
    streaming: state.streaming,
    streamingContent: state.content,
    toolCalls: state.toolCalls,
    tokenMetrics: state.tokenMetrics,
    error: state.error,
    sendMessage: send,
    cancel,
  };
}

/** Subscribe to the set of session ids currently streaming (for the flyout dot). */
export function useActiveStreamingSessions(): string[] {
  const subscribe = useCallback((cb: () => void) => chatStream.subscribeActive(cb), []);
  // getSnapshot must be referentially stable when nothing changed; the store
  // returns a fresh array each call, so memoize via a cached join key.
  const lastRef = useRef<{ key: string; val: string[] }>({ key: "", val: [] });
  const getSnapshot = useCallback(() => {
    const arr = chatStream.activeSessions();
    const key = arr.slice().sort().join(",");
    if (key !== lastRef.current.key) lastRef.current = { key, val: arr };
    return lastRef.current.val;
  }, []);
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
