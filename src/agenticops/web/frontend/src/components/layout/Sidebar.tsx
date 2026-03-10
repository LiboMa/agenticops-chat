import { NavLink } from "react-router-dom";
import { cn } from "@/lib/cn";

const NAV_ITEMS = [
  { to: "/app", label: "Dashboard", end: true, icon: "📊" },
  { to: "/app/chat", label: "Chat", end: false, icon: "💬" },
  { to: "/app/resources", label: "Resources", end: false, icon: "📦" },
  { to: "/app/issues", label: "Issues", end: false, icon: "🚨" },
  { to: "/app/fix-plans", label: "Fix Plans", end: false, icon: "🔧" },
  { to: "/app/reports", label: "Reports", end: false, icon: "📝" },
  { to: "/app/network", label: "Network", end: false, icon: "🌐" },
] as const;

const MANAGE_ITEMS = [
  { to: "/app/schedules", label: "Schedules", end: false, icon: "📅" },
  { to: "/app/notifications", label: "Notifications", end: false, icon: "🔔" },
  { to: "/app/audit-log", label: "Audit Log", end: false, icon: "📋" },
  { to: "/app/knowledge-base", label: "Knowledge Base", end: false, icon: "📖" },
] as const;

const NEW_ITEMS = [
  { to: "/app/ai", label: "AI Center", end: false, icon: "🧠" },
  { to: "/app/diagnose", label: "Diagnose", end: false, icon: "🔍" },
  { to: "/app/knowledge", label: "Knowledge", end: false, icon: "📚" },
] as const;

function NavSection({ title, items }: { title?: string; items: readonly { to: string; label: string; end: boolean; icon: string }[] }) {
  return (
    <>
      {title && (
        <p className="px-3 text-xs font-medium text-gray-500 uppercase tracking-wider mb-1 mt-3">
          {title}
        </p>
      )}
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-lg transition-colors",
              isActive
                ? "bg-gray-800 text-white"
                : "text-gray-400 hover:bg-gray-800/50 hover:text-gray-200",
            )
          }
        >
          <span className="text-base">{item.icon}</span>
          {item.label}
        </NavLink>
      ))}
    </>
  );
}

export function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 w-56 bg-gray-900 border-r border-gray-800 flex flex-col z-30">
      {/* Logo */}
      <div className="h-14 flex items-center px-5 border-b border-gray-800">
        <span className="text-blue-400 text-lg font-bold tracking-tight">
          ClawOps
        </span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-3 px-3 space-y-0.5 overflow-y-auto">
        <NavSection items={NAV_ITEMS} />

        <div className="border-t border-gray-800 my-3" />
        <NavSection title="Manage" items={MANAGE_ITEMS} />

        <div className="border-t border-gray-800 my-3" />
        <NavSection title="L5 New" items={NEW_ITEMS} />
      </nav>

      {/* Footer */}
      <div className="border-t border-gray-800 px-3 py-3">
        <NavLink
          to="/app/settings"
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-lg transition-colors",
              isActive
                ? "bg-gray-800 text-white"
                : "text-gray-400 hover:bg-gray-800/50 hover:text-gray-200",
            )
          }
        >
          <span className="text-base">⚙️</span>
          Settings
        </NavLink>
        <div className="px-3 pt-1">
          <span className="text-xs text-gray-600">ClawOps v0.9.0-beta</span>
        </div>
      </div>
    </aside>
  );
}
