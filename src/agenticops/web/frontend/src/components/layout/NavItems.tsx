import { useState } from "react";
import { NavLink } from "react-router-dom";
import * as Tooltip from "@radix-ui/react-tooltip";
import { usePersistedState } from "@/hooks/usePersistedState";
import { useStats } from "@/hooks/useStats";
import { useLocale } from "@/i18n/LocaleContext";
import { reorderNavIds, moveId } from "@/lib/navOrder";
import { NavPreviewCard } from "./NavPreviewCard";

export const NAV_ITEMS = [
  { id: "dashboard", to: "/app", icon: "grid", labelKey: "nav.dashboard", end: true },
  { id: "chat", to: "/app/chat", icon: "chat", labelKey: "nav.chat", end: false },
  { id: "issues", to: "/app/issues", icon: "clock", labelKey: "nav.issues", end: false, badge: true },
  { id: "schedules", to: "/app/schedules", icon: "calendar", labelKey: "nav.schedules", end: false },
  { id: "reports", to: "/app/reports", icon: "file", labelKey: "nav.reports", end: false },
  { id: "agent-metrics", to: "/app/agent-metrics", icon: "barchart", labelKey: "nav.agentMetrics", end: false },
  { id: "skills", to: "/app/skills", icon: "puzzle", labelKey: "nav.skills", end: false },
  { id: "galaxy", to: "/app/galaxy", icon: "galaxy", labelKey: "nav.galaxy", end: false },
  { id: "security", to: "/app/security", icon: "shield", labelKey: "nav.security", end: false },
] as const;

export const ICON_PATHS: Record<string, string> = {
  grid: "M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z",
  chat: "M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z",
  clock: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z",
  calendar: "M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z",
  file: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z",
  barchart: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z",
  puzzle: "M11 4a2 2 0 114 0v1a1 1 0 001 1h3a2 2 0 012 2v3a1 1 0 01-1 1 2 2 0 100 4 1 1 0 011 1v3a2 2 0 01-2 2h-3a1 1 0 01-1-1 2 2 0 10-4 0 1 1 0 01-1 1H7a2 2 0 01-2-2v-3a1 1 0 011-1 2 2 0 100-4 1 1 0 01-1-1V7a2 2 0 012-2h3a1 1 0 001-1V4z",
  galaxy: "M12 2a10 10 0 100 20 10 10 0 000-20zm0 4a6 6 0 016 6M12 8a4 4 0 00-4 4m4-2a2 2 0 100 4 2 2 0 000-4z",
  shield: "M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z",
  cog: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.573-1.066z",
};

export function SvgIcon({ d }: { d: string }) {
  return (
    <svg className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d={d} />
    </svg>
  );
}

export function NavItems({ expanded }: { expanded: boolean }) {
  const { t } = useLocale();
  const stats = useStats();
  const hasOpenIssues = (stats.data?.open_anomalies ?? 0) > 0;

  const currentIds = NAV_ITEMS.map((i) => i.id as string);
  const [storedOrder, setStoredOrder] = usePersistedState<string[]>("aiops-nav-order", currentIds);
  const order = reorderNavIds(storedOrder, currentIds);
  const items = order.map((id) => NAV_ITEMS.find((i) => i.id === id)!);

  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);

  const onDrop = (targetId: string) => {
    if (dragId) setStoredOrder(moveId(order, dragId, targetId));
    setDragId(null);
    setOverId(null);
  };

  return (
    <nav className={`flex-1 flex flex-col py-3 gap-1 ${expanded ? "px-2" : "items-center"}`}>
      {items.map((item) => (
        <Tooltip.Root key={item.id}>
          <Tooltip.Trigger asChild>
            <div
              draggable={expanded}
              onDragStart={() => setDragId(item.id)}
              onDragOver={(e) => { if (dragId) { e.preventDefault(); setOverId(item.id); } }}
              onDragLeave={() => setOverId((cur) => (cur === item.id ? null : cur))}
              onDrop={() => onDrop(item.id)}
              onDragEnd={() => { setDragId(null); setOverId(null); }}
              className={overId === item.id && dragId !== item.id ? "border-t-2 border-primary" : "border-t-2 border-transparent"}
            >
              <NavLink
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `relative flex items-center rounded-lg transition-colors ${
                    expanded ? "gap-3 px-3 h-10 w-full" : "w-10 h-10 justify-center"
                  } ${
                    isActive
                      ? "bg-primary/10 text-primary border-l-2 border-primary"
                      : "text-muted-foreground hover:text-foreground hover:bg-accent"
                  }`
                }
              >
                <SvgIcon d={ICON_PATHS[item.icon]} />
                {expanded && <span className="text-sm truncate">{t(item.labelKey)}</span>}
                {"badge" in item && item.badge && hasOpenIssues && (
                  <span className={`absolute w-2 h-2 rounded-full bg-red-500 ${expanded ? "top-2 left-7" : "top-1.5 right-1.5"}`} />
                )}
              </NavLink>
            </div>
          </Tooltip.Trigger>
          <Tooltip.Portal>
            <Tooltip.Content
              side="right"
              sideOffset={8}
              className="px-2.5 py-1.5 bg-card border border-border rounded-md shadow-lg z-50"
            >
              <NavPreviewCard id={item.id} labelKey={item.labelKey} />
              <Tooltip.Arrow className="fill-card" />
            </Tooltip.Content>
          </Tooltip.Portal>
        </Tooltip.Root>
      ))}
    </nav>
  );
}
