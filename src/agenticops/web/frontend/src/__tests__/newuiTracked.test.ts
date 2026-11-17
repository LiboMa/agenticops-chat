import { describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";

/** The repository's .gitignore carries the Python template's directory names (`lib/`, `parts/`, `build/`, `var/` …),
 *  and they match anywhere in the tree: a NewUI folder with such a name is silently left out of every commit, and the
 *  commit ships a build that imports files git never saw. This fails the moment a NewUI file is ignored. */
describe("every NewUI source file can be committed", () => {
  it("has no file that .gitignore swallows", () => {
    let ignored: string;
    try {
      ignored = execFileSync("git", ["ls-files", "--others", "--ignored", "--exclude-standard", "--", "src/newui", "src/__tests__"],
        { cwd: resolve(__dirname, "../.."), encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
    } catch {
      return;                                   // not a git checkout (a copy made for a clean build): nothing to check
    }
    expect(ignored.split("\n").filter(Boolean)).toEqual([]);
  });
});
