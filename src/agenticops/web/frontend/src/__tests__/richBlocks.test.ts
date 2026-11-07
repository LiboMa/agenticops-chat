import { describe, it, expect } from "vitest";
import { splitRichBlocks, parseChartSpec, mermaidSource } from "@/lib/richBlocks";

const CH = '{"type":"bar","x":["a","b"],"series":[{"name":"n","data":[1,2]}]}';
const F = "```";

describe("splitRichBlocks", () => {
  it("plain markdown is one segment", () =>
    expect(splitRichBlocks("# Hi\ntext")).toEqual([{ kind: "md", text: "# Hi\ntext" }]));
  it("md, chart, md", () => {
    const s = splitRichBlocks(`before\n${F}chart\n${CH}\n${F}\nafter`);
    expect(s.map((x) => x.kind)).toEqual(["md", "chart", "md"]);
    expect((s[1] as any).spec.series[0].data).toEqual([1, 2]);
  });
  it("bad chart JSON keeps its source with spec null", () =>
    expect(splitRichBlocks(`${F}chart\n{nope\n${F}`)).toEqual([{ kind: "chart", spec: null, source: "{nope" }]));
  it("mermaid block", () =>
    expect(splitRichBlocks(`${F}mermaid\nflowchart LR\nA-->B\n${F}`))
      .toEqual([{ kind: "mermaid", source: "flowchart LR\nA-->B" }]));
  it("an unclosed chart fence (still streaming) stays markdown, never a parse error", () =>
    expect(splitRichBlocks(`x\n${F}chart\n{"type":"ba`)).toEqual([{ kind: "md", text: `x\n${F}chart\n{"type":"ba` }]));
  it("fence language is case-insensitive", () =>
    expect(splitRichBlocks(`${F}CHART\n${CH}\n${F}`)[0].kind).toBe("chart"));
  it("other fences pass through as markdown", () =>
    expect(splitRichBlocks(`${F}bash\nls\n${F}`)).toEqual([{ kind: "md", text: `${F}bash\nls\n${F}` }]));
});

describe("parseChartSpec", () => {
  it("validates", () => {
    expect(parseChartSpec(CH)?.type).toBe("bar");
    expect(parseChartSpec('{"type":"radar","x":[1],"series":[{"name":"a","data":[1]}]}')).toBeNull();
    expect(parseChartSpec('{"type":"line","x":[1,2],"series":[{"name":"a","data":[1]}]}')).toBeNull();
    expect(parseChartSpec('{"type":"pie","x":["a"],"series":[{"name":"a","data":[1]},{"name":"b","data":[2]}]}')).toBeNull();
    expect(parseChartSpec('{"type":"pie","x":["a"],"series":[{"name":"a","data":[-1]}]}')).toBeNull();
    expect(parseChartSpec('{"type":"bar","x":[],"series":[]}')).toBeNull();
    expect(parseChartSpec('{"type":"line","x":[1,2],"series":[{"name":"a","data":[1,null]}]}')?.series[0].data)
      .toEqual([1, null]);
  });
  it("too many series or points is refused", () => {
    const x = Array.from({ length: 501 }, (_, i) => i);
    expect(parseChartSpec(JSON.stringify({ type: "line", x, series: [{ name: "a", data: x }] }))).toBeNull();
    const series = Array.from({ length: 13 }, (_, i) => ({ name: `s${i}`, data: [1] }));
    expect(parseChartSpec(JSON.stringify({ type: "bar", x: ["a"], series }))).toBeNull();
  });
});

describe("mermaidSource", () => {
  it("strips init directives", () => {
    expect(mermaidSource('%%{init: {"securityLevel":"loose"}}%%\nflowchart LR\nA-->B')).toBe("flowchart LR\nA-->B");
    expect(mermaidSource('flowchart LR\n%%{init:\n {"theme":"x"}\n}%%\nA-->B')).toBe("flowchart LR\n\nA-->B");
  });
});
