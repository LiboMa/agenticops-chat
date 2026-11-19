import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

/** The house rule (2026-07-04): every dialog closes on Escape. A component of the classic interface that draws its
 *  own full-screen overlay (`fixed inset-0`) must close on it — through a Radix dialog (`Dialog.*`, `ModalFrame`),
 *  `useCloseOnEscape`, or a key handler of its own. MVP-2.9.0 N25 found 13 of 28 that did not.
 *
 *  Read from the source, by its shape: a component is the text from its `function Name(` line to the next such
 *  line; an overlay line within two lines of another is that overlay's backdrop, not a second overlay. */
const src = resolve(__dirname, "..");

function files(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) { if (name !== "__tests__" && name !== "newui") files(path, out); }
    else if (name.endsWith(".tsx")) out.push(path.slice(src.length + 1));
  }
  return out;
}
const WITH_OVERLAY = files(src).sort().filter((file) => readFileSync(join(src, file), "utf8").includes("fixed inset-0"));

const COMPONENT = /^(?:export default |export )?function ([A-Z]\w*)\(/;
const CLOSES = /Dialog\.(Root|Overlay|Content)|<ModalFrame|useCloseOnEscape\(|"Escape"/;

export function overlaysWithoutEscape(file: string, code: string): string[] {
  const lines = code.split("\n");
  const starts = lines.flatMap((line, at) => { const m = COMPONENT.exec(line); return m ? [{ at, name: m[1] }] : []; });
  const out: string[] = [];
  lines.forEach((line, at) => {
    if (!line.includes("fixed inset-0")) return;
    if (lines.slice(Math.max(0, at - 2), at).some((above) => above.includes("fixed inset-0"))) return;      // its backdrop
    const owner = [...starts].reverse().find((s) => s.at <= at);
    const end = starts.find((s) => s.at > at)?.at ?? lines.length;
    if (!CLOSES.test(lines.slice(owner?.at ?? 0, end).join("\n"))) out.push(file + ":" + (at + 1) + " " + (owner?.name ?? "?"));
  });
  return out;
}

describe("the scan", () => {
  const overlay = '    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">';
  const component = (name: string, ...body: string[]) => ["function " + name + "({ onClose }: Props) {", ...body, "  return (", overlay, "    </div>", "  );", "}"];
  const scan = (...lines: string[]) => overlaysWithoutEscape("x.tsx", lines.join("\n")).map((hit) => hit.replace(/^x\.tsx:\d+ /, ""));

  it("names a component whose overlay nothing closes on Escape", () => {
    expect(scan(...component("FormModal"))).toEqual(["FormModal"]);
    expect(scan("export default function Page() {", "  return (", overlay, "  );", "}")).toEqual(["Page"]);
  });
  it("is content with the shared hook, a Radix dialog, the modal frame, or a key handler of its own", () => {
    expect(scan(...component("A", "  useCloseOnEscape(onClose);"))).toEqual([]);
    expect(scan(...component("B", '  useEffect(() => { const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); }; }, []);'))).toEqual([]);
    expect(scan("function C() {", "  return (", '    <Dialog.Overlay className="fixed inset-0 z-50 bg-black/30" />', "  );", "}")).toEqual([]);
    expect(scan("function D() {", "  return <ModalFrame>", overlay, "  </ModalFrame>;", "}")).toEqual([]);
  });
  it("one component's handler does not cover the next component in the file", () => {
    expect(scan(...component("First", "  useCloseOnEscape(onClose);"), ...component("Second"))).toEqual(["Second"]);
    expect(scan(...component("First"), ...component("Second", "  useCloseOnEscape(onClose);"))).toEqual(["First"]);
  });
  it("a backdrop inside an overlay is not a second overlay", () => {
    expect(scan("function Panel() {", "  return (", '    <div className="fixed inset-0 z-50 flex">', '      <div className="fixed inset-0 bg-black/30" onClick={onClose} />', "    </div>", "  );", "}")).toEqual(["Panel"]);
  });
});

describe("every hand-drawn overlay of the classic interface closes on Escape", () => {
  it("there are overlays to check", () => {
    expect(WITH_OVERLAY.length).toBeGreaterThan(15);
    expect(WITH_OVERLAY).toContain("pages/Settings.tsx");
  });
  it.each(WITH_OVERLAY)("%s", (file) => {
    expect(overlaysWithoutEscape(file, readFileSync(join(src, file), "utf8"))).toEqual([]);
  });
});
