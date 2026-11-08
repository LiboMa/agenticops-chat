import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useVirtualizer } from "@tanstack/react-virtual";
import { MessageAttachments } from "./MessageAttachments";
import { mergeDeliveries } from "@/lib/messageAttachments";
import type { AttachmentDelivery } from "@/lib/chatStream";
import { SuggestionChips } from "./SuggestionChips";
import { WorkSteps } from "./WorkSteps";
import { MessageActions } from "./MessageActions";
import { RichContent } from "./rich/RichContent";
import type { ChatMessage, ToolStep } from "@/api/types";
import { renderMessageMarkdown } from "@/lib/markdownCache";
import { contextRefFromPath, type ContextRef } from "@/lib/contextRef";
import { messageErrorDetail, messageStatusKey } from "@/lib/chatMessageStatus";
import { splitWork } from "@/lib/workSteps";
import { canRegenerate, type RegenCheck } from "@/lib/messageActions";
import { nextStick } from "@/lib/stickToBottom";
import { useLocale } from "@/i18n/LocaleContext";
import { thinkingTail } from "@/lib/thinking";

interface Props {
  messages: ChatMessage[];
  streamingContent?: string;
  streamingToolCalls?: ToolStep[];
  streamingTokenMetrics?: { input: number; output: number } | null;
  streaming?: boolean;
  hasOlder?: boolean;
  isFetchingOlder?: boolean;
  onLoadOlder?: () => void;
  onSuggestionPick?: (text: string) => void;
  onContextRefClick?: (ref: ContextRef) => void; // I# / C# refs open the context panel instead of navigating
  /** 2026-11-07: how the attachments of the message being answered reached the model (the stream's frame) */
  pendingDeliveries?: AttachmentDelivery[];
  /** the model's thinking summary so far (live only, 2026-11-08) */
  streamingThinking?: string;
  /** send the last answer's question again (a new answer follows) */
  onRegenerate?: (text: string) => void;
  onSaveReport?: () => void;
  readOnly?: boolean;
}

const AWAY_PX = 200;   // further than this from the bottom: offer «back to bottom»

/** The conversation, ChatGPT-style (2026-11-07): one centered column; the user's messages in a bubble on the right,
 *  answers flat with their work log above and their actions below. Rows are virtualized; the streaming answer is a
 *  trailer below them. */
