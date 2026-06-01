import { renderMarkdown } from "@/lib/renderMarkdown";

/**
 * Persisted chat messages are immutable, so their rendered HTML can be cached
 * by message id forever. This keeps virtualized rows cheap to re-mount on
 * scroll-back (no markdown re-parse). Streaming content is NOT cached here.
 */
const cache = new Map<number, string>();

export function renderMessageMarkdown(id: number, content: string): string {
  const hit = cache.get(id);
  if (hit !== undefined) return hit;
  const html = renderMarkdown(content);
  cache.set(id, html);
  return html;
}
