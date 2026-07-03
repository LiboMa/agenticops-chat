import { useState } from "react";
import { useTraceTimeline } from "@/hooks/useTraceTimeline";
import type { ChatMessage } from "@/api/types";

interface Props {
  msg: ChatMessage;
}

export function TokenMetrics({ msg }: Props) {
  const [expanded, setExpanded] = useState(false);
  const tu = msg.token_usage;
  if (!tu) return null;

  const input = tu.input ?? 0;
  const output = tu.output ?? 0;
  const cacheRead = tu.cache_read ?? 0;
  const total = input + output + cacheRead + (tu.cache_write ?? 0);
  const cost = tu.cost_usd ?? msg.cost_usd ?? 0;

  const timelineQ = useTraceTimeline(msg.trace_id, expanded);

  return (
    <div className="mt-1">
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-xs text-muted-foreground tabular-nums hover:text-foreground transition-colors"
      >
        ↑{input.toLocaleString()} ↓{output.toLocaleString()} Σ{total.toLocaleString()}
        {cost > 0 && <span className="ml-1 text-green-600 dark:text-green-400">${cost.toFixed(4)}</span>}
        <span className="ml-1">{expanded ? "▴" : "▾"}</span>
      </button>

      {expanded && (
        <div className="mt-1 ml-2 text-xs border-l-2 border-muted pl-2">
          {tu.model && (
            <div className="text-muted-foreground mb-1">Model: {tu.model}</div>
          )}
          {cacheRead > 0 && (
            <div className="text-muted-foreground">
              Cache read: {cacheRead.toLocaleString()} ({((cacheRead / (input + cacheRead)) * 100).toFixed(0)}%)
            </div>
          )}

          {timelineQ.isLoading && <div className="text-muted-foreground">Loading trace...</div>}
          {timelineQ.data && timelineQ.data.calls.length > 1 && (
            <table className="mt-1 w-full text-[11px] tabular-nums">
              <thead>
                <tr className="text-muted-foreground">
                  <th className="text-left font-normal pr-2">Agent</th>
                  <th className="text-right font-normal pr-2">In</th>
                  <th className="text-right font-normal pr-2">Out</th>
                  <th className="text-right font-normal pr-2">Cache</th>
                  <th className="text-right font-normal">$</th>
                </tr>
              </thead>
              <tbody>
                {timelineQ.data.calls.map((c) => (
                  <tr key={c.id}>
                    <td className="pr-2">{c.agent_name}</td>
                    <td className="text-right pr-2">{c.input_tokens.toLocaleString()}</td>
                    <td className="text-right pr-2">{c.output_tokens.toLocaleString()}</td>
                    <td className="text-right pr-2">{c.cache_read_tokens.toLocaleString()}</td>
                    <td className="text-right text-green-600 dark:text-green-400">
                      {c.cost_usd != null ? `$${c.cost_usd.toFixed(4)}` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
