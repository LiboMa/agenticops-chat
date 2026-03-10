import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

function StatCard({ label, value, sub, color }: { label: string; value: string | number; sub?: string; color: string }) {
  return (
    <div className="bg-gray-800 rounded-xl p-5 shadow-lg">
      <p className="text-xs text-gray-400 uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-3xl font-bold ${color}`}>{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-1">{sub}</p>}
    </div>
  );
}

export default function OpsHub() {
  const stats = useQuery({ queryKey: ["stats"], queryFn: () => api("/api/stats") });
  const memStats = useQuery({ queryKey: ["memory-agents"], queryFn: () => api("/api/memory/agents") });
  const proactive = useQuery({ queryKey: ["proactive-alerts"], queryFn: () => api("/api/proactive/alerts") });
  const anomalies = useQuery({
    queryKey: ["anomalies-recent"],
    queryFn: () => api("/api/anomalies?limit=10&sort=created_at:desc"),
  });

  const totalMemories = memStats.data?.agents?.reduce((s: number, a: any) => s + (a.total || 0), 0) ?? 0;
  const alertCount = proactive.data?.count ?? 0;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Ops Hub</h1>

      {/* Summary Cards */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard
          label="Active Alerts"
          value={stats.data?.active_anomalies ?? "—"}
          color="text-red-400"
        />
        <StatCard
          label="Open RCA"
          value={stats.data?.pending_rca ?? "—"}
          color="text-orange-400"
        />
        <StatCard
          label="Agent Memories"
          value={totalMemories}
          sub={`${memStats.data?.agents?.length ?? 0} agents`}
          color="text-blue-400"
        />
        <StatCard
          label="Predictions"
          value={alertCount}
          sub="proactive alerts"
          color="text-green-400"
        />
      </div>

      {/* Two-column layout */}
      <div className="grid grid-cols-3 gap-6">
        {/* Alert Feed */}
        <div className="col-span-2 bg-gray-800 rounded-xl p-5 shadow-lg">
          <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-4">
            Recent Anomalies
          </h2>
          <div className="space-y-2">
            {anomalies.data?.items?.slice(0, 8).map((a: any) => (
              <a
                key={a.id}
                href={`/app/issues/${a.id}`}
                className="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-gray-700/50 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <span className={`w-2 h-2 rounded-full ${
                    a.severity === "critical" ? "bg-red-500" :
                    a.severity === "high" ? "bg-orange-500" :
                    a.severity === "medium" ? "bg-yellow-500" : "bg-blue-500"
                  }`} />
                  <span className="text-sm text-gray-200 truncate max-w-md">
                    {a.title || a.anomaly_type}
                  </span>
                </div>
                <span className="text-xs text-gray-500">
                  {a.created_at ? new Date(a.created_at).toLocaleTimeString() : ""}
                </span>
              </a>
            )) ?? (
              <p className="text-sm text-gray-500">No recent anomalies</p>
            )}
          </div>
        </div>

        {/* Quick Actions */}
        <div className="bg-gray-800 rounded-xl p-5 shadow-lg">
          <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-4">
            Quick Actions
          </h2>
          <div className="space-y-2">
            <a href="/app/diagnose" className="block py-2 px-3 text-sm text-gray-300 hover:bg-gray-700/50 rounded-lg transition-colors">
              🔍 View Diagnose Center
            </a>
            <a href="/app/ai" className="block py-2 px-3 text-sm text-gray-300 hover:bg-gray-700/50 rounded-lg transition-colors">
              🧠 AI Center
            </a>
            <a href="/app/knowledge" className="block py-2 px-3 text-sm text-gray-300 hover:bg-gray-700/50 rounded-lg transition-colors">
              📚 Knowledge Base
            </a>
            <a href="/app/network" className="block py-2 px-3 text-sm text-gray-300 hover:bg-gray-700/50 rounded-lg transition-colors">
              🌐 Network Topology
            </a>
          </div>

          {/* Proactive Alerts Preview */}
          {alertCount > 0 && (
            <>
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mt-5 mb-2">
                Proactive Alerts
              </h3>
              {proactive.data?.alerts?.slice(0, 3).map((a: any) => (
                <div key={a.id} className="py-1.5 px-3 text-xs text-gray-400 truncate">
                  🔮 {a.content?.substring(0, 80)}
                </div>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
