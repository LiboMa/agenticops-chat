import { describe, it, expect } from "vitest";
import { splitWork, workTotals } from "@/lib/workSteps";
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
});
