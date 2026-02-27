import { useState } from "react";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { cn } from "@/lib/cn";
import {
  useSPOFAnalysis,
  useCapacityRisk,
  useDependencyChain,
  useChangeSimulation,
} from "@/hooks/useGraphTopology";

/* ------------------------------------------------------------------ */
/*  Props                                                              */
/* ------------------------------------------------------------------ */

interface SreAnalysisPanelProps {
  region: string;
  vpcId: string;
}

/* ------------------------------------------------------------------ */
/*  Collapsible section helper                                         */
/* ------------------------------------------------------------------ */

function Section({
  title,
  icon,
  children,
  defaultOpen = false,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 w-full px-4 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50 transition-colors"
      >
        {icon}
        <span className="flex-1 text-left">{title}</span>
        <svg
          className={cn(
            "w-4 h-4 text-slate-400 transition-transform",
            open && "rotate-180",
          )}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && <div className="px-4 pb-4 space-y-3">{children}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Risk level color helpers                                           */
/* ------------------------------------------------------------------ */

function riskColor(level: string) {
  switch (level.toLowerCase()) {
    case "critical":
      return "text-red-700 bg-red-100";
    case "high":
      return "text-orange-700 bg-orange-100";
    case "medium":
      return "text-amber-700 bg-amber-100";
    default:
      return "text-slate-700 bg-slate-100";
  }
}

function utilBarColor(pct: number) {
  if (pct >= 90) return "bg-red-500";
  if (pct >= 80) return "bg-orange-500";
  if (pct >= 60) return "bg-amber-400";
  return "bg-green-500";
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export function SreAnalysisPanel({ region, vpcId }: SreAnalysisPanelProps) {
  /* ---------- SPOF ---------- */
  const spof = useSPOFAnalysis(region, vpcId);

  /* ---------- Capacity Risk ---------- */
  const capacity = useCapacityRisk(region, vpcId);

  /* ---------- Dependency Chain ---------- */
  const [faultNodeId, setFaultNodeId] = useState("");
  const depChain = useDependencyChain(region, vpcId);

  /* ---------- Change Simulation ---------- */
  const [edgeSource, setEdgeSource] = useState("");
  const [edgeTarget, setEdgeTarget] = useState("");
  const changeSim = useChangeSimulation(region, vpcId);

  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-semibold text-slate-900 flex items-center gap-2">
          <svg
            className="w-5 h-5 text-primary-500"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
          </svg>
          SRE Analysis
        </h2>
      </CardHeader>
      <CardBody className="space-y-3">
        {/* ---------------------------------------------------------- */}
        {/* 1. SPOF Detection                                           */}
        {/* ---------------------------------------------------------- */}
        <Section
          title="Single Point of Failure Detection"
          icon={
            <svg className="w-4 h-4 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          }
        >
          <button
            onClick={() => spof.refetch()}
            disabled={spof.isFetching}
            className="px-3 py-1.5 text-xs font-medium rounded-md bg-red-50 text-red-700 border border-red-200 hover:bg-red-100 disabled:opacity-50 transition-colors"
          >
            {spof.isFetching ? "Analyzing..." : "Run SPOF Analysis"}
          </button>

          {spof.error && (
            <p className="text-xs text-red-600">{spof.error.message}</p>
          )}

          {spof.data && (
            <div className="space-y-3">
              <p className="text-xs text-slate-500">{spof.data.summary}</p>

              {spof.data.articulation_points.length > 0 && (
                <div>
                  <h4 className="text-xs font-semibold text-slate-700 mb-1.5">
                    Articulation Points ({spof.data.articulation_points.length})
                  </h4>
                  <div className="space-y-2">
                    {spof.data.articulation_points.map((item) => (
                      <div
                        key={item.node_id}
                        className="flex items-start gap-2 p-2.5 rounded-md bg-red-50 border border-red-200 text-sm"
                      >
                        <span className="px-1.5 py-0.5 text-[10px] rounded font-mono bg-red-100 text-red-700">
                          {item.node_type}
                        </span>
                        <div className="flex-1 min-w-0">
                          <div className="text-xs font-medium text-slate-800 truncate">
                            {item.label}
                          </div>
                          <div className="text-[10px] text-slate-500 mt-0.5">
                            {item.impact_description}
                          </div>
                        </div>
                        <span className="text-[10px] text-red-600 font-medium whitespace-nowrap">
                          {item.affected_components} affected
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {spof.data.bridges.length > 0 && (
                <div>
                  <h4 className="text-xs font-semibold text-slate-700 mb-1.5">
                    Bridge Connections ({spof.data.bridges.length})
                  </h4>
                  <div className="space-y-1.5">
                    {spof.data.bridges.map((bridge, i) => (
                      <div
                        key={`${bridge.source}-${bridge.target}-${i}`}
                        className="flex items-center gap-2 px-2.5 py-1.5 rounded-md bg-amber-50 border border-amber-200 text-xs"
                      >
                        <span className="font-medium text-slate-700 truncate">
                          {bridge.source_label}
                        </span>
                        <svg className="w-3 h-3 text-slate-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path d="M13 7l5 5m0 0l-5 5m5-5H6" />
                        </svg>
                        <span className="font-medium text-slate-700 truncate">
                          {bridge.target_label}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {spof.data.total_spofs === 0 && (
                <div className="text-xs text-green-600 flex items-center gap-1.5 p-2 bg-green-50 rounded-md border border-green-200">
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  No single points of failure detected.
                </div>
              )}
            </div>
          )}
        </Section>

        {/* ---------------------------------------------------------- */}
        {/* 2. Capacity Risk                                            */}
        {/* ---------------------------------------------------------- */}
        <Section
          title="Capacity Risk Assessment"
          icon={
            <svg className="w-4 h-4 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          }
        >
          <button
            onClick={() => capacity.refetch()}
            disabled={capacity.isFetching}
            className="px-3 py-1.5 text-xs font-medium rounded-md bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100 disabled:opacity-50 transition-colors"
          >
            {capacity.isFetching ? "Assessing..." : "Run Capacity Assessment"}
          </button>

          {capacity.error && (
            <p className="text-xs text-red-600">{capacity.error.message}</p>
          )}

          {capacity.data && (
            <div className="space-y-3">
              <p className="text-xs text-slate-500">{capacity.data.summary}</p>

              {capacity.data.items.length > 0 ? (
                <div className="space-y-2">
                  {capacity.data.items.map((item) => (
                    <div
                      key={`${item.node_id}-${item.metric}`}
                      className="p-2.5 rounded-md border border-slate-200 bg-white"
                    >
                      <div className="flex items-center justify-between mb-1.5">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="text-xs font-medium text-slate-800 truncate">
                            {item.label}
                          </span>
                          <span className="text-[10px] font-mono text-slate-400">
                            {item.metric}
                          </span>
                        </div>
                        <span
                          className={cn(
                            "px-1.5 py-0.5 text-[10px] rounded font-medium uppercase",
                            riskColor(item.risk_level),
                          )}
                        >
                          {item.risk_level}
                        </span>
                      </div>
                      {/* Utilization bar */}
                      <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden">
                        <div
                          className={cn("h-full rounded-full transition-all", utilBarColor(item.utilization_pct))}
                          style={{ width: `${Math.min(item.utilization_pct, 100)}%` }}
                        />
                      </div>
                      <div className="flex items-center justify-between mt-1 text-[10px] text-slate-500">
                        <span>
                          {item.current} / {item.maximum}
                        </span>
                        <span className="font-medium">
                          {item.utilization_pct.toFixed(1)}%
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-green-600 flex items-center gap-1.5 p-2 bg-green-50 rounded-md border border-green-200">
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  No capacity risks above threshold.
                </div>
              )}
            </div>
          )}
        </Section>

        {/* ---------------------------------------------------------- */}
        {/* 3. Dependency Chain                                         */}
        {/* ---------------------------------------------------------- */}
        <Section
          title="Dependency Chain Analysis"
          icon={
            <svg className="w-4 h-4 text-primary-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7" />
            </svg>
          }
        >
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <label className="block text-[10px] text-slate-500 mb-1">
                Fault Node ID
              </label>
              <input
                type="text"
                value={faultNodeId}
                onChange={(e) => setFaultNodeId(e.target.value)}
                placeholder="e.g. i-0abc123def456"
                className="w-full px-2.5 py-1.5 text-xs border border-slate-200 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-400 focus:border-primary-400"
              />
            </div>
            <button
              onClick={() => {
                if (faultNodeId.trim()) {
                  depChain.mutate(faultNodeId.trim());
                }
              }}
              disabled={depChain.isPending || !faultNodeId.trim()}
              className="px-3 py-1.5 text-xs font-medium rounded-md bg-primary-50 text-primary-700 border border-primary-200 hover:bg-primary-100 disabled:opacity-50 transition-colors whitespace-nowrap"
            >
              {depChain.isPending ? "Analyzing..." : "Trace Impact"}
            </button>
          </div>

          {depChain.error && (
            <p className="text-xs text-red-600">
              {depChain.error instanceof Error ? depChain.error.message : "Analysis failed"}
            </p>
          )}

          {depChain.data && (
            <div className="space-y-3">
              <div className="flex items-center gap-3 text-xs">
                <span className="text-slate-500">
                  Fault:{" "}
                  <span className="font-mono font-medium text-slate-700">
                    {depChain.data.fault_node_id}
                  </span>
                </span>
                <span
                  className={cn(
                    "px-1.5 py-0.5 rounded text-[10px] font-medium uppercase",
                    riskColor(depChain.data.severity),
                  )}
                >
                  {depChain.data.severity}
                </span>
                <span className="text-slate-500">
                  {depChain.data.total_affected} affected
                </span>
              </div>

              {/* Tree by depth */}
              {Object.entries(depChain.data.depth_levels)
                .sort(([a], [b]) => Number(a) - Number(b))
                .map(([depth, nodeIds]) => (
                  <div key={depth}>
                    <h4 className="text-[10px] font-semibold text-slate-500 uppercase tracking-wide mb-1">
                      Depth {depth}
                    </h4>
                    <div className="flex flex-wrap gap-1.5">
                      {(nodeIds as string[]).map((nodeId) => {
                        const node = depChain.data!.affected_nodes.find(
                          (n) => n.node_id === nodeId,
                        );
                        return (
                          <span
                            key={nodeId}
                            className="inline-flex items-center gap-1 px-2 py-1 text-[10px] rounded bg-slate-100 border border-slate-200"
                          >
                            <span className="font-mono text-slate-600">
                              {node?.label ?? nodeId}
                            </span>
                            {node?.node_type && (
                              <span className="text-slate-400">
                                ({node.node_type})
                              </span>
                            )}
                          </span>
                        );
                      })}
                    </div>
                  </div>
                ))}

              {depChain.data.total_affected === 0 && (
                <div className="text-xs text-green-600 flex items-center gap-1.5 p-2 bg-green-50 rounded-md border border-green-200">
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  No downstream dependencies affected.
                </div>
              )}
            </div>
          )}
        </Section>

        {/* ---------------------------------------------------------- */}
        {/* 4. Change Simulation                                        */}
        {/* ---------------------------------------------------------- */}
        <Section
          title="Change Simulation"
          icon={
            <svg className="w-4 h-4 text-violet-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
            </svg>
          }
        >
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <label className="block text-[10px] text-slate-500 mb-1">
                Edge Source
              </label>
              <input
                type="text"
                value={edgeSource}
                onChange={(e) => setEdgeSource(e.target.value)}
                placeholder="e.g. subnet-abc123"
                className="w-full px-2.5 py-1.5 text-xs border border-slate-200 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-400 focus:border-primary-400"
              />
            </div>
            <div className="flex-1">
              <label className="block text-[10px] text-slate-500 mb-1">
                Edge Target
              </label>
              <input
                type="text"
                value={edgeTarget}
                onChange={(e) => setEdgeTarget(e.target.value)}
                placeholder="e.g. igw-def456"
                className="w-full px-2.5 py-1.5 text-xs border border-slate-200 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-400 focus:border-primary-400"
              />
            </div>
            <button
              onClick={() => {
                if (edgeSource.trim() && edgeTarget.trim()) {
                  changeSim.mutate({
                    edgeSource: edgeSource.trim(),
                    edgeTarget: edgeTarget.trim(),
                  });
                }
              }}
              disabled={
                changeSim.isPending || !edgeSource.trim() || !edgeTarget.trim()
              }
              className="px-3 py-1.5 text-xs font-medium rounded-md bg-violet-50 text-violet-700 border border-violet-200 hover:bg-violet-100 disabled:opacity-50 transition-colors whitespace-nowrap"
            >
              {changeSim.isPending ? "Simulating..." : "Simulate"}
            </button>
          </div>

          {changeSim.error && (
            <p className="text-xs text-red-600">
              {changeSim.error instanceof Error
                ? changeSim.error.message
                : "Simulation failed"}
            </p>
          )}

          {changeSim.data && (
            <div className="space-y-3">
              <div className="flex items-center gap-3 text-xs text-slate-500">
                <span>
                  Edge:{" "}
                  <span className="font-mono text-slate-700">
                    {changeSim.data.edge_source}
                  </span>
                  {" -> "}
                  <span className="font-mono text-slate-700">
                    {changeSim.data.edge_target}
                  </span>
                </span>
                <span
                  className={cn(
                    "px-1.5 py-0.5 rounded text-[10px] font-medium",
                    changeSim.data.edge_existed
                      ? "bg-amber-100 text-amber-700"
                      : "bg-slate-100 text-slate-600",
                  )}
                >
                  {changeSim.data.edge_existed
                    ? "Existing edge"
                    : "Edge not found"}
                </span>
              </div>

              <p className="text-xs text-slate-600">
                {changeSim.data.impact_summary}
              </p>

              {changeSim.data.total_connections_lost > 0 && (
                <div className="text-xs font-medium text-red-600">
                  {changeSim.data.total_connections_lost} connection(s) would be
                  lost
                </div>
              )}

              {changeSim.data.lost_reachability.length > 0 && (
                <div className="space-y-2">
                  {changeSim.data.lost_reachability.map((diff) => (
                    <div
                      key={diff.node_id}
                      className="p-2.5 rounded-md border border-slate-200 bg-white"
                    >
                      <div className="text-xs font-mono font-medium text-slate-700 mb-1.5">
                        {diff.node_id}
                      </div>
                      {diff.lost.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {diff.lost.map((target) => (
                            <span
                              key={target}
                              className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded bg-red-50 border border-red-200 text-red-700"
                            >
                              <svg
                                className="w-2.5 h-2.5"
                                fill="none"
                                viewBox="0 0 24 24"
                                stroke="currentColor"
                                strokeWidth={2}
                              >
                                <path d="M6 18L18 6M6 6l12 12" />
                              </svg>
                              {target}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {changeSim.data.total_connections_lost === 0 && (
                <div className="text-xs text-green-600 flex items-center gap-1.5 p-2 bg-green-50 rounded-md border border-green-200">
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  No reachability loss from removing this edge.
                </div>
              )}
            </div>
          )}
        </Section>
      </CardBody>
    </Card>
  );
}
