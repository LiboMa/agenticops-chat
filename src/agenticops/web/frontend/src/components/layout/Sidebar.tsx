import { NavLink } from "react-router-dom";
import { cn } from "@/lib/cn";

const NAV_ITEMS = [
  { to: "/app", label: "Dashboard", end: true },
  { to: "/app/chat", label: "Chat", end: false },
  { to: "/app/issues", label: "Issues", end: false },
  { to: "/app/fix-plans", label: "Fix Plans", end: false },
  { to: "/app/resources", label: "Resources", end: false },
  { to: "/app/network", label: "Network", end: false },
  { to: "/app/reports", label: "Reports", end: false },
] as const;

const MANAGE_ITEMS = [
  { to: "/app/schedules", label: "Schedules", end: false },
  { to: "/app/notifications", label: "Notifications", end: false },
  { to: "/app/audit-log", label: "Audit Log", end: false },
  { to: "/app/knowledge-base", label: "Knowledge Base", end: false },
] as const;

const L5_ITEMS = [
  { to: "/app/ai", label: "AI Center", end: false },
  { to: "/app/diagnose", label: "Diagnose", end: false },
  { to: "/app/knowledge", label: "Knowledge", end: false },
] as const;

function NavItem({ to, label, end }: { to: string; label: string; end: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          "block px-3 py-2 text-sm rounded-lg transition-colors duration-150",
          isActive
            ? "bg-[#2f2f2f] text-[#ececec] font-medium"
            : "text-[#9b9b9b] hover:bg-[#383838] hover:text-[#ececec]",
        )
      }
    >
      {label}
    </NavLink>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-3 pt-4 pb-1 text-[11px] font-medium text-[#666] uppercase tracking-wider">
      {children}
    </p>
  );
}

export function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 w-[260px] bg-[#171717] flex flex-col z-30">
      {/* Logo */}
      <div className="h-14 flex items-center px-4 border-b border-[#424242]">
        <span className="text-[#ececec] text-base font-semibold tracking-tight">
          ClawOps
        </span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-2 px-2 space-y-0.5 overflow-y-auto">
        {NAV_ITEMS.map((item) => (
          <NavItem key={item.to} {...item} />
        ))}

        <SectionLabel>Manage</SectionLabel>
        {MANAGE_ITEMS.map((item) => (
          <NavItem key={item.to} {...item} />
        ))}

        <SectionLabel>AI Ops</SectionLabel>
        {L5_ITEMS.map((item) => (
          <NavItem key={item.to} {...item} />
        ))}
      </nav>

      {/* Footer */}
      <div className="border-t border-[#424242] px-2 py-2">
        <NavLink
          to="/app/settings"
          className={({ isActive }) =>
            cn(
              "block px-3 py-2 text-sm rounded-lg transition-colors duration-150",
              isActive
                ? "bg-[#2f2f2f] text-[#ececec] font-medium"
                : "text-[#9b9b9b] hover:bg-[#383838] hover:text-[#ececec]",
            )
          }
        >
          Settings
        </NavLink>
        <div className="px-3 pt-1">
          <span className="text-[11px] text-[#666]">v0.9.0-beta</span>
        </div>
      </div>
    </aside>
  );
}
