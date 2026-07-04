import { useRef, useMemo, useLayoutEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ToolCallChip } from "./ToolCallChip";
import { TokenMetrics } from "./TokenMetrics";
import { SuggestionChips } from "./SuggestionChips";
import type { ChatMessage } from "@/api/types";
import { renderMarkdown } from "@/lib/renderMarkdown";
import { renderMessageMarkdown } from "@/lib/markdownCache";

interface Props {
  messages: ChatMessage[];
  streamingContent?: string;
  streamingToolCalls?: Array<{ name: string; status: string }>;
  streamingTokenMetrics?: { input: number; output: number } | null;
  streaming?: boolean;
  hasOlder?: boolean;
  isFetchingOlder?: boolean;
  onLoadOlder?: () => void;
  onSuggestionPick?: (text: string) => void;
  onIssueRefClick?: (issueId: number) => void;
}

export function MessageList({
  messages,
  streamingContent,
  streamingToolCalls,
  streamingTokenMetrics,
  streaming,
  hasOlder,
  isFetchingOlder,
  onLoadOlder,
  onSuggestionPick,
  onIssueRefClick,
}: Props) {
  const navigate = useNavigate();
  const parentRef = useRef<HTMLDivElement>(null);

  const handleRefClick = (e: React.MouseEvent) => {
    const anchor = (e.target as HTMLElement).closest("a.md-ref") as HTMLAnchorElement | null;
    if (!anchor) return;
    e.preventDefault();
    const pathname = new URL(anchor.href).pathname;
    const issueMatch = pathname.match(/^\/app\/issues\/(\d+)$/);
    if (issueMatch && onIssueRefClick) {
      onIssueRefClick(Number(issueMatch[1]));
      return;
    }
    navigate(pathname);
  };

  // One virtual row per message; the streaming bubble is rendered as a sticky
  // trailer below the virtualizer (always at the bottom), not virtualized.
  const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 80,
    overscan: 8,
    getItemKey: (i) => messages[i].id,
  });

  // Scroll bookkeeping refs.
  const stickToBottomRef = useRef(true);            // auto-scroll only when the user is at the bottom
  const distanceFromBottomRef = useRef(0);          // captured on scroll, used to anchor on prepend
  const prevFirstIdRef = useRef<number | undefined>(undefined);
  const prevLenRef = useRef(0);

  // Track scroll position: whether the user is pinned to the bottom, and the
  // distance-from-bottom used to anchor the view when older pages prepend.
  const onScroll = () => {
    const el = parentRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottomRef.current = distanceFromBottom < 80;
    distanceFromBottomRef.current = distanceFromBottom;
    if (hasOlder && !isFetchingOlder && el.scrollTop < 120) onLoadOlder?.();
  };

  // Scroll management runs before paint (useLayoutEffect) to avoid flicker.
  //  - prepend (older page loaded at top → first id changed AND length grew):
  //    keep the same distance from the bottom so the viewport stays on the same
  //    content despite rows added above (no yank-to-bottom, no visible jump).
  //  - append / streaming (content added at the bottom): stick to bottom only
  //    if the user was already there.
  useLayoutEffect(() => {
    const el = parentRef.current;
    if (!el) return;
    const firstId = messages[0]?.id;
    const prepended =
      prevFirstIdRef.current !== undefined &&
      firstId !== prevFirstIdRef.current &&
      messages.length > prevLenRef.current;

    if (prepended) {
      el.scrollTop = el.scrollHeight - el.clientHeight - distanceFromBottomRef.current;
    } else if (stickToBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
    prevFirstIdRef.current = firstId;
    prevLenRef.current = messages.length;
  }, [messages, streamingContent, streaming]);

  const streamingHtml = useMemo(
    () => (streamingContent ? renderMarkdown(streamingContent.split("<<SUGGEST>>")[0]) : ""),
    [streamingContent],
  );

  if (messages.length === 0 && !streamingContent && !streaming) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center text-muted-foreground">
          <p className="text-lg font-medium">Start a conversation</p>
          <p className="text-sm mt-1">
            Ask about your AWS resources, health issues, or request a report.
          </p>
        </div>
      </div>
    );
  }

  const items = virtualizer.getVirtualItems();

  return (
    <div
      ref={parentRef}
      onScroll={onScroll}
      onClick={handleRefClick}
      className="flex-1 overflow-y-auto px-6 py-4"
    >
      {isFetchingOlder && (
        <div className="text-center text-xs text-muted-foreground py-2">Loading older messages…</div>
      )}

      {/* Virtualized message rows */}
      <div style={{ height: `${virtualizer.getTotalSize()}px`, position: "relative", width: "100%" }}>
        {items.map((vi) => {
          const msg = messages[vi.index];
          return (
            <div
              key={vi.key}
              data-index={vi.index}
              ref={virtualizer.measureElement}
              style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${vi.start}px)` }}
              className="pb-7"
            >
              <MessageRow
                msg={msg}
                isLast={vi.index === messages.length - 1}
                streaming={streaming}
                onSuggestionPick={onSuggestionPick}
              />
            </div>
          );
        })}
      </div>

      {/* Thinking indicator — streaming started but no content yet */}
      {streaming && !streamingContent && (!streamingToolCalls || streamingToolCalls.length === 0) && (
        <div className="flex gap-3 animate-[fadeIn_0.2s_ease-out] pt-2">
          <div className="flex-shrink-0 w-7 h-7 rounded-full bg-primary-600 flex items-center justify-center text-white text-xs font-semibold">AI</div>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span className="flex gap-1">
              <span className="w-1.5 h-1.5 bg-primary-400 rounded-full animate-bounce [animation-delay:0ms]" />
              <span className="w-1.5 h-1.5 bg-primary-400 rounded-full animate-bounce [animation-delay:150ms]" />
              <span className="w-1.5 h-1.5 bg-primary-400 rounded-full animate-bounce [animation-delay:300ms]" />
            </span>
            Thinking...
          </div>
        </div>
      )}

      {/* Streaming assistant message (sticky trailer) */}
      {streaming && (streamingContent || (streamingToolCalls && streamingToolCalls.length > 0)) && (
        <div className="flex gap-3 animate-[fadeIn_0.2s_ease-out] pt-2">
          <div className="flex-shrink-0 w-7 h-7 rounded-full bg-primary-600 flex items-center justify-center text-white text-xs font-semibold">AI</div>
          <div className="flex-1 max-w-3xl space-y-2">
            {streamingToolCalls && streamingToolCalls.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-1">
                {streamingToolCalls.map((t, i) => (<ToolCallChip key={i} name={t.name} status={t.status} />))}
              </div>
            )}
            {streamingContent && (
              <div className="text-sm text-foreground leading-relaxed report-content max-w-none">
                <span dangerouslySetInnerHTML={{ __html: streamingHtml }} />
                <span className="inline-block w-1.5 h-4 bg-primary-500 animate-pulse ml-0.5 align-text-bottom" />
              </div>
            )}
            {streamingTokenMetrics && (
              <span className="text-xs text-muted-foreground tabular-nums">
                ↑{streamingTokenMetrics.input.toLocaleString()} ↓{streamingTokenMetrics.output.toLocaleString()} Σ{(streamingTokenMetrics.input + streamingTokenMetrics.output).toLocaleString()}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function MessageRow({ msg, isLast, streaming, onSuggestionPick }: {
  msg: ChatMessage;
  isLast?: boolean;
  streaming?: boolean;
  onSuggestionPick?: (text: string) => void;
}) {
  return (
    <div className={msg.role === "user" ? "flex justify-end" : "flex gap-3"}>
      {msg.role === "assistant" && (
        <div className="flex-shrink-0 w-7 h-7 rounded-full bg-primary-600 flex items-center justify-center text-white text-xs font-semibold">AI</div>
      )}
      <div className={msg.role === "user"
        ? "bg-primary-50 border border-primary-100 rounded-2xl rounded-br-md px-4 py-2.5 max-w-2xl text-primary-900"
        : "flex-1 max-w-3xl space-y-2"}>
        {msg.role === "user" && msg.attachments && msg.attachments.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-1">
            {msg.attachments.map((att, i) => (
              <span key={i} className="inline-flex items-center gap-1 text-xs bg-primary-100 text-primary-700 px-2 py-0.5 rounded-full">
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                </svg>
                {att.filename}
              </span>
            ))}
          </div>
        )}
        {msg.role === "assistant" && msg.tool_calls && msg.tool_calls.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-1">
            {msg.tool_calls.map((t, i) => (<ToolCallChip key={i} name={t.name} status={t.status} />))}
          </div>
        )}
        <div
          className="text-sm text-foreground leading-relaxed report-content max-w-none"
          dangerouslySetInnerHTML={{ __html: renderMessageMarkdown(msg.id, msg.content) }}
        />
        {msg.role === "assistant" && msg.token_usage && (
          <TokenMetrics msg={msg} />
        )}
        {msg.role === "assistant" && isLast && !streaming && onSuggestionPick &&
          Array.isArray(msg.suggestions) && msg.suggestions.length > 0 && (
          <SuggestionChips suggestions={msg.suggestions} onPick={onSuggestionPick} />
        )}
      </div>
    </div>
  );
}
