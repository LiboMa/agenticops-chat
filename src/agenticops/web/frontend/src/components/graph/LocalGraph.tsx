/**
 * The local graph (MVP-2.6.1 spec §3.E.3): the neighbourhood of one issue, resource or change request from
 * GET /api/graph/focus — laid out once with d3-force, drawn as SVG, and listed underneath for reading without
 * the drawing. The blast-radius numbers in the header are the API's; nothing here counts them.
 */
import { useId, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  forceSimulation, forceLink, forceManyBody, forceCollide, forceX, forceY, type SimulationNodeDatum,
} from "d3-force";
import type { GalaxyHealth, LocationPathEdge } from "@/api/types";
import { Spinner } from "@/components/ui/Spinner";
import { useGraphFocus } from "@/hooks/useGraphFocus";
import { useLocale } from "@/i18n/LocaleContext";
import { cn } from "@/lib/cn";
import { buildLocalGraph, type FocusSubject, type LgLink, type LgNode, type LocalGraphModel } from "@/lib/localGraph";

// Galaxy's NEBULA palette, so a resource reads the same colour on both pages
const HEALTH_FILL: Record<GalaxyHealth, string> = {
  unknown: "#6b7280", notice: "#8fa6c4", warning: "#f5b53d", critical: "#f0555a",
};
const RULE_EDGE = "#64748b";
const LLM_EDGE = "#b18bf0";
const PATH_EDGE = "#38bdf8";
const RELATED_EDGE = "#8fa6c4";
const DASH: Record<string, string | undefined> = { llm: "5 4", merged: "6 3", candidate: "1 4" };

interface Pos { x: number; y: number }
type SimNode = SimulationNodeDatum & { id: string };

/** Positions for every node: anchors pinned at the centre (a small ring when there are several), 300 ticks. */
function layout(model: LocalGraphModel): Map<string, Pos> {
  const sim: SimNode[] = model.nodes.map((n) => ({ id: n.id }));
  const byId = new Map(sim.map((n) => [n.id, n]));
  model.anchorIds.forEach((id, i, all) => {
    const n = byId.get(id)!;
    const a = (2 * Math.PI * i) / all.length;
    const r = all.length > 1 ? 50 : 0;
    n.fx = r * Math.cos(a);
    n.fy = r * Math.sin(a);
  });
  const links = model.links.map((l) => ({ source: l.source, target: l.target }));
  forceSimulation(sim)
    .force("link", forceLink<SimNode, { source: string; target: string }>(links).id((d) => d.id).distance(70))
    .force("charge", forceManyBody().strength(-220))
    .force("collide", forceCollide(22))
    .force("x", forceX(0).strength(0.04))
    .force("y", forceY(0).strength(0.04))
    .stop()
    .tick(300);
  return new Map(sim.map((n) => [n.id, { x: n.fx ?? n.x ?? 0, y: n.fy ?? n.y ?? 0 }]));
}

function viewBox(pos: Map<string, Pos>): string {
  const xs = [...pos.values()].map((p) => p.x);
  const ys = [...pos.values()].map((p) => p.y);
  const pad = 40;
  const [x0, x1] = [Math.min(...xs) - pad, Math.max(...xs) + pad];
  const [y0, y1] = [Math.min(...ys) - pad, Math.max(...ys) + pad];
  return `${x0} ${y0} ${Math.max(x1 - x0, 160)} ${Math.max(y1 - y0, 120)}`;
}

// Merged and candidate lines bend a little, so one never hides a structural edge between the same two nodes
function linkPath(a: Pos, b: Pos, bend: boolean): string {
  if (!bend) return `M${a.x},${a.y} L${b.x},${b.y}`;
  const [mx, my] = [(a.x + b.x) / 2, (a.y + b.y) / 2];
  const [dx, dy] = [b.x - a.x, b.y - a.y];
  return `M${a.x},${a.y} Q${mx - dy * 0.2},${my + dx * 0.2} ${b.x},${b.y}`;
}

function linkStyle(l: LgLink): { stroke: string; dash?: string; width: number } {
  if (l.onPath) return { stroke: PATH_EDGE, width: 3 };
  if (l.kind !== "structural") return { stroke: RELATED_EDGE, dash: DASH[l.kind], width: 1.5 };
  return l.llm ? { stroke: LLM_EDGE, dash: DASH.llm, width: 1.5 } : { stroke: RULE_EDGE, width: 1.5 };
}

function short(s: string, n = 18): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

function onActivate(fn: () => void) {
  return {
    onClick: fn,
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        fn();
      }
    },
  };
}

