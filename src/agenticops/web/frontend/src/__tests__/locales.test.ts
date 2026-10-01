import { describe, it, expect } from "vitest";
import en from "@/locales/en.json";
import zh from "@/locales/zh.json";

describe("locale parity", () => {
  it("en and zh carry exactly the same keys", () => {
    expect(Object.keys(zh).sort()).toEqual(Object.keys(en).sort());
  });
  it("no value is left empty", () => {
    for (const table of [en, zh] as Record<string, string>[]) {
      expect(Object.entries(table).filter(([, v]) => !v.trim())).toEqual([]);
    }
  });
});
