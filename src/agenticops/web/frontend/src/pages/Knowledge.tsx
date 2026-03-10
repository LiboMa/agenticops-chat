import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

type Tab = "kb" | "sops" | "skills";

export default function Knowledge() {
  const [tab, setTab] = useState<Tab>("kb");
  const [query, setQuery] = useState("");

  const kbResults = useQuery({
    queryKey: ["kb-search", query],
    queryFn: () => api(`/api/knowledge/search?q=${encodeURIComponent(query)}`),
    enabled: tab === "kb" && query.length > 2,
  });

  const sops = useQuery({
    queryKey: ["learning-sops"],
    queryFn: () => api("/api/learning/sops"),
    enabled: tab === "sops",
  });

  const skills = useQuery({
    queryKey: ["learning-skills"],
    queryFn: () => api("/api/learning/skills"),
    enabled: tab === "skills",
  });

  const tabs: { key: Tab; label: string; icon: string }[] = [
    { key: "kb", label: "KB Search", icon: "🔎" },
    { key: "sops", label: "SOPs", icon: "📝" },
    { key: "skills", label: "Skills", icon: "⚡" },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">📚 Knowledge Center</h1>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-800 rounded-lg p-1 w-fit">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
              tab === t.key
                ? "bg-gray-700 text-white"
                : "text-gray-400 hover:text-gray-200"
            }`}
          >
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {/* KB Search */}
      {tab === "kb" && (
        <div className="space-y-4">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search knowledge base..."
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40"
          />
          {kbResults.data?.results?.map((r: any, i: number) => (
            <div key={i} className="bg-gray-800 rounded-xl p-4 shadow-lg">
              <p className="text-sm text-gray-200">{r.content || r.text}</p>
              {r.score && (
                <span className="text-xs text-gray-500 mt-2 inline-block">
                  relevance: {(r.score * 100).toFixed(0)}%
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* SOPs */}
      {tab === "sops" && (
        <div className="space-y-3">
          {sops.data?.sops?.length > 0 ? (
            sops.data.sops.map((s: any, i: number) => (
              <div key={i} className="bg-gray-800 rounded-xl p-4 shadow-lg">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-200">{s.filename}</span>
                  <span className="text-xs text-gray-500">{s.size} bytes</span>
                </div>
                <p className="text-xs text-gray-400 mt-2 whitespace-pre-wrap">{s.preview?.substring(0, 300)}</p>
              </div>
            ))
          ) : (
            <p className="text-sm text-gray-500 text-center py-8">
              No auto-generated SOPs yet — SOPAutoWriter will create them after RCA
            </p>
          )}
        </div>
      )}

      {/* Skills */}
      {tab === "skills" && (
        <div className="space-y-3">
          {skills.data?.skills?.length > 0 ? (
            skills.data.skills.map((s: any, i: number) => (
              <div key={i} className="bg-gray-800 rounded-xl p-4 shadow-lg">
                <p className="text-sm text-gray-200">{s.content?.substring(0, 200)}</p>
                <div className="flex gap-3 mt-2">
                  <span className="text-xs text-gray-500">
                    confidence: {(s.confidence * 100).toFixed(0)}%
                  </span>
                  <span className="text-xs text-gray-500">{s.created_at}</span>
                </div>
              </div>
            ))
          ) : (
            <p className="text-sm text-gray-500 text-center py-8">
              No skill gaps detected yet — SkillGapDetector runs after RCA
            </p>
          )}
        </div>
      )}
    </div>
  );
}
