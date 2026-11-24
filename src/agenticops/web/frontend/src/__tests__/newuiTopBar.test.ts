import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/** The owner, 2026-11-20: in a window 761–859 px wide (in Chinese; below about 1,050 px in English, where the words
 *  are longer) NewUI's top bar did not fit — «回到旧版» stood on end, four lines over the hosted page's own header,
 *  and the avatar was cut off at the window's edge. The stages had been looked at at 1440, 1024 and 390 only.
 *
 *  The bar is ONE row that never wraps and never runs past the window, in any language. What gives way, in this
 *  order: the 24-hour band — its box is a size container, so it can shrink to nothing however long the words beside
 *  it are, and the band is shown only while the box has room for it —, then the two text buttons (they are in the
 *  account menu from there down, as on a phone) and the scope is held narrower; on a phone the page's name may
 *  shorten. */
const css = readFileSync(resolve(__dirname, "../newui/newui.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
const shell = readFileSync(resolve(__dirname, "../newui/shell/NewShell.tsx"), "utf8");

/** The text of every block of an at-rule whose head matches. */
function blocks(head: RegExp): string {
  const out: string[] = [];
  for (const m of css.matchAll(/@(media|container)([^{]*)\{/g)) {
    if (!head.test(`@${m[1]}${m[2]}`.trim())) continue;
    let depth = 1, k = m.index! + m[0].length;
    while (k < css.length && depth) { if (css[k] === "{") depth++; else if (css[k] === "}") depth--; k++; }
    out.push(css.slice(m.index! + m[0].length, k - 1));
  }
  return out.join("\n");
}
/** The stylesheet without its at-rule blocks: what holds at every width. */
const always = (() => {
  let text = "", i = 0;
  for (const m of css.matchAll(/@(media|container|keyframes)[^{]*\{/g)) {
    if (m.index! < i) continue;
    let depth = 1, k = m.index! + m[0].length;
    while (k < css.length && depth) { if (css[k] === "{") depth++; else if (css[k] === "}") depth--; k++; }
    text += css.slice(i, m.index!); i = k;
  }
  return text + css.slice(i);
})();
/** The declarations of the rules (in `text`) whose selector list holds exactly this selector. */
function decls(text: string, selector: string): string {
  const out: string[] = [];
  for (const m of text.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (m[1].split(",").map((s) => s.trim()).includes(selector)) out.push(m[2]);
  }
  return out.join(";");
}
const px = (text: string, prop: string) => Number(new RegExp(`${prop}\\s*:\\s*(\\d+)px`).exec(text)?.[1]);

describe("NewUI's top bar is one row that fits the window", () => {
  it.each([".nf .top .chip-btn", ".nf .top .tabs button", ".nf .top .ro"])("%s never breaks into lines", (sel) => {
    expect(decls(always, sel)).toMatch(/white-space\s*:\s*nowrap/);
  });

  it("every part of the bar keeps its width — only the band's box gives way", () => {
    expect(decls(always, ".nf .top > *")).toMatch(/flex\s*:\s*none/);
    const box = decls(always, ".nf .top > .pulsebox");
    expect(box).toMatch(/flex\s*:\s*1 1 0/);
    expect(box).toMatch(/min-width\s*:\s*0(?![\d.])/);
  });

  it("the band's box is a size container, named for NewUI: what is in it cannot hold the bar open", () => {
    expect(decls(always, ".nf .top > .pulsebox")).toMatch(/container\s*:\s*nf-pulse\s*\/\s*inline-size/);
  });

  it("the band is shown only while its box holds its label and its own smallest width", () => {
    const band = decls(always, ".nf .pulse");
    const needs = px(band, "min-width") + px(band, "margin-left");          // 120 + 76: the label sits in the margin
    expect(needs).toBeGreaterThan(150);
    const hidden = blocks(new RegExp(`^@container nf-pulse \\(max-width:\\s*${needs - 1}px\\)$`));
    expect(decls(hidden, ".nf .pulsebox .pulse")).toMatch(/display\s*:\s*none/);
  });

  it("the two text buttons leave the bar well before it runs out of room, and are in the account menu from there down", () => {
    const at = [...css.matchAll(/@media \(max-width:\s*(\d+)px\)\s*\{[^{}]*\.nf \.who \.wide\s*\{\s*display\s*:\s*none/g)].map((m) => Number(m[1]));
    const mid = Math.max(...at);
    // in English a read-only account's bar needs about 900 px without the band (measured: tabs 234, a long page
    // name 130, the group on the right 456, gaps and padding 86); the phone's layout begins at 760
    expect(mid).toBeGreaterThanOrEqual(940);
    expect(mid).toBeLessThan(1100);
    const block = blocks(new RegExp(`^@media \\(max-width:\\s*${mid}px\\)$`));
    expect(decls(block, ".nf .who .wide")).toMatch(/display\s*:\s*none/);
    expect(decls(block, ".nf .menu .narrow.mid")).toMatch(/display\s*:\s*flex/);
  });

  it("each text button of the bar has its entry in the account menu; the scope's entry stays the phone's", () => {
    const wide = [...shell.matchAll(/className="chip-btn wide"/g)].length;
    const mid = [...shell.matchAll(/className="mi narrow mid"/g)].length;
    expect(wide).toBe(2);
    expect(mid).toBe(wide);
    expect(shell).toMatch(/scope\("mi narrow scope-m"\)/);                  // not `mid`: the bar keeps its scope above 760 px
  });

  it("the group on the right keeps its width like the rest; from the middle breakpoint down the scope is held narrower", () => {
    // a group that may shrink is squeezed below what its buttons need, and the avatar ends up past the window
    // (seen at 320 px while this was being fixed): the group is rigid, and the scope's own cap is what narrows
    expect(decls(always, ".nf .top > .who")).toBe("");
    expect(decls(always, ".nf .who > *")).toBe("");
    const above = px(decls(always, ".nf .who select.scope"), "max-width");
    const below = px(decls(blocks(/^@media \(max-width:\s*960px\)$/), ".nf .who select.scope"), "max-width");
    expect(above).toBe(170);
    expect(below).toBeGreaterThanOrEqual(96);
    expect(below).toBeLessThanOrEqual(120);
  });

  it("on a phone the band's box is gone, so the three parts are spread as they were", () => {
    expect(decls(blocks(/^@media \(max-width:\s*760px\)$/), ".nf .top > .pulsebox")).toMatch(/display\s*:\s*none/);
  });

  it("on a phone a read-only account's badge is said in the account menu instead, and only the page's name may shorten", () => {
    // in English a read-only account's bar is 40–100 px wider than a 390 px screen: «Read-only» and the avatar
    // were past its edge (measured 2026-11-20)
    const phone = blocks(/^@media \(max-width:\s*760px\)$/);
    expect(decls(phone, ".nf .who .ro")).toMatch(/display\s*:\s*none/);
    expect(shell).toMatch(/\{readOnly && <div className="whoami narrow">\{t\("shell\.readOnly"\)\}<\/div>\}/);
    const name = decls(phone, ".nf .top > .pageswrap");
    expect(name).toMatch(/flex\s*:\s*0 1 auto/);
    expect(name).toMatch(/min-width\s*:\s*0(?![\d.])/);
    const chip = decls(phone, ".nf .pageswrap > .chip-btn");
    expect(chip).toMatch(/max-width\s*:\s*100%/);
    expect(chip).toMatch(/overflow\s*:\s*hidden/);
    expect(chip).toMatch(/text-overflow\s*:\s*ellipsis/);
  });

  it("the shell puts the band in that box", () => {
    expect(shell).toMatch(/<div className="pulsebox"><Pulse accountId=\{accountId\} \/><\/div>/);
  });
});
