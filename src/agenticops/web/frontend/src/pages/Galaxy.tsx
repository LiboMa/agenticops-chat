import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import {
  forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide, forceX, forceY,
  type Simulation,
} from "d3-force";
import { select } from "d3-selection";
import { zoom as d3zoom, zoomIdentity, type ZoomBehavior } from "d3-zoom";
import { drag as d3drag } from "d3-drag";
import { useLocale } from "@/i18n/LocaleContext";
import { useGalaxyStatus, useGalaxyGraph, useGalaxyRebuild } from "@/hooks/useGalaxy";
import type { GalaxyGraphNode } from "@/api/types";
import { GalaxyNodePanel } from "@/components/galaxy/GalaxyNodePanel";

// ── palette (Nebula Violet — the single Galaxy theme, validated via dataviz) ──
interface Palette {
  surface: string; acct: string; group: string;
  healthy: string; warning: string; critical: string;
  ruleEdge: string; llmEdge: string; label: string;
}
const NEBULA: Palette = {
  // violet-black canvas, aqua cores, richer violet llm edge — fixed (no theme switch)
  surface: "#0b0b12", acct: "#5b8def", group: "#22c39a",
  healthy: "#6b7280", warning: "#f5b53d", critical: "#f0555a",
  ruleEdge: "rgba(140,140,170,0.18)", llmEdge: "#b18bf0", label: "#eae6f5",
};
function starColor(p: Palette, health?: string) {
  return health === "critical" ? p.critical : health === "warning" ? p.warning : p.healthy;
}

// simulation node/link types (d3 mutates x/y/vx/vy in place)
interface SimNode extends GalaxyGraphNode {
  x?: number; y?: number; vx?: number; vy?: number; fx?: number | null; fy?: number | null; r: number;
}
interface SimLink { source: SimNode | string; target: SimNode | string; r: string; p: "rule" | "llm"; ev?: string; c?: number; }

