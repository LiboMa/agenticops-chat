import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";

/** The pages put a full-width space (U+3000) between a sentence and what follows it. Written bare at the start or the
 *  end of a JSX text line it never reaches the page: the build trims a line's edges, and to it U+3000 is whitespace —
 *  «…weblab-ec2-role» ran straight into the next sentence (found in the browser after the final review). Mid-line it
 *  survives. So at a line's edge the space is written as an expression: {"　"}. */
function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? sources(join(dir, e.name)) : /\.tsx$/.test(e.name) ? [join(dir, e.name)] : []);
}

describe("a gap written into a NewUI page reaches the page", () => {
  it("has no bare full-width space at the edge of a line", () => {
    const root = resolve(__dirname, "../newui");
    const lost = sources(root).flatMap((f) => readFileSync(f, "utf8").split("\n")
      .map((line, n) => [line, n + 1] as const)
      .filter(([line]) => /^\s*　/.test(line) || /　\s*$/.test(line))
      .map(([, n]) => `${f.slice(root.length + 1)}:${n}`));
    expect(lost).toEqual([]);
  });
});