type Selected = { kind: "node" | "link"; id: string } | null;

interface LocalGraphProps {
  subject: FocusSubject;
  path?: LocationPathEdge[]; // the RCA causal chain to highlight (location.path)
  note?: string; // e.g. "for reference only" while RBAC is in shadow mode
  height?: number;
}

export function LocalGraph({ subject, path, note, height = 360 }: LocalGraphProps) {
  const { t } = useLocale();
  const uid = useId().replace(/:/g, "");
  const [showLlm, setShowLlm] = useState(false);
  const [sel, setSel] = useState<Selected>(null);
  const { data: focus, isLoading, isError, isPlaceholderData } = useGraphFocus(subject, showLlm);

  const model = useMemo(() => (focus ? buildLocalGraph(focus, { showLlm, path }) : null), [focus, showLlm, path]);
  const pos = useMemo(() => (model && model.nodes.length ? layout(model) : null), [model]);

  if (isLoading) return <Spinner label={t("common.loading")} />;
  if (isError || !focus || !model) return <p className="text-sm text-destructive">{t("common.error")}</p>;

  const plus = focus.blast.truncated ? "+" : "";
  const node = sel?.kind === "node" ? model.nodes.find((n) => n.id === sel.id) : undefined;
  const link = sel?.kind === "link" ? model.links.find((l) => l.id === sel.id) : undefined;
  const nodeName = (id: string) => model.nodes.find((n) => n.id === id)?.label ?? id;

  const header = (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <span title={focus.blast.truncated ? t("graph.blast.truncatedHint") : undefined}>
        {t("graph.blast.structural")} <b className="text-foreground">{focus.blast.structural}{plus}</b>
        {" · "}{t("graph.blast.potential")} <b className="text-foreground">{focus.blast.potential}{plus}</b>
        {" · "}{t("graph.blast.observed")} <b className="text-foreground">{focus.blast.observed}</b>
      </span>
      {note && <span className="rounded bg-muted px-1.5 py-0.5">{note}</span>}
      <label className="ml-auto flex items-center gap-1.5">
        <input type="checkbox" checked={showLlm} onChange={(e) => setShowLlm(e.target.checked)} />
        {t("graph.showLlm")}
      </label>
      {model.hiddenLlm > 0 && <span>{t("graph.hiddenLlm").replace("{n}", String(model.hiddenLlm))}</span>}
    </div>
  );

  if (focus.build_id == null || !pos) {
    const a = focus.anchor;
    const why = focus.build_id == null ? t("graph.noBuild")
      : a.status === "anchored" ? t("graph.empty")
      : t(`anchor.${a.status}`) + (a.status === "ambiguous"
        ? ` — ${t("anchor.candidatesN").replace("{n}", String(a.candidates.length))}` : "");
    return (
      <div className="space-y-2">
        {header}
        <p className="rounded border border-dashed p-6 text-center text-sm text-muted-foreground">{why}</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {header}
      {model.truncated.length > 0 && (
        <p className="text-xs text-amber-500">
          {t("graph.truncatedPrefix")} {model.truncated.map((r) => t(`graph.truncated.${r}`)).join(" · ")}
        </p>
      )}

      <svg viewBox={viewBox(pos)} className={cn("w-full rounded border bg-muted/20", isPlaceholderData && "opacity-60")}
           style={{ height }} role="group" aria-label={t("graph.title")}>
        <defs>
          {[["arrow", RULE_EDGE], ["arrow-llm", LLM_EDGE], ["arrow-path", PATH_EDGE]].map(([id, fill]) => (
            <marker key={id} id={`${uid}-${id}`} viewBox="0 0 10 10" refX="20" refY="5" markerWidth="6"
                    markerHeight="6" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill={fill} />
            </marker>
          ))}
        </defs>

        {model.links.map((l) => {
          const [a, b] = [pos.get(l.source)!, pos.get(l.target)!];
          const st = linkStyle(l);
          const picked = sel?.kind === "link" && sel.id === l.id; // a node and its link can share an id
          const d = linkPath(a, b, l.kind !== "structural");
          const arrow = l.kind !== "structural" ? undefined
            : `url(#${uid}-${l.onPath ? "arrow-path" : l.llm ? "arrow-llm" : "arrow"})`;
          const label = `${nodeName(l.source)} → ${nodeName(l.target)} ${l.relationType ?? t(`graph.legend.${l.kind}`)}`;
          return (
            <g key={l.id} role="button" tabIndex={0} aria-label={label} className="cursor-pointer outline-none"
               {...onActivate(() => setSel({ kind: "link", id: l.id }))}>
              <path d={d} fill="none" stroke={st.stroke} strokeWidth={picked ? st.width + 1.5 : st.width}
                    strokeDasharray={st.dash} strokeLinecap="round" markerEnd={arrow} />
              <path d={d} fill="none" stroke="transparent" strokeWidth={10} />
            </g>
          );
        })}

        {model.nodes.map((n) => {
          const p = pos.get(n.id)!;
          const r = n.anchor ? 12 : 8;
          const outside = n.kind !== "resource";
          const picked = sel?.kind === "node" && sel.id === n.id;
          return (
            <g key={n.id} transform={`translate(${p.x},${p.y})`} role="button" tabIndex={0}
               aria-label={`${n.label} ${t(`galaxy.health.${n.health}`)}`} className="cursor-pointer outline-none"
               opacity={n.absent ? 0.45 : 1} {...onActivate(() => setSel({ kind: "node", id: n.id }))}>
              {n.kind === "issue"
                ? <rect x={-r} y={-r} width={2 * r} height={2 * r} rx={3} fill={HEALTH_FILL[n.health]} />
                : <circle r={r} fill={HEALTH_FILL[n.health]} />}
              <circle r={r + 3} fill="none"
                      stroke={n.onPath ? PATH_EDGE : picked || n.anchor ? "currentColor" : "transparent"}
                      strokeWidth={n.onPath ? 2.5 : 1.5} strokeDasharray={outside || n.absent ? "3 2" : undefined}
                      className="text-foreground" />
              {n.issueIds.length > 0 && (
                <g transform={`translate(${r},${-r})`}>
                  <circle r={6} fill="#f0555a" />
                  <text textAnchor="middle" dy="3" fontSize="8" fill="#fff">{n.issueIds.length}</text>
                </g>
              )}
              <text y={r + 13} textAnchor="middle" fontSize="10" className="fill-muted-foreground">
                {short(n.label)}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        {(Object.keys(HEALTH_FILL) as GalaxyHealth[]).map((h) => (
          <span key={h} className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: HEALTH_FILL[h] }} />
            {t(`galaxy.health.${h}`)}
          </span>
        ))}
        {([["rule", RULE_EDGE, undefined], ["llm", LLM_EDGE, DASH.llm], ["path", PATH_EDGE, undefined],
           ["merged", RELATED_EDGE, DASH.merged], ["candidate", RELATED_EDGE, DASH.candidate]] as const)
          .map(([k, stroke, dash]) => (
            <span key={k} className="flex items-center gap-1">
              <svg width="18" height="6" aria-hidden="true">
                <line x1="0" y1="3" x2="18" y2="3" stroke={stroke} strokeWidth={k === "path" ? 3 : 1.5}
                      strokeDasharray={dash} strokeLinecap="round" />
              </svg>
              {t(`graph.legend.${k}`)}
            </span>
          ))}
      </div>

      {node && <NodeDetail node={node} />}
      {link && <LinkDetail link={link} from={nodeName(link.source)} to={nodeName(link.target)} />}

      <details className="text-xs">
        <summary className="cursor-pointer text-muted-foreground">{t("graph.listView")}</summary>
        <table className="mt-2 w-full">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th className="py-1 pr-2">{t("graph.col.resource")}</th><th className="pr-2">{t("graph.col.type")}</th>
              <th className="pr-2">{t("graph.col.hops")}</th><th className="pr-2">{t("graph.col.health")}</th>
              <th>{t("graph.col.issues")}</th>
            </tr>
          </thead>
          <tbody>
            {model.nodes.map((n) => (
              <tr key={n.id} className="border-t">
                <td className="py-1 pr-2">
                  {n.ref != null ? <Link to={`/app/resources/${n.ref}`} className="hover:underline">{n.label}</Link>
                    : n.label}
                  {n.anchor && <span className="ml-1 text-muted-foreground">({t("graph.anchor")})</span>}
                </td>
                <td className="pr-2">{n.type ?? t(`graph.kind.${n.kind}`)}</td>
                <td className="pr-2">{n.hops ?? "—"}</td>
                <td className="pr-2">{t(`galaxy.health.${n.health}`)}</td>
                <td><IssueLinks ids={n.issueIds} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-3 font-medium">{t("graph.relations")}</p>
        <ul className="mt-1 space-y-0.5">
          {model.links.filter((l) => l.kind === "structural").map((l) => (
            <li key={l.id}>
              {nodeName(l.source)} → {nodeName(l.target)} <code>{l.relationType}</code>
              <span className="text-muted-foreground"> ({l.provenance}{l.onPath ? ` · ${t("graph.legend.path")}` : ""})</span>
            </li>
          ))}
        </ul>
        {focus.related.merged.length > 0 && <p className="mt-3 font-medium">{t("graph.legend.merged")}</p>}
        <ul className="mt-1 space-y-0.5">
          {focus.related.merged.map((m) => <li key={m.resource_id}><MergedLine m={m} /></li>)}
        </ul>
        {focus.related.candidates.length > 0 && <p className="mt-3 font-medium">{t("graph.legend.candidate")}</p>}
        <ul className="mt-1 space-y-0.5">
          {focus.related.candidates.map((c) => <li key={c.issue_id}><CandidateLine c={c} /></li>)}
        </ul>
      </details>
    </div>
  );
}

function IssueLinks({ ids }: { ids: number[] }) {
  if (!ids.length) return <>—</>;
  return (
    <>
      {ids.map((id, i) => (
        <span key={id}>
          {i > 0 && ", "}
          <Link to={`/app/issues/${id}`} className="text-primary hover:underline">I#{id}</Link>
        </span>
      ))}
    </>
  );
}

function MergedLine({ m }: { m: LgNode["merged"][number] }) {
  const { t } = useLocale();
  return (
    <>
      {m.ref != null ? <Link to={`/app/resources/${m.ref}`} className="hover:underline">{m.name || m.resource_id}</Link>
        : <span>{m.resource_id}</span>}
      <span className="text-muted-foreground">
        {" "}{t("graph.signals").replace("{n}", String(m.signals))}
        {m.last_at ? ` · ${m.last_at}` : ""}{m.ref == null ? ` · ${t(`anchor.${m.anchor_status}`)}` : ""}
      </span>
    </>
  );
}

function CandidateLine({ c }: { c: LgNode["candidates"][number] }) {
  const { t } = useLocale();
  return (
    <>
      <Link to={`/app/issues/${c.issue_id}`} className="text-primary hover:underline">I#{c.issue_id}</Link>
      {" "}{c.title}
      <span className="text-muted-foreground">
        {" "}({c.severity} · {t("graph.hopsN").replace("{n}", String(c.hops))} · {c.signal_at})
      </span>
    </>
  );
}

function NodeDetail({ node: n }: { node: LgNode }) {
  const { t } = useLocale();
  return (
    <div className="rounded border p-3 text-xs space-y-1">
      <p className="font-medium text-foreground">
        {n.label} <span className="text-muted-foreground">{n.type ?? t(`graph.kind.${n.kind}`)}</span>
      </p>
      <p className="text-muted-foreground">
        {t(`galaxy.health.${n.health}`)}
        {n.hops != null && ` · ${t("graph.hopsN").replace("{n}", String(n.hops))}`}
        {n.absent && ` · ${t("galaxy.absent")}`}
      </p>
      {n.ref != null && (
        <Link to={`/app/resources/${n.ref}`} className="text-primary hover:underline">{t("galaxy.openResource")}</Link>
      )}
      {n.issueIds.length > 0 && <p>{t("galaxy.openIssues")}: <IssueLinks ids={n.issueIds} /></p>}
      {n.merged.map((m) => <p key={m.resource_id}>{t("graph.legend.merged")}: <MergedLine m={m} /></p>)}
      {n.candidates.map((c) => <p key={c.issue_id}>{t("graph.legend.candidate")}: <CandidateLine c={c} /></p>)}
    </div>
  );
}

function LinkDetail({ link: l, from, to }: { link: LgLink; from: string; to: string }) {
  const { t } = useLocale();
  return (
    <div className="rounded border p-3 text-xs space-y-1">
      <p className="font-medium text-foreground">
        {from} → {to} <code>{l.relationType ?? t(`graph.legend.${l.kind}`)}</code>
      </p>
      {l.kind === "structural" && (
        <>
          <p><span className="text-muted-foreground">{t("graph.provenance")}:</span> {l.provenance}</p>
          <p className="whitespace-pre-wrap break-words">
            <span className="text-muted-foreground">{t("graph.evidence")}:</span> {l.evidence || "—"}
          </p>
          <p><span className="text-muted-foreground">{t("graph.observedAt")}:</span> {l.observedAt ?? "—"}</p>
        </>
      )}
      {l.merged && <p><MergedLine m={l.merged} /></p>}
      {l.candidates?.map((c) => <p key={c.issue_id}><CandidateLine c={c} /></p>)}
    </div>
  );
}
