import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/** MVP-2.9.0 N27 (the whole sweep): a long word in rendered markdown — a bare web address in a report's list was
 *  the one found — wraps instead of widening the page at phone width. `break-word`, not `anywhere`: `anywhere`
 *  also lets a table squeeze its columns to one letter instead of scrolling inside its own container. */
const css = readFileSync(resolve(__dirname, "../index.css"), "utf8");

describe("rendered markdown", () => {
  const base = /(?:^|\n)\.report-content\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";

  it("wraps a word longer than its line", () => {
    expect(base).toMatch(/overflow-wrap:\s*break-word\s*;/);
  });
  it("does not squeeze a table's columns: the table scrolls in its own container", () => {
    expect(css).not.toMatch(/\.report-content[^{]*\{[^}]*overflow-wrap:\s*anywhere/);
    expect(css).toMatch(/\.report-content \.md-table-wrap\s*\{[^}]*overflow-x-auto/);
  });
});
