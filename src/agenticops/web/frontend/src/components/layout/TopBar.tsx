import { useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import { formatUtcClock } from "@/lib/formatDate";

const ROUTE_LABELS: Record<string, string> = {
  "/app": "Dashboard",
  "/app/resources": "Resources",
  "/app/issues": "Issues",
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
  const isDetail = location.pathname.match(/\/app\/issues\/(\d+)/);

  return (
    <header className="h-14 bg-[#2f2f2f] border-b border-[#424242] flex items-center justify-between px-6 sticky top-0 z-20">
      <nav className="flex items-center gap-1.5 text-sm">
        <span className="text-[#666]">AgenticAIOps</span>
        <span className="text-[#666]">/</span>
        <span className="font-medium text-[#ececec]">{pageLabel}</span>
        {isDetail && (
          <>
            <span className="text-[#666]">/</span>
            <span className="text-[#9b9b9b]">#{isDetail[1]}</span>
          </>
        )}
      </nav>
      <div className="text-sm text-[#666] font-mono">
        {formatUtcClock(now)}
      </div>
    </header>
  );
}
