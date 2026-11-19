import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

/** The list endpoints that answer `{items, total}` (the 2.8.0 spec's rule; MVP-2.9.0 moves them one stage at a time).
 *  When one changes shape, every caller must change in the same commit: a caller that still reads the answer as an
 *  array shows an empty list, or throws — quietly. This test reads the code for exactly that. Add the path here in
 *  the commit that changes the endpoint. */
const PAGED = ["/health-issues", "/changes", "/security/findings"];

const src = resolve(__dirname, "..");
function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) { if (name !== "__tests__" && name !== "node_modules") walk(p, out); }
    else if (/\.(ts|tsx)$/.test(name)) out.push(p);
  }
  return out;
}

/** apiFetch<T>(path) calls: the type argument and the start of the path (a string, or a template up to its first hole). */
function calls(code: string): { type: string; path: string }[] {
  return [...code.matchAll(/apiFetch<([^>(]*(?:<[^>]*>)?[^>(]*)>\(\s*[`"']([^`"'$?]*)/g)].map((m) => ({ type: m[1].trim(), path: m[2] }));
}

describe("a paged list is never read as an array", () => {
  const all = walk(src).flatMap((file) => calls(readFileSync(file, "utf8")).map((c) => ({ ...c, file: file.slice(src.length + 1) })));
  it("the test sees the calls", () => {
    expect(all.length).toBeGreaterThan(80);
    expect(all.some((c) => c.path === "/changes")).toBe(true);
    // (a path built by a helper — hooks/useHealthIssues — is not a literal here: its caller is typed by hand,
    //  HealthIssuePage; this test covers the calls that name their path)
  });
  it.each(PAGED)("GET %s", (path) => {
    // the list itself: the path exactly (a sub-resource — /changes/3/timeline — is another endpoint)
    const wrong = all.filter((c) => c.path === path && /\[\]$/.test(c.type));
    expect(wrong).toEqual([]);
  });
});
