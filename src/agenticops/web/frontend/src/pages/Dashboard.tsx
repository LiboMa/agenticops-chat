import { useStats } from "@/hooks/useStats";
import { useAnomalies } from "@/hooks/useAnomalies";
import { useResourceTypeCounts } from "@/hooks/useResourceTypeCounts";
import { useExecutorStatus } from "@/hooks/useExecutorStatus";
import { StatCard } from "@/components/ui/StatCard";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatShortDate } from "@/lib/formatDate";
import { useNavigate } from "react-router-dom";
import { useMemo } from "react";

export default function Dashboard() {
  const stats = useStats();
  const anomalies = useAnomalies({ status: "open" });
  const typeCounts = useResourceTypeCounts();
  const executor = useExecutorStatus();
  const navigate = useNavigate();

  const resourceTypes = useMemo(() => {
    if (!typeCounts.data) return [];
    return Object.entries(typeCounts.data).sort((a, b) => b[1] - a[1]);
  }, [typeCounts.data]);

  if (stats.isLoading) return <Spinner label="Loading dashboard..." />;
  if (stats.error)
    return (
      <ErrorBanner
        message={stats.error.message}
        onRetry={() => stats.refetch()}
      />
    );

  const s = stats.data!;

  return (
    <div className="space-y-8">
      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total Resources" value={s.total_resources} />
        <StatCard label="Open Issues" value={s.open_anomalies} colorClass="text-red-400" />
        <StatCard label="Critical Issues" value={s.critical_anomalies} colorClass="text-red-500" />
        <StatCard label="Accounts" value={s.total_accounts} />
      </div>

      {/* Pipeline Status */}
      {executor.data && (
        <Card>
          <CardHeader>
            <h2 className="text-sm font-semibold text-[#ececec]">Pipeline Status</h2>
          </CardHeader>
          <CardBody>
            <div className="flex items-center gap-6 flex-wrap">
              <div className="flex items-center gap-2">
                <span
                  className={`inline-block w-2 h-2 rounded-full ${
                    executor.data.running ? "bg-green-500" : "bg-[#666]"
                  }`}
                />
                <span className="text-sm text-[#9b9b9b]">
                  Executor {executor.data.enabled ? "Enabled" : "Disabled"}
                </span>
              </div>
              <div className="text-sm text-[#9b9b9b]">
                Active: <span className="text-[#ececec] font-medium">{executor.data.active_executions}</span>
              </div>
              <div className="text-sm text-[#9b9b9b]">
                Auto-resolve:{" "}
                <span className={executor.data.auto_resolve ? "text-green-400" : "text-[#666]"}>
                  {executor.data.auto_resolve ? "On" : "Off"}
                </span>
              </div>
            </div>
          </CardBody>
        </Card>
      )}

      {/* Recent Issues */}
      <Card>
        <CardHeader>
          <h2 className="text-sm font-semibold text-[#ececec]">Recent Issues</h2>
        </CardHeader>
        <CardBody className="p-0">
          {anomalies.isLoading ? (
            <Spinner />
          ) : anomalies.data && anomalies.data.length > 0 ? (
            <table className="w-full">
              <thead>
                <tr className="border-b border-[#424242]">
                  <th className="px-6 py-3 text-left text-[11px] font-medium text-[#666] uppercase tracking-wider">
                    Severity
                  </th>
                  <th className="px-6 py-3 text-left text-[11px] font-medium text-[#666] uppercase tracking-wider">
                    Title
                  </th>
                  <th className="px-6 py-3 text-left text-[11px] font-medium text-[#666] uppercase tracking-wider">
                    Resource
                  </th>
                  <th className="px-6 py-3 text-left text-[11px] font-medium text-[#666] uppercase tracking-wider">
                    Detected
                  </th>
                </tr>
              </thead>
              <tbody>
                {anomalies.data.slice(0, 10).map((a) => (
                  <tr
                    key={a.id}
                    className="border-b border-[#424242]/50 hover:bg-[#383838] cursor-pointer transition-colors duration-150"
                    onClick={() => navigate(`/app/issues/${a.id}`)}
                  >
                    <td className="px-6 py-3">
                      <SeverityBadge severity={a.severity} />
                    </td>
                    <td className="px-6 py-3 text-sm text-[#ececec]">
                      {a.title.length > 50
                        ? a.title.slice(0, 50) + "..."
                        : a.title}
                    </td>
                    <td className="px-6 py-3 text-sm text-[#9b9b9b] font-mono">
                      {a.resource_type}/{a.resource_id.slice(0, 20)}
                    </td>
                    <td className="px-6 py-3 text-sm text-[#9b9b9b]">
                      {formatShortDate(a.detected_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="p-8 text-center text-[#666] text-sm">
              No issues detected.
            </div>
          )}
        </CardBody>
      </Card>

      {/* Resources by Type */}
      <Card>
        <CardHeader>
          <h2 className="text-sm font-semibold text-[#ececec]">Resources by Type</h2>
        </CardHeader>
        <CardBody>
          {typeCounts.isLoading ? (
            <Spinner />
          ) : resourceTypes.length > 0 ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {resourceTypes.map(([type, count]) => (
                <div key={type} className="text-center p-4 bg-[#383838] rounded-lg">
                  <div className="text-2xl font-semibold text-[#ececec]">
                    {count}
                  </div>
                  <div className="text-xs text-[#9b9b9b] mt-1">{type}</div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center text-[#666] text-sm">
              No resources found.
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
