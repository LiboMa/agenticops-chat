import { NavLink } from "react-router-dom";
import { cn } from "@/lib/cn";

const NAV_SECTIONS = [
  {
    label: "Ops Hub",
    items: [
      { to: "/app", label: "Overview", end: true, icon: "🏠" },
      { to: "/app/dashboard", label: "Dashboard", end: false, icon: "📊" },
      { to: "/app/issues", label: "Issues", end: false, icon: "🚨" },
      { to: "/app/notifications", label: "Notifications", end: false, icon: "🔔" },
      { to: "/app/notification-logs", label: "Notification Logs", end: false, icon: "📋" },
    ],
  },
  {
    label: "Diagnose",
    items: [
      { to: "/app/diagnose", label: "RCA Overview", end: false, icon: "🔍" },
      { to: "/app/fix-plans", label: "Fix Plans", end: false, icon: "🔧" },
      { to: "/app/network", label: "Network", end: false, icon: "🌐" },
      { to: "/app/resources", label: "Resources", end: false, icon: "📦" },
    ],
  },
  {
    label: "AI Center",
    items: [
      { to: "/app/ai", label: "Memory & Proactive", end: false, icon: "🧠" },
      { to: "/app/chat", label: "Chat", end: false, icon: "💬" },
    ],
  },
  {
    label: "Knowledge",
    items: [
      { to: "/app/knowledge", label: "Overview", end: false, icon: "📚" },
      { to: "/app/knowledge-base", label: "Knowledge Base", end: false, icon: "📖" },
      { to: "/app/reports", label: "Reports", end: false, icon: "📝" },
    ],
  },
  {
    label: "System",
    items: [
      { to: "/app/system", label: "Overview", end: false, icon: "⚙️" },
      { to: "/app/settings", label: "Settings", end: false, icon: "🔩" },
      { to: "/app/schedules", label: "Schedules", end: false, icon: "📅" },
      { to: "/app/audit-log", label: "Audit Log", end: false, icon: "📜" },
    ],
  },
] as const;

export function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 w-56 bg-gray-900 border-r border-gray-800 flex flex-col z-30 overflow-y-auto">
      {/* Logo */}
      <div className="h-14 flex items-center px-5 border-b border-gray-800">
        <span className="text-blue-400 text-lg font-bold tracking-tight">
          ClawOps
        </span>
        <span className="ml-2 text-xs text-gray-500 font-mono">L5</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-3 px-3 space-y-4">
        {NAV_SECTIONS.map((section) => (
          <div key={section.label}>
            <div className="px-3 py-1 text-xs font-semibold text-gray-500 uppercase tracking-wider">
              {section.label}
            </div>
            <div className="space-y-0.5 mt-1">
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-2.5 px-3 py-2 text-sm font-medium rounded-lg transition-colors",
                      isActive
                        ? "bg-gray-800 text-white"
                        : "text-gray-400 hover:bg-gray-800/50 hover:text-gray-200",
                    )
                  }
                >
                  <span className="text-sm">{item.icon}</span>
                  {item.label}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="border-t border-gray-800 px-4 py-3">
        <div className="text-xs text-gray-600">
          ClawOps v0.9.0-beta
        </div>
      </div>
    </aside>
  );
}
