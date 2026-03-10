import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useNavigate } from "react-router-dom";

export default function Diagnose() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const navigate = useNavigate();

  const anomalies = useQuery({
    queryKey: ["anomalies"],
    queryFn: () => api("/api/anomalies?limit=50&sort=created_at:desc"),
  });

  const detail = useQuery({
    queryKey: ["anomaly-detail", selectedId],
    queryFn: () => api(`/api/anomalies/${selectedId}`),
    enabled: !!selectedId,
  });

  const rca = useQuery({
    queryKey: ["anomaly-rca", selectedId],
    queryFn: () => api(`/api/anomalies/${selectedId}/rca`),
    enabled: !!selectedId,
  });

  const items = anomalies.data?.items ?? [];
  const d = detail.data;
  const r = rca.data;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-white">🔍 Diagnose Center</h1>

      <div className="grid grid-cols-12 gap-4 h-[calc(100vh-10rem)]">
        {/* Anomaly List (left) */}
        <div className="col-span-4 bg-gray-800 rounded-xl p-4 overflow-y-auto ">
          <h2 className="text-xs font-semibold text-[#666] uppercase tracking-wider mb-3">
            Anomalies ({items.length})
          </h2>
          <div className="space-y-1">
            {items.map((a: any) => (
              <button
                key={a.id}
                onClick={() => setSelectedId(a.id)}
                className={`w-full text-left py-2.5 px-3 rounded-lg text-sm transition-colors ${
                  selectedId === a.id
                    ? "bg-blue-600/20 text-blue-300 border border-blue-500/30"
                    : "text-[#666] hover:bg-[#383838]/50"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                    a.severity === "critical" ? "bg-red-500" :
                    a.severity === "high" ? "bg-orange-500" :
                    a.severity === "medium" ? "bg-yellow-500" : "bg-blue-500"
                  }`} />
                  <span className="truncate">{a.title || a.anomaly_type}</span>
                </div>
                <p className="text-xs text-[#9b9b9b] mt-0.5 pl-4">
                  {a.created_at ? new Date(a.created_at).toLocaleString() : ""}
                </p>
              </button>
            ))}
          </div>
        </div>

        {/* Detail (right) */}
        <div className="col-span-8 bg-gray-800 rounded-xl p-5 overflow-y-auto ">
          {!selectedId ? (
            <div className="flex items-center justify-center h-full text-[#9b9b9b]">
              Select an anomaly to view details
            </div>
          ) : detail.isLoading ? (
            <div className="flex items-center justify-center h-full text-[#9b9b9b]">
              Loading...
            </div>
          ) : (
            <div className="space-y-6">
              {/* Header */}
              <div>
                <h2 className="text-lg font-semibold text-white">
                  {d?.title || d?.anomaly_type}
                </h2>
                <div className="flex gap-3 mt-2">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                    d?.severity === "critical" ? "bg-red-900/50 text-red-300" :
                    d?.severity === "high" ? "bg-orange-900/50 text-orange-300" :
                    "bg-gray-700 text-[#666]"
                  }`}>{d?.severity}</span>
                  <span className="px-2 py-0.5 rounded text-xs bg-gray-700 text-[#666]">
                    {d?.status}
                  </span>
                </div>
              </div>

              {/* Description */}
              {d?.description && (
                <div>
                  <h3 className="text-xs font-semibold text-[#666] uppercase mb-2">Description</h3>
                  <p className="text-sm text-[#666] leading-relaxed">{d.description}</p>
                </div>
              )}

              {/* RCA Result */}
              {r && (
                <div className="space-y-4">
                  <h3 className="text-xs font-semibold text-[#666] uppercase">Root Cause Analysis</h3>

                  {r.root_cause && (
                    <div className="bg-gray-900/50 rounded-lg p-4">
                      <p className="text-sm font-medium text-orange-300">Root Cause</p>
                      <p className="text-sm text-[#666] mt-1">{r.root_cause}</p>
                    </div>
                  )}

                  {r.confidence !== undefined && (
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-[#666]">Confidence</span>
                      <div className="w-32 bg-gray-700 rounded-full h-2">
                        <div
                          className={`h-2 rounded-full ${
                            r.confidence >= 0.8 ? "bg-green-500" :
                            r.confidence >= 0.5 ? "bg-yellow-500" : "bg-red-500"
                          }`}
                          style={{ width: `${r.confidence * 100}%` }}
                        />
                      </div>
                      <span className="text-xs text-[#666]">{(r.confidence * 100).toFixed(0)}%</span>
                    </div>
                  )}

                  {r.recommendations?.length > 0 && (
                    <div>
                      <p className="text-xs font-semibold text-[#666] uppercase mb-2">Recommendations</p>
                      <ul className="space-y-1">
                        {r.recommendations.map((rec: string, i: number) => (
                          <li key={i} className="text-sm text-[#666] flex gap-2">
                            <span className="text-green-400">→</span>
                            {rec}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              {/* View Full Detail button */}
              <button
                onClick={() => navigate(`/app/issues/${selectedId}`)}
                className="text-sm text-blue-400 hover:text-blue-300 underline"
              >
                View full detail →
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
