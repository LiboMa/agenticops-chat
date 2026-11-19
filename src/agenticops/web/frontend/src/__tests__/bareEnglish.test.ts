import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import ts from "typescript";

/** MVP-2.9.0 N25 (the 2.8.0 spec's R19): no English sentence is written straight into a page of the classic
 *  interface — every sentence a person reads comes from the locale files, so it exists in both languages. A
 *  «sentence» is two English words in a row, at least one of them an ordinary word; a technical identifier (a model
 *  id, `OPENAI_API_KEY`, `L0 / L1`, one product name) is not one — single words are not checked. Read with the
 *  TypeScript parser: JSX text, the text-bearing attributes, an object's text-bearing properties (`label:`,
 *  `desc:` …), and strings — with or without a variable in them — placed where text goes. NewUI has its own words
 *  and its own test (`newuiLocales.test.ts`). */
const src = resolve(__dirname, "..");

function pages(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) { if (name !== "__tests__" && name !== "newui") pages(path, out); }
    else if (name.endsWith(".tsx")) out.push(path.slice(src.length + 1));
  }
  return out;
}
/** Every .tsx of the classic interface. */
const CHECKED = pages(src).sort();

/** The names under which text is handed on — as an attribute (`label="…"`) or as an object's property (`{ label: "…" }`). */
const TEXT_PROPS = new Set(["label", "description", "desc", "placeholder", "title", "aria-label", "alt", "emptyText", "header", "actionLabel", "message", "error"]);
/** Two words in a row, one of them an ordinary word (two lowercase letters or more): «Scan Focus», «Expected a JSON
 *  object», «IAM roles» — not `L0 / L1`, not `OPENAI_API_KEY`, not one word. */
const WORD = "[A-Za-z]*[a-z]{2,}[A-Za-z]*";
const SENTENCE = new RegExp("\\b" + WORD + "[ ,]+[A-Za-z]+\\b|\\b[A-Za-z]+[ ,]+" + WORD + "\\b");
const isSentence = (text: string) => SENTENCE.test(text.replace(/\s+/g, " ").trim());
const ORDINARY = new RegExp("\\b" + WORD + "\\b", "g");
const CODE_TAGS = ["code", "pre", "kbd"];

