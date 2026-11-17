import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/** NewUI's stylesheet arrives with a lazy chunk and is never unloaded: one unscoped rule would restyle the classic
 *  pages for the rest of the visit. So every selector starts with `.nf` and every animation name with `nf-`. */
const css = readFileSync(resolve(__dirname, "../newui/newui.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

interface Rule { selectors: string[]; body: string }

/** Top-level rules and the rules inside @media; @keyframes are collected by name. */
function parse(text: string, rules: Rule[] = [], keyframes: string[] = []): { rules: Rule[]; keyframes: string[] } {
  let i = 0;
  while (i < text.length) {
    const open = text.indexOf("{", i);
    if (open < 0) break;
    const head = text.slice(i, open).trim();
    let depth = 1, k = open + 1;
    while (k < text.length && depth) { if (text[k] === "{") depth++; else if (text[k] === "}") depth--; k++; }
    const inner = text.slice(open + 1, k - 1);
    if (head.startsWith("@keyframes")) keyframes.push(head.split(/\s+/)[1]);
    else if (head.startsWith("@media")) parse(inner, rules, keyframes);
    else if (head.startsWith("@")) throw new Error(`an at-rule this test does not know: ${head}`);
    else rules.push({ selectors: splitSelectors(head), body: inner });
    i = k;
  }
  return { rules, keyframes };
}

function splitSelectors(head: string): string[] {
  const out: string[] = [];
  let depth = 0, cur = "";
  for (const ch of head) {
    if (ch === "(" || ch === "[") depth++;
    if (ch === ")" || ch === "]") depth--;
    if (ch === "," && depth === 0) { out.push(cur.trim()); cur = ""; } else cur += ch;
  }
  out.push(cur.trim());
  return out;
}

const { rules, keyframes } = parse(css);
const WORDS = new Set(["none", "linear", "ease", "ease-in", "ease-out", "ease-in-out", "infinite", "forwards", "backwards",
  "both", "normal", "reverse", "alternate", "alternate-reverse", "running", "paused", "important"]);

describe("newui.css stays inside .nf", () => {
  it("has rules to check", () => {
    expect(rules.length).toBeGreaterThan(300);
    expect(keyframes.length).toBeGreaterThan(5);
  });

  it("starts every selector with .nf", () => {
    const loose = rules.flatMap((r) => r.selectors).filter((s) => !/^\.nf(?![\w-])/.test(s));
    expect(loose).toEqual([]);
  });

  it("never styles the page itself", () => {
    const page = rules.flatMap((r) => r.selectors).filter((s) => /(^|[\s>+~,])(html|body|:root)(?![\w-])/.test(s));
    expect(page).toEqual([]);
  });

  it("names every animation nf-…, and uses only the ones it declares", () => {
    expect(keyframes.filter((k) => !k.startsWith("nf-"))).toEqual([]);
    const used = new Set<string>();
    for (const r of rules) {
      for (const m of r.body.matchAll(/animation(?:-name)?\s*:\s*([^;}]+)/g)) {
        for (const word of m[1].replace(/var\([^)]*\)|\([^)]*\)/g, " ").split(/[\s,!]+/)) {
          if (!word || WORDS.has(word) || /^[\d.]/.test(word) || /^(steps|cubic-bezier)/.test(word)) continue;
          used.add(word);
        }
      }
    }
    expect([...used].filter((u) => !keyframes.includes(u))).toEqual([]);
  });

  it("does not use a class name Tailwind already gives a meaning to", () => {
    // `grid` is Tailwind's display:grid — a <table class="grid"> would stop being a table
    const bare = rules.flatMap((r) => r.selectors).filter((s) => /\.(grid|flex|block|hidden|table|fixed|absolute|relative|sticky|truncate|container|border|shadow|ring|filter|blur|transition|transform|outline|underline|italic|uppercase|visible|invisible|collapse|contents|inline|static|resize|grow|shrink)(?![\w-])/.test(s));
    expect(bare).toEqual([]);
  });
});
