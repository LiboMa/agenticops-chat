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
  retry: () => void;
  /** «全景» is on the page: fetch the graph now (elsewhere it is fetched once the page has settled) */
  want: () => void;
}

const Ctx = createContext<WorldApi>({ status: "loading", graph: null, layout: null, builtAt: null, building: false, staleAt: null, sky: null,
                                      retry: () => {}, want: () => {} });
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
  useEffect(() => {                                                    // day / night: the canvas takes the page's colours
    const id = window.requestAnimationFrame(() => sky?.recolor());
    return () => window.cancelAnimationFrame(id);
  }, [sky, theme]);

  const retry = useCallback(() => { void q.refetch(); }, [q]);
  const want = useCallback(() => setWanted(true), []);
  const api = useMemo<WorldApi>(() => ({
    status: built ? (built.graph.nodes.length ? "ready" : "empty") : q.isError ? "failed" : "loading",
    graph: built?.graph ?? null, layout: built?.layout ?? null,
    // the status names the newest build, which may be one still running: only the build the map shows has a time here
    builtAt: status.data?.build && status.data.build.id === q.data?.build_id ? status.data.build.finished_at : null,
    building: status.data?.build?.status === "running",
    staleAt: q.isError && q.data ? q.dataUpdatedAt : null,
    sky, retry, want,
  }), [built, q.isError, q.data, q.dataUpdatedAt, status.data, sky, retry, want]);

  return (
    <Ctx.Provider value={api}>
      <canvas id="sky" ref={canvas} aria-hidden="true" />
      {children}
    </Ctx.Provider>
  );
}
