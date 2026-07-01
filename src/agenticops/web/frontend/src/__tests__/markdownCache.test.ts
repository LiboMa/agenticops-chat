import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/renderMarkdown", () => ({
  renderMarkdown: vi.fn((md: string) => `<p>${md}</p>`),
}));

import { renderMessageMarkdown } from "@/lib/markdownCache";
import { renderMarkdown } from "@/lib/renderMarkdown";

const mockedRenderMarkdown = vi.mocked(renderMarkdown);

describe("renderMessageMarkdown", () => {
  beforeEach(() => {
    mockedRenderMarkdown.mockClear();
  });

  it("calls renderMarkdown on first invocation with a given id", () => {
    // Use a unique id to avoid cross-test cache hits
    const id = 1000;
    const content = "Hello world";
    const result = renderMessageMarkdown(id, content);

    expect(mockedRenderMarkdown).toHaveBeenCalledTimes(1);
    expect(mockedRenderMarkdown).toHaveBeenCalledWith(content);
    expect(result).toBe("<p>Hello world</p>");
  });

  it("returns cached result on subsequent calls with same id", () => {
    const id = 2000;
    const content = "Cached content";

    const first = renderMessageMarkdown(id, content);
    const second = renderMessageMarkdown(id, content);

    // renderMarkdown should only be called once for the same id
    expect(mockedRenderMarkdown).toHaveBeenCalledTimes(1);
    expect(first).toBe(second);
  });

  it("does not re-render even if content argument differs for the same id", () => {
    const id = 3000;

    const first = renderMessageMarkdown(id, "original");
    const second = renderMessageMarkdown(id, "different");

    expect(mockedRenderMarkdown).toHaveBeenCalledTimes(1);
    expect(first).toBe(second);
    expect(second).toBe("<p>original</p>");
  });

  it("caches different ids independently", () => {
    const id1 = 4000;
    const id2 = 4001;

    const result1 = renderMessageMarkdown(id1, "content A");
    const result2 = renderMessageMarkdown(id2, "content B");

    expect(mockedRenderMarkdown).toHaveBeenCalledTimes(2);
    expect(result1).toBe("<p>content A</p>");
    expect(result2).toBe("<p>content B</p>");
  });

  it("returns the rendered HTML string", () => {
    const id = 5000;
    mockedRenderMarkdown.mockReturnValueOnce("<strong>test</strong>");

    const result = renderMessageMarkdown(id, "**test**");
    expect(result).toBe("<strong>test</strong>");
  });
});
