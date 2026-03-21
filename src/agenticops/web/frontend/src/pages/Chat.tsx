import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useChatSessions, useCreateChatSession } from "@/hooks/useChatSessions";
import { useChatSession } from "@/hooks/useChatSession";
import { useChat } from "@/hooks/useChat";
import { usePersistedState } from "@/hooks/usePersistedState";
import { SessionFlyout } from "@/components/chat/SessionFlyout";
import { MessageList } from "@/components/chat/MessageList";
import { ChatInput } from "@/components/chat/ChatInput";
import { DragHandle } from "@/components/chat/DragHandle";
import { ContextPanel } from "@/components/chat/ContextPanel";
import SaveReportDialog from "@/components/chat/SaveReportDialog";
import { useLocale } from "@/i18n/LocaleContext";

export default function Chat() {
  const { t } = useLocale();
  const { sessionId: urlSessionId } = useParams<{ sessionId?: string }>();
  const navigate = useNavigate();
  const { data: sessions } = useChatSessions();
  const createMut = useCreateChatSession();
  const creatingRef = useRef(false);
  const [detailLevel, setDetailLevel] = usePersistedState("aiops-detail-level", "medium");

  // Determine selected session from URL parameter
  const selectedId = urlSessionId || null;

  // Auto-create a new session when navigating to /app/chat without a session ID
  useEffect(() => {
    if (urlSessionId || creatingRef.current) return;
    creatingRef.current = true;
    createMut.mutateAsync(undefined).then((s) => {
      navigate(`/app/chat/${s.session_id}`, { replace: true });
    }).finally(() => {
      creatingRef.current = false;
    });
  }, [urlSessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  const { data: detail } = useChatSession(selectedId);
  const { streaming, streamingContent, toolCalls, tokenMetrics, error, sendMessage, cancel } =
    useChat(selectedId);
  const [showSaveReport, setShowSaveReport] = useState(false);
  const currentSession = sessions?.find((s) => s.session_id === selectedId);

  // Three-zone layout state
  const [flyoutOpen, setFlyoutOpen] = useState(false);
  const [contextIssueId, setContextIssueId] = useState<number | null>(null);
  const [splitRatio, setSplitRatio] = usePersistedState("aiops-chat-split", 0.55);

  // Session selection handler - navigates to new URL
  const handleSelectSession = (id: string) => {
    navigate(`/app/chat/${id}`);
  };

  return (
    <div className="flex h-[calc(100vh-2.25rem)] -m-6">
      {/* Left: Session Flyout */}
      <SessionFlyout
        open={flyoutOpen}
        selectedId={selectedId}
        onSelect={handleSelectSession}
        onClose={() => setFlyoutOpen(false)}
      />

      {/* Center: Chat area */}
      <div
        style={{ flex: contextIssueId ? `0 0 ${splitRatio * 100}%` : "1 1 auto" }}
        className="flex flex-col min-w-0"
      >
        {!selectedId ? (
          <div className="flex-1 flex items-center justify-center text-muted-foreground">
            {t("chat.selectSession")}
          </div>
        ) : (
          <>
            {/* Session toolbar */}
            <div className="flex items-center gap-2 px-4 py-2 border-b border-border bg-card/50">
              {/* Flyout toggle */}
              <button
                onClick={() => setFlyoutOpen((prev) => !prev)}
                className="w-7 h-7 flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                title={t("chat.sessions")}
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M4 6h16M4 12h16M4 18h16"
                  />
                </svg>
              </button>

              {/* Session name */}
              <h3 className="text-sm font-medium text-foreground truncate flex-1">
                {currentSession?.name ?? "Chat"}
              </h3>

              {/* Save as Report button */}
              <button
                onClick={() => setShowSaveReport(true)}
                className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground bg-secondary hover:bg-muted border border-border rounded-md transition-colors"
              >
                <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                  />
                </svg>
                {t("chat.saveAsReport")}
              </button>
            </div>

            {/* Messages */}
            <MessageList
              messages={detail?.messages ?? []}
              streamingContent={streamingContent}
              streamingToolCalls={toolCalls}
              streamingTokenMetrics={tokenMetrics}
              streaming={streaming}
            />

            {/* Error banner */}
            {error && (
              <div className="mx-6 mb-2 px-3 py-2 bg-destructive/10 border border-destructive/20 rounded-lg text-sm text-destructive">
                {error}
              </div>
            )}

            {/* Chat input */}
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

      {/* Right: Context Panel (drag handle + panel) */}
      {contextIssueId && (
        <>
          <DragHandle onResize={setSplitRatio} />
          <div
            style={{ flex: `1 1 ${(1 - splitRatio) * 100}%` }}
            className="min-w-0"
          >
            <ContextPanel
              issueId={contextIssueId}
              onClose={() => setContextIssueId(null)}
            />
          </div>
        </>
      )}

      {/* Save Report Dialog */}
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
