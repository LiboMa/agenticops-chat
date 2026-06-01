import { useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { chatStream } from "@/lib/chatStream";
import { appendMessageToCache, nextTempId } from "@/hooks/useChatMessages";
import type { ChatSession, ChatMessage } from "@/api/types";

/**
 * Lazy (deferred) session creation for the welcome flow:
 *   1. Create a ChatSession
 *   2. Seed the user's first message into the messages cache (shows immediately)
 *   3. Start streaming the first message via the chatStream store (survives nav)
 *   4. Navigate to the new session URL
 */
export function useLazySessionCreate() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [creating, setCreating] = useState(false);
  const creatingRef = useRef(false);

  const sendFirstMessage = useCallback(
    async (content: string, file?: File, detailLevel?: string) => {
      if (creatingRef.current) return;
      creatingRef.current = true;
      setCreating(true);
      try {
        const session = await apiFetch<ChatSession>("/chat/sessions", {
          method: "POST",
          body: JSON.stringify({ name: undefined }),
        });
        localStorage.setItem("aiops-last-session-id", session.session_id);
        qc.invalidateQueries({ queryKey: ["chat-sessions"] });
        // Seed the user's message into the cache so it shows the moment the
        // Chat page mounts (the history query starts empty for a new session).
        const userMsg: ChatMessage = {
          id: nextTempId(),
          role: "user",
          content,
          attachments: file ? [{ filename: file.name, size: file.size }] : undefined,
          created_at: new Date().toISOString(),
        };
        appendMessageToCache(qc, session.session_id, userMsg);
        // Kick off the stream in the store, then navigate. The Chat page binds
        // to the in-flight stream for this session id on mount.
        void chatStream.send(session.session_id, content, file, detailLevel);
        navigate(`/app/chat/${session.session_id}`, { replace: true });
      } finally {
        creatingRef.current = false;
        setCreating(false);
      }
    },
    [navigate, qc],
  );

  return { sendFirstMessage, creating };
}
