import { describe, it, expect } from "vitest";
import { splitWork, stepStatus, workTotals } from "@/lib/workSteps";
import type { ToolStep } from "@/api/types";

const T = (o: Partial<ToolStep>): ToolStep => ({ name: "x", status: "done", ...o });
const shape = (r: ReturnType<typeof splitWork>) => r.timeline.map((i) => (i.kind === "text" ? i.text : "TOOL"));

describe("splitWork", () => {
  it("no tools: everything is the answer", () =>
    expect(splitWork("Hi", [])).toEqual({ timeline: [], answer: "Hi" }));

  it("legacy tools without offsets: tools in the block, content is the answer", () =>
    expect(splitWork("Hi", [T({ call_id: "a" })]))
      .toEqual({ timeline: [{ kind: "tool", tool: T({ call_id: "a" }) }], answer: "Hi" }));

  it("narration before the tool goes in the block", () => {
    const r = splitWork("Let me check. Result", [T({ text_offset: 14, text_end: 14 })]);
    expect(r.timeline.map((i) => i.kind)).toEqual(["text", "tool"]);
    expect(shape(r)[0]).toBe("Let me check.");
    expect(r.answer).toBe("Result");
  });

  it("text written while a step runs stays with the step", () => {
    const r = splitWork("Ainner Final", [T({ text_offset: 1, text_end: 6 })]);
    expect(shape(r)).toEqual(["A", "TOOL", "inner"]);
    expect(r.answer).toBe("Final");
  });

  it("an answer written before a trailing tool is still the answer", () => {
    const r = splitWork("The answer.", [T({ text_offset: 11, text_end: 11 })]);
    expect(r.answer).toBe("The answer.");
    expect(r.timeline.map((i) => i.kind)).toEqual(["tool"]);
  });

  it("offsets past the end are clamped (redaction shortened the text) and no text is lost", () => {
    const r = splitWork("Short", [T({ text_offset: 999, text_end: 999 })]);
    expect(r.answer).toBe("Short");
  });

  it("live with a running tool: no fallback, the text stays in the block", () => {
    const r = splitWork("Checking", [T({ status: "running", text_offset: 8 })], { live: true });
    expect(r.answer).toBe("");
    expect(shape(r)[0]).toBe("Checking");
  });

  it("two tools with narration between", () => {
    const r = splitWork("a b c", [T({ text_offset: 2, text_end: 2 }), T({ text_offset: 4, text_end: 4 })]);
    expect(shape(r)).toEqual(["a", "TOOL", "b", "TOOL"]);
    expect(r.answer).toBe("c");
  });
});

describe("workTotals", () => {
  it("sums the durations; null when none is known", () => {
    expect(workTotals([T({ duration_ms: 1200 }), T({ duration_ms: 800 })])).toEqual({ count: 2, ms: 2000 });
    expect(workTotals([T({})])).toEqual({ count: 1, ms: null });
  });
  it("is the span on the turn's clock when every step knows when it started (parallel steps overlap)", () => {
    expect(workTotals([T({ started_ms: 0, duration_ms: 1000 }), T({ started_ms: 200, duration_ms: 1000 })]))
      .toEqual({ count: 2, ms: 1200 });
  });
});

import { formatDuration } from "@/lib/workSteps";
describe("formatDuration", () => {
  const t = (k: string) => (k === "chat.work.seconds" ? "{n} s" : "{m} min {s} s");
  it("seconds with one decimal under a minute, minutes above", () => {
    expect(formatDuration(850, t)).toBe("0.9 s");
    expect(formatDuration(52_000, t)).toBe("52 s");
    expect(formatDuration(125_000, t)).toBe("2 min 5 s");
  });
});

describe("splitWork offsets are UTF-16 units (the server counts them the same way)", () => {
  it("an emoji before a step does not shift the cut", () => {
    const narration = "🔍 Found 🔴 api down. Checking logs:";
    const r = splitWork(narration + "Root cause: x", [T({ text_offset: narration.length, text_end: narration.length })]);
    expect(r.answer).toBe("Root cause: x");
    expect((r.timeline[0] as any).text).toBe(narration);
  });
});

describe("stepStatus — a step says its state in words (MVP-2.8.0 S1)", () => {
  it("is running while the step runs", () => {
    expect(stepStatus(T({ status: "running" }))).toBe("running");
  });
  it("is ok / error from the result", () => {
    expect(stepStatus(T({ outcome: "ok" }))).toBe("ok");
    expect(stepStatus(T({ outcome: "error" }))).toBe("error");
  });
  it("is unknown for a finished step stored without an outcome — never assumed successful", () => {
    expect(stepStatus(T({}))).toBe("unknown");
    expect(stepStatus(T({ outcome: "unknown" }))).toBe("unknown");
  });
});
