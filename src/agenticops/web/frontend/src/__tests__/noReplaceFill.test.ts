import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import ts from "typescript";

/** Review of MVP-2.9.0 (④): a localized template is filled by ONE function, `lib/placeholders.fillPlaceholders` —
 *  never by `.replace("{name}", value)`. That spelling filled the first occurrence only, read `$&` / `$1` in a value
 *  as a pattern (a user name or an error message with a `$` came out mangled) and filled a placeholder that a
 *  value brought in on the next `.replace`. 186 such chains in 75 files were rewritten; this keeps it so. Read with
 *  the TypeScript parser: a `.replace` / `.replaceAll` whose pattern is a string `"{word}"`, or a template that
 *  builds one (`` `{${key}}` ``). A regex pattern is not this (`lib/changeDetail.reviewSummary` drops segments). */
const src = resolve(__dirname, "..");

function files(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) { if (name !== "__tests__") files(path, out); }
    else if (/\.(ts|tsx)$/.test(name) && !name.endsWith(".d.ts")) out.push(path.slice(src.length + 1));
  }
  return out;
}

export function fillsByHand(text: string, file = "x.tsx"): number[] {
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const lines: number[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)
        && ["replace", "replaceAll"].includes(node.expression.name.text) && node.arguments.length === 2) {
      const a = node.arguments[0];
      const literal = (ts.isStringLiteral(a) || ts.isNoSubstitutionTemplateLiteral(a)) && /^\{\w+\}$/.test(a.text);
      const built = ts.isTemplateExpression(a) && a.head.text === "{";
      if (literal || built) lines.push(sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return lines;
}

describe("no template is filled by hand", () => {
  it("the check sees both spellings", () => {
    expect(fillsByHand('t("a").replace("{n}", n).replace("{m}", m)')).toEqual([1, 1]);
    expect(fillsByHand("s.replace(`{${k}}`, v)")).toEqual([1]);
    expect(fillsByHand('s.replace(/\\{(\\w+)\\}/g, f); s.replace("x", "y")')).toEqual([]);
  });
  it("every file calls fillPlaceholders instead", () => {
    const found = files(src).filter((f) => f !== join("lib", "placeholders.ts"))
      .flatMap((f) => fillsByHand(readFileSync(join(src, f), "utf8"), f).map((line) => `${f}:${line}`));
    expect(found).toEqual([]);
  });
});
