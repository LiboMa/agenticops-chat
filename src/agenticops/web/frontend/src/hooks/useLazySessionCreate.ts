import { useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ChatSession } from "@/api/types";

/**
 * Hook for lazy (deferred) session creation.
 *
 * Instead of creating a ChatSession on page load, this hook exposes
 * `sendFirstMessage` which:
 *   1. Creates a new ChatSession
 *   2. Navigates to it
 *   3. Stores the pending first message so the Chat component can
 *      send it via the normal SSE-streaming `useChat.sendMessage` path
 *
 * Validates: Requirements 1.3
 */

interface UseLazySessionCreateReturn {
  sendFirstMessage: (content: string, file?: File) => Promise<void>;
  creating: boolean;
  /** The pending first message content (consumed by Chat after navigation) */
  pendingMessage: string | null;
  pendingFile: File | undefined;
  /** Clear the pending message after it has been sent */
  clearPending: () => void;
}

export function useLazySessionCreate(): UseLazySessionCreateReturn {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);
  const [pendingFile, setPendingFile] = useState<File | undefined>(undefined);
  const creatingRef = useRef(false);

  const sendFirstMessage = useCallback(
    async (content: string, file?: File) => {
      if (creatingRef.current) return;
      creatingRef.current = true;
      setCreating(true);

      try {
        // 1. Create a new ChatSession
        const session = await apiFetch<ChatSession>("/chat/sessions", {
          method: "POST",
          body: JSON.stringify({ name: undefined }),
        });

        // 2. Persist session id to localStorage for future restoration
        localStorage.setItem("aiops-last-session-id", session.session_id);

        // 3. Store the pending message so Chat can send it via useChat (SSE)
        setPendingMessage(content);
        setPendingFile(file);

        // 4. Invalidate session list so the sidebar picks it up
        qc.invalidateQueries({ queryKey: ["chat-sessions"] });

        // 5. Navigate to the new session URL — this triggers useChat to bind
        navigate(`/app/chat/${session.session_id}`, { replace: true });
      } catch (err) {
        // Reset on failure so user can retry
        creatingRef.current = false;
        setCreating(false);
        throw err;
      }
    },
    [navigate, qc],
  );

  const clearPending = useCallback(() => {
    setPendingMessage(null);
    setPendingFile(undefined);
    creatingRef.current = false;
    setCreating(false);
  }, []);

  return { sendFirstMessage, creating, pendingMessage, pendingFile, clearPending };
}