export function MessageList({
  messages, streamingContent, streamingToolCalls, streamingTokenMetrics, streaming, hasOlder, isFetchingOlder,
  onLoadOlder, onSuggestionPick, onContextRefClick, pendingDeliveries, onRegenerate, onSaveReport, readOnly,
  streamingThinking,
}: Props) {
  const { t } = useLocale();
  const navigate = useNavigate();
  const parentRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [away, setAway] = useState(false);
  let lastUserIndex = -1;
  for (let i = messages.length - 1; i >= 0; i--) if (messages[i].role === "user") { lastUserIndex = i; break; }

  const handleRefClick = (e: React.MouseEvent) => {
    const anchor = (e.target as HTMLElement).closest("a.md-ref") as HTMLAnchorElement | null;
    if (!anchor) return;
    e.preventDefault();
    const pathname = new URL(anchor.href).pathname;
    const ref = contextRefFromPath(pathname);
    if (ref && onContextRefClick) {
      onContextRefClick(ref);
      return;
    }
    navigate(pathname);
  };

  const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 120,
    overscan: 8,
    getItemKey: (i) => messages[i].id,
  });

  const stickToBottomRef = useRef(true);            // auto-scroll only when the user is at the bottom
  const distanceFromBottomRef = useRef(0);          // captured on scroll, used to anchor on prepend
  const prevFirstIdRef = useRef<number | undefined>(undefined);
  const prevLenRef = useRef(0);
  const userScrollAt = useRef(0);                    // when the user last scrolled (wheel, touch, keys, scrollbar)
  const markUser = () => { userScrollAt.current = Date.now(); };

  const onScroll = () => {
    const el = parentRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    // only the user's own scroll unsticks: rows measuring taller than estimated move the offset too
    stickToBottomRef.current = nextStick(stickToBottomRef.current, distanceFromBottom,
                                         Date.now() - userScrollAt.current < 1000);
    distanceFromBottomRef.current = distanceFromBottom;
    setAway(distanceFromBottom > AWAY_PX);
    if (hasOlder && !isFetchingOlder && el.scrollTop < 120) onLoadOlder?.();
  };

  // prepend (older page at the top): keep the distance from the bottom; append / streaming: follow when stuck
  useLayoutEffect(() => {
    const el = parentRef.current;
    if (!el) return;
    const firstId = messages[0]?.id;
    const prepended = prevFirstIdRef.current !== undefined && firstId !== prevFirstIdRef.current
      && messages.length > prevLenRef.current;
    if (prepended) el.scrollTop = el.scrollHeight - el.clientHeight - distanceFromBottomRef.current;
    else if (stickToBottomRef.current) el.scrollTop = el.scrollHeight;
    prevFirstIdRef.current = firstId;
    prevLenRef.current = messages.length;
  }, [messages, streamingContent, streaming]);

  // A row that grows after it painted (a chart laid out, a flowchart rendered, a step opened) keeps a stuck view at
  // the bottom
  useEffect(() => {
    const el = parentRef.current, content = contentRef.current;
    if (!el || !content || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => { if (stickToBottomRef.current) el.scrollTop = el.scrollHeight; });
    ro.observe(content);
    return () => ro.disconnect();
  }, []);

  const jumpToBottom = () => {
    const el = parentRef.current;
    if (!el) return;
    stickToBottomRef.current = true;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  };

  const liveTools = streamingToolCalls ?? [];
  const liveText = (streamingContent ?? "").split("<<SUGGEST>>")[0];
  const liveAnswer = useMemo(() => splitWork(liveText, liveTools, { live: true }).answer, [liveText, liveTools]);
  const liveThinking = thinkingTail(streamingThinking ?? "");

  const items = virtualizer.getVirtualItems();

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div ref={parentRef} onScroll={onScroll} onClick={handleRefClick} onWheel={markUser} onTouchMove={markUser}
           onKeyDown={markUser} onPointerDown={markUser} tabIndex={-1} className="flex-1 overflow-y-auto outline-none">
        <div ref={contentRef} className="mx-auto w-full max-w-[760px] px-4 pb-6 pt-6">
          {isFetchingOlder && (
            <div className="py-2 text-center text-xs text-muted-foreground">Loading older messages…</div>
          )}

          <div style={{ height: `${virtualizer.getTotalSize()}px`, position: "relative", width: "100%" }}>
            {items.map((vi) => {
              const msg = messages[vi.index];
              const isLast = vi.index === messages.length - 1;
              return (
                <div key={vi.key} data-index={vi.index} ref={virtualizer.measureElement}
                     style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${vi.start}px)` }}
                     className="pb-8">
                  <MessageRow
                    msg={msg}
                    isLast={isLast}
                    streaming={streaming}
                    regen={isLast ? canRegenerate(messages, vi.index, !!streaming) : { ok: false, reason: "not_last" }}
                    onSuggestionPick={onSuggestionPick}
                    onRegenerate={onRegenerate}
                    onSaveReport={onSaveReport}
                    readOnly={readOnly}
                    deliveries={vi.index === lastUserIndex ? pendingDeliveries : undefined}
                  />
                </div>
              );
            })}
          </div>

          {/* The answer being written: its live work log, then the answer so far */}
          {streaming && (
            <div className="animate-[fadeIn_0.2s_ease-out] pb-4">
              {liveTools.length === 0 && !liveText ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <span className="flex gap-1" aria-hidden>
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary/70 [animation-delay:0ms]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary/70 [animation-delay:150ms]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary/70 [animation-delay:300ms]" />
                  </span>
                  <span className="shrink-0">{t("chat.thinking")}</span>
                  {liveThinking && <span className="min-w-0 truncate text-muted-foreground/80" title={liveThinking}>{liveThinking}</span>}
                </div>
              ) : (
                <>
                  <WorkSteps tools={liveTools} content={liveText} live thinking={liveThinking} />
                  {liveAnswer && <RichContent text={liveAnswer} streaming />}
                  <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-primary/70 align-text-bottom" aria-hidden />
                  {streamingTokenMetrics && (
                    <div className="mt-1 text-xs tabular-nums text-muted-foreground">
                      ↑{streamingTokenMetrics.input.toLocaleString()} ↓{streamingTokenMetrics.output.toLocaleString()}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {away && (
        <button type="button" onClick={jumpToBottom} aria-label={t("chat.jumpToBottom")} title={t("chat.jumpToBottom")}
                className="absolute bottom-3 left-1/2 flex h-9 w-9 -translate-x-1/2 items-center justify-center rounded-full border border-border bg-background text-foreground shadow-md hover:bg-muted">
          <svg className="h-4 w-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
            <path d="M8 3v10M3.5 8.5 8 13l4.5-4.5" />
          </svg>
        </button>
      )}
    </div>
  );
}

function MessageRow({ msg, isLast, streaming, regen, onSuggestionPick, onRegenerate, onSaveReport, readOnly, deliveries }: {
  msg: ChatMessage;
  isLast?: boolean;
  streaming?: boolean;
  regen: RegenCheck;
  onSuggestionPick?: (text: string) => void;
  onRegenerate?: (text: string) => void;
  onSaveReport?: () => void;
  readOnly?: boolean;
  deliveries?: AttachmentDelivery[];
}) {
  const { t } = useLocale();
  const answerRef = useRef<HTMLDivElement>(null);
  const statusKey = messageStatusKey(msg);
  const errorDetail = messageErrorDetail(msg);
  const tools = msg.tool_calls ?? [];
  const answer = useMemo(() => (msg.role === "assistant" ? splitWork(msg.content, tools).answer : msg.content),
    // a stored message never changes; a temp id is replaced by a new row
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [msg.id, msg.content, msg.tool_calls]);

  if (msg.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-3xl bg-muted px-4 py-2.5 text-[15px] text-foreground">
          {msg.attachments && msg.attachments.length > 0 && (
            <MessageAttachments attachments={mergeDeliveries(msg.attachments, deliveries ?? [])} />
          )}
          <div className="report-content max-w-none leading-relaxed [&_.md-p:last-child]:mb-0"
               dangerouslySetInnerHTML={{ __html: renderMessageMarkdown(msg.id, msg.content) }} />
        </div>
      </div>
    );
  }

  return (
    <div>
      <WorkSteps tools={tools} content={msg.content} />
      {answer && <div ref={answerRef}><RichContent text={answer} cacheKey={msg.id} /></div>}
      {/* S5: an interrupted or failed reply says so — by its kind of failure, never the raw exception */}
      {statusKey && (
        <div className={`mt-2 rounded-lg border px-3 py-2 text-xs ${statusKey === "chat.status.interrupted"
          ? "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300"
          : "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-400"}`}>
          {t(statusKey)}
          {errorDetail && <div className="mt-0.5 break-words">{t("chat.error.reason").replace("{reason}", errorDetail)}</div>}
        </div>
      )}
      {answer.trim() && (
        <MessageActions msg={msg} answer={answer} answerRef={answerRef} regen={regen}
                        onRegenerate={onRegenerate} onSaveReport={onSaveReport} readOnly={readOnly} />
      )}
      {isLast && !streaming && onSuggestionPick && Array.isArray(msg.suggestions) && msg.suggestions.length > 0 && (
        <SuggestionChips suggestions={msg.suggestions} onPick={onSuggestionPick} />
      )}
    </div>
  );
}
