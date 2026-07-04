import { NavLink } from "react-router-dom";
import * as Tooltip from "@radix-ui/react-tooltip";
import { usePersistedState } from "@/hooks/usePersistedState";
import { useLocale } from "@/i18n/LocaleContext";
import { NavItems, ICON_PATHS, SvgIcon } from "./NavItems";

export function IconSidebar() {
  const { t } = useLocale();
  const [expanded, setExpanded] = usePersistedState<boolean>("aiops-nav-expanded", false);

  return (
    <Tooltip.Provider delayDuration={200}>
      <aside
        className={`fixed inset-y-0 left-0 bg-card border-r border-border flex flex-col z-30 transition-[width] duration-200 ${
          expanded ? "w-[200px]" : "w-[52px]"
        }`}
      >
        {/* Logo */}
        <div className={`h-[52px] flex items-center border-b border-border ${expanded ? "px-3 gap-2" : "justify-center"}`}>
          <img src={`${import.meta.env.BASE_URL}logo-icon.svg`} alt="AgenticOps" className="w-8 h-8 drop-shadow-md shrink-0" />
          {expanded && <span className="text-sm font-semibold text-foreground truncate">AgenticOps</span>}
        </div>

        {/* Sortable nav */}
        <NavItems expanded={expanded} />

        {/* Bottom: settings + collapse toggle */}
        <div className={`flex flex-col pb-3 gap-1 border-t border-border pt-3 ${expanded ? "px-2" : "items-center"}`}>
          <NavLink
            to="/app/settings"
            className={({ isActive }) =>
              `flex items-center rounded-lg transition-colors ${
                expanded ? "gap-3 px-3 h-10 w-full" : "w-10 h-10 justify-center"
              } ${
                isActive
                  ? "bg-primary/10 text-primary border-l-2 border-primary"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent"
              }`
            }
          >
            <SvgIcon d={ICON_PATHS.cog} />
            {expanded && <span className="text-sm truncate">{t("nav.settings")}</span>}
          </NavLink>
          <button
            onClick={() => setExpanded(!expanded)}
            className={`flex items-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors ${
              expanded ? "gap-3 px-3 h-10 w-full" : "w-10 h-10 justify-center"
            }`}
            title={expanded ? t("nav.collapse") : t("nav.expand")}
          >
            <svg className={`h-5 w-5 shrink-0 transition-transform ${expanded ? "" : "rotate-180"}`} fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
            </svg>
            {expanded && <span className="text-sm truncate">{t("nav.collapse")}</span>}
          </button>
          {!expanded && <span className="text-[8px] text-muted-foreground/50 font-mono">v1.0</span>}
        </div>
      </aside>
    </Tooltip.Provider>
  );
}
