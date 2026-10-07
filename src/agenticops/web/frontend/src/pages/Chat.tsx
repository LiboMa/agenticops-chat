import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useParams, useNavigate } from "react-router-dom";
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
import { contextRefFromQuery, contextRefQuery, type ContextRef } from "@/lib/contextRef";
import { contextForNewChat, contextLineKey } from "@/lib/chatContext";
import { STARTERS } from "@/lib/chatMessageStatus";
import { fillPlaceholders } from "@/lib/placeholders";
import { refLabel } from "@/lib/contextRef";
import { useBootstrap } from "@/hooks/useBootstrap";
import { FALLBACK_POLICY } from "@/lib/attachments";
import type { ChatContextView } from "@/api/types";
import { useAccountScope } from "@/components/layout/AccountScope";
import { useAnomaly } from "@/hooks/useAnomaly";
import { useChange } from "@/hooks/useChanges";
import SaveReportDialog from "@/components/chat/SaveReportDialog";
import { useLocale } from "@/i18n/LocaleContext";
import { ApiError } from "@/api/client";
import { apiFetch } from "@/api/client";
import { currentUserId, userKey } from "@/lib/home";

// Per signed-in user: a shared browser must never reopen someone else's last conversation
const lastSessionKey = () => userKey("aiops-last-session-id", currentUserId());

