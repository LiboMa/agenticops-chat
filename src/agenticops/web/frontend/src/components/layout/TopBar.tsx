import { useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import { formatUtcClock } from "@/lib/formatDate";

const ROUTE_LABELS: Record<string, string> = {
  "/app": "Dashboard",
  "/app/resources": "Resources",
  "/app/anomalies": "Anomalies",
  "/app/reports": "Reports",
  "/app/network": "Network",
  "/app/accounts": "Accounts",
  "/app/audit": "Audit Log",
};

export function TopBar() {
  const location = useLocation();
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(timer);
  }, []);

  // Determine breadcrumb label
  const basePath = "/" + location.pathname.split("/").slice(1, 3).join("/");
  const pageLabel = ROUTE_LABELS[basePath] ?? "Detail";

  // Check for detail routes
  const isDetail = location.pathname.match(/\/app\/anomalies\/(\d+)/);

  return (
    <header className="h-16 bg-white border-b border-gray-200 flex items-center justify-between px-6 sticky top-0 z-20">
      <nav className="flex items-center gap-2 text-sm">
        <span className="text-gray-400">AgenticAIOps</span>
        <span className="text-gray-300">/</span>
        <span className="font-medium text-gray-800">{pageLabel}</span>
        {isDetail && (
          <>
            <span className="text-gray-300">/</span>
            <span className="text-gray-600">#{isDetail[1]}</span>
          </>
        )}
      </nav>
      <div className="text-sm text-gray-500 font-mono">
        {formatUtcClock(now)}
      </div>
    </header>
  );
}
