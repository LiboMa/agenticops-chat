import { NavLink } from "react-router-dom";
import { cn } from "@/lib/cn";

const MAIN_NAV = [
  { to: "/app", label: "Ops Hub", end: true, icon: "🏠" },
  { to: "/app/issues", label: "Issues", end: false, icon: "⚠️" },
  { to: "/app/diagnose", label: "Diagnose", end: false, icon: "🔍" },
  { to: "/app/ai", label: "AI Center", end: false, icon: "🧠" },
  { to: "/app/knowledge", label: "Knowledge", end: false, icon: "📚" },
  { to: "/app/system", label: "System", end: false, icon: "⚙️" },
] as const;

export function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 w-56 bg-gray-900 border-r border-gray-800 flex flex-col z-30">
      {/* Logo */}
      <div className="h-14 flex items-center px-5 border-b border-gray-800">
        <span className="text-blue-400 text-lg font-bold tracking-tight">
          ClawOps
        </span>
        <span className="ml-2 text-xs text-gray-500 font-mono">L5</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-4 px-3 space-y-1">
        {MAIN_NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 px-3 py-2.5 text-sm font-medium rounded-lg transition-colors",
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
