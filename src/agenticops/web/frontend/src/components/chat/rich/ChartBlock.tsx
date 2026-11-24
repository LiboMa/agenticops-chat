import { useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { useLocale } from "@/i18n/LocaleContext";
import { useTheme } from "@/hooks/useTheme";
import type { ChartSpec } from "@/lib/richBlocks";
import { ZoomDialog } from "./ZoomDialog";

// The dataviz reference categorical palette, in its fixed order, one step per mode (validated 2026-11-07 with
// validate_palette.js: light and dark pass; three light slots sit under 3:1 on white, so every chart ships with a
// tooltip, a legend for ≥ 2 series and a data table in the enlarged view — the relief rule).
const SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
const SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];

const INK = "hsl(var(--muted-foreground))";
const GRID = "hsl(var(--border))";
const SURFACE = "hsl(var(--card))";

function rows(spec: ChartSpec) {
  return spec.x.map((x, i) => {
    const row: Record<string, string | number | null> = { x: String(x) };
    spec.series.forEach((s, k) => { row[`s${k}`] = s.data[i]; });
    return row;
  });
}

function Plot({ spec, height }: { spec: ChartSpec; height: number }) {
  const { theme } = useTheme();
  const palette = theme === "dark" ? SERIES_DARK : SERIES_LIGHT;
  const color = (k: number) => palette[k % palette.length];
  const data = rows(spec);
  const unit = spec.unit ? ` ${spec.unit}` : "";
  const fmt = (v: unknown) => (typeof v === "number" ? `${v.toLocaleString()}${unit}` : "—");
  const tooltip = (
    <Tooltip formatter={(v) => fmt(v)}
             contentStyle={{ background: SURFACE, border: `1px solid ${GRID}`, borderRadius: 8, fontSize: 12 }}
             labelStyle={{ color: "hsl(var(--foreground))" }} itemStyle={{ color: "hsl(var(--foreground))" }} />
  );
  // legend text wears the text colour, never the series colour (the coloured dot carries identity)
  const legendText = (v: unknown) => <span style={{ color: "hsl(var(--foreground))" }}>{String(v)}</span>;
  const legend = spec.series.length > 1
    ? <Legend wrapperStyle={{ fontSize: 12 }} iconType="circle" formatter={legendText} /> : null;
  const axes = (
    <>
      <CartesianGrid vertical={false} stroke={GRID} strokeDasharray="3 3" />
      <XAxis dataKey="x" tick={{ fill: INK, fontSize: 11 }} tickLine={false} axisLine={{ stroke: GRID }} />
      <YAxis tick={{ fill: INK, fontSize: 11 }} tickLine={false} axisLine={false} width={44} />
    </>
  );

  let chart;
  if (spec.type === "pie") {
    const slices = spec.x.map((x, i) => ({ name: String(x), value: spec.series[0].data[i] ?? 0 }));
    chart = (
      <PieChart>
        <Pie data={slices} dataKey="value" nameKey="name" innerRadius="55%" outerRadius="80%" paddingAngle={1}
             stroke={SURFACE} strokeWidth={2} isAnimationActive={false}>
          {slices.map((_, i) => <Cell key={i} fill={color(i)} />)}
        </Pie>
        {tooltip}
        <Legend wrapperStyle={{ fontSize: 12 }} iconType="circle" formatter={legendText} />
      </PieChart>
    );
  } else if (spec.type === "bar") {
    chart = (
      <BarChart data={data} barGap={2} barCategoryGap="20%">
        {axes}{tooltip}{legend}
        {spec.series.map((s, k) => (
          <Bar key={k} dataKey={`s${k}`} name={s.name} fill={color(k)} radius={[4, 4, 0, 0]} maxBarSize={36}
               isAnimationActive={false} />
        ))}
      </BarChart>
    );
  } else if (spec.type === "area") {
    chart = (
      <AreaChart data={data}>
        {axes}{tooltip}{legend}
        {spec.series.map((s, k) => (
          <Area key={k} dataKey={`s${k}`} name={s.name} type="monotone" stroke={color(k)} fill={color(k)}
                fillOpacity={0.15} strokeWidth={2} connectNulls={false} isAnimationActive={false} />
        ))}
      </AreaChart>
    );
  } else {
    chart = (
      <LineChart data={data}>
        {axes}{tooltip}{legend}
        {spec.series.map((s, k) => (
          <Line key={k} dataKey={`s${k}`} name={s.name} type="monotone" stroke={color(k)} strokeWidth={2}
                dot={{ r: 4, strokeWidth: 2, stroke: SURFACE }} activeDot={{ r: 5 }} connectNulls={false}
                isAnimationActive={false} />
        ))}
      </LineChart>
    );
  }
  return <ResponsiveContainer width="100%" height={height}>{chart}</ResponsiveContainer>;
}

function DataTable({ spec }: { spec: ChartSpec }) {
  const { t } = useLocale();
  return (
    <div className="mt-4 overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <caption className="px-3 py-2 text-left text-xs text-muted-foreground">{t("chat.rich.data")}</caption>
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th className="px-3 py-2 font-medium" />
            {spec.series.map((s, k) => <th key={k} className="px-3 py-2 font-medium">{s.name}</th>)}
          </tr>
        </thead>
        <tbody>
          {spec.x.map((x, i) => (
            <tr key={i} className="border-b border-border last:border-0">
              <td className="px-3 py-1.5 text-foreground">{String(x)}</td>
              {spec.series.map((s, k) => (
                <td key={k} className="px-3 py-1.5 tabular-nums text-foreground">
                  {s.data[i] === null ? "—" : `${s.data[i]!.toLocaleString()}${spec.unit ? ` ${spec.unit}` : ""}`}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A chart the agent wrote as a ```chart block — or, when its data does not validate, the block as code. */
export function ChartBlock({ spec, source }: { spec: ChartSpec | null; source: string }) {
  const { t } = useLocale();
  const [zoom, setZoom] = useState(false);
  if (!spec) {
    return (
      <div className="my-3">
        <pre className="md-pre"><code>{source}</code></pre>
        <p className="-mt-2 mb-3 text-xs text-muted-foreground">{t("chat.rich.chartInvalid")}</p>
      </div>
    );
  }
  const title = spec.title || t("chat.rich.chart");
  return (
    <figure className="my-3 rounded-xl border border-border bg-card px-3 pb-2 pt-3">
      <figcaption className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
        <span className="min-w-0 flex-1 truncate font-medium text-foreground">{title}</span>
        <button type="button" onClick={() => setZoom(true)} className="rounded px-1.5 py-0.5 hover:bg-muted hover:text-foreground"
                title={t("chat.rich.enlarge")} aria-label={t("chat.rich.enlarge")}>⤢</button>
      </figcaption>
      <div className="h-[260px] w-full"><Plot spec={spec} height={260} /></div>
      {zoom && (
        <ZoomDialog title={title} onClose={() => setZoom(false)} zoomable={false}>
          <Plot spec={spec} height={420} />
          <DataTable spec={spec} />
        </ZoomDialog>
      )}
    </figure>
  );
}
