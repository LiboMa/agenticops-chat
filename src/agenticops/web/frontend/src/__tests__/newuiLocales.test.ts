import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import en from "@/newui/locales/en.json";
import zh from "@/newui/locales/zh.json";
import { fill, nfT } from "@/newui/i18n";

const Z = zh as Record<string, string>, E = en as Record<string, string>;
const holes = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe("NewUI's own words (they ship with the NewUI chunk, not with the first screen)", () => {
  it("has the same keys in both languages", () => {
    expect(Object.keys(Z).filter((k) => !(k in E))).toEqual([]);
    expect(Object.keys(E).filter((k) => !(k in Z))).toEqual([]);
  });

  it("leaves no text empty", () => {
    expect(Object.keys(Z).filter((k) => !Z[k].trim() || !E[k].trim())).toEqual([]);
  });

  it("uses the same {variables} in both languages", () => {
    expect(Object.keys(Z).filter((k) => holes(Z[k]).join() !== holes(E[k]).join())).toEqual([]);
  });

  it("never mentions the prototype or sample data", () => {
    const bad = Object.keys(Z).filter((k) => /原型|示例|设计稿/.test(Z[k]) || /prototype|sample data|interaction draft|clickable/i.test(E[k]));
    expect(bad).toEqual([]);
  });
});

describe("nfT", () => {
  it("fills {variables}, numbers included, and leaves an unknown one empty", () => {
    expect(fill("{i} / {n}", { i: 7, n: 140 })).toBe("7 / 140");
    expect(fill("等了 {t}", {})).toBe("等了 ");
    expect(fill("no holes")).toBe("no holes");
  });

  it("answers in the asked language, falls back to Chinese, then to the key", () => {
    expect(nfT("zh", "lens.decide")).toBe("待决");
    expect(nfT("en", "lens.decide")).toBe("Decide");
    expect(nfT("en", "no.such.key")).toBe("no.such.key");
    expect(nfT("zh", "pos", { i: 2, n: 9 })).toBe("2 / 9");
  });
});

/** The keys the code asks for. A key that is missing shows as its own name on the page («story.rca.none»), in both
 *  languages, and nothing else fails — so the code is read here: every key written as a literal in a `t(…)` call
 *  must exist, and every key built from a prefix (t(`phase.${id}`)) must have at least one key under that prefix. */
function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? sources(join(dir, e.name)) : /\.tsx?$/.test(e.name) ? [join(dir, e.name)] : []);
}

function askedKeys(code: string): { literals: string[]; prefixes: string[] } {
  const literals: string[] = [], prefixes: string[] = [];
  for (const call of code.matchAll(/\bt\(/g)) {
    let depth = 1, j = call.index! + call[0].length;
    const from = j;
    while (j < code.length && depth) { if (code[j] === "(") depth++; else if (code[j] === ")") depth--; j++; }
    const key = code.slice(from, j - 1).split(", {")[0];                 // the key expression, without the variables
    for (const m of key.matchAll(/"([a-zA-Z]\w*(?:\.\w+)+)"/g)) literals.push(m[1]);
    for (const m of key.matchAll(/`([a-zA-Z][\w.]*)\.\$\{/g)) prefixes.push(m[1]);
  }
  return { literals, prefixes };
}

describe("every key the NewUI code asks for exists", () => {
  const root = resolve(__dirname, "../newui");
  const asked = sources(root).map((f) => ({ file: f.slice(root.length + 1), ...askedKeys(readFileSync(f, "utf8")) }));

  it("reads the code", () => {
    expect(asked.length).toBeGreaterThan(40);
    expect(asked.flatMap((a) => a.literals).length).toBeGreaterThan(300);
  });

  it("has every literal key", () => {
    const missing = asked.flatMap((a) => a.literals.filter((k) => !(k in Z)).map((k) => `${a.file}: ${k}`));
    expect([...new Set(missing)]).toEqual([]);
  });

  it("has at least one key under every prefix a key is built from", () => {
    const keys = Object.keys(Z);
    const missing = asked.flatMap((a) => a.prefixes.filter((p) => !keys.some((k) => k.startsWith(`${p}.`))).map((p) => `${a.file}: ${p}.*`));
    expect([...new Set(missing)]).toEqual([]);
  });

  it("has a sentence for each of the six steps, each step state, and each kind of ask on the story page", () => {
    for (const k of [
      ...["found", "rca", "plan", "approve", "run", "accept", "request", "review"].map((s) => `phase.${s}`),
      ...["done", "now", "bad", "closed", "todo"].map((s) => `spine.${s}`),
      ...["approve", "accept", "resolve", "confirm", "rerun", "generate", "replan", "failed", "not_started", "start_review", "clarify", "generic"].map((s) => `story.ask.${s}`),
      "wait.you", "wait.person", "wait.agent", "wait.agentIdle", "wait.executor", "wait.none",
    ]) expect(Z[k], k).toBeTruthy();
  });
});
