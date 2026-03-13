import { useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import { formatUtcClock } from "@/lib/formatDate";
import { useTheme } from "@/hooks/useTheme";

const ROUTE_LABELS: Record<string, string> = {
  "/app": "Dashboard",
  "/app/chat": "Chat",
  "/app/resources": "Resources",
  "/app/issues": "Issues",
  "/app/fix-plans": "Fix Plans",
  "/app/reports": "Reports",
  "/app/schedules": "Schedules",
  "/app/notifications": "Notifications",
  "/app/audit": "Audit Log",
  "/app/kb": "Knowledge Base",
  "/app/skills": "Skills",
  "/app/settings": "Settings",
  "/app/accounts": "Accounts",
};

interface TopBarProps {
  onSearchClick?: () => void;
}

export function TopBar({ onSearchClick }: TopBarProps) {
  const location = useLocation();
  const [now, setNow] = useState(new Date());
  const { theme, toggle, fontSize, setFontSize } = useTheme();

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(timer);
  }, []);

  const segments = location.pathname.replace(/\/+$/, "").split("/");
  const basePath = "/" + segments.slice(1, 3).join("/");
  const pageLabel = ROUTE_LABELS[basePath] ?? "Detail";
  const isDetail = location.pathname.match(/\/app\/issues\/(\d+)/);

  return (
    <header className="h-12 border-b flex items-center justify-between px-6 sticky top-0 z-20 bg-background/80 backdrop-blur-sm">
      <nav className="flex items-center gap-1.5 text-[13px]">
        <span className="text-muted-foreground">aiops</span>
        <span className="text-muted-foreground/40">/</span>
        <span className="font-medium">{pageLabel}</span>
        {isDetail && (
          <>
            <span className="text-muted-foreground/40">/</span>
            <span className="text-muted-foreground font-mono">#{isDetail[1]}</span>
          </>
        )}
      </nav>
      <div className="flex items-center gap-1">
        <span className="text-[11px] text-muted-foreground font-mono tracking-wide mr-2">
          {formatUtcClock(now)}
        </span>

        {onSearchClick && (
          <button
            onClick={onSearchClick}
            className="flex items-center gap-1.5 px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground bg-secondary hover:bg-muted border border-border rounded-md transition-colors mr-1"
            title="Search (⌘K)"
          >
            <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <span className="font-mono">⌘K</span>
          </button>
        )}

        {/* Font size selector */}
        <div className="flex items-center border border-border rounded-md overflow-hidden">
          {(["small", "medium", "large"] as const).map((size) => (
            <button
              key={size}
              onClick={() => setFontSize(size)}
              className={`px-2 py-1 text-xs transition-colors ${
                fontSize === size
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent"
              }`}
              title={`Font size: ${size}`}
            >
              {{ small: "A-", medium: "A", large: "A+" }[size]}
            </button>
          ))}
        </div>

        <button
          onClick={toggle}
          className="w-8 h-8 rounded-md flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
          title={theme === "light" ? "Switch to dark" : "Switch to light"}
        >
          {theme === "light" ? (
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
            </svg>
          ) : (
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
            </svg>
          )}
        </button>
      </div>
    </header>
  );
}
