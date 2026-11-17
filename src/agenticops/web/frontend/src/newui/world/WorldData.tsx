import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useAccounts } from "@/hooks/useAccounts";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { GalaxyGraph } from "@/api/types";
import { useGalaxyStatus } from "@/hooks/useGalaxy";
import { useTheme } from "@/hooks/useTheme";
import { indexGraph, type WorldGraph } from "../lib/world/graph";
import { layout as layOut, type Layout } from "../lib/world/layout";
import { Sky } from "./Sky";
import type { Sky3, Sky3Handlers } from "./Sky3";

/** The map's data and its one canvas, for the whole of NewUI: «全景» draws it in full, the other lenses have it as a
 *  faint backdrop. The graph is the latest COMPLETED build of the relation graph (GET /api/galaxy/graph) — a snapshot;
 *  `builtAt` says of when. */
export interface WorldApi {
  status: "loading" | "failed" | "empty" | "ready";
  graph: WorldGraph | null;
  layout: Layout | null;
  /** when the build the map shows finished (API time string); null = not known */
  builtAt: string | null;
  /** a newer build is running right now */
  building: boolean;
  /** the last good answer is older than the newest attempt: when it came (epoch ms) */
  staleAt: number | null;
  sky: Sky | null;
  /** the 3D view, once someone has asked for it (the engine is a chunk of its own, fetched then) */
  sky3: Sky3 | null;
  /** fetch the 3D engine and start it; false = it could not be loaded or the browser has no WebGL */
  load3d: (handlers: Sky3Handlers) => Promise<boolean>;
  retry: () => void;
  /** «全景» is on the page: fetch the graph now (elsewhere it is fetched once the page has settled) */
  want: () => void;
}

const Ctx = createContext<WorldApi>({ status: "loading", graph: null, layout: null, builtAt: null, building: false, staleAt: null, sky: null, sky3: null,
                                      load3d: async () => false, retry: () => {}, want: () => {} });
export const useWorld = () => useContext(Ctx);

const BACKDROP_DELAY_MS = 1500;

export function WorldLayer({ children }: { children: ReactNode }) {
  // elsewhere than on «全景» the map is only a backdrop: it must not compete with the page's own first requests
  const [wanted, setWanted] = useState(false);
  useEffect(() => { const id = window.setTimeout(() => setWanted(true), BACKDROP_DELAY_MS); return () => window.clearTimeout(id); }, []);
  const q = useQuery({ queryKey: ["galaxy-graph"], queryFn: () => apiFetch<GalaxyGraph>("/galaxy/graph"), staleTime: 60_000, enabled: wanted });
  const status = useGalaxyStatus();
  const accounts = useAccounts();
  const { theme } = useTheme();
  const canvas = useRef<HTMLCanvasElement>(null);
  const [sky, setSky] = useState<Sky | null>(null);
  const [sky3, setSky3] = useState<Sky3 | null>(null);
  const host3 = useRef<HTMLDivElement>(null), labels3 = useRef<HTMLDivElement>(null), clabels3 = useRef<HTMLDivElement>(null);
  const handlers3 = useRef<Sky3Handlers>({ pick: () => {}, hover: () => {} });
  const loading3 = useRef<Promise<boolean> | null>(null);

  const names = useMemo(() => new Map((accounts.data ?? []).map((a) => [a.id, a.name] as const)), [accounts.data]);
  const built = useMemo(() => {
    if (!q.data) return null;
    const graph = indexGraph(q.data, names);
    return { graph, layout: layOut(graph) };
  }, [q.data, names]);

  useEffect(() => {
    const el = canvas.current, root = el?.closest<HTMLElement>(".nf");
    if (!el || !root) return;
    const made = new Sky(el, root);
    made.start();
    setSky(made);
    return () => { made.dispose(); setSky(null); };
  }, []);
  useEffect(() => { sky?.setGraph(built?.graph ?? null, built?.layout ?? null); }, [sky, built]);
  useEffect(() => { sky3?.setGraph(built?.graph ?? null, built?.layout ?? null); }, [sky3, built]);
  useEffect(() => () => { sky3?.dispose(); }, [sky3]);
  useEffect(() => {                                                    // day / night: the canvas takes the page's colours
    const id = window.requestAnimationFrame(() => { sky?.recolor(); sky3?.recolor(); });
    return () => window.cancelAnimationFrame(id);
  }, [sky, sky3, theme]);

  const retry = useCallback(() => { void q.refetch(); }, [q]);
  const want = useCallback(() => setWanted(true), []);
  const load3d = useCallback((handlers: Sky3Handlers): Promise<boolean> => {
    handlers3.current = handlers;                       // the lens that is on the page now
    loading3.current ??= import("./Sky3").then(({ Sky3: Engine }) => {
      const host = host3.current, labels = labels3.current, clabels = clabels3.current, root = host?.closest<HTMLElement>(".nf");
      if (!host || !labels || !clabels || !root) return false;
      setSky3(new Engine(host, labels, clabels, root, {
        pick: (i) => handlers3.current.pick(i), hover: (i, x, y) => handlers3.current.hover(i, x, y),
      }));
      return true;
    }).catch(() => { loading3.current = null; return false; });        // no WebGL, or the chunk did not arrive: stay on the flat map; try again next time
    return loading3.current;
  }, []);
  const api = useMemo<WorldApi>(() => ({
    status: built ? (built.graph.nodes.length ? "ready" : "empty") : q.isError ? "failed" : "loading",
    graph: built?.graph ?? null, layout: built?.layout ?? null,
    // the status names the newest build, which may be one still running: only the build the map shows has a time here
    builtAt: status.data?.build && status.data.build.id === q.data?.build_id ? status.data.build.finished_at : null,
    building: status.data?.build?.status === "running",
    staleAt: q.isError && q.data ? q.dataUpdatedAt : null,
    sky, sky3, load3d, retry, want,
  }), [built, q.isError, q.data, q.dataUpdatedAt, status.data, sky, sky3, load3d, retry, want]);

  return (
    <Ctx.Provider value={api}>
      <canvas id="sky" ref={canvas} aria-hidden="true" />
      <div id="g3d" ref={host3} hidden aria-hidden="true" />
      <div id="labels" ref={labels3} hidden aria-hidden="true" />
      <div id="clabels" ref={clabels3} hidden aria-hidden="true" />
      {children}
    </Ctx.Provider>
  );
}
