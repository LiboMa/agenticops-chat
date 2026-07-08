import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ReactFlow, ReactFlowProvider, Background, Controls, MarkerType,
  applyNodeChanges, type Node, type Edge, type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useLocale } from "@/i18n/LocaleContext";
import {
  useGalaxyStatus, useGalaxyOverview, useGalaxyExpand, useGalaxyRebuild,
} from "@/hooks/useGalaxy";
import { layoutGraph } from "@/lib/galaxyLayout";
import type { GalaxyNode, GalaxyEdge } from "@/api/types";

const HEALTH_BORDER: Record<string, string> = {
  healthy: "#3f3f46", warning: "#f59e0b", critical: "#ef4444",
};

function toFlow(nodes: GalaxyNode[], edges: GalaxyEdge[]): { nodes: Node[]; edges: Edge[] } {
  const fNodes: Node[] = nodes.map((n) => ({
    id: n.id,
    data: { label: n.kind === "resource" ? `${n.resource_type}\n${n.name}`
                    : `${n.name}${n.resource_count != null ? ` (${n.resource_count})` : ""}`, raw: n },
    position: { x: 0, y: 0 },
    style: {
      border: `2px solid ${HEALTH_BORDER[n.health ?? "healthy"]}`,
      borderRadius: 8, padding: 6, fontSize: 11, whiteSpace: "pre-line",
      background: n.kind === "group" ? "#1e293b" : n.kind === "account" ? "#0f172a" : "#18181b",
      color: "#e4e4e7", width: 180,
    },
  }));
  const fEdges: Edge[] = edges.map((e, i) => ({
    id: `${e.source}-${e.target}-${e.relation_type}-${i}`,
    source: e.source, target: e.target,
    label: e.relation_type,
    animated: e.provenance === "llm",
    style: { stroke: e.provenance === "llm" ? "#a78bfa" : "#52525b",
             strokeDasharray: e.provenance === "llm" ? "6 4" : undefined },
    markerEnd: { type: MarkerType.ArrowClosed },
    data: { raw: e },
  }));
  return { nodes: layoutGraph(fNodes, fEdges), edges: fEdges };
}

