import { useState, useCallback, lazy, Suspense } from "react";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { VpcSelector } from "@/components/network/VpcSelector";
import { VpcListTable } from "@/components/network/VpcListTable";
import { TopologySummary } from "@/components/network/TopologySummary";
import { SubnetsTable } from "@/components/network/SubnetsTable";
import { BlackholeAlert } from "@/components/network/BlackholeAlert";
import { SgDependencyMap } from "@/components/network/SgDependencyMap";
import { useVpcs } from "@/hooks/useVpcs";
import { useVpcTopology } from "@/hooks/useVpcTopology";
import { useRegions } from "@/hooks/useRegions";
import { useVpcGraph, useRegionGraph, useMultiRegionGraph, useVpcAnomalies, useSubnetReachability } from "@/hooks/useGraphTopology";
import type { AnomalyItem } from "@/api/types";
import { cn } from "@/lib/cn";

const TopologyGraph = lazy(
  () => import("@/components/topology/TopologyGraph")
);
const RegionTopologyGraph = lazy(
  () => import("@/components/topology/RegionTopologyGraph")
);

type ViewMode = "table" | "graph";

export default function Network() {
  const [region, setRegion] = useState("us-east-1");
  const [vpcId, setVpcId] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("table");
  const [selectedSubnetId, setSelectedSubnetId] = useState<string | null>(null);
  const [selectedRegions, setSelectedRegions] = useState<string[]>([]);
  const [topologyScope, setTopologyScope] = useState<"region" | "multi_region">("region");

  const regionsQuery = useRegions();
  const vpcs = useVpcs(region);
  const topology = useVpcTopology(region, vpcId);
  const vpcGraph = useVpcGraph(region, vpcId);
  const regionGraph = useRegionGraph(region);
  const multiRegionGraph = useMultiRegionGraph(selectedRegions);
  const anomalies = useVpcAnomalies(region, vpcId);
  const reachability = useSubnetReachability(region, vpcId, selectedSubnetId ?? "");

  const handleListVpcs = () => {
    vpcs.refetch();
  };

  const handleAnalyze = () => {
    if (vpcId.trim()) {
      topology.refetch();
      vpcGraph.refetch();
      anomalies.refetch();
    }
  };

  const handleScanRegion = () => {
    regionGraph.refetch();
  };

  const handleScanMultiRegion = () => {
    multiRegionGraph.refetch();
  };

  const handleToggleRegionSelection = (code: string) => {
    setSelectedRegions((prev) =>
      prev.includes(code) ? prev.filter((r) => r !== code) : [...prev, code]
    );
  };

  const handleUseVpc = (id: string) => {
    setVpcId(id);
  };

  // Drill-down from region graph: click a VPC node -> analyze its topology
  const handleRegionVpcClick = useCallback(
    (clickedVpcId: string) => {
      setVpcId(clickedVpcId);
      setTimeout(() => {
        topology.refetch();
        vpcGraph.refetch();
        anomalies.refetch();
      }, 0);
    },
    [topology, vpcGraph, anomalies],
  );

  // Subnet click -> fetch reachability from backend
  const handleSubnetClick = useCallback(
    (subnetId: string) => {
      if (selectedSubnetId === subnetId) {
        setSelectedSubnetId(null);
      } else {
        setSelectedSubnetId(subnetId);
        setTimeout(() => {
          reachability.refetch();
        }, 0);
      }
    },
    [selectedSubnetId, reachability],
  );

  return (
    <div className="space-y-6">
      {/* Input Form */}
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-gray-900">
            Network Topology
          </h2>
        </CardHeader>
        <CardBody>
          <VpcSelector
            region={region}
            regions={regionsQuery.data ?? [{ code: "us-east-1", name: "US East (N. Virginia)" }]}
            vpcId={vpcId}
            onRegionChange={setRegion}
            onVpcIdChange={setVpcId}
            onListVpcs={handleListVpcs}
            onAnalyze={handleAnalyze}
            onScanRegion={handleScanRegion}
            isLoadingVpcs={vpcs.isFetching}
            isLoadingTopology={topology.isFetching || vpcGraph.isFetching}
            isLoadingRegionTopology={regionGraph.isFetching}
          />

          {/* VPC List */}
          {vpcs.error && (
            <ErrorBanner
              message={vpcs.error.message}
              onRetry={handleListVpcs}
            />
          )}
          {vpcs.data && (
            <div className="mt-4">
              <VpcListTable
                region={vpcs.data.region}
                vpcs={vpcs.data.vpcs}
                onUseVpc={handleUseVpc}
              />
            </div>
          )}
        </CardBody>
      </Card>

      {/* Topology Scope Toggle */}
      <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1 w-fit">
        <button
          onClick={() => setTopologyScope("region")}
          className={cn(
            "px-3 py-1.5 text-sm font-medium rounded-md transition-colors",
            topologyScope === "region"
              ? "bg-white text-gray-900 shadow-sm"
              : "text-gray-500 hover:text-gray-700"
          )}
        >
          Single Region
        </button>
        <button
          onClick={() => setTopologyScope("multi_region")}
          className={cn(
            "px-3 py-1.5 text-sm font-medium rounded-md transition-colors",
            topologyScope === "multi_region"
              ? "bg-white text-gray-900 shadow-sm"
              : "text-gray-500 hover:text-gray-700"
          )}
        >
          Multi-Region
        </button>
      </div>

      {/* Multi-Region Panel */}
      {topologyScope === "multi_region" && (
        <Card>
          <CardHeader>
            <h2 className="text-lg font-semibold text-gray-900">
              Cross-Region Network Topology
            </h2>
          </CardHeader>
          <CardBody>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Select regions (or leave empty for all):
                </label>
                <div className="flex flex-wrap gap-2">
                  {(regionsQuery.data ?? []).map((r) => (
                    <button
                      key={r.code}
                      onClick={() => handleToggleRegionSelection(r.code)}
                      className={cn(
                        "px-2.5 py-1 text-xs rounded-full border transition-colors",
                        selectedRegions.includes(r.code)
                          ? "bg-indigo-100 border-indigo-400 text-indigo-700"
                          : "bg-white border-gray-300 text-gray-600 hover:border-gray-400"
                      )}
                    >
                      {r.code}
                    </button>
                  ))}
                </div>
              </div>
              <button
                onClick={handleScanMultiRegion}
                disabled={multiRegionGraph.isFetching}
                className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700 disabled:opacity-50"
              >
                {multiRegionGraph.isFetching ? "Scanning..." : "Scan Multi-Region Topology"}
              </button>
            </div>

            {multiRegionGraph.error && (
              <ErrorBanner
                message={multiRegionGraph.error.message}
                onRetry={handleScanMultiRegion}
              />
            )}

            {multiRegionGraph.data && (
              <div className="mt-4">
                <div className="flex items-center gap-3 text-sm text-gray-500 mb-3">
                  <span>{multiRegionGraph.data.metadata.node_count} Nodes</span>
                  <span>{multiRegionGraph.data.metadata.edge_count} Connections</span>
                  {multiRegionGraph.data.metadata.anomaly_count > 0 && (
                    <span className="text-red-600 font-medium">
                      {multiRegionGraph.data.metadata.anomaly_count} Anomalies
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-400 mb-3">
                  Cross-region edges are shown with dashed lines. Click a VPC node to drill down.
                </p>
                <Suspense
                  fallback={<Spinner label="Loading multi-region topology graph..." />}
                >
                  <RegionTopologyGraph
                    graph={multiRegionGraph.data}
                    onVpcClick={handleRegionVpcClick}
                  />
                </Suspense>
              </div>
            )}
          </CardBody>
        </Card>
      )}

      {/* Region Topology Overview */}
      {topologyScope === "region" && regionGraph.isFetching && (
        <Spinner label="Scanning region topology..." />
      )}

      {topologyScope === "region" && regionGraph.error && (
        <ErrorBanner
          message={regionGraph.error.message}
          onRetry={handleScanRegion}
        />
      )}

      {topologyScope === "region" && regionGraph.data && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900">
                Region Overview — {region}
              </h2>
              <div className="flex items-center gap-3 text-sm text-gray-500">
                <span>{regionGraph.data.metadata.node_count} Nodes</span>
                <span>{regionGraph.data.metadata.edge_count} Connections</span>
              </div>
            </div>
          </CardHeader>
          <CardBody>
            <p className="text-xs text-gray-400 mb-3">
              Click a VPC node to drill into its detailed topology.
            </p>
            <Suspense
              fallback={<Spinner label="Loading region topology graph..." />}
            >
              <RegionTopologyGraph
                graph={regionGraph.data}
                onVpcClick={handleRegionVpcClick}
              />
            </Suspense>
          </CardBody>
        </Card>
      )}

      {/* Single-VPC Topology Results */}
      {(topology.isFetching || vpcGraph.isFetching) && (
        <Spinner label="Analyzing VPC topology..." />
      )}

      {(topology.error || vpcGraph.error) && (
        <ErrorBanner
          message={(topology.error ?? vpcGraph.error)!.message}
          onRetry={handleAnalyze}
        />
      )}

      {topology.data && (
        <>
          <TopologySummary topology={topology.data} />

          {/* Anomalies Panel */}
          {anomalies.data && anomalies.data.total_anomalies > 0 && (
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-red-800">
                    Topology Anomalies ({anomalies.data.total_anomalies})
                  </h2>
                  <span className="text-xs text-gray-500">
                    {anomalies.data.summary}
                  </span>
                </div>
              </CardHeader>
              <CardBody>
                <div className="space-y-2">
                  {anomalies.data.anomalies.map((anomaly: AnomalyItem, i: number) => (
                    <div
                      key={`${anomaly.node_id}-${i}`}
                      className={cn(
                        "flex items-start gap-3 p-3 rounded-md border text-sm",
                        anomaly.severity === "critical"
                          ? "bg-red-50 border-red-200"
                          : anomaly.severity === "high"
                            ? "bg-orange-50 border-orange-200"
                            : "bg-yellow-50 border-yellow-200"
                      )}
                    >
                      <span
                        className={cn(
                          "px-1.5 py-0.5 text-xs rounded font-medium uppercase",
                          anomaly.severity === "critical"
                            ? "bg-red-600 text-white"
                            : anomaly.severity === "high"
                              ? "bg-orange-500 text-white"
                              : "bg-yellow-500 text-white"
                        )}
                      >
                        {anomaly.severity}
                      </span>
                      <div className="flex-1">
                        <div className="font-medium text-gray-800">
                          {anomaly.type.replace(/_/g, " ")}
                        </div>
                        <div className="text-gray-600 text-xs mt-0.5">
                          {anomaly.description}
                        </div>
                      </div>
                      <span className="text-xs font-mono text-gray-400">
                        {anomaly.node_id}
                      </span>
                    </div>
                  ))}
                </div>
              </CardBody>
            </Card>
          )}

          {/* View Mode Toggle */}
          <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1 w-fit">
            <button
              onClick={() => setViewMode("table")}
              className={cn(
                "px-3 py-1.5 text-sm font-medium rounded-md transition-colors",
                viewMode === "table"
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              )}
            >
              <span className="flex items-center gap-1.5">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <rect x="3" y="3" width="18" height="18" rx="2" />
                  <path d="M3 9h18M3 15h18M9 3v18" />
                </svg>
                Table View
              </span>
            </button>
            <button
              onClick={() => setViewMode("graph")}
              className={cn(
                "px-3 py-1.5 text-sm font-medium rounded-md transition-colors",
                viewMode === "graph"
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              )}
            >
              <span className="flex items-center gap-1.5">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <circle cx="6" cy="6" r="3" />
                  <circle cx="18" cy="18" r="3" />
                  <circle cx="18" cy="6" r="3" />
                  <path d="M8.5 7.5L15.5 16.5M8.5 6L15.5 6" />
                </svg>
                Graph View
              </span>
            </button>
          </div>

          {viewMode === "graph" && vpcGraph.data ? (
            <Suspense fallback={<Spinner label="Loading topology graph..." />}>
              <TopologyGraph
                graph={vpcGraph.data}
                reachability={reachability.data ?? null}
                onSubnetClick={handleSubnetClick}
              />
            </Suspense>
          ) : (
            <>
              {/* VPC Details */}
              <Card>
                <CardBody>
                  <h3 className="text-lg font-semibold text-gray-900 mb-3">
                    VPC Details
                  </h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div>
                      <span className="text-gray-500">VPC ID:</span>{" "}
                      <span className="font-mono">{topology.data.vpc_id}</span>
                    </div>
                    <div>
                      <span className="text-gray-500">CIDR:</span>{" "}
                      {topology.data.vpc_cidr}
                    </div>
                    <div>
                      <span className="text-gray-500">Name:</span>{" "}
                      {topology.data.vpc_name ?? "-"}
                    </div>
                    <div>
                      <span className="text-gray-500">Region:</span>{" "}
                      {topology.data.region}
                    </div>
                  </div>
                </CardBody>
              </Card>

              <SubnetsTable subnets={topology.data.subnets} />

              <BlackholeAlert routes={topology.data.blackhole_routes} />

              <SgDependencyMap dependencies={topology.data.security_group_dependency_map} />
            </>
          )}
        </>
      )}
    </div>
  );
}