export function bareEnglish(file: string, code: string): string[] {
  const sf = ts.createSourceFile(file, code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const hits: string[] = [];
  const at = (node: ts.Node, text: string) => {
    const line = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1;
    hits.push(file + ":" + line + " " + text.replace(/\s+/g, " ").trim().slice(0, 70));
  };
  /** A string placed where text goes: a child of an element, the value of a text-bearing attribute, or of an
   *  object's text-bearing property. */
  const inTextPosition = (node: ts.Node): boolean => {
    for (let p: ts.Node | undefined = node.parent; p; p = p.parent) {
      if (ts.isJsxExpression(p)) {
        const owner = p.parent;
        if (ts.isJsxAttribute(owner)) return TEXT_PROPS.has(owner.name.getText(sf));
        return ts.isJsxElement(owner) || ts.isJsxFragment(owner);
      }
      if (ts.isJsxAttribute(p)) return TEXT_PROPS.has(p.name.getText(sf));
      if (ts.isPropertyAssignment(p)) return TEXT_PROPS.has(p.name.getText(sf).replace(/["']/g, ""));
      // only what chooses or joins text is looked through; anything else — a call's argument (t("…"), cn("…"),
      // replace("…")) first of all — is not text
      if (!(ts.isConditionalExpression(p) || ts.isBinaryExpression(p) || ts.isParenthesizedExpression(p) || ts.isTemplateExpression(p) || ts.isTemplateSpan(p))) return false;
    }
    return false;
  };
  /** A string with variables in it, as it reads: each variable is `{}`. */
  const flat = (node: ts.TemplateExpression) => node.head.text + node.templateSpans.map((span) => "{}" + span.literal.text).join("");
  const isCodeElement = (el: ts.Node): boolean => ts.isJsxElement(el) && CODE_TAGS.includes(el.openingElement.tagName.getText(sf));
  /** What <code>, <pre> or <kbd> shows — written as text or as a string — is a command, a key or an identifier: it
   *  stays as written. (An attribute of such an element is not what it shows.) */
  const inCode = (node: ts.Node): boolean => {
    for (let p: ts.Node | undefined = node.parent; p; p = p.parent) {
      if (ts.isJsxAttribute(p)) return false;
      if (ts.isJsxElement(p) || ts.isJsxFragment(p)) return isCodeElement(p);
    }
    return false;
  };
  /** Prose split over an element's children — `{n} server{s} found`, `Click <b>Save</b> now`: two ordinary words
   *  in the element's own text, none of its pieces a sentence by itself (that piece is reported on its own). */
  const split = (el: ts.JsxElement | ts.JsxFragment): string | null => {
    const texts = el.children.filter(ts.isJsxText);
    if (texts.length === el.children.length || isCodeElement(el) || texts.some((c) => isSentence(c.text))) return null;
    const own = el.children.map((c) => (ts.isJsxText(c) ? c.text : " {} ")).join("");
    return (own.match(ORDINARY) ?? []).length >= 2 ? own : null;
  };
  const visit = (node: ts.Node) => {
    if (ts.isJsxText(node)) { if (isSentence(node.text) && !inCode(node)) at(node, node.text); }
    else if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) { if (isSentence(node.text) && inTextPosition(node) && !inCode(node)) at(node, node.text); }
    else if (ts.isTemplateExpression(node)) { const text = flat(node); if (isSentence(text) && inTextPosition(node) && !inCode(node)) at(node, text); }
    else if (ts.isJsxElement(node) || ts.isJsxFragment(node)) { const own = split(node); if (own !== null) at(node, own); }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return hits;
}

describe("the scanner", () => {
  const scan = (code: string) => bareEnglish("x.tsx", code).map((h) => h.replace(/^x\.tsx:\d+ /, ""));
  it("sees a sentence in JSX text, in a text attribute and in a string where text goes", () => {
    expect(scan(`const a = <p>Scan Focus</p>;`)).toEqual(["Scan Focus"]);
    expect(scan(`const a = <X label="Auto RCA" />;`)).toEqual(["Auto RCA"]);
    expect(scan(`const a = <p>{ok ? "All categories" : name}</p>;`)).toEqual(["All categories"]);
    expect(scan(`const a = <X title={busy ? "Reset to tier default" : undefined} />;`)).toEqual(["Reset to tier default"]);
  });
  it("reads a string with a variable in it, and an object's text properties", () => {
    expect(scan("const a = <p>{`Dismiss Selected (${n})`}</p>;")).toEqual(["Dismiss Selected ({})"]);
    expect(scan(`const tabs = [{ key: "review", label: "Review Queue" }];`)).toEqual(["Review Queue"]);
    expect(scan(`const meta = { FullScan: { label: busy ? "Full Scan" : name, desc: "Scan all cloud resources." } };`))
      .toEqual(["Full Scan", "Scan all cloud resources."]);
    expect(scan("const r = { valid: false, error: `Servers missing a command: ${names}` };")).toEqual(["Servers missing a command: {}"]);
  });
  it("reads a sentence however its words are joined or chosen", () => {
    expect(scan(`const a = <p>{name || "No name yet"}</p>;`)).toEqual(["No name yet"]);
    expect(scan(`const a = <p>{(busy ? "Still working" : "All done")}</p>;`)).toEqual(["Still working", "All done"]);
    expect(scan(`const a = <p>Expected a JSON object</p>;`)).toEqual(["Expected a JSON object"]);   // a one-letter word, then an acronym
    expect(scan(`const a = <p>IAM roles</p>;`)).toEqual(["IAM roles"]);                               // an acronym first
    expect(scan("const a = <p>{`${ok ? \"All done\" : \"\"}!`}</p>;")).toEqual(["All done"]);             // a string chosen inside another
  });
  it("reads prose that is split over an element's children", () => {
    expect(scan(`const a = <span>{n} server{n > 1 ? "s" : ""} found</span>;`)).toEqual(["{} server {} found"]);
    expect(scan(`const a = <p>Click <b>Save</b> now</p>;`)).toEqual(["Click {} now"]);
    expect(scan(`const a = <p>Two words here, then {n}</p>;`)).toEqual(["Two words here, then"]);    // said once, by its own text
    expect(scan(`const a = <p>{name} Agent</p>;`)).toEqual([]);                                       // one word
    expect(scan(`const a = <p>v{version} · {count}</p>;`)).toEqual([]);
  });
  it("leaves words that come from the locale files, class names, identifiers and single words alone", () => {
    expect(scan(`const a = <p className="text-sm font-medium">{t("settings.title")}</p>;`)).toEqual([]);
    expect(scan(`const a = <p>{t("x").replace("{n}", "two words")}</p>;`)).toEqual([]);
    expect(scan(`const a = <code>OPENAI_API_KEY</code>;`)).toEqual([]);
    expect(scan(`const a = <b>Agent</b>;`)).toEqual([]);
    expect(scan(`const a = <p className={on ? "bg-card text-foreground" : "bg-muted text-muted"}>x</p>;`)).toEqual([]);
    expect(scan(`const a = <p>L0 / L1</p>;`)).toEqual([]);
    expect(scan(`const a = <p><code className="font-mono">aiops service restart</code></p>;`)).toEqual([]);   // a command is not prose
    expect(scan(`const tone = { draft: "bg-secondary text-muted-foreground", services: "IAM Roles, KMS" };`)).toEqual([]);   // a class list, a list of product names
    expect(scan("const s = { border: `1px solid ${c}` };")).toEqual([]);
    expect(scan(`const a = <p>{"L0 / L1"}</p>;`)).toEqual([]);
    expect(scan("const a = <p>{`${done} / ${total}`}</p>;")).toEqual([]);
    expect(scan(`const a = <kbd>{mac ? "Cmd K" : "Ctrl K"}</kbd>;`)).toEqual([]);                     // a key, written as a string
    expect(scan(`const a = <code>aiops users create {name}</code>;`)).toEqual([]);                   // a command with a variable in it
    expect(scan(`const a = <code title="Copy this command">ls</code>;`)).toEqual(["Copy this command"]);   // … its tooltip is prose
    expect(scan("const a = <code>{`aiops users create ${name}`}</code>;")).toEqual([]);
    expect(scan(`const a = <code>kubectl {verb} pods</code>;`)).toEqual([]);
    expect(scan(`const a = <p>Agent: metrics</p>;`)).toEqual([]);                                     // one piece of text: two words in a row, or nothing
  });
});

describe("no English sentence is written straight into a classic page", () => {
  it("there are pages to check", () => {
    expect(CHECKED.length).toBeGreaterThan(100);
    expect(CHECKED).toContain("pages/Settings.tsx");
  });
  it.each(CHECKED)("%s", (file) => {
    expect(bareEnglish(file, readFileSync(join(src, file), "utf8"))).toEqual([]);
  });
});