function GalaxyInner() {
  const { t } = useLocale();
  const navigate = useNavigate();
  const status = useGalaxyStatus();
  const overview = useGalaxyOverview();
  const rebuild = useGalaxyRebuild();

  const [expandedGroup, setExpandedGroup] = useState<string | null>(null);
  const [worstOnly, setWorstOnly] = useState(false);
  const expand = useGalaxyExpand(expandedGroup, [], worstOnly);

  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selected, setSelected] = useState<GalaxyNode | null>(null);

  // Overview or expanded view feeds the canvas.
  const graph = useMemo(() => {
    if (expandedGroup && expand.data) return toFlow(expand.data.nodes, expand.data.edges);
    if (overview.data) return toFlow(overview.data.nodes, overview.data.edges);
    return { nodes: [], edges: [] };
  }, [expandedGroup, expand.data, overview.data]);

  useEffect(() => { setNodes(graph.nodes); setEdges(graph.edges); }, [graph]);

  const onNodesChange = useCallback((c: NodeChange[]) => setNodes((n) => applyNodeChanges(c, n)), []);

  const onNodeClick = useCallback((_: unknown, node: Node) => {
    setSelected((node.data as { raw: GalaxyNode }).raw);
  }, []);
  const onNodeDoubleClick = useCallback((_: unknown, node: Node) => {
    const raw = (node.data as { raw: GalaxyNode }).raw;
    if (raw.kind === "group" || raw.kind === "account") {
      setExpandedGroup((cur) => (cur === raw.id ? null : raw.id));
    }
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setSelected(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const b = status.data?.build;
  return (
    <div className="relative h-full w-full">
      {/* Build status bar */}
      <div className="absolute top-0 left-0 right-0 z-10 flex items-center gap-3 px-4 py-2
                      bg-card/90 border-b border-border text-xs text-muted-foreground">
        <span className="font-medium text-foreground">{t("nav.galaxy")}</span>
        {b ? (
          <span>
            {b.status === "running" ? t("galaxy.building")
              : `${t("galaxy.builtNodes")}: ${b.node_count} · ${t("galaxy.edges")}: ${b.edge_count} · $${b.cost_usd.toFixed(4)} · ${t("galaxy.dropped")}: ${b.dropped_edge_count}`}
          </span>
        ) : <span>{t("galaxy.noBuild")}</span>}
        {b?.status === "failed" && <span className="text-red-400">{b.error}</span>}
        <span className="ml-auto">{t("galaxy.nextCheck")}: {status.data?.next_check_minutes}m</span>
        {expandedGroup && (
          <button className="px-2 py-1 rounded bg-accent hover:bg-accent/70"
                  onClick={() => setExpandedGroup(null)}>{t("galaxy.backToOverview")}</button>
        )}
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={worstOnly} onChange={(e) => setWorstOnly(e.target.checked)} />
          {t("galaxy.worstOnly")}
        </label>
        <button className="px-2 py-1 rounded bg-primary/20 text-primary hover:bg-primary/30 disabled:opacity-50"
                disabled={rebuild.isPending || b?.status === "running"}
                onClick={() => rebuild.mutate(true)}>{t("galaxy.rebuild")}</button>
      </div>

      {expand.data?.truncated && (
        <div className="absolute top-10 left-1/2 -translate-x-1/2 z-10 px-3 py-1 rounded
                        bg-amber-500/20 text-amber-300 text-xs">{t("galaxy.truncated")}</div>
      )}

      <div className="h-full w-full pt-9">
        {overview.data && overview.data.nodes.length === 0 && !expandedGroup ? (
          <div className="flex h-full items-center justify-center text-muted-foreground text-sm">
            {t("galaxy.empty")}
          </div>
        ) : (
          <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange}
                     onNodeClick={onNodeClick} onNodeDoubleClick={onNodeDoubleClick} fitView>
            <Background />
            <Controls />
          </ReactFlow>
        )}
      </div>

      {/* Detail panel (house rule: slideInRight + ESC) */}
      {selected && (
        <div className="absolute top-9 right-0 bottom-0 w-80 z-20 bg-card border-l border-border
                        p-4 overflow-y-auto animate-[slideInRight_0.2s_ease-out]">
          <div className="flex items-center justify-between mb-2">
            <h3 className="font-medium text-foreground text-sm">{selected.name}</h3>
            <button className="text-muted-foreground hover:text-foreground" onClick={() => setSelected(null)}>✕</button>
          </div>
          {selected.kind === "resource" ? (
            <div className="space-y-2 text-xs text-muted-foreground">
              <div>{t("galaxy.type")}: {selected.resource_type}</div>
              <div>{t("galaxy.region")}: {selected.region}</div>
              <div>{t("galaxy.health")}: {selected.health}</div>
              <button className="mt-2 px-2 py-1 rounded bg-accent hover:bg-accent/70 text-foreground"
                      onClick={() => navigate(`/app/resources/${selected.id.replace("res:", "")}`)}>
                {t("galaxy.openResource")}
              </button>
            </div>
          ) : (
            <div className="space-y-2 text-xs text-muted-foreground">
              <div>{t("galaxy.resources")}: {selected.resource_count}</div>
              <div>{t("galaxy.openIssues")}: {selected.open_issues}</div>
              <div>{t("galaxy.health")}: {selected.health}</div>
              {selected.types && (
                <div>{Object.entries(selected.types).map(([k, v]) => `${k}:${v}`).join("  ")}</div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function Galaxy() {
  return (
    <ReactFlowProvider>
      <GalaxyInner />
    </ReactFlowProvider>
  );
}
