import { useState, useEffect } from "react";
import { useChatSessions } from "@/hooks/useChatSessions";
import { useChatSession } from "@/hooks/useChatSession";
import { useChat } from "@/hooks/useChat";
import { SessionList } from "@/components/chat/SessionList";
import { MessageList } from "@/components/chat/MessageList";
import { ChatInput } from "@/components/chat/ChatInput";

export default function Chat() {
  const { data: sessions } = useChatSessions();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailLevel, setDetailLevel] = useState("medium");

  // Auto-select first session
  useEffect(() => {
    if (!selectedId && sessions && sessions.length > 0) {
      setSelectedId(sessions[0].session_id);
    }
  }, [sessions, selectedId]);

  const { data: detail } = useChatSession(selectedId);
  const { streaming, streamingContent, toolCalls, tokenMetrics, error, sendMessage, cancel } =
    useChat(selectedId);

  return (
    <div className="flex h-[calc(100vh-4rem)] bg-white -m-6 rounded-xl overflow-hidden border border-slate-200 shadow-card">
      <SessionList selectedId={selectedId} onSelect={setSelectedId} />

      <div className="flex-1 flex flex-col min-w-0">
        {!selectedId ? (
          <div className="flex-1 flex items-center justify-center text-slate-400">
            Select a session or create a new one
          </div>
        ) : (
          <>
            <MessageList
              messages={detail?.messages ?? []}
              streamingContent={streamingContent}
              streamingToolCalls={toolCalls}
              streamingTokenMetrics={tokenMetrics}
              streaming={streaming}
            />
            {error && (
              <div className="mx-6 mb-2 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
                {error}
              </div>
            )}
            <ChatInput
              onSend={(msg, file) => sendMessage(msg, file, detailLevel)}
              onCancel={cancel}
              disabled={streaming}
              streaming={streaming}
              detailLevel={detailLevel}
              onDetailLevelChange={setDetailLevel}
            />
          </>
        )}
      </div>
    </div>
  );
}
