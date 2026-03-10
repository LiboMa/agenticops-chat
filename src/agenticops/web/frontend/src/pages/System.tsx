import { useState } from "react";
import { lazy, Suspense } from "react";
import { Spinner } from "@/components/ui/Spinner";

const Settings = lazy(() => import("@/pages/Settings"));
const Accounts = lazy(() => import("@/pages/Accounts"));
const Schedules = lazy(() => import("@/pages/Schedules"));
const AuditLog = lazy(() => import("@/pages/AuditLog"));

type Tab = "settings" | "accounts" | "schedules" | "audit";

export default function System() {
  const [tab, setTab] = useState<Tab>("settings");

  const tabs: { key: Tab; label: string }[] = [
    { key: "settings", label: "⚙️ Settings" },
    { key: "accounts", label: "🏢 Accounts" },
    { key: "schedules", label: "📅 Schedules" },
    { key: "audit", label: "📋 Audit Log" },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">⚙️ System</h1>

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
            {t.label}
          </button>
        ))}
      </div>

      <Suspense fallback={<Spinner />}>
        {tab === "settings" && <Settings />}
        {tab === "accounts" && <Accounts />}
        {tab === "schedules" && <Schedules />}
        {tab === "audit" && <AuditLog />}
      </Suspense>
    </div>
  );
}
