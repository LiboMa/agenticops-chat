import { useStats } from "@/hooks/useStats";
import { useAnomalies } from "@/hooks/useAnomalies";
import { useResourceTypeCounts } from "@/hooks/useResourceTypeCounts";
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
  const navigate = useNavigate();

  // Sort type counts descending
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
    <div className="space-y-6">
      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Total Resources"
          value={s.total_resources}
          colorClass="text-pd-green-600"
        />
        <StatCard
          label="Open Anomalies"
          value={s.open_anomalies}
          colorClass="text-red-600"
        />
        <StatCard
          label="Critical Issues"
          value={s.critical_anomalies}
          colorClass="text-red-800"
        />
        <StatCard
          label="Accounts"
          value={s.total_accounts}
          colorClass="text-gray-700"
        />
      </div>

      {/* Recent Anomalies */}
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-gray-900">
            Recent Anomalies
          </h2>
        </CardHeader>
        <CardBody className="p-0">
          {anomalies.isLoading ? (
            <Spinner />
          ) : anomalies.data && anomalies.data.length > 0 ? (
            <table className="w-full">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Severity
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Title
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Resource
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Detected
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {anomalies.data.slice(0, 10).map((a) => (
                  <tr
                    key={a.id}
                    className="hover:bg-gray-50 cursor-pointer transition-colors"
                    onClick={() => navigate(`/app/anomalies/${a.id}`)}
                  >
                    <td className="px-6 py-3">
                      <SeverityBadge severity={a.severity} />
                    </td>
                    <td className="px-6 py-3 text-sm text-gray-900">
                      {a.title.length > 50
                        ? a.title.slice(0, 50) + "..."
                        : a.title}
                    </td>
                    <td className="px-6 py-3 text-sm text-gray-500 font-mono">
                      {a.resource_type}/{a.resource_id.slice(0, 20)}
                    </td>
                    <td className="px-6 py-3 text-sm text-gray-500">
                      {formatShortDate(a.detected_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="p-8 text-center text-gray-500 text-sm">
              No anomalies detected.
            </div>
          )}
        </CardBody>
      </Card>

      {/* Resources by Type */}
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-gray-900">
            Resources by Type
          </h2>
        </CardHeader>
        <CardBody>
          {typeCounts.isLoading ? (
            <Spinner />
          ) : resourceTypes.length > 0 ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {resourceTypes.map(([type, count]) => (
                <div key={type} className="text-center p-4 bg-gray-50 rounded-lg">
                  <div className="text-2xl font-bold text-pd-green-600">
                    {count}
                  </div>
                  <div className="text-sm text-gray-500 mt-1">{type}</div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center text-gray-500 text-sm">
              No resources found.
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