function hexA(hex: string, a: number): string {
  const c = hex.replace("#", "");
  const r = parseInt(c.slice(0, 2), 16), g = parseInt(c.slice(2, 4), 16), b = parseInt(c.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}
function shortGrp(s: string) { return s.length > 18 ? s.slice(0, 18) + "…" : s; }

export default function Galaxy() {
  const { t } = useLocale();
  const status = useGalaxyStatus();
  const graph = useGalaxyGraph();
  const rebuild = useGalaxyRebuild();

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  // React state that must drive DOM: the selected node (opens panel) + focus label
  const [selected, setSelected] = useState<GalaxyGraphNode | null>(null);
  const [focusLabel, setFocusLabel] = useState<string | null>(null);

  // mutable refs shared with the imperative render loop
  const stateRef = useRef({
    nodes: [] as SimNode[], links: [] as SimLink[],
    adj: new Map<string, Set<string>>(), byId: new Map<string, SimNode>(),
    hover: null as SimNode | null, selectedId: null as string | null,
    focusSet: null as Set<string> | null,
    tx: 0, ty: 0, scale: 0.85, t: 0,
  });
  const simRef = useRef<Simulation<SimNode, undefined> | null>(null);
  const rafRef = useRef<number>(0);

  const data = graph.data;

  // node health tallies shown in the legend box
  const counts = useMemo(() => {
    let critical = 0, warning = 0, healthy = 0;
    for (const n of data?.nodes ?? []) {
      if (n.kind !== "resource") continue;
      if (n.health === "critical") critical++;
      else if (n.health === "warning") warning++;
      else healthy++;
    }
    return { critical, warning, healthy };
  }, [data]);

  // ── build sim + render loop when graph data arrives ──────────────────
  useEffect(() => {
    if (!data || !canvasRef.current || !wrapRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d")!;
    const S = stateRef.current;
    const DPR = Math.min(2, window.devicePixelRatio || 1);
    let W = 0, H = 0;

    // build nodes/links
    const byId = new Map<string, SimNode>();
    const nodes: SimNode[] = data.nodes.map((n) => {
      const o: SimNode = { ...n, r: 0 };
      o.r = n.kind === "account" ? 16
          : n.kind === "group" ? 7 + Math.min(9, Math.sqrt((n.members || 1)) * 1.6)
          : (n.health && n.health !== "healthy") ? 3.6 : 2.4;
      byId.set(o.id, o);
      return o;
    });
    const links: SimLink[] = data.edges
      .filter((e) => byId.has(e.s) && byId.has(e.t))
      .map((e) => ({ source: e.s, target: e.t, r: e.r, p: e.p, ev: e.ev, c: e.c }));
    const adj = new Map<string, Set<string>>();
    nodes.forEach((n) => adj.set(n.id, new Set()));
    links.forEach((l) => {
      adj.get(l.source as string)!.add(l.target as string);
      adj.get(l.target as string)!.add(l.source as string);
    });
    S.nodes = nodes; S.links = links; S.adj = adj; S.byId = byId;

    const sim = forceSimulation<SimNode>(nodes)
      .force("link", forceLink<SimNode, SimLink>(links).id((d) => d.id)
        .distance((l) => ((l.source as SimNode).kind === "group" || (l.target as SimNode).kind === "group") ? 26 : 18)
        .strength(0.6))
      .force("charge", forceManyBody<SimNode>().strength((d) => d.kind === "resource" ? -14 : -160).distanceMax(340))
      .force("center", forceCenter(0, 0))
      .force("collide", forceCollide<SimNode>().radius((d) => d.r + 2))
      .force("x", forceX(0).strength(0.02))
      .force("y", forceY(0).strength(0.02))
      .alphaDecay(0.018);
    simRef.current = sim;

    function resize() {
      const rect = wrapRef.current!.getBoundingClientRect();
      W = rect.width; H = rect.height;
      canvas.width = W * DPR; canvas.height = H * DPR;
      canvas.style.width = W + "px"; canvas.style.height = H + "px";
    }
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(wrapRef.current);

    // zoom / pan
    const zoomB: ZoomBehavior<HTMLCanvasElement, unknown> = d3zoom<HTMLCanvasElement, unknown>()
      .scaleExtent([0.15, 6])
      .on("zoom", (ev) => { S.tx = ev.transform.x; S.ty = ev.transform.y; S.scale = ev.transform.k; });
    select(canvas).call(zoomB).call(zoomB.transform, zoomIdentity.translate(W / 2, H / 2).scale(0.85));

    // drag to pin
    const dragB = d3drag<HTMLCanvasElement, unknown>()
      .subject((ev) => { const n = nodeAt(ev.x, ev.y); if (n) { n.fx = n.x; n.fy = n.y; } return n as unknown as { x: number; y: number }; })
      .on("start", (ev) => { if (!ev.active) sim.alphaTarget(0.15).restart(); })
      .on("drag", (ev) => { const n = ev.subject as unknown as SimNode; if (n) { const [wx, wy] = worldFromScreen(ev.x, ev.y); n.fx = wx; n.fy = wy; } })
      .on("end", (ev) => { if (!ev.active) sim.alphaTarget(0); });
    select(canvas).call(dragB);

    function worldFromScreen(sx: number, sy: number): [number, number] {
      return [(sx - S.tx) / S.scale, (sy - S.ty) / S.scale];
    }
    function nodeAt(sx: number, sy: number): SimNode | null {
      const [wx, wy] = worldFromScreen(sx, sy); let best: SimNode | null = null, bd = 1e9;
      for (const n of nodes) {
        const dx = (n.x || 0) - wx, dy = (n.y || 0) - wy, d = dx * dx + dy * dy;
        const rr = (n.r + 4) * (n.r + 4) / (S.scale * S.scale);
        if (d < rr && d < bd) { bd = d; best = n; }
      }
      return best;
    }
    (S as unknown as { nodeAt: typeof nodeAt }).nodeAt = nodeAt;

    // render loop
    function draw() {
      const P = NEBULA;
      S.t += 0.05;
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
      ctx.fillStyle = P.surface; ctx.fillRect(0, 0, W, H);
      ctx.save(); ctx.translate(S.tx, S.ty); ctx.scale(S.scale, S.scale);
      const focusSet = S.focusSet;
      const dim = !!(S.hover || focusSet);
      const litSet = S.hover ? adj.get(S.hover.id) : null;

      // nebula halos
      for (const n of nodes) {
        if (n.kind === "resource") continue;
        if (focusSet && !focusSet.has(n.id)) continue;
        const col = n.kind === "account" ? P.acct : P.group;
        const R = n.r * 6;
        const g = ctx.createRadialGradient(n.x!, n.y!, 0, n.x!, n.y!, R);
        g.addColorStop(0, hexA(col, 0.28)); g.addColorStop(1, hexA(col, 0));
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(n.x!, n.y!, R, 0, 7); ctx.fill();
      }
      // edges
      ctx.lineWidth = 1 / S.scale;
      for (const l of links) {
        const s = l.source as SimNode, tg = l.target as SimNode;
        if (focusSet && !(focusSet.has(s.id) && focusSet.has(tg.id))) continue;
        const on = !dim || (litSet && (s === S.hover || tg === S.hover));
        if (l.p === "llm") {
          ctx.strokeStyle = on ? hexA(P.llmEdge, 0.9) : hexA(P.llmEdge, 0.12);
          ctx.setLineDash([5 / S.scale, 4 / S.scale]);
        } else {
          ctx.strokeStyle = on ? "rgba(150,150,160,0.5)" : P.ruleEdge;
          ctx.setLineDash([]);
        }
        ctx.beginPath(); ctx.moveTo(s.x!, s.y!); ctx.lineTo(tg.x!, tg.y!); ctx.stroke();
      }
      ctx.setLineDash([]);
      // nodes
      for (const n of nodes) {
        if (focusSet && !focusSet.has(n.id)) continue;
        const isHot = n.kind === "resource" && n.health !== "healthy";
        const faded = dim && !(S.hover && (n === S.hover || (litSet && litSet.has(n.id))));
        const col = n.kind === "account" ? P.acct : n.kind === "group" ? P.group : starColor(P, n.health);
        let r = n.r;
        if (isHot) {
          const pulse = 0.5 + 0.5 * Math.sin(S.t * (n.health === "critical" ? 2.2 : 1.4));
          r = n.r * (1 + pulse * 0.5); ctx.shadowColor = col; ctx.shadowBlur = 10 + pulse * 14;
        } else if (n.kind !== "resource") { ctx.shadowColor = col; ctx.shadowBlur = 12; }
        else { ctx.shadowColor = col; ctx.shadowBlur = n.health === "healthy" ? 4 : 8; }
        ctx.globalAlpha = faded ? 0.12 : 1;
        ctx.fillStyle = col; ctx.beginPath(); ctx.arc(n.x!, n.y!, r, 0, 7); ctx.fill();
        ctx.shadowBlur = 0; ctx.globalAlpha = 1;
        if (n.id === S.selectedId) {
          ctx.strokeStyle = P.label; ctx.lineWidth = 1.5 / S.scale;
          ctx.beginPath(); ctx.arc(n.x!, n.y!, r + 4 / S.scale, 0, 7); ctx.stroke();
        }
        if ((n.kind !== "resource" && S.scale > 0.5) || n === S.hover) {
          ctx.globalAlpha = faded ? 0.2 : 0.92; ctx.fillStyle = P.label;
          ctx.font = `${(n.kind === "resource" ? 10 : 12) / S.scale}px system-ui`; ctx.textAlign = "center";
          const lbl = n.kind === "group" ? `${shortGrp(n.name)} (${n.members})` : n.name;
          ctx.fillText(lbl, n.x!, n.y! - r - 4 / S.scale); ctx.globalAlpha = 1;
        }
      }
      ctx.restore();
      rafRef.current = requestAnimationFrame(draw);
    }
    draw();

    // pointer: hover + click-vs-drag
    let downXY: [number, number] | null = null, moved = false;
    function onMove(ev: MouseEvent) {
      const rect = canvas.getBoundingClientRect();
      const n = nodeAt(ev.clientX - rect.left, ev.clientY - rect.top);
      S.hover = n;
      canvas.style.cursor = n ? "pointer" : "grab";
      if (downXY && Math.hypot(ev.clientX - downXY[0], ev.clientY - downXY[1]) > 4) moved = true;
    }
    function onDown(ev: MouseEvent) { downXY = [ev.clientX, ev.clientY]; moved = false; }
    function onClick(ev: MouseEvent) {
      if (moved) { downXY = null; return; }
      const rect = canvas.getBoundingClientRect();
      const n = nodeAt(ev.clientX - rect.left, ev.clientY - rect.top);
      if (n) { S.selectedId = n.id; setSelected({ ...n }); }
      else { S.selectedId = null; setSelected(null); }
      downXY = null;
    }
    function onDbl(ev: MouseEvent) {
      const rect = canvas.getBoundingClientRect();
      const n = nodeAt(ev.clientX - rect.left, ev.clientY - rect.top);
      if (n && (n.kind === "group" || n.kind === "account")) {
        const fs = new Set<string>([n.id]); adj.get(n.id)!.forEach((id) => fs.add(id));
        S.focusSet = fs; setFocusLabel(shortGrp(n.name));
      } else if (!n) { S.focusSet = null; setFocusLabel(null); }
    }
    canvas.addEventListener("mousemove", onMove);
    canvas.addEventListener("mousedown", onDown);
    canvas.addEventListener("click", onClick);
    canvas.addEventListener("dblclick", onDbl);

    return () => {
      cancelAnimationFrame(rafRef.current);
      sim.stop(); ro.disconnect();
      canvas.removeEventListener("mousemove", onMove);
      canvas.removeEventListener("mousedown", onDown);
      canvas.removeEventListener("click", onClick);
      canvas.removeEventListener("dblclick", onDbl);
    };
  }, [data]);

  const exitFocus = useCallback(() => { stateRef.current.focusSet = null; setFocusLabel(null); }, []);
  const closePanel = useCallback(() => { stateRef.current.selectedId = null; setSelected(null); }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { if (selected) closePanel(); else if (focusLabel) exitFocus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected, focusLabel, closePanel, exitFocus]);

  const b = status.data?.build;
  const P = NEBULA;
  return (
    // escape AppShell <main> p-6 auto-height box; Canvas needs an explicit-height parent.
    // Galaxy is a fixed Nebula-Violet starfield — chrome uses fixed dark values
    // (not theme tokens) so it stays consistent whether the app is light or dark.
    <div className="relative h-[calc(100vh-2.25rem)] -m-6 w-auto" style={{ background: P.surface }}>
      {/* status bar */}
      <div className="absolute top-0 left-0 right-0 z-10 flex items-center gap-3 px-4 py-2
                      bg-black/40 backdrop-blur border-b border-white/10 text-xs text-[#c9c6d6]">
        <span className="font-semibold text-white">✦ {t("nav.galaxy")}</span>
        <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded
                         bg-amber-400/15 text-amber-300 border border-amber-400/30">
          {t("galaxy.experimental")}
        </span>
        {b ? (
          <span className="text-[#9691a8]">
            {b.status === "running" ? t("galaxy.building")
              : `${b.node_count} ${t("galaxy.builtNodes")} · ${b.edge_count} ${t("galaxy.edges")} · $${b.cost_usd.toFixed(4)} · ${t("galaxy.dropped")}: ${b.dropped_edge_count}`}
          </span>
        ) : <span className="text-[#9691a8]">{t("galaxy.noBuild")}</span>}
        {b?.status === "failed" && <span className="text-red-400">{b.error}</span>}

        <span className="ml-auto text-[#9691a8]">{t("galaxy.nextCheck")}: {status.data?.next_check_minutes}m</span>
        {focusLabel && (
          <button className="px-2 py-1 rounded bg-white/5 hover:bg-white/10 text-white" onClick={exitFocus}>
            {t("galaxy.backToOverview")} · {focusLabel}
          </button>
        )}
        {rebuild.isError && <span className="text-red-400">{String(rebuild.error)}</span>}
        <button className="px-2 py-1 rounded bg-violet-400/20 text-violet-200 hover:bg-violet-400/30 disabled:opacity-50"
                disabled={rebuild.isPending || b?.status === "running"}
                onClick={() => rebuild.mutate(true)}>
          {rebuild.isPending || b?.status === "running" ? t("galaxy.building") : t("galaxy.rebuild")}
        </button>
      </div>

      {/* canvas */}
      <div ref={wrapRef} className="absolute inset-0 top-9">
        {graph.isLoading ? (
          <div className="flex h-full items-center justify-center text-[#9691a8] text-sm">…</div>
        ) : data && data.nodes.length === 0 ? (
          <div className="flex h-full items-center justify-center text-[#9691a8] text-sm">{t("galaxy.empty")}</div>
        ) : (
          <canvas ref={canvasRef} className="block" />
        )}
      </div>

      {/* legend + live health tallies (co-located) */}
      <div className="absolute left-4 bottom-4 z-10 text-[11px] leading-relaxed text-[#c9c6d6]
                      bg-black/40 backdrop-blur border border-white/10 rounded-lg px-3 py-2 min-w-[168px]">
        <LegendRow c={P.healthy} label={t("galaxy.legendHealthy")} count={counts.healthy} />
        <LegendRow c={P.warning} label={t("galaxy.legendWarning")} count={counts.warning} emphasize={counts.warning > 0} />
        <LegendRow c={P.critical} label={t("galaxy.legendCritical")} count={counts.critical} emphasize={counts.critical > 0} />
        <div className="flex items-center gap-2 mt-1 pt-1 border-t border-white/15">
          <Dot c={P.acct} /> {t("galaxy.legendAccount")} <Dot c={P.group} /> {t("galaxy.legendGroup")}
        </div>
        <div className="mt-1 text-[#9691a8]">{t("galaxy.legendHint")}</div>
      </div>

      {selected && <GalaxyNodePanel node={selected} onClose={closePanel} />}
    </div>
  );
}

function Dot({ c }: { c: string }) {
  return <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: c, boxShadow: `0 0 6px ${c}` }} />;
}

function LegendRow({ c, label, count, emphasize }: { c: string; label: string; count: number; emphasize?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <Dot c={c} />
      <span className="flex-1">{label}</span>
      <span className={emphasize ? "font-semibold tabular-nums" : "tabular-nums text-[#9691a8]"}
            style={emphasize ? { color: c } : undefined}>{count}</span>
    </div>
  );
}
