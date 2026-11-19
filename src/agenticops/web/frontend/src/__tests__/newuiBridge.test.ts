import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/** The palette bridge (round 3): while NewUI's frame hosts a classic page, `html.nf-on` restates the classic design
 *  tokens (index.css) with NewUI's palette, so the page — and every dialog it opens on <body> — takes the new look
 *  without one page file changing. These tests are what keeps that honest: nothing leaks to the classic interface,
 *  no token is left at its classic value, the colours ARE NewUI's, and text stays readable on every surface. */
const read = (rel: string) => readFileSync(resolve(__dirname, rel), "utf8");
const bridge = read("../bridge.css");
const index = read("../index.css");
const newui = read("../newui/newui.css");

const noComments = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, "");

/** `selector { body }` pairs of a stylesheet, at-rules opened (their inner rules are returned, the at-rule is not). */
function rules(css: string): { selector: string; body: string }[] {
  const out: { selector: string; body: string }[] = [];
  const text = noComments(css);
  let i = 0;
  const walk = (end: number) => {
    while (i < end) {
      const open = text.indexOf("{", i);
      if (open === -1 || open >= end) { i = end; return; }
      const head = text.slice(i, open).trim();
      let depth = 1, j = open + 1;
      while (j < text.length && depth > 0) { if (text[j] === "{") depth++; else if (text[j] === "}") depth--; j++; }
      if (head.startsWith("@")) { i = open + 1; walk(j - 1); i = j; }
      else { out.push({ selector: head, body: text.slice(open + 1, j - 1) }); i = j; }
    }
  };
  walk(text.length);
  return out;
}

/** The custom properties a block declares, with the `/* token *​/` note that follows a value (kept from the raw text). */
function vars(css: string, selector: string): Map<string, { value: string; note: string | null }> {
  const at = css.indexOf(`${selector}{`) !== -1 ? css.indexOf(`${selector}{`) : css.indexOf(`${selector} {`);
  expect(at, `block ${selector}`).toBeGreaterThan(-1);
  const open = css.indexOf("{", at), close = css.indexOf("}", open);
  const out = new Map<string, { value: string; note: string | null }>();
  for (const m of css.slice(open + 1, close).matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);[ \t]*(?:\/\*\s*([a-z0-9-]+)\s*\*\/)?/g)) {
    out.set(m[1], { value: m[2].trim(), note: m[3] ?? null });
  }
  return out;
}

type Rgb = [number, number, number];
const hexRgb = (hex: string): Rgb => [1, 3, 5].map((k) => parseInt(hex.slice(k, k + 2), 16)) as Rgb;
function hslRgb(triplet: string): Rgb {
  const m = /^(-?[\d.]+)\s+([\d.]+)%\s+([\d.]+)%/.exec(triplet);
  if (!m) throw new Error(`not an HSL triplet: ${triplet}`);
  const h = ((Number(m[1]) % 360) + 360) % 360, s = Number(m[2]) / 100, l = Number(m[3]) / 100;
  const c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs(((h / 60) % 2) - 1)), k = l - c / 2;
  const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return [r, g, b].map((v) => Math.round((v + k) * 255)) as Rgb;
}
const lum = ([r, g, b]: Rgb) => {
  const f = (v: number) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
};
const contrast = (a: Rgb, b: Rgb) => { const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };

const root = vars(index, ":root");
const day = vars(bridge, "html.nf-on");
const night = vars(bridge, "html.nf-on.dark");
const isColour = (v: string) => /^-?[\d.]+\s+[\d.]+%\s+[\d.]+%/.test(v);

describe("the bridge touches nothing unless NewUI's frame is on the page", () => {
  it("every selector starts with html.nf-on", () => {
    const all = rules(bridge);
    expect(all.length).toBeGreaterThan(4);
    for (const r of all) for (const one of r.selector.split(",")) expect(one.trim(), r.selector).toMatch(/^html\.nf-on(?![\w-])/);
  });
  it("declares no keyframes or font faces of its own", () => {
    expect(noComments(bridge)).not.toMatch(/@keyframes|@font-face|@import/);
  });
});

