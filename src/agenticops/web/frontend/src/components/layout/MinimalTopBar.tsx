import { useLocation } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { useTheme } from "@/hooks/useTheme";

const ROUTE_LABELS: Record<string, string> = {
  "/app": "nav.dashboard",
  "/app/chat": "nav.chat",
  "/app/issues": "nav.issues",
  "/app/schedules": "nav.schedules",
  "/app/reports": "nav.reports",
  "/app/settings": "nav.settings",
};

export function MinimalTopBar() {
  const location = useLocation();
  const { t, locale, setLocale } = useLocale();
  const { theme, toggle } = useTheme();

  const segments = location.pathname.replace(/\/+$/, "").split("/");
  const basePath = "/" + segments.slice(1, 3).join("/");
  const labelKey = ROUTE_LABELS[basePath] ?? "nav.dashboard";

  return (
    <header className="h-9 border-b border-border flex items-center justify-between px-4 sticky top-0 z-20 bg-background/80 backdrop-blur-sm">
      <span className="text-sm font-medium text-foreground">{t(labelKey)}</span>
      <div className="flex items-center gap-1.5">
        {/* Locale toggle */}
        <button
          onClick={() => setLocale(locale === "en" ? "zh" : "en")}
          className="px-2 py-0.5 text-[11px] font-medium text-muted-foreground hover:text-foreground bg-secondary hover:bg-muted border border-border rounded transition-colors"
        >
          {locale === "en" ? "CN" : "EN"}
        </button>
        {/* Theme toggle */}
        <button
          onClick={toggle}
          className="w-7 h-7 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
          title={theme === "light" ? "Switch to dark" : "Switch to light"}
        >
          {theme === "light" ? (
            <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
            </svg>
          ) : (
            <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
            </svg>
          )}
        </button>
      </div>
    </header>
  );
}
