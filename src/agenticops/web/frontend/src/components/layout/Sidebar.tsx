import { NavLink } from "react-router-dom";
import { cn } from "@/lib/cn";

const NAV_ITEMS = [
  { to: "/app", label: "Dashboard", end: true, icon: "grid" },
  { to: "/app/chat", label: "Chat", end: false, icon: "chat" },
  { to: "/app/resources", label: "Resources", end: false, icon: "server" },
  { to: "/app/issues", label: "Issues", end: false, icon: "alert" },
  { to: "/app/fix-plans", label: "Fix Plans", end: false, icon: "wrench" },
  { to: "/app/reports", label: "Reports", end: false, icon: "file" },
] as const;

const MANAGE_ITEMS = [
  { to: "/app/schedules", label: "Schedules", end: false, icon: "calendar" },
  { to: "/app/notifications", label: "Notifications", end: false, icon: "bell" },
  { to: "/app/audit", label: "Audit Log", end: false, icon: "clipboard" },
  { to: "/app/kb", label: "Knowledge Base", end: false, icon: "book" },
  { to: "/app/skills", label: "Skills", end: false, icon: "puzzle" },
] as const;

function I({ d }: { d: string }) {
  return (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d={d} />
    </svg>
  );
}

const ICON_PATHS: Record<string, string> = {
  grid: "M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z",
  chat: "M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z",
  server: "M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01",
  alert: "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z",
  wrench: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.573-1.066z",
  file: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z",
  globe: "M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9",
  calendar: "M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z",
  bell: "M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9",
  cog: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.573-1.066z",
  clipboard: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01",
  book: "M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253",
  puzzle: "M11 4a2 2 0 114 0v1a1 1 0 001 1h3a2 2 0 012 2v3a1 1 0 01-1 1h-1a2 2 0 100 4h1a1 1 0 011 1v3a2 2 0 01-2 2h-3a1 1 0 01-1-1v-1a2 2 0 10-4 0v1a1 1 0 01-1 1H6a2 2 0 01-2-2v-3a1 1 0 00-1-1H2a2 2 0 110-4h1a1 1 0 001-1V8a2 2 0 012-2h3a1 1 0 001-1V4z",
  cloud: "M2.25 15a4.5 4.5 0 004.5 4.5H18a3.75 3.75 0 001.332-7.257 3 3 0 00-3.758-3.848 5.25 5.25 0 00-10.233 2.33A4.502 4.502 0 002.25 15z",
};

function NavItem({ to, label, icon, end }: { to: string; label: string; icon: string; end: boolean }) {
  const path = ICON_PATHS[icon];
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-2.5 px-3 py-1.5 text-[13px] font-medium rounded-md transition-colors",
          isActive
            ? "bg-primary-50 text-primary-700"
            : "text-muted-foreground hover:text-foreground hover:bg-accent",
        )
      }
    >
      {path ? <I d={path} /> : null}
      {label}
    </NavLink>
  );
}

export function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 w-56 bg-card border-r flex flex-col z-30">
      <div className="h-12 flex items-center px-5 border-b gap-2.5">
        {/* Animated logo mark */}
        <div className="relative flex items-center justify-center w-7 h-7 rounded-lg bg-gradient-to-br from-primary-500 to-primary-700 dark:from-primary-400 dark:to-primary-600 shadow-md shadow-primary-500/25 dark:shadow-primary-400/20">
          <svg viewBox="0 0 24 24" fill="none" className="w-4 h-4 text-white" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2L2 7l10 5 10-5-10-5z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
          <div className="absolute inset-0 rounded-lg bg-white/10 animate-pulse" style={{ animationDuration: "3s" }} />
        </div>
        {/* Wordmark */}
        <div className="flex items-baseline gap-0">
          <span className="text-[15px] font-bold tracking-tight bg-gradient-to-r from-primary-600 to-primary-400 dark:from-primary-300 dark:to-primary-500 bg-clip-text text-transparent">
            Agentic
          </span>
          <span className="text-[15px] font-bold tracking-tight text-foreground/80">
            Ops
          </span>
        </div>
      </div>

      <nav className="flex-1 py-2 px-3 overflow-y-auto space-y-0.5">
        {NAV_ITEMS.map((item) => (
          <NavItem key={item.to} {...item} />
        ))}

        <div className="my-3" />
        <p className="px-3 text-[10px] font-medium text-muted-foreground uppercase tracking-[0.12em] mb-1">
          Manage
        </p>
        {MANAGE_ITEMS.map((item) => (
          <NavItem key={item.to} {...item} />
        ))}
      </nav>

      <div className="border-t px-3 py-3 space-y-1">
        <NavItem to="/app/settings" label="Settings" icon="cog" end={false} />
        <div className="px-3 pt-1">
          <span className="text-[10px] text-muted-foreground/50 font-mono">v1.0.0</span>
        </div>
      </div>
    </aside>
  );
}
