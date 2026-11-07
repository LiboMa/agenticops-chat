import type { ToolStep } from "@/api/types";

/** One line of an answer's work log: the model's narration, or a tool step (2026-11-07). */
export type TimelineItem = { kind: "text"; text: string } | { kind: "tool"; tool: ToolStep };

/**
 * Split a reply into its work log and its answer, by where each step sat in the reply text (`text_offset` when it
 * began, `text_end` when its result came back — both character offsets the server recorded).
 *
 * - Text before a step, and text written while a step ran (an enhanced_task's own output), is narration: it goes in
 *   the work log, in order, between the steps.
 * - Text after the last step's result is the answer.
 * - An answer the model wrote BEFORE a trailing step (nothing after it) is still the answer: the last non-empty
 *   narration piece is taken out of the log. Not while live — the reply is still being written.
 * - Offsets are clamped to the text (the DB redaction can shorten a reply that quoted a secret): no text is lost.
 * - Older rows have no offsets: their steps are listed, the whole text is the answer.
 */
export function splitWork(content: string, tools: ToolStep[], opts: { live?: boolean } = {}):
  { timeline: TimelineItem[]; answer: string } {
  if (tools.length === 0) return { timeline: [], answer: content };
  if (tools.some((t) => typeof t.text_offset !== "number")) {
    return { timeline: tools.map((tool) => ({ kind: "tool" as const, tool })), answer: content };
  }
  const len = content.length;
  const clamp = (n: number) => Math.min(Math.max(0, n), len);
  const sorted = tools.map((tool, i) => ({ tool, i, at: clamp(tool.text_offset!) }))
    .sort((a, b) => a.at - b.at || a.i - b.i);
  const last = sorted[sorted.length - 1].at;
  const running = opts.live && tools.some((t) => t.status === "running");
  const end = running ? len
    : Math.max(last, ...sorted.map((s) => clamp(typeof s.tool.text_end === "number" ? s.tool.text_end : s.at)));

  const timeline: TimelineItem[] = [];
  const pushText = (from: number, to: number) => {
    const text = content.slice(from, to).trim();
    if (text) timeline.push({ kind: "text", text });
  };
  pushText(0, sorted[0].at);
  sorted.forEach((s, k) => {
    timeline.push({ kind: "tool", tool: s.tool });
    pushText(s.at, k + 1 < sorted.length ? sorted[k + 1].at : end);
  });

  let answer = content.slice(end).trim();
  if (!answer && !opts.live) {
    for (let k = timeline.length - 1; k >= 0; k--) {
      const item = timeline[k];
      if (item.kind === "text") {
        answer = item.text;
        timeline.splice(k, 1);
        break;
      }
    }
  }
  return { timeline, answer };
}

/** How many steps and how long they took in all (null when no step has a duration: an older row). */
export function workTotals(tools: ToolStep[]): { count: number; ms: number | null } {
  const known = tools.filter((t) => typeof t.duration_ms === "number");
  return { count: tools.length, ms: known.length ? known.reduce((sum, t) => sum + (t.duration_ms ?? 0), 0) : null };
}
