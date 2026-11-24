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

/** How many steps and how long they took: the span on the turn's clock when every step knows when it started
 *  (steps run in parallel — a sum would count the overlap), else the sum of the known durations (older rows), else
 *  null (no duration known). */
export type StepStatus = "running" | "ok" | "error" | "unknown";

/** A step's state in words (MVP-2.8.0 S1): the result decides ok / error; a finished step stored without an
 *  outcome (pre-S5 history) is unknown — never shown as a success. */
export function stepStatus(tool: ToolStep, opts: { live?: boolean } = {}): StepStatus {
  // a step stored as running belongs to a turn that failed or was cut off: once the turn is not live, unknown
  if (tool.status === "running") return opts.live === false ? "unknown" : "running";
  if (tool.outcome === "ok") return "ok";
  if (tool.outcome === "error") return "error";
  return "unknown";
}

export function workTotals(tools: ToolStep[]): { count: number; ms: number | null } {
  const known = tools.filter((t) => typeof t.duration_ms === "number");
  if (known.length === 0) return { count: tools.length, ms: null };
  if (known.length === tools.length && tools.every((t) => typeof t.started_ms === "number")) {
    const start = Math.min(...tools.map((t) => t.started_ms!));
    const end = Math.max(...tools.map((t) => t.started_ms! + t.duration_ms!));
    return { count: tools.length, ms: end - start };
  }
  return { count: tools.length, ms: known.reduce((sum, t) => sum + (t.duration_ms ?? 0), 0) };
}

/** "0.9 s" under ten seconds, "52 s" under a minute, "2 min 5 s" above — in the user's language. */
export function formatDuration(ms: number, t: (k: string) => string): string {
  const s = ms / 1000;
  if (s < 60) {
    const n = s < 10 ? (Math.round(s * 10) / 10).toString() : String(Math.round(s));
    return t("chat.work.seconds").replace("{n}", n);
  }
  const total = Math.round(s);
  return t("chat.work.minutes").replace("{m}", String(Math.floor(total / 60))).replace("{s}", String(total % 60));
}
