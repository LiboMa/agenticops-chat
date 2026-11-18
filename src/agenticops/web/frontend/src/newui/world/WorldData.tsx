import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useAccounts } from "@/hooks/useAccounts";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { GalaxyGraph, GalaxyHealthRead } from "@/api/types";
import { useGalaxyStatus } from "@/hooks/useGalaxy";
import { useTheme } from "@/hooks/useTheme";
import { applyHealth, indexGraph, type WorldGraph } from "../lib/world/graph";
import { layout as layOut, type Layout } from "../lib/world/layout";
import { Sky } from "./Sky";
import type { Sky3, Sky3Handlers } from "./Sky3";

/** The map's data and its one canvas, for the whole of NewUI: «全景» draws it in full, the other lenses have it as a
 *  faint backdrop. Two ages live on one map. The RELATIONS are the latest COMPLETED build of the relation graph (GET
 *  /api/galaxy/graph) — a snapshot, `builtAt` says of when. HEALTH and «gone» are not the build's: they are read
 *  again every HEALTH_POLL_MS (GET /api/galaxy/health) and after every decision, and put onto the same graph, so a
 *  ring follows its issue and not the next build; `healthAt` says when they were last read. */
export interface WorldApi {
  status: "loading" | "failed" | "empty" | "ready";
  graph: WorldGraph | null;
  layout: Layout | null;
  /** when the build the map shows finished (API time string); null = not known */
  builtAt: string | null;
  /** when health and «gone» were last read (API time string); null = not known */
  healthAt: string | null;
  /** back in time (N15): the moment asked for (ms; null = now), the moment the health on the graph is of, whether
   *  the asked moment's reading is still on its way or failed, and the switch. The relations stay the build's */
  asOf: number | null;
  shownAsOf: string | null;
  replayBusy: boolean;
  replayFailed: boolean;
  setAsOf: (at: number | null) => void;
  /** goes up each time a reading changed some resource's health or «gone»: what depends on them is worked out again */
  healthRev: number;
  /** a newer build is running right now */
  building: boolean;
  /** the newest build is not the one on the map and did not complete: it failed (with when), so the map is older
   *  than the schedule would make it */
  newerFailed: { id: number; at: string | null } | null;
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

const Ctx = createContext<WorldApi>({ status: "loading", graph: null, layout: null, builtAt: null, healthAt: null, healthRev: 0, building: false,
                                      asOf: null, shownAsOf: null, replayBusy: false, replayFailed: false, setAsOf: () => {},
                                      newerFailed: null, staleAt: null, sky: null, sky3: null, load3d: async () => false, retry: () => {}, want: () => {} });
export const useWorld = () => useContext(Ctx);

const BACKDROP_DELAY_MS = 1500;
/** How often health and «gone» are read again while NewUI is open (the browser pauses it in a hidden tab). */
export const HEALTH_POLL_MS = 30_000;
export const HEALTH_QUERY_KEY = ["galaxy-health"] as const;

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

  // health and «gone», read again on their own and put onto the same graph (no new layout, the camera stays).
  // `asOf` (N15) = read them for a moment of the last 24 hours instead: one reading per moment, not polled — the
  // past does not change; a decision still refreshes the reading of now (the key's prefix).
  const [asOf, setAsOf] = useState<number | null>(null);
  const health = useQuery({
    queryKey: [...HEALTH_QUERY_KEY, asOf ?? "now"],
    queryFn: () => apiFetch<GalaxyHealthRead>(`/galaxy/health${asOf !== null ? `?at=${encodeURIComponent(new Date(asOf).toISOString())}` : ""}`),
    enabled: !!built, refetchInterval: asOf === null ? HEALTH_POLL_MS : false, staleTime: asOf === null ? 5_000 : 5 * 60_000, retry: asOf === null ? 3 : 1,
  });
  const [healthRev, setHealthRev] = useState(0);
  const [healthAt, setHealthAt] = useState<string | null>(null);
  const [shownAsOf, setShownAsOf] = useState<string | null>(null);
  useEffect(() => {
    if (!built) return;
    if (health.data && applyHealth(built.graph, health.data)) setHealthRev((r) => r + 1);
    setHealthAt(built.graph.healthAt);              // the graph's own reading when there is no newer one
    setShownAsOf(built.graph.asOf);                 // …and the moment that reading is OF (null = now)
  }, [built, health.data]);

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
    // the graph says when its own build finished; an older server does not, and then only the status of that very
    // build has a time (the status names the newest build, which may be one still running, or one that failed)
    builtAt: built?.graph.builtAt ?? (status.data?.build && status.data.build.id === q.data?.build_id ? status.data.build.finished_at : null),
    healthAt, healthRev,
    asOf, shownAsOf, setAsOf,
    // the map shows the reading before until the asked moment's arrives: say so, and say when it did not
    replayBusy: asOf !== null && health.isFetching && !health.data,
    replayFailed: asOf !== null && health.isError && !health.data,
    building: status.data?.build?.status === "running",
    newerFailed: status.data?.build && status.data.build.status === "failed" && q.data?.build_id != null && status.data.build.id !== q.data.build_id
      ? { id: status.data.build.id, at: status.data.build.finished_at } : null,
    staleAt: q.isError && q.data ? q.dataUpdatedAt : null,
    sky, sky3, load3d, retry, want,
  }), [built, q.isError, q.data, q.dataUpdatedAt, status.data, healthAt, healthRev, asOf, shownAsOf, health.isFetching, health.isError, health.data,
       sky, sky3, load3d, retry, want]);

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
