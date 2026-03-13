import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useChatSessions } from "@/hooks/useChatSessions";
import { useChatSession } from "@/hooks/useChatSession";
import { useChat } from "@/hooks/useChat";
import { usePersistedState } from "@/hooks/usePersistedState";
import { SessionList } from "@/components/chat/SessionList";
import { MessageList } from "@/components/chat/MessageList";
import { ChatInput } from "@/components/chat/ChatInput";
import SaveReportDialog from "@/components/chat/SaveReportDialog";

export default function Chat() {
  const { sessionId: urlSessionId } = useParams<{ sessionId?: string }>();
  const navigate = useNavigate();
  const { data: sessions } = useChatSessions();
  const [lastSessionId, setLastSessionId] = usePersistedState<string | null>("aiops-last-session", null);
  const [detailLevel, setDetailLevel] = usePersistedState("aiops-detail-level", "medium");

  // Determine selected session from URL parameter
  const selectedId = urlSessionId || null;

  // Auto-redirect to a session if none in URL
  useEffect(() => {
    if (urlSessionId) {
      // URL has session ID - save it to localStorage
      setLastSessionId(urlSessionId);
      return;
    }
    // No session in URL - try localStorage first, then first session from API
    const target = lastSessionId || (sessions && sessions.length > 0 ? sessions[0].session_id : null);
    if (target) {
      navigate(`/app/chat/${target}`, { replace: true });
    }
  }, [urlSessionId, sessions, lastSessionId, navigate, setLastSessionId]);

  const { data: detail } = useChatSession(selectedId);
  const { streaming, streamingContent, toolCalls, tokenMetrics, error, sendMessage, cancel } =
    useChat(selectedId);
  const [showSaveReport, setShowSaveReport] = useState(false);
  const currentSession = sessions?.find((s) => s.session_id === selectedId);

  // Session selection handler - navigates to new URL
  const handleSelectSession = (id: string) => {
    navigate(`/app/chat/${id}`);
  };

  return (
    <div className="flex h-[calc(100vh-4rem)] bg-background -m-6 rounded-xl overflow-hidden border border-border shadow-card">
      <SessionList selectedId={selectedId} onSelect={handleSelectSession} />

      <div className="flex-1 flex flex-col min-w-0">
        {!selectedId ? (
          <div className="flex-1 flex items-center justify-center text-muted-foreground">
            Select a session or create a new one
          </div>
        ) : (
          <>
            {/* Session toolbar */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-card/50">
              <h3 className="text-sm font-medium text-foreground truncate">
                {currentSession?.name ?? "Chat"}
              </h3>
              <button
                onClick={() => setShowSaveReport(true)}
                className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground bg-secondary hover:bg-muted border border-border rounded-md transition-colors"
              >
                <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                Save as Report
              </button>
            </div>
            <MessageList
              messages={detail?.messages ?? []}
              streamingContent={streamingContent}
              streamingToolCalls={toolCalls}
              streamingTokenMetrics={tokenMetrics}
              streaming={streaming}
            />
            {error && (
              <div className="mx-6 mb-2 px-3 py-2 bg-destructive/10 border border-destructive/20 rounded-lg text-sm text-destructive">
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

      {showSaveReport && selectedId && currentSession && (
        <SaveReportDialog
          sessionId={selectedId}
          sessionName={currentSession.name}
          onClose={() => setShowSaveReport(false)}
        />
      )}
    </div>
  );
}
