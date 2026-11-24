import { describe, it, expect, vi } from "vitest";
import { renderMermaidCached } from "@/lib/mermaidCache";

describe("mermaidCache", () => {
  it("renders a source once per theme, even when asked concurrently", async () => {
    const render = vi.fn(async (_id: string, src: string) => `<svg>${src}</svg>`);
    const [a, b] = await Promise.all([renderMermaidCached("A-->B", "light", render),
                                      renderMermaidCached("A-->B", "light", render)]);
    expect(a).toBe(b);
    expect(render).toHaveBeenCalledTimes(1);
    await renderMermaidCached("A-->B", "dark", render);
    expect(render).toHaveBeenCalledTimes(2);
  });
  it("a failed render is not cached", async () => {
    const bad = vi.fn(async () => { throw new Error("parse"); });
    await expect(renderMermaidCached("x", "light", bad)).rejects.toThrow();
    await expect(renderMermaidCached("x", "light", bad)).rejects.toThrow();
    expect(bad).toHaveBeenCalledTimes(2);
  });
});

describe("peekMermaid", () => {
  it("a finished render is readable synchronously (a remounted row paints at once)", async () => {
    const { peekMermaid } = await import("@/lib/mermaidCache");
    expect(peekMermaid("C-->D", "light")).toBeUndefined();
    await renderMermaidCached("C-->D", "light", async () => "<svg>cd</svg>");
    expect(peekMermaid("C-->D", "light")).toBe("<svg>cd</svg>");
  });
});
