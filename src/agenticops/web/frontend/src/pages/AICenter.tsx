import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

function MemoryCard({ agent }: { agent: any }) {
  const total = agent.total ?? 0;
  const types = agent.by_type ?? {};
  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <p className="text-sm font-medium text-gray-200">{agent.agent_id}</p>
      <p className="text-2xl font-bold text-blue-400 mt-1">{total}</p>
      <div className="flex gap-2 mt-2">
        {Object.entries(types).map(([k, v]) => (
          <span key={k} className="text-xs bg-gray-700 text-gray-400 px-2 py-0.5 rounded">
            {k}: {v as number}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function AICenter() {
  const memAgents = useQuery({ queryKey: ["memory-agents"], queryFn: () => api("/api/memory/agents") });
  const proAlerts = useQuery({ queryKey: ["proactive-alerts"], queryFn: () => api("/api/proactive/alerts") });
  const proPatterns = useQuery({ queryKey: ["proactive-patterns"], queryFn: () => api("/api/proactive/patterns") });
  const timeline = useQuery({ queryKey: ["learning-timeline"], queryFn: () => api("/api/learning/timeline") });

  const agents = memAgents.data?.agents ?? [];
  const totalMem = agents.reduce((s: number, a: any) => s + (a.total || 0), 0);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">🧠 AI Center</h1>

      {/* Memory Overview */}
      <div className="bg-gray-800/50 rounded-xl p-5 shadow-lg">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
            Agent Memory
          </h2>
          <span className="text-xl font-bold text-blue-400">{totalMem} total</span>
        </div>
        <div className="grid grid-cols-4 gap-3">
          {agents.filter((a: any) => a.total > 0).map((agent: any) => (
            <MemoryCard key={agent.agent_id} agent={agent} />
          ))}
        </div>
        {agents.every((a: any) => !a.total) && (
          <p className="text-sm text-gray-500 text-center py-4">
            No memories yet — agents will learn from incidents
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-6">
        {/* Proactive Predictions */}
        <div className="bg-gray-800/50 rounded-xl p-5 shadow-lg">
          <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-4">
            🔮 Proactive Predictions
          </h2>
          {proPatterns.data?.patterns?.length > 0 ? (
            <div className="space-y-2">
              {proPatterns.data.patterns.map((p: any, i: number) => (
                <div key={i} className="flex items-center justify-between py-2 px-3 bg-gray-800 rounded-lg">
                  <div>
                    <span className="text-sm font-medium text-gray-200">{p.category}</span>
                    <span className="text-xs text-gray-500 ml-2">×{p.occurrences}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="w-20 bg-gray-700 rounded-full h-1.5">
                      <div
                        className={`h-1.5 rounded-full ${
                          p.score >= 0.85 ? "bg-red-500" :
                          p.score >= 0.65 ? "bg-orange-500" :
                          p.score >= 0.3 ? "bg-yellow-500" : "bg-gray-500"
                        }`}
                        style={{ width: `${Math.min(p.score * 100, 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-400 w-10 text-right">
                      {(p.score * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-500 text-center py-4">
              No recurring patterns detected
            </p>
          )}

          {/* Proactive Alerts */}
          {proAlerts.data?.count > 0 && (
            <div className="mt-4 pt-4 border-t border-gray-700">
              <h3 className="text-xs text-gray-400 uppercase mb-2">Recent Alerts</h3>
              {proAlerts.data.alerts.slice(0, 5).map((a: any) => (
                <div key={a.id} className="py-1.5 text-xs text-gray-400 truncate">
                  {a.content?.substring(0, 120)}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Learning Timeline */}
        <div className="bg-gray-800/50 rounded-xl p-5 shadow-lg">
          <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-4">
            📈 Learning Timeline
          </h2>
          {timeline.data?.events?.length > 0 ? (
            <div className="space-y-3">
              {timeline.data.events.slice(0, 10).map((e: any, i: number) => (
                <div key={i} className="flex gap-3">
                  <span className="text-base mt-0.5">
                    {e.type === "case_study" ? "📋" :
                     e.type === "skill" ? "⚡" :
                     e.type === "sop" ? "📝" :
                     e.type === "prediction" ? "🔮" : "💡"}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-gray-200 truncate">{e.content?.substring(0, 100)}</p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {e.agent} · {e.type} · {e.confidence ? `${(e.confidence * 100).toFixed(0)}%` : ""}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-500 text-center py-4">
              No learning events yet
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
