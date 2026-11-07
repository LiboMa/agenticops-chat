import { useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { chatStream } from "@/lib/chatStream";
import { optimisticAttachments, type UploadItem } from "@/lib/attachmentUpload";
import { appendMessageToCache, nextTempId } from "@/hooks/useChatMessages";
import type { ChatSession, ChatMessage } from "@/api/types";
import { currentUserId, userKey } from "@/lib/home";
import type { NewChatContext } from "@/lib/chatContext";

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
  const [createError, setCreateError] = useState<string | null>(null);
  const creatingRef = useRef(false);

  const sendFirstMessage = useCallback(
    // `search` rides along to the new session's URL (Chat keeps an open context panel through the remount);
    // `context` (S5) is what the chat is about and its account — the server resolves and checks it
    async (content: string, attachmentIds: string[] = [], items: UploadItem[] = [], search = "",
           context?: NewChatContext): Promise<boolean> => {
      if (creatingRef.current) return false;
      creatingRef.current = true;
      setCreating(true);
      setCreateError(null);
      try {
        const session = await apiFetch<ChatSession>("/chat/sessions", {
          method: "POST",
          body: JSON.stringify({ name: undefined, context }),
        });
        localStorage.setItem(userKey("aiops-last-session-id", currentUserId()), session.session_id);
        qc.invalidateQueries({ queryKey: ["chat-sessions"] });
        // Seed the user's message into the cache so it shows the moment the
        // Chat page mounts (the history query starts empty for a new session).
        const userMsg: ChatMessage = {
          id: nextTempId(),
          role: "user",
          content,
          attachments: optimisticAttachments(items),
          created_at: new Date().toISOString(),
        };
        appendMessageToCache(qc, session.session_id, userMsg);
        // Start the stream in the store and move to the chat once the server has taken the message (its first
        // frame, before the agent runs): a refused send (an attachment still processing or gone, 2026-11-07)
        // stays on this composer, with its text and attachments, instead of vanishing into the new chat.
        const accepted = await new Promise<boolean>((resolve) => {
          void chatStream.send(session.session_id, content, attachmentIds, undefined, () => resolve(true))
            .then((ok) => { if (!ok) resolve(false); });
        });
        if (!accepted) {
          setCreateError(chatStream.getSnapshot(session.session_id).error?.message ?? "The message was not sent");
          return false;
        }
        navigate(`/app/chat/${session.session_id}${search}`, { replace: true });
        return true;
      } catch (err) {
        // the chat was not created (the linked issue is gone, an account changed): nothing was sent
        setCreateError(err instanceof Error ? err.message : String(err));
        return false;
      } finally {
        creatingRef.current = false;
        setCreating(false);
      }
    },
    [navigate, qc],
  );

  return { sendFirstMessage, creating, createError };
}
