import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/** The owner, 2026-11-20 («对话页有 Bug，显示不全»): on the chat page text was cut where it should be read whole.
 *  Found on the preview: the model drop-down cut every model id after `global.anthropic.claude-opus-…` (the ids of
 *  Opus 5.5, 5, 4.8 … read alike), and a sent file's chip — its name held to a fixed 14rem beside a badge, a size
 *  and a label — was wider than a phone's screen, so the whole conversation scrolled sideways. Markup is read as
 *  text: these are class lists, and what they do was looked at in the browser (the E2E report). */
const read = (path: string) => readFileSync(resolve(__dirname, "..", path), "utf8");

describe("the model drop-down shows what it lists", () => {
  const model = read("components/chat/ModelSelector.tsx");
  const list = model.slice(model.indexOf("<Popover.Content"), model.indexOf("</Popover.Content>"));
  const contentClass = /<Popover\.Content[^>]*?className="([^"]+)"/s.exec(model)?.[1] ?? "";

  it("there is a list to read", () => {
    expect(list.length).toBeGreaterThan(1000);
    expect(contentClass).not.toBe("");
  });
  it("cuts no line of the list: a name, an id and a hint wrap instead", () => {
    expect(list).not.toMatch(/\btruncate\b|line-clamp|text-ellipsis/);
  });
  it("an id has no space to wrap at: it may break anywhere", () => {
    const ids = list.split("\n").filter((l) => /font-mono/.test(l));
    expect(ids.length).toBe(2);                                           // the current model outside the presets, and each preset
    for (const line of ids) expect(line).toMatch(/\bbreak-all\b/);
  });
  it("is never wider or taller than the window leaves it", () => {
    expect(contentClass).toMatch(/max-w-\[calc\(100vw-[\d.]+rem\)\]/);
    expect(contentClass).toMatch(/max-h-\[min\([\d.]+rem,var\(--radix-popover-content-available-height\)\)\]/);
    expect(contentClass).toMatch(/\boverflow-y-auto\b/);
    expect(model).toMatch(/collisionPadding=\{\d+\}/);
  });
  it("is wide enough for an id on one or two lines", () => {
    const w = /\bw-(\d+)\b/.exec(contentClass);
    expect(Number(w?.[1])).toBeGreaterThanOrEqual(80);                    // 20rem; it was 16rem
  });
});

describe("a sent file's chip", () => {
  const files = read("components/chat/MessageAttachments.tsx");
  const chip = /const cls = "([^"]+)"/.exec(files)?.[1] ?? "";
  const name = files.split("\n").find((l) => l.includes("{a.filename}</span>")) ?? "";

  it("is never wider than the message it belongs to", () => {
    expect(chip).toMatch(/\bmax-w-full\b/);
    expect(chip).toMatch(/\bmin-w-0\b/);
  });
  it("shows the file's name whole: it wraps, it is not cut", () => {
    expect(name).not.toBe("");
    expect(name).not.toMatch(/\btruncate\b|max-w-\[14rem\]/);
    expect(name).toMatch(/\bmin-w-0\b/);
    expect(name).toMatch(/\bbreak-all\b/);
  });
  it("the chip's badge, size and label keep their width beside a long name", () => {
    const body = files.slice(files.indexOf("const body = ("), files.indexOf("const cls ="));
    const spans = body.split("\n").filter((l) => /<span className=/.test(l) && !l.includes("{a.filename}"));
    expect(spans.length).toBe(3);
    for (const line of spans) expect(line).toMatch(/\bshrink-0\b/);
  });
});
