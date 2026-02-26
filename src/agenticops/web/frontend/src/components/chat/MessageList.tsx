import { useEffect, useRef, useMemo } from "react";
import { ToolCallChip } from "./ToolCallChip";
import { TokenMetrics } from "./TokenMetrics";
import type { ChatMessage } from "@/api/types";
import { renderMarkdown } from "@/lib/renderMarkdown";

interface Props {
  messages: ChatMessage[];
  streamingContent?: string;
  streamingToolCalls?: Array<{ name: string; status: string }>;
  streamingTokenMetrics?: { input: number; output: number } | null;
  streaming?: boolean;
}

export function MessageList({
  messages,
  streamingContent,
  streamingToolCalls,
  streamingTokenMetrics,
  streaming,
}: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, streamingContent]);

  // Render streaming markdown — memoize to avoid unnecessary re-parses
  const streamingHtml = useMemo(
    () => (streamingContent ? renderMarkdown(streamingContent) : ""),
    [streamingContent],
  );

  if (messages.length === 0 && !streamingContent) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center text-slate-400">
          <p className="text-lg font-medium">Start a conversation</p>
          <p className="text-sm mt-1">
            Ask about your AWS resources, health issues, or request a report.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
      {messages.map((msg) => (
        <div key={msg.id} className={msg.role === "user" ? "flex justify-end" : "flex gap-3"}>
          {msg.role === "assistant" && (
            <div className="flex-shrink-0 w-7 h-7 rounded-full bg-primary-600 flex items-center justify-center text-white text-xs font-semibold">
              AI
            </div>
          )}
          <div className={msg.role === "user"
            ? "bg-primary-50 border border-primary-100 rounded-xl px-4 py-2.5 max-w-2xl"
            : "flex-1 max-w-3xl space-y-2"
          }>
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
                {msg.tool_calls.map((t, i) => (
                  <ToolCallChip key={i} name={t.name} status={t.status} />
                ))}
              </div>
            )}
            <div
              className="text-sm text-slate-700 leading-relaxed report-content max-w-none"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
            />
            {msg.role === "assistant" && msg.token_usage && (
              <TokenMetrics input={msg.token_usage.input} output={msg.token_usage.output} />
            )}
          </div>
        </div>
      ))}

      {/* Streaming assistant message */}
      {(streamingContent || (streamingToolCalls && streamingToolCalls.length > 0)) && (
        <div className="flex gap-3">
          <div className="flex-shrink-0 w-7 h-7 rounded-full bg-primary-600 flex items-center justify-center text-white text-xs font-semibold">
            AI
          </div>
          <div className="flex-1 max-w-3xl space-y-2">
            {streamingToolCalls && streamingToolCalls.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-1">
                {streamingToolCalls.map((t, i) => (
                  <ToolCallChip key={i} name={t.name} status={t.status} />
                ))}
              </div>
            )}
            {streamingContent && (
              <div className="text-sm text-slate-700 leading-relaxed report-content max-w-none">
                <span dangerouslySetInnerHTML={{ __html: streamingHtml }} />
                {streaming && (
                  <span className="inline-block w-1.5 h-4 bg-primary-500 animate-pulse ml-0.5 align-text-bottom" />
                )}
              </div>
            )}
            {streamingTokenMetrics && (
              <TokenMetrics input={streamingTokenMetrics.input} output={streamingTokenMetrics.output} />
            )}
          </div>
        </div>
      )}

      <div ref={endRef} />
    </div>
  );
}
