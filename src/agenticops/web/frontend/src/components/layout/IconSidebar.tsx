import { NavLink } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { useStats } from "@/hooks/useStats";
import * as Tooltip from "@radix-ui/react-tooltip";

const NAV_ITEMS = [
  { to: "/app", icon: "grid", labelKey: "nav.dashboard", end: true },
  { to: "/app/chat", icon: "chat", labelKey: "nav.chat", end: false },
  { to: "/app/issues", icon: "clock", labelKey: "nav.issues", end: false, badge: true },
  { to: "/app/schedules", icon: "calendar", labelKey: "nav.schedules", end: false },
  { to: "/app/reports", icon: "file", labelKey: "nav.reports", end: false },
  { to: "/app/agent-metrics", icon: "barchart", labelKey: "nav.agentMetrics", end: false },
  { to: "/app/skills", icon: "puzzle", labelKey: "nav.skills", end: false },
] as const;

const ICON_PATHS: Record<string, string> = {
  grid: "M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z",
  chat: "M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z",
  clock: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z",
  calendar: "M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z",
  file: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z",
  barchart: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z",
  puzzle: "M11 4a2 2 0 114 0v1a1 1 0 001 1h3a2 2 0 012 2v3a1 1 0 01-1 1 2 2 0 100 4 1 1 0 011 1v3a2 2 0 01-2 2h-3a1 1 0 01-1-1 2 2 0 10-4 0 1 1 0 01-1 1H7a2 2 0 01-2-2v-3a1 1 0 011-1 2 2 0 100-4 1 1 0 01-1-1V7a2 2 0 012-2h3a1 1 0 001-1V4z",
  cog: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.573-1.066z",
};

function SvgIcon({ d }: { d: string }) {
  return (
    <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d={d} />
    </svg>
  );
}

export function IconSidebar() {
  const { t } = useLocale();
  const stats = useStats();
  const hasOpenIssues = (stats.data?.open_anomalies ?? 0) > 0;

  return (
    <Tooltip.Provider delayDuration={200}>
      <aside className="fixed inset-y-0 left-0 w-[52px] bg-card border-r border-border flex flex-col z-30">
        {/* Logo */}
        <div className="h-[52px] flex items-center justify-center border-b border-border">
          <img src={`${import.meta.env.BASE_URL}logo-icon.svg`} alt="AgenticOps" className="w-8 h-8 drop-shadow-md" />
        </div>

        {/* Nav icons */}
        <nav className="flex-1 flex flex-col items-center py-3 gap-1">
          {NAV_ITEMS.map((item) => (
            <Tooltip.Root key={item.to}>
              <Tooltip.Trigger asChild>
                <NavLink
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `relative w-10 h-10 flex items-center justify-center rounded-lg transition-colors ${
                      isActive
                        ? "bg-primary/10 text-primary border-l-2 border-primary"
                        : "text-muted-foreground hover:text-foreground hover:bg-accent"
                    }`
                  }
                >
                  <SvgIcon d={ICON_PATHS[item.icon]} />
                  {"badge" in item && item.badge && hasOpenIssues && (
                    <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-red-500" />
                  )}
                </NavLink>
              </Tooltip.Trigger>
              <Tooltip.Portal>
                <Tooltip.Content
                  side="right"
                  sideOffset={8}
                  className="px-2.5 py-1.5 text-xs font-medium text-foreground bg-card border border-border rounded-md shadow-lg z-50"
                >
                  {t(item.labelKey)}
                  <Tooltip.Arrow className="fill-card" />
                </Tooltip.Content>
              </Tooltip.Portal>
            </Tooltip.Root>
          ))}
        </nav>

        {/* Settings bottom */}
        <div className="flex flex-col items-center pb-3 gap-1 border-t border-border pt-3">
          <Tooltip.Root>
            <Tooltip.Trigger asChild>
              <NavLink
                to="/app/settings"
                className={({ isActive }) =>
                  `w-10 h-10 flex items-center justify-center rounded-lg transition-colors ${
                    isActive
                      ? "bg-primary/10 text-primary border-l-2 border-primary"
                      : "text-muted-foreground hover:text-foreground hover:bg-accent"
                  }`
                }
              >
                <SvgIcon d={ICON_PATHS.cog} />
              </NavLink>
            </Tooltip.Trigger>
            <Tooltip.Portal>
              <Tooltip.Content
                side="right"
                sideOffset={8}
                className="px-2.5 py-1.5 text-xs font-medium text-foreground bg-card border border-border rounded-md shadow-lg z-50"
              >
                {t("nav.settings")}
                <Tooltip.Arrow className="fill-card" />
              </Tooltip.Content>
            </Tooltip.Portal>
          </Tooltip.Root>
          <span className="text-[8px] text-muted-foreground/50 font-mono">v1.0</span>
        </div>
      </aside>
    </Tooltip.Provider>
  );
}
