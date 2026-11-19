import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import ts from "typescript";

/** MVP-2.9.0 N27 (the whole sweep): no page scrolls sideways on a phone, and no column is cut off. A table is as
 *  wide as its columns need, so every hand-written `<table>` either
 *    · sits inside an element that scrolls sideways itself — a Tailwind `overflow-x-auto` / `overflow-auto`, or,
 *      in NewUI, a class its stylesheet makes scroll (`.nf .iscroll{…overflow:auto}`) — or
 *    · is a fixed-layout table as wide as its container (`table-fixed w-full`: its columns share that width).
 *  Otherwise the whole page widens (Settings → Knowledge base did, by about 600 px at 390 px). `overflow-hidden`
 *  does not count: it cuts the columns off instead. Read with the TypeScript parser; the scrolling element must be
 *  an ancestor in the same file — a table's own scrolling class does nothing (a table does not scroll its columns). */
const src = resolve(__dirname, "..");

function files(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) { if (name !== "__tests__") files(path, out); }
    else if (name.endsWith(".tsx")) out.push(path.slice(src.length + 1));
  }
  return out;
}
const WITH_TABLE = files(src).sort().filter((file) => readFileSync(join(src, file), "utf8").includes("<table"));

const SCROLLS = /\boverflow-(x-)?(auto|scroll)\b/;
/** NewUI's own classes that scroll: the stylesheet says so, not a Tailwind class. */
export function scrollingClasses(css: string): Set<string> {
  return new Set([...css.matchAll(/\.nf \.([\w-]+)\{[^}]*\boverflow(?:-x)?:\s*(?:auto|scroll)\b[^}]*\}/g)].map((m) => m[1]));
}
const NF_SCROLLS = scrollingClasses(readFileSync(join(src, "newui/newui.css"), "utf8"));

export function tablesWithoutScroll(file: string, code: string, nfScrolls: Set<string> = new Set()): string[] {
  const sf = ts.createSourceFile(file, code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const hits: string[] = [];
  const classOf = (el: ts.JsxOpeningElement) => {
    const attr = el.attributes.properties.find((p) => ts.isJsxAttribute(p) && p.name.getText(sf) === "className");
    return attr ? attr.getText(sf) : "";
  };
  const scrolls = (cls: string) => SCROLLS.test(cls) || (cls.match(/[\w-]+/g) ?? []).some((word) => nfScrolls.has(word));
  const visit = (node: ts.Node) => {
    if (ts.isJsxElement(node) && node.openingElement.tagName.getText(sf) === "table") {
      const own = classOf(node.openingElement);
      let fine = /\btable-fixed\b/.test(own) && /\bw-full\b/.test(own);
      for (let p: ts.Node | undefined = node.parent; p && !fine; p = p.parent) {
        if (ts.isJsxElement(p) && scrolls(classOf(p.openingElement))) fine = true;
      }
      if (!fine) hits.push(file + ":" + (sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1));
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return hits;
}

describe("the scan", () => {
  const scan = (...lines: string[]) => tablesWithoutScroll("x.tsx", ["function Page() {", "  return (", ...lines, "  );", "}"].join("\n"), new Set(["iscroll"])).map((hit) => hit.replace(/^x\.tsx:/, "line "));

  it("names a table that nothing scrolls", () => {
    expect(scan("<Card>", '  <table className="w-full"><tbody /></table>', "</Card>")).toEqual(["line 4"]);
  });
  it("is content with a scrolling ancestor, however far up", () => {
    expect(scan('<div className="overflow-x-auto">', '  <table className="w-full"><tbody /></table>', "</div>")).toEqual([]);
    expect(scan('<div className="rounded-lg border overflow-auto">', "  <section>", "    {rows.length > 0 ? (", "      <table><tbody /></table>", "    ) : null}", "  </section>", "</div>")).toEqual([]);
  });
  it("is content with a class the new interface's stylesheet makes scroll", () => {
    expect(scan('<div className="iscroll">', '  <table className="tgrid"><tbody /></table>', "</div>")).toEqual([]);
    expect(scan('<div className="ilist">', '  <table className="tgrid"><tbody /></table>', "</div>")).toEqual(["line 4"]);
  });
  it("is content with a fixed-layout table as wide as its container", () => {
    expect(scan('<div className="overflow-hidden">', '  <table className="w-full table-fixed"><tbody /></table>', "</div>")).toEqual([]);
    expect(scan('<table className="table-fixed"><tbody /></table>')).toEqual(["line 3"]);            // fixed, but as wide as it likes
  });
  it("the table's own scrolling class does not count, nor a sibling's, nor a class that only hides", () => {
    expect(scan('<table className="w-full overflow-x-auto"><tbody /></table>')).toEqual(["line 3"]);
    expect(scan("<div>", '  <div className="overflow-x-auto" />', "  <table><tbody /></table>", "</div>")).toEqual(["line 5"]);
    expect(scan('<div className="overflow-hidden">', "  <table><tbody /></table>", "</div>")).toEqual(["line 4"]);
  });
  it("reads which classes scroll from the stylesheet", () => {
    const css = ".nf .iscroll{flex:1;min-height:0;overflow:auto}\n.nf .wide{overflow-x: scroll}\n.nf .cut{overflow:hidden}\n.nf .btn{position:relative;overflow:hidden}";
    expect([...scrollingClasses(css)].sort()).toEqual(["iscroll", "wide"]);
  });
});

describe("every hand-written table scrolls inside its own container", () => {
  it("there are tables to check, and the new interface's stylesheet names a scrolling class", () => {
    expect(WITH_TABLE.length).toBeGreaterThan(10);
    expect(WITH_TABLE).toContain("components/settings/KBTab.tsx");
    expect(NF_SCROLLS.has("iscroll")).toBe(true);
  });
  it.each(WITH_TABLE)("%s", (file) => {
    expect(tablesWithoutScroll(file, readFileSync(join(src, file), "utf8"), file.startsWith("newui/") ? NF_SCROLLS : new Set())).toEqual([]);
  });
});
