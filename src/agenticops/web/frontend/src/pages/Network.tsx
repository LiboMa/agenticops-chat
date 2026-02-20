import { useState, lazy, Suspense } from "react";
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
import { cn } from "@/lib/cn";

const TopologyGraph = lazy(
  () => import("@/components/topology/TopologyGraph")
);

type ViewMode = "table" | "graph";

export default function Network() {
  const [region, setRegion] = useState("us-east-1");
  const [vpcId, setVpcId] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("table");

  const vpcs = useVpcs(region);
  const topology = useVpcTopology(region, vpcId);

  const handleListVpcs = () => {
    vpcs.refetch();
  };

  const handleAnalyze = () => {
    if (vpcId.trim()) {
      topology.refetch();
    }
  };

  const handleUseVpc = (id: string) => {
    setVpcId(id);
  };

  return (
    <div className="space-y-6">
      {/* Input Form */}
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-gray-900">
            VPC Topology Analysis
          </h2>
        </CardHeader>
        <CardBody>
          <VpcSelector
            region={region}
            vpcId={vpcId}
            onRegionChange={setRegion}
            onVpcIdChange={setVpcId}
            onListVpcs={handleListVpcs}
            onAnalyze={handleAnalyze}
            isLoadingVpcs={vpcs.isFetching}
            isLoadingTopology={topology.isFetching}
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

      {/* Topology Results */}
      {topology.isFetching && <Spinner label="Analyzing topology..." />}

      {topology.error && (
        <ErrorBanner
          message={topology.error.message}
          onRetry={handleAnalyze}
        />
      )}

      {topology.data && (
        <>
          <TopologySummary topology={topology.data} />

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

          {viewMode === "graph" ? (
            <Suspense fallback={<Spinner label="Loading topology graph..." />}>
              <TopologyGraph topology={topology.data} />
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
