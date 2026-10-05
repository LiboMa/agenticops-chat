import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useLocale } from "@/i18n/LocaleContext";
import { FONT_SIZES, useTheme, type FontSize } from "@/hooks/useTheme";
import { useAuth } from "@/hooks/useAuth";
import { breadcrumbFor } from "@/lib/navGroups";
import { savePreferences } from "@/lib/preferences";
import { HomePrefsDialog, MobileNav } from "./Sidebar";

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

function initials(name: string | null | undefined, email: string | null | undefined): string {
  const src = (name || email || "?").trim();
  const words = src.split(/[\s@._-]+/).filter(Boolean);
  return ((words[0]?.[0] ?? "?") + (words[1]?.[0] ?? "")).toUpperCase();
}

/** The workspace top bar: breadcrumb (hidden ≤800px, where the menu takes its place), search, the language
 *  switch and the avatar menu (account, theme, font size, home, sign out — on phones too). */
export function TopBar({ onSearch }: { onSearch: () => void }) {
  const { t, locale, setLocale } = useLocale();
  const { pathname } = useLocation();
  const crumb = breadcrumbFor(pathname);
  const section = crumb.sectionKey ? t(crumb.sectionKey) : t("notFound.title");

  useEffect(() => {
    document.title = `AgenticOps · ${section}`;
  }, [section]);

  const pickLocale = (next: "zh" | "en") => {
    if (next === locale) return;
    setLocale(next);
    void savePreferences({ locale: next });  // the user's choice follows them to their other browsers
  };

  return (
    <header className="sticky top-0 z-20 flex h-[var(--topbar-h)] items-center justify-between gap-4 border-b border-border bg-card px-7 max-[1350px]:px-5 max-[800px]:px-3.5">
      <div className="flex min-w-0 items-center gap-2.5 text-xs text-muted-foreground">
        <MobileNav />
        <nav aria-label={t("topbar.breadcrumb")} className="flex min-w-0 items-center gap-2.5 max-[800px]:hidden">
          <span>AgenticOps</span>
          <span aria-hidden="true">/</span>
          <b className="truncate font-medium text-foreground">{section}</b>
          {crumb.object && (<><span aria-hidden="true">/</span><span className="font-mono text-foreground">{crumb.object}</span></>)}
        </nav>
      </div>

      <div className="flex shrink-0 items-center gap-3 max-[1100px]:gap-2">
        <button type="button" onClick={onSearch} aria-label={t("topbar.search")}
                className="flex w-[205px] items-center gap-2 rounded-[5px] border border-border bg-canvas px-2.5 py-1.5 text-xs text-muted-foreground hover:border-primary/40 max-[1350px]:w-[165px] max-[1100px]:w-auto max-[600px]:hidden">
          <svg className="h-3.5 w-3.5 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="11" cy="11" r="7" /><path strokeLinecap="round" d="M20 20l-3.5-3.5" />
          </svg>
          <span className="truncate max-[1100px]:hidden">{t("topbar.searchPlaceholder")}</span>
          <kbd className="ml-auto text-[10px] text-muted-foreground/80 max-[1100px]:hidden">{isMac ? "⌘K" : "Ctrl K"}</kbd>
        </button>

        <div role="group" aria-label="Language / 语言" className="flex rounded-[5px] border border-border p-0.5">
          {(["zh", "en"] as const).map((l) => (
            <button key={l} type="button" onClick={() => pickLocale(l)} aria-pressed={locale === l}
                    className={`rounded-[3px] px-2 py-1 text-[11px] max-[600px]:px-1.5 max-[600px]:text-[10px] ${
                      locale === l ? "bg-selected font-semibold text-primary" : "text-muted-foreground hover:text-foreground"}`}>
              {l === "zh" ? "中文" : "English"}
            </button>
          ))}
        </div>

        <AvatarMenu />
      </div>
    </header>
  );
}

function AvatarMenu() {
  const { t } = useLocale();
  const { theme, toggle, fontSize, setFontSize } = useTheme();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [homeOpen, setHomeOpen] = useState(false);
  const item = "flex cursor-pointer select-none items-center justify-between gap-3 rounded px-2.5 py-1.5 text-sm text-foreground outline-none data-[highlighted]:bg-selected";

  return (
    <>
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button type="button" aria-label={t("topbar.account")}
                  className="flex h-[29px] w-[29px] items-center justify-center rounded-full bg-secondary text-[10px] font-semibold text-muted-foreground hover:bg-selected hover:text-primary">
            {initials(user?.name, user?.email)}
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content align="end" sideOffset={6}
                                className="z-50 min-w-[220px] rounded-md border border-border bg-card p-1.5 shadow-lg animate-[slideInRight_0.2s_ease-out]">
            {user && <DropdownMenu.Label className="truncate px-2.5 py-1.5 text-xs text-muted-foreground">{user.email}</DropdownMenu.Label>}
            <DropdownMenu.Separator className="my-1 h-px bg-border" />
            <DropdownMenu.Item className={item} onSelect={(e) => { e.preventDefault(); toggle(); }}>
              {t("topbar.theme")}
              <span className="text-xs text-muted-foreground">{theme === "dark" ? t("topbar.themeDark") : t("topbar.themeLight")}</span>
            </DropdownMenu.Item>
            <div className="px-2.5 py-1.5">
              <p className="mb-1 text-sm text-foreground">{t("topbar.fontSize")}</p>
              <div role="radiogroup" aria-label={t("topbar.fontSize")} className="flex gap-1">
                {(Object.keys(FONT_SIZES) as FontSize[]).map((size) => (
                  <button key={size} type="button" role="radio" aria-checked={fontSize === size} onClick={() => setFontSize(size)}
                          className={`flex-1 rounded border px-2 py-1 text-xs ${fontSize === size ? "border-primary bg-selected text-primary" : "border-border text-muted-foreground"}`}>
                    {t(`topbar.font.${size}`)}
                  </button>
                ))}
              </div>
            </div>
            <DropdownMenu.Item className={item} onSelect={() => setHomeOpen(true)}>{t("home.prefsTitle")}</DropdownMenu.Item>
            <DropdownMenu.Separator className="my-1 h-px bg-border" />
            <DropdownMenu.Item className={item} onSelect={async () => { await logout(); navigate("/app/login", { replace: true }); }}>
              {t("topbar.signOut")}
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
      <HomePrefsDialog open={homeOpen} onOpenChange={setHomeOpen} />
    </>
  );
}
