import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

/** Where the code is cut (round 3). The classic interface is the default and must paint as it always did: nothing
 *  of NewUI may be pulled into the entry chunk. And a classic page must not wait for NewUI's chunk when the new frame
 *  hosts it: the frame's host is in the entry, NewUI's shell loads beside it. */
const src = resolve(__dirname, "..");
const read = (rel: string) => readFileSync(join(src, rel), "utf8");
const noComments = (code: string) => code.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

const staticImports = (code: string) => [...noComments(code).matchAll(/^\s*import\s+(?:[^"'()]*?\s+from\s+)?["']([^"']+)["']/gm)].map((m) => m[1]);
const lazyImports = (code: string) => [...noComments(code).matchAll(/\bimport\(\s*["']([^"']+)["']\s*\)/g)].map((m) => m[1]);

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out); else if (/\.(ts|tsx)$/.test(name)) out.push(p);
  }
  return out;
}

const ENTRY = ["App.tsx", "main.tsx", "components/layout/ShellSwitch.tsx", "components/layout/NewFrame.tsx", "components/layout/AppShell.tsx",
               "components/layout/HomeResolver.tsx"];

describe("the entry chunk has nothing of NewUI in it", () => {
  it.each(ENTRY)("%s imports nothing from @/newui statically", (file) => {
    expect(staticImports(read(file)).filter((p) => p.startsWith("@/newui") || p.includes("/newui/"))).toEqual([]);
  });
  it("NewUI is reached through import() only — its shell from the frame, its lenses from the routes", () => {
    expect(lazyImports(read("components/layout/NewFrame.tsx"))).toContain("@/newui/shell/NewShell");
    expect(lazyImports(read("App.tsx"))).toContain("@/newui/NewLenses");
  });
  it("the bridge stylesheet comes with the entry, not with NewUI's chunk", () => {
    expect(staticImports(read("components/layout/NewFrame.tsx"))).toContain("@/bridge.css");
    for (const file of walk(join(src, "newui"))) expect(staticImports(readFileSync(file, "utf8")), file).not.toContain("@/bridge.css");
  });
});

describe("NewUI's chunk has no classic page in it", () => {
  it("nothing under newui/ imports a page", () => {
    const hits = walk(join(src, "newui")).filter((file) => {
      const code = readFileSync(file, "utf8");
      return [...staticImports(code), ...lazyImports(code)].some((p) => p.startsWith("@/pages/") || /(^|\/)pages\//.test(p));
    });
    expect(hits).toEqual([]);
  });
});

describe("the classic branch paints at once", () => {
  const sw = noComments(read("components/layout/ShellSwitch.tsx"));
  it("ShellSwitch imports the classic shell statically and reads the choice synchronously", () => {
    expect(staticImports(sw)).toContain("./AppShell");
    expect(sw).toMatch(/readChoice\(\)/);
    expect(sw).not.toMatch(/useEffect|useState|Suspense/);
  });
});

describe("index.html puts the frame's palette on before the first paint", () => {
  const html = readFileSync(resolve(src, "../index.html"), "utf8");
  it("reads the same per-user key as lib/shellChoice and sets nf-on", () => {
    expect(html).toContain('"aiops-shell:"');
    expect(html).toContain('classList.add("nf-on")');
  });
});