export default function Chat() {
  const { t } = useLocale();
  const { sessionId: urlSessionId } = useParams<{ sessionId?: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { data: sessions } = useChatSessions();
  // «Ask Agent» (MVP-2.7.0 S4): /app/chat?ref=I12 opens a new chat with that record as its context, sends nothing
  const [initialRef] = useState(() => contextRefFromQuery(location.search));

  // Whether we're in "welcome" mode (no active session)
  const [showWelcome, setShowWelcome] = useState(false);
  // Track whether localStorage restoration has been attempted
  const restorationAttempted = useRef(false);

  // Lazy session creation hook
  const { sendFirstMessage, creating, createError } = useLazySessionCreate();
  const scope = useAccountScope();

  // Determine selected session from URL parameter
  const selectedId = urlSessionId || null;

  // --- Requirement 1.1, 1.2, 1.5, 1.6, 1.7 ---
  // When no URL sessionId: check localStorage for last session, validate it, navigate or show welcome.
  // When URL sessionId present: just use it (page refresh case, Req 1.7).
  useEffect(() => {
    if (urlSessionId || restorationAttempted.current) return;
    restorationAttempted.current = true;
    if (initialRef) {  // a new conversation about that record: never resume the last session
      setShowWelcome(true);
      return;
    }

    const lastSessionId = localStorage.getItem(lastSessionKey());
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
          localStorage.removeItem(lastSessionKey());
        }
        setShowWelcome(true);
      });
  }, [urlSessionId, navigate]);

  // --- Requirement 1.4 ---
  // Save current sessionId to localStorage when user leaves the page
  useEffect(() => {
    if (!selectedId) return;

    // Persist on every navigation to a valid session
    localStorage.setItem(lastSessionKey(), selectedId);

    const handleBeforeUnload = () => {
      localStorage.setItem(lastSessionKey(), selectedId);
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

  // Metadata of the open session: also its name when it is not among the 50 listed (e.g. a shared link)
  const { data: sessionDetail } = useChatSession(selectedId);
  const { messages, fetchOlder, hasOlder, isFetchingOlder } = useChatMessages(selectedId);
  const { streaming, streamingContent, toolCalls, tokenMetrics, error, sendMessage, cancel } =
    useSessionStream(selectedId);
  const [showSaveReport, setShowSaveReport] = useState(false);
  const currentSession = sessions?.find((s) => s.session_id === selectedId)
    ?? (sessionDetail?.session_id === selectedId ? sessionDetail : undefined);

  // Three-zone layout state
  const [flyoutOpen, setFlyoutOpen] = useState(false);
  const [contextRef, setContextRef] = useState<ContextRef | null>(initialRef);
  // S5: the top bar shows the account this chat is bound to, locked — an open chat's own, or (before the first
  // message) the account of the issue / change it was asked about; a new free chat leaves the scope usable
  const refIssue = useAnomaly(!selectedId && contextRef?.kind === "issue" ? contextRef.id : 0);
  const refChange = useChange(!selectedId && contextRef?.kind === "change" ? contextRef.id : 0);
  const lockValue = selectedId ? (currentSession ? currentSession.context?.account_id ?? null : undefined)
    : contextRef ? (contextRef.kind === "issue" ? refIssue.data?.account_id ?? null : refChange.data?.account_id ?? null)
    : undefined;
  const { lockTo } = scope;
  const maxFiles = (useBootstrap().data?.upload_policy ?? FALLBACK_POLICY).max_files;
  const [prefill, setPrefill] = useState<{ text: string; nonce: number } | null>(null);
  const [stopped, setStopped] = useState(false);  // S5: stopping the reply is not cancelling any execution
  // What the welcome composer will start the chat with (the server confirms it on creation)
  const welcomeCtx: ChatContextView | null = contextRef
    ? { primary: { entity_type: contextRef.kind === "issue" ? "health_issue" : "change_request", entity_id: contextRef.id,
                   ref: refLabel(contextRef), title: (contextRef.kind === "issue" ? refIssue.data?.title : refChange.data?.title) ?? null },
        account_id: lockValue ?? null, account_name: contextRef.kind === "issue" ? refIssue.data?.account_name ?? null : null,
        region: null, scope_locked: false }
    : scope.accountId != null
      ? { primary: null, account_id: scope.accountId, account_name: scope.accountName, region: null, scope_locked: false }
      : null;
  useEffect(() => { lockTo(lockValue); }, [lockValue, lockTo]);
  useEffect(() => () => lockTo(undefined), [lockTo]);
  // the ref has done its job once read: it leaves the URL (a reload is an ordinary Chat visit). Keyed on the URL,
  // not on mount: the first message moves /app/chat?ref= to /app/chat/:id?ref= on the same Chat instance (S5).
  useEffect(() => {
    const ref = contextRefFromQuery(location.search);
    if (!ref) return;
    setContextRef(ref);
    const params = new URLSearchParams(location.search);
    params.delete("ref");
    const rest = params.toString();
    navigate({ pathname: location.pathname, search: rest ? `?${rest}` : "" }, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.search]);
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
  const handleWelcomeSend = (content: string, files: File[]) =>
    sendFirstMessage(content, files, contextRef ? contextRefQuery(contextRef) : "", contextForNewChat(contextRef, scope.accountId));

  return (
    <div ref={flyoutContainerRef} className="flex h-[calc(100vh-var(--topbar-h))] -m-6">
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
        style={{ flex: contextRef ? `0 0 ${splitRatio * 100}%` : "1 1 auto" }}
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

              <div className="w-full max-w-[760px] text-center">
                <h2 className="text-xl font-semibold text-foreground mb-2">
                  {t("chat.welcome")}
                </h2>
                <p className="mx-auto text-sm text-muted-foreground max-w-md">
                  {t("chat.welcomeHint")}
                </p>
                {/* Starters fill the composer — they never send */}
                <div className="mt-5 flex flex-wrap justify-center gap-2">
                  {STARTERS.map((id) => (
                    <button key={id} type="button"
                            onClick={() => setPrefill({ text: t(`chat.starter.${id}.prompt`), nonce: Date.now() })}
                            className="rounded-full border border-border bg-card px-3.5 py-1.5 text-sm text-foreground hover:border-primary/40 hover:bg-selected">
                      {t(`chat.starter.${id}.label`)}
                    </button>
                  ))}
                </div>
                <p className="mt-3 text-xs text-muted-foreground">{t("chat.attach.count").replace("{limit}", String(maxFiles))}</p>
              </div>
            </div>

            {createError && (
              <div role="alert" className="mx-6 mb-2 px-3 py-2 bg-destructive/10 border border-destructive/20 rounded-lg text-sm text-destructive">
                {t("chat.createFailed").replace("{error}", createError)}
              </div>
            )}
            <ContextLine ctx={welcomeCtx} t={t} />
            {/* Chat input in welcome mode — triggers lazy session creation (Req 1.3) */}
            <ChatInput
              onSend={handleWelcomeSend}
              disabled={creating}
              streaming={false}
              sessionId={null}
              prefill={prefill}
            />
          </>
        ) : !selectedId ? (
          <div className="flex-1 flex items-center justify-center text-muted-foreground">
            {t("chat.selectSession")}
          </div>
        ) : (
          <>
            {/* Session toolbar */}
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border/60">
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

              {/* Session name; a linked chat names its object and links to it (S5) */}
              <div className="min-w-0 flex-1 text-center">
                <h3 className="text-sm font-medium text-foreground truncate">
                  {currentSession?.name ?? "Chat"}
                </h3>
                {currentSession?.context?.primary && (
                  <p className="truncate text-xs text-muted-foreground">
                    <span className="font-mono">{currentSession.context.primary.ref}</span>
                    {currentSession.context.primary.title && ` · ${currentSession.context.primary.title}`}
                    {" · "}
                    <Link className="text-primary hover:underline"
                          to={currentSession.context.primary.entity_type === "health_issue"
                            ? `/app/issues/${currentSession.context.primary.entity_id}`
                            : `/app/changes/${currentSession.context.primary.entity_id}`}>
                      {t(currentSession.context.primary.entity_type === "health_issue" ? "chat.viewIssue" : "chat.viewChange")}
                    </Link>
                  </p>
                )}
              </div>

              {/* Save as Report button */}
              <button
                onClick={() => setShowSaveReport(true)}
                className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted border border-border/60 rounded-lg transition-colors"
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
              onSuggestionPick={(text) => sendMessage(text)}
              onContextRefClick={setContextRef}
            />

            {/* Error banner */}
            {error && (
              <div role="alert" className="mx-6 mb-2 px-3 py-2 bg-destructive/10 border border-destructive/20 rounded-lg text-sm text-destructive">
                {t(`chat.error.${error.code}`)}
              </div>
            )}

            {/* Chat input */}
            {stopped && !streaming && (
              <div role="status" className="mx-auto mb-2 flex w-full max-w-[760px] items-start justify-between gap-3 px-4 text-xs text-muted-foreground">
                <span>{t("chat.stopNotice")}</span>
                <button type="button" onClick={() => setStopped(false)} className="shrink-0 underline">{t("home.dismiss")}</button>
              </div>
            )}
            <ContextLine ctx={currentSession?.context} t={t} />
            <ChatInput
              onSend={(msg, files) => { setStopped(false); return sendMessage(msg, files); }}
              onCancel={() => { cancel(); setStopped(true); }}
              disabled={streaming}
              streaming={streaming}
              sessionId={selectedId}
            />
          </>
        )}
      </div>

      {/* Right: Context Panel (drag handle + panel) */}
      {contextRef && (
        <>
          <DragHandle onResize={setSplitRatio} />
          <div
            style={{ flex: `1 1 ${(1 - splitRatio) * 100}%` }}
            className="min-w-0"
          >
            <ContextPanel
              subject={contextRef}
              onClose={() => setContextRef(null)}
              onAgentCheck={() => {
                const key = contextRef.kind === "issue" ? "chat.contextPanel.checkPrompt" : "chat.contextPanel.checkChangePrompt";
                const prompt = t(key).replace("{id}", String(contextRef.id));
                // no session yet (welcome): create one, and keep the panel open across the new session's page
                if (selectedId) sendMessage(prompt);
                else void sendFirstMessage(prompt, undefined, contextRefQuery(contextRef), contextForNewChat(contextRef, null));
              }}
              agentCheckDisabled={streaming}
            />
          </div>
        </>
      )}

      {/* Save Report Dialog */}
      {showSaveReport && selectedId && currentSession && (
        <SaveReportDialog
          sessionId={selectedId}
          sessionName={currentSession.name}
          isPrivate={currentSession.visibility === "private"}
          onClose={() => setShowSaveReport(false)}
        />
      )}
    </div>
  );
}

/** The conversation's context in one line, above the composer (S5): linked, bound to an account, or all accounts. */
function ContextLine({ ctx, t }: { ctx: ChatContextView | null | undefined; t: (k: string) => string }) {
  const line = contextLineKey(ctx);
  return (
    <p className="mx-auto mb-1.5 w-full max-w-[760px] truncate px-4 text-xs text-muted-foreground">
      {fillPlaceholders(t(line.key), line.params).replace(/ · $/, "")}
    </p>
  );
}
