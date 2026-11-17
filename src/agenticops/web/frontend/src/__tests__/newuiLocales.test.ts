import { describe, expect, it } from "vitest";
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
