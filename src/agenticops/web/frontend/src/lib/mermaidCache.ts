/**
 * Rendered mermaid SVG by (theme, source) — 2026-11-07. Chat rows are virtualized: a row scrolled away and back
 * mounts again, and must not render (or change height) again. Concurrent asks share one render; a failed render is
 * forgotten, so the next mount can try again.
 */
const cache = new Map<string, Promise<string>>();
const done = new Map<string, string>();   // resolved renders, readable synchronously (a remounted row paints at once)
let seq = 0;

export function renderMermaidCached(
  source: string,
  theme: "light" | "dark",
  render: (id: string, src: string) => Promise<string>,
): Promise<string> {
  const key = `${theme}\u0000${source}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const p = render(`aiops-mermaid-${++seq}`, source);
  cache.set(key, p);
  p.then((svg) => { done.set(key, svg); },
         () => { if (cache.get(key) === p) cache.delete(key); });
  return p;
}

/** The SVG already rendered for this source and theme, if any. */
export function peekMermaid(source: string, theme: "light" | "dark"): string | undefined {
  return done.get(`${theme}\u0000${source}`);
}

export function mermaidCacheSize(): number {
  return cache.size;
}
