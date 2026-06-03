import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useChatSessions } from "@/hooks/useChatSessions";
import { useChatSession } from "@/hooks/useChatSession";
import { useSessionStream } from "@/hooks/useSessionStream";
import { useChatMessages } from "@/hooks/useChatMessages";
import { useLazySessionCreate } from "@/hooks/useLazySessionCreate";
import { usePersistedState } from "@/hooks/usePersistedState";
import { SessionFlyout } from "@/components/chat/SessionFlyout";
import { MessageList } from "@/components/chat/MessageList";
import { ChatInput } from "@/components/chat/ChatInput";
import { DragHandle } from "@/components/chat/DragHandle";
import { ContextPanel } from "@/components/chat/ContextPanel";
import SaveReportDialog from "@/components/chat/SaveReportDialog";
import { useLocale } from "@/i18n/LocaleContext";
import { ApiError } from "@/api/client";
import { apiFetch } from "@/api/client";

const LAST_SESSION_KEY = "aiops-last-session-id";

export default function Chat() {
  const { t } = useLocale();
  const { sessionId: urlSessionId } = useParams<{ sessionId?: string }>();
  const navigate = useNavigate();
  const { data: sessions } = useChatSessions();
  const [detailLevel, setDetailLevel] = usePersistedState("aiops-detail-level", "medium");

  // Whether we're in "welcome" mode (no active session)
  const [showWelcome, setShowWelcome] = useState(false);
  // Track whether localStorage restoration has been attempted
  const restorationAttempted = useRef(false);

  // Lazy session creation hook
  const { sendFirstMessage, creating } = useLazySessionCreate();

  // Determine selected session from URL parameter
  const selectedId = urlSessionId || null;

  // --- Requirement 1.1, 1.2, 1.5, 1.6, 1.7 ---
  // When no URL sessionId: check localStorage for last session, validate it, navigate or show welcome.
  // When URL sessionId present: just use it (page refresh case, Req 1.7).
  useEffect(() => {
    if (urlSessionId || restorationAttempted.current) return;
    restorationAttempted.current = true;

    const lastSessionId = localStorage.getItem(LAST_SESSION_KEY);
    if (!lastSessionId) {
      setShowWelcome(true);
      return;
    }

    // Validate the stored sessionId still exists (Req 1.5)
    apiFetch(`/chat/sessions/${lastSessionId}`)
      .then(() => {
        navigate(`/app/chat/${lastSessionId}`, { replace: true });
      })
      .catch((err: unknown) => {
        // Session deleted or not found — clear localStorage and show welcome (Req 1.5)
        if (err instanceof ApiError && err.status === 404) {
          localStorage.removeItem(LAST_SESSION_KEY);
        }
        setShowWelcome(true);
      });
  }, [urlSessionId, navigate]);

  // --- Requirement 1.4 ---
  // Save current sessionId to localStorage when user leaves the page
  useEffect(() => {
    if (!selectedId) return;

    // Persist on every navigation to a valid session
    localStorage.setItem(LAST_SESSION_KEY, selectedId);

    const handleBeforeUnload = () => {
      localStorage.setItem(LAST_SESSION_KEY, selectedId);
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [selectedId]);

  // When URL gains a sessionId, exit welcome mode
  useEffect(() => {
    if (urlSessionId) {
      setShowWelcome(false);
    }
  }, [urlSessionId]);

  useChatSession(selectedId); // metadata only — primes session existence/validation
  const { messages, fetchOlder, hasOlder, isFetchingOlder } = useChatMessages(selectedId);
  const { streaming, streamingContent, toolCalls, tokenMetrics, error, sendMessage, cancel } =
    useSessionStream(selectedId);
  const [showSaveReport, setShowSaveReport] = useState(false);
  const currentSession = sessions?.find((s) => s.session_id === selectedId);

  // Three-zone layout state
  const [flyoutOpen, setFlyoutOpen] = useState(false);
  const [contextIssueId, setContextIssueId] = useState<number | null>(null);
  const [splitRatio, setSplitRatio] = usePersistedState("aiops-chat-split", 0.55);

  // Flyout resizable width (px), persisted
  const [flyoutWidth, setFlyoutWidth] = usePersistedState("aiops-flyout-width", 220);
  const [flyoutDragging, setFlyoutDragging] = useState(false);
  const flyoutDraggingRef = useRef(false);
  const flyoutContainerRef = useRef<HTMLDivElement>(null);
  const flyoutRaf = useRef(0);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!flyoutDraggingRef.current || !flyoutContainerRef.current) return;
      cancelAnimationFrame(flyoutRaf.current);
      flyoutRaf.current = requestAnimationFrame(() => {
        if (!flyoutContainerRef.current) return;
        const parentRect = flyoutContainerRef.current.getBoundingClientRect();
        const newWidth = e.clientX - parentRect.left;
        setFlyoutWidth(Math.min(400, Math.max(160, newWidth)));
      });
    };
    const handleMouseUp = () => {
      if (flyoutDraggingRef.current) {
        cancelAnimationFrame(flyoutRaf.current);
        flyoutDraggingRef.current = false;
        setFlyoutDragging(false);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      }
    };
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      cancelAnimationFrame(flyoutRaf.current);
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [setFlyoutWidth]);

  // Session selection handler - navigates to new URL
  const handleSelectSession = (id: string) => {
    navigate(`/app/chat/${id}`);
  };

  // --- Requirement 1.3 ---
  // Handle first message in welcome state: create session lazily, then send message
  const handleWelcomeSend = (content: string, files: File[]) => {
    sendFirstMessage(content, files, detailLevel);
  };

  return (
    <div ref={flyoutContainerRef} className="flex h-[calc(100vh-2.25rem)] -m-6">
      {/* Left: Session Flyout (resizable) */}
      <div
        style={{ width: flyoutOpen ? `${flyoutWidth}px` : 0 }}
        className={`flex-shrink-0 overflow-hidden ${flyoutDragging ? "" : "transition-[width] duration-200 ease-in-out"} ${flyoutOpen ? "" : "w-0"}`}
      >
        <SessionFlyout
          open={flyoutOpen}
          selectedId={selectedId}
          onSelect={handleSelectSession}
          onClose={() => setFlyoutOpen(false)}
        />
      </div>

      {/* Flyout ↔ Chat drag handle (always visible) */}
      <div
        onMouseDown={(e) => {
          e.preventDefault();
          if (!flyoutOpen) setFlyoutOpen(true);
          flyoutDraggingRef.current = true;
          setFlyoutDragging(true);
          document.body.style.cursor = "col-resize";
          document.body.style.userSelect = "none";
        }}
        onDoubleClick={() => setFlyoutOpen((prev) => !prev)}
        className="w-[6px] flex-shrink-0 cursor-col-resize group flex items-center justify-center hover:bg-primary/20 transition-colors"
      >
        <div className="flex flex-col gap-1">
          <div className="w-1 h-1 rounded-full bg-border group-hover:bg-primary/60 transition-colors" />
          <div className="w-1 h-1 rounded-full bg-border group-hover:bg-primary/60 transition-colors" />
          <div className="w-1 h-1 rounded-full bg-border group-hover:bg-primary/60 transition-colors" />
        </div>
      </div>

      {/* Center: Chat area */}
      <div
        style={{ flex: contextIssueId ? `0 0 ${splitRatio * 100}%` : "1 1 auto" }}
        className="flex flex-col min-w-0"
      >
        {showWelcome && !selectedId ? (
          /* Welcome screen — no session yet (Req 1.1) */
          <>
            <div className="flex-1 flex flex-col items-center justify-center gap-4 px-6">
              {/* Flyout toggle in welcome mode */}
              <button
                onClick={() => setFlyoutOpen((prev) => !prev)}
                className="absolute top-4 left-4 w-7 h-7 flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
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

              <div className="text-center">
                <h2 className="text-lg font-semibold text-foreground mb-2">
                  {t("chat.welcome")}
                </h2>
                <p className="text-sm text-muted-foreground max-w-md">
                  {t("chat.welcomeHint")}
                </p>
              </div>
            </div>

            {/* Chat input in welcome mode — triggers lazy session creation (Req 1.3) */}
            <ChatInput
              onSend={handleWelcomeSend}
              disabled={creating}
              streaming={false}
              detailLevel={detailLevel}
              onDetailLevelChange={setDetailLevel}
            />
          </>
        ) : !selectedId ? (
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
              messages={messages}
              streamingContent={streamingContent}
              streamingToolCalls={toolCalls}
              streamingTokenMetrics={tokenMetrics}
              streaming={streaming}
              hasOlder={hasOlder}
              isFetchingOlder={isFetchingOlder}
              onLoadOlder={fetchOlder}
            />

            {/* Error banner */}
            {error && (
              <div className="mx-6 mb-2 px-3 py-2 bg-destructive/10 border border-destructive/20 rounded-lg text-sm text-destructive">
                {error}
              </div>
            )}

            {/* Chat input */}
            <ChatInput
              onSend={(msg, files) => sendMessage(msg, files, detailLevel)}
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
