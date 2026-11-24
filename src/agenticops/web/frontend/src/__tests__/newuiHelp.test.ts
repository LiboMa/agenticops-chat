import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { HELP_ROWS } from "@/newui/shell/Help";

/** MVP-2.9.0 N27 (the keyboard list, checked key by key): the list names every key the map handles. `R` — auto-
 *  rotation in 3D — worked and was on its own button, and the list did not have it. Read from the lens's source:
 *  the single keys its handler compares against are the keys of the list's two map rows. */
const lens = readFileSync(resolve(__dirname, "../newui/world/WorldLens.tsx"), "utf8");

describe("the keyboard list", () => {
  const rowKeys = (label: string) => (HELP_ROWS.find(([, l]) => l === label)?.[0] ?? []).map((k) => k.toLowerCase());

  it("names every key the map handles, and no key the map does not", () => {
    const handler = lens.slice(lens.indexOf("useLensKeys({"), lens.indexOf("onEscape:"));
    const handled = [...new Set([...handler.matchAll(/\bkey === "(.)"/g)].map((m) => m[1]))].sort();
    expect(handled.length).toBeGreaterThan(8);
    expect([...rowKeys("help.world"), ...rowKeys("help.replay")].sort()).toEqual(handled);
  });
  it("no row is empty and no row's words are used twice", () => {
    expect(HELP_ROWS.every(([keys]) => keys.length > 0)).toBe(true);
    expect(new Set(HELP_ROWS.map(([, label]) => label)).size).toBe(HELP_ROWS.length);
  });
});
