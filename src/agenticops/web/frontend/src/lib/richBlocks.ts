/**
 * Rich blocks in a chat answer (2026-11-07): the Web chat agent writes statistics as a ```chart block of JSON and
 * flows as a ```mermaid block; everything else stays markdown. Model output is DATA here — a chart spec is validated
 * and only ever drawn, mermaid source is stripped of its init directives before a strict render.
 */

export interface ChartSpec {
  type: "bar" | "line" | "area" | "pie";
  title?: string;
  unit?: string;
  x: (string | number)[];
  series: { name: string; data: (number | null)[] }[];
}

export type RichSegment =
  | { kind: "md"; text: string }
  | { kind: "chart"; spec: ChartSpec | null; source: string }
  | { kind: "mermaid"; source: string };

export const CHART_LIMITS = { maxSeries: 12, maxPoints: 500 };

const TYPES = new Set(["bar", "line", "area", "pie"]);

/**
 * The answer as markdown / chart / mermaid segments. Fences follow renderMarkdown's rule (a line starting with ```
 * toggles). A chart or mermaid fence becomes its own segment only once it is CLOSED — while the answer streams, a
 * half-written block stays markdown (a code block), so it never flashes as a parse error. Other fences stay inside
 * the markdown around them.
 */
export function splitRichBlocks(md: string): RichSegment[] {
  const lines = md.split("\n");
  const out: RichSegment[] = [];
  let mdBuf: string[] = [];
  const flushMd = () => {
    if (mdBuf.length === 0) return;
    const text = mdBuf.join("\n");
    const prev = out[out.length - 1];
    if (prev?.kind === "md") prev.text += "\n" + text;
    else out.push({ kind: "md", text });
    mdBuf = [];
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const t = line.trimStart();
    if (!t.startsWith("```")) {
      mdBuf.push(line);
      continue;
    }
    const lang = t.slice(3).trim().toLowerCase();
    // find the closing fence of the block this line opens
    let close = -1;
    for (let j = i + 1; j < lines.length; j++) {
      if (lines[j].trimStart().startsWith("```")) { close = j; break; }
    }
    if ((lang === "chart" || lang === "mermaid") && close !== -1) {
      flushMd();
      const source = lines.slice(i + 1, close).join("\n").trim();
      out.push(lang === "chart" ? { kind: "chart", spec: parseChartSpec(source), source } : { kind: "mermaid", source });
      i = close;
      continue;
    }
    // any other fence (or an unclosed rich one): it and its body stay markdown
    const end = close === -1 ? lines.length - 1 : close;
    mdBuf.push(...lines.slice(i, end + 1));
    i = end;
  }
  flushMd();
  return out;
}

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** A chart spec the model wrote, or null when any rule is broken (the block then shows as code with a notice). */
export function parseChartSpec(json: string): ChartSpec | null {
  let raw: unknown;
  try {
    raw = JSON.parse(json);
  } catch {
    return null;
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.type !== "string" || !TYPES.has(r.type)) return null;
  if (!Array.isArray(r.x) || r.x.length === 0 || r.x.length > CHART_LIMITS.maxPoints) return null;
  if (!r.x.every((v) => typeof v === "string" || finite(v))) return null;
  if (!Array.isArray(r.series) || r.series.length === 0 || r.series.length > CHART_LIMITS.maxSeries) return null;
  const series: ChartSpec["series"] = [];
  for (const s of r.series) {
    if (!s || typeof s !== "object") return null;
    const { name, data } = s as Record<string, unknown>;
    if (typeof name !== "string" || !Array.isArray(data) || data.length !== r.x.length) return null;
    if (!data.every((v) => v === null || finite(v))) return null;
    series.push({ name, data: data as (number | null)[] });
  }
  if (r.type === "pie" && (series.length !== 1 || series[0].data.some((v) => v !== null && v < 0))) return null;
  return {
    type: r.type as ChartSpec["type"],
    ...(typeof r.title === "string" ? { title: r.title } : {}),
    ...(typeof r.unit === "string" ? { unit: r.unit } : {}),
    x: r.x as (string | number)[],
    series,
  };
}

/** Mermaid source the renderer may draw: no `%%{ … }%%` init directives (they can reconfigure it), and nothing that
 *  makes the browser fetch an outside image while it draws — an `<img>` tag in a label (raw or escaped) or an image
 *  shape `A@{ img: "…" }` (an answer never loads outside addresses: it would leak the reader's IP). Trimmed. */
export function mermaidSource(src: string): string {
  return src
    .replace(/%%\{[\s\S]*?\}%%/g, "")
    .replace(/<img\b[^>]*>/gi, "")
    .replace(/&lt;img\b[\s\S]*?&gt;/gi, "")
    .replace(/@\{[^}]*\bimg\s*:[^}]*\}/gi, "")
    .trim();
}
