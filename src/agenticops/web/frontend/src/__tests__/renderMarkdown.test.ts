import { describe, it, expect } from "vitest";
import { renderMarkdown } from "@/lib/renderMarkdown";

const countAnchors = (html: string) => (html.match(/<a /g) ?? []).length;

describe("renderMarkdown href allowlist — unsafe schemes render as plain text (R3)", () => {
  it.each([
    ["javascript scheme", "[x](javascript:alert%281%29)"],
    ["mixed-case javascript", "[x](JaVaScRiPt:alert%281%29)"],
    ["leading-space javascript", "[x]( javascript:alert%281%29)"],
    ["a real tab inside the scheme", "[x](java\tscript:alert%281%29)"],
    ["data: base64 html", "[x](data:text/html;base64,PHNjcmlwdD4=)"],
    ["vbscript", "[x](vbscript:msgbox)"],
  ])("%s → label kept, no anchor", (_label, md) => {
    const html = renderMarkdown(md);
    expect(html).toContain("x");
    expect(html).not.toContain("<a");
  });
});

describe("renderMarkdown href allowlist — safe links kept (R3)", () => {
  it("keeps an https link and escapes the & in the query", () => {
    const html = renderMarkdown("[a](https://example.com/a?b=1&c=2)");
    expect(html).toContain('href="https://example.com/a?b=1&amp;c=2"');
  });

  it.each([
    ["root-relative", "[a](/app/issues/3)", "/app/issues/3"],
    ["fragment", "[a](#section)", "#section"],
    ["uppercase scheme", "[a](HTTPS://EXAMPLE.COM)", "HTTPS://EXAMPLE.COM"],
  ])("%s keeps its href", (_label, md, href) => {
    expect(renderMarkdown(md)).toContain(`href="${href}"`);
  });
});

describe("renderMarkdown ref autolinks (R3)", () => {
  it("C#12 → change link with the exact anchor", () => {
    expect(renderMarkdown("C#12")).toContain(
      '<a href="/app/changes/12" class="md-link md-ref" title="Change #12">C#12</a>',
    );
  });

  it("I#3 and R#4 still render their existing anchors", () => {
    const html = renderMarkdown("I#3 R#4");
    expect(html).toContain('href="/app/issues/3"');
    expect(html).toContain('href="/app/resources/4"');
  });

  it("ABC#5 is not a change link", () => {
    expect(renderMarkdown("ABC#5")).not.toContain("/app/changes/");
  });
});

describe("renderMarkdown protected anchors (R3)", () => {
  it("a #C#1 fragment inside a real link is not rewritten", () => {
    const html = renderMarkdown("[doc](https://x.com/p#C#1)");
    expect(countAnchors(html)).toBe(1);
    expect(html).toContain('href="https://x.com/p#C#1"');
  });

  it("a C#2 label inside a real link is not autolinked", () => {
    const html = renderMarkdown("[C#2](https://x.com)");
    expect(countAnchors(html)).toBe(1);
    expect(html).not.toContain("/app/changes/");
  });

  it("a forged NUL placeholder cannot inject an anchor or leak 'undefined'", () => {
    const html = renderMarkdown("a\u00000\u0000b");
    expect(html).not.toContain("undefined");
    expect(html).not.toContain("<a");
  });
});