describe("no classic token is left at its classic value", () => {
  it("index.css has the tokens the test reads", () => {
    expect(root.size).toBeGreaterThan(38);
    expect(root.has("--primary-600")).toBe(true);
    expect(root.has("--topbar-h")).toBe(true);
  });
  it("day restates every token of :root", () => {
    expect([...root.keys()].filter((k) => !day.has(k))).toEqual([]);
  });
  it("night restates every colour day states — html.nf-on outranks .dark, so a missing one would show day's value at night", () => {
    expect([...day.entries()].filter(([k, v]) => isColour(v.value) && !night.has(k)).map(([k]) => k)).toEqual([]);
  });
  it("a colour stays an HSL triplet, the form Tailwind's hsl(var(--x)) reads", () => {
    for (const [k, v] of root) if (isColour(v.value)) {
      expect(isColour(day.get(k)!.value), `day ${k}`).toBe(true);
      expect(isColour(night.get(k)!.value), `night ${k}`).toBe(true);
    }
  });
});

describe("the colours are NewUI's own", () => {
  const palette = (theme: "night" | "day") => vars(newui, `.nf[data-theme="${theme}"]`);
  it.each([["day", day], ["night", night]] as const)("%s: every value marked with a NewUI token equals that token", (theme, block) => {
    const nf = palette(theme);
    const marked = [...block.entries()].filter(([, v]) => v.note !== null);
    expect(marked.length).toBeGreaterThan(14);
    for (const [k, v] of marked) {
      const hex = nf.get(`--${v.note}`)?.value;
      expect(hex, `${theme} ${k} names --${v.note}`).toMatch(/^#[0-9A-Fa-f]{6}$/);
      const want = hexRgb(hex!), got = hslRgb(v.value);
      for (let c = 0; c < 3; c++) expect(Math.abs(want[c] - got[c]), `${theme} ${k} (${v.value}) vs --${v.note} ${hex}`).toBeLessThanOrEqual(1);
    }
  });
  it("the surfaces, the text and the lines are marked — not left to a hand-picked value", () => {
    for (const block of [day, night]) {
      for (const k of ["--background", "--foreground", "--card", "--popover", "--muted", "--muted-foreground", "--border", "--input", "--canvas", "--primary"]) {
        expect(block.get(k)?.note, k).not.toBeNull();
      }
    }
  });
});

describe("text stays readable on every surface it can sit on (≥ 4.5 : 1)", () => {
  const rgb = (block: typeof day, name: string): Rgb => hslRgb(block.get(name)!.value);
  const SURFACES = ["--background", "--card", "--popover", "--canvas", "--muted", "--secondary", "--accent"];
  const TEXTS = ["--foreground", "--muted-foreground", "--primary", "--status-ok", "--status-warn", "--status-danger", "--destructive"];
  it.each([["day", day], ["night", night]] as const)("%s: body text, quiet text, the primary and the status colours", (theme, block) => {
    for (const s of SURFACES) for (const t of TEXTS) {
      expect(contrast(rgb(block, t), rgb(block, s)), `${theme} ${t} on ${s}`).toBeGreaterThanOrEqual(4.5);
    }
  });
  it.each([["day", day], ["night", night]] as const)("%s: a filled control's own text", (theme, block) => {
    for (const [fill, text] of [["--primary", "--primary-foreground"], ["--primary-hover", "--primary-foreground"], ["--destructive", "--destructive-foreground"],
                                ["--secondary", "--secondary-foreground"], ["--accent", "--accent-foreground"], ["--card", "--card-foreground"],
                                ["--popover", "--popover-foreground"]]) {
      expect(contrast(rgb(block, text), rgb(block, fill)), `${theme} ${text} on ${fill}`).toBeGreaterThanOrEqual(4.5);
    }
  });
  it.each([["day", day], ["night", night]] as const)("%s: the primary scale used as text (text-primary-600 / 700) on a page and on its own tint", (theme, block) => {
    for (const t of ["--primary-600", "--primary-700"]) for (const s of ["--background", "--card", "--canvas", "--muted", "--primary-50"]) {
      expect(contrast(rgb(block, t), rgb(block, s)), `${theme} ${t} on ${s}`).toBeGreaterThanOrEqual(4.5);
    }
  });
  // 27 classic lines write «bg-primary-600 text-white»: white on NewUI's bright amber is 1.8 : 1
  it("day: white on the filled steps of the scale", () => {
    for (const fill of ["--primary-500", "--primary-600", "--primary-700"]) {
      expect(contrast([255, 255, 255], rgb(day, fill)), `white on ${fill}`).toBeGreaterThanOrEqual(4.5);
    }
  });
  it("night: the filled steps are bright, so their «text-white» is re-inked — the rule exists and the ink reads", () => {
    const ink = rules(bridge).filter((r) => /^html\.nf-on\.dark\b/.test(r.selector) && /bg-primary-600/.test(r.selector) && /text-white/.test(r.selector));
    expect(ink.length).toBe(1);
    expect(ink[0].body).toMatch(/color\s*:\s*hsl\(var\(--primary-foreground\)\)/);
    for (const fill of ["bg-primary-500", "bg-primary-600", "bg-primary-700"]) expect(ink[0].selector, fill).toContain(fill);
    for (const fill of ["--primary-500", "--primary-600", "--primary-700"]) {
      expect(contrast(rgb(night, "--primary-foreground"), rgb(night, fill)), `ink on ${fill}`).toBeGreaterThanOrEqual(4.5);
    }
  });
});

describe("day: the classic pages' own status hues read on NewUI's day surfaces", () => {
  // measured on the preview: text-green-600 on the day canvas is 2.7 : 1 (3.1 on the classic canvas), emerald-500 and
  // amber-500 on white 2.5 and 2.2. The page files stay as they are; under the frame these classes take NewUI's status
  // colours (each ≥ 4.5 on every surface, tested above). Night is left alone: there the classes sit on light chips.
  const inked = (cls: string) => rules(bridge).filter((r) => r.selector.split(",").some((one) => one.trim() === `html.nf-on:not(.dark) .${cls}`));
  it.each([
    ["text-green-500", "--status-ok"], ["text-green-600", "--status-ok"], ["text-emerald-500", "--status-ok"], ["text-emerald-600", "--status-ok"],
    ["text-amber-500", "--status-warn"], ["text-amber-600", "--status-warn"], ["text-orange-500", "--status-warn"], ["text-orange-600", "--status-warn"],
    ["text-red-500", "--status-danger"], ["text-red-600", "--status-danger"],
  ])(".%s → %s", (cls, token) => {
    const hit = inked(cls);
    expect(hit).toHaveLength(1);
    expect(hit[0].body).toContain(`hsl(var(${token}))`);
  });
  it("no night rule re-inks them", () => {
    expect(rules(bridge).filter((r) => /^html\.nf-on\.dark\b/.test(r.selector) && /\.text-(green|emerald|amber|orange|red)-/.test(r.selector))).toEqual([]);
  });
});

describe("the frame's measurements", () => {
  it("--topbar-h is the top bar plus the command bar, so a page sized to the classic frame clears both", () => {
    expect(day.get("--topbar-h")?.value).toBe("112px");                       // 48 + 64 (newui.css --top / --bar)
    expect(vars(newui, ".nf").get("--top")?.value).toBe("48px");
    expect(vars(newui, ".nf").get("--bar")?.value).toBe("64px");
  });
  it("the classic sidebar's width is nothing here", () => {
    expect(day.get("--side-w")?.value).toBe("0px");
  });
  it("the chat list's drawer starts where the sidebar ends — through --side-w, the sidebar's width in the classic interface", () => {
    const chat = read("../pages/Chat.tsx");
    expect(chat).toContain("left-[var(--side-w)]");
    expect(chat).not.toMatch(/left-\[(166|200)px\]/);
    // index.css: nothing below 801px (the sidebar is a menu there), then the widths components/layout/Sidebar.tsx is drawn at
    expect(root.get("--side-w")?.value).toBe("0px");
    expect(index).toMatch(/@media \(min-width: 801px\)\s*\{\s*:root\s*\{\s*--side-w:\s*166px;\s*\}\s*\}/);
    expect(index).toMatch(/@media \(min-width: 1101px\)\s*\{\s*:root\s*\{\s*--side-w:\s*200px;\s*\}\s*\}/);
    expect(read("../components/layout/Sidebar.tsx")).toMatch(/w-\[200px\][^"]*max-\[1100px\]:w-\[166px\]/);
  });
  it("printing a page does not print the frame", () => {
    const print = /@media print\s*\{([\s\S]*?)\n\}/.exec(noComments(bridge));
    expect(print?.[1]).toMatch(/html\.nf-on \.nf\.hosting\s*\{[^}]*display\s*:\s*none/);
    // …but a lens IS the frame: hidden whenever the palette is on, «待决», a story or the table printed an empty
    // sheet (N27, review — before round 3 they printed what the screen showed)
    expect(print?.[1]).not.toMatch(/html\.nf-on \.nf\s*\{/);
  });
});
