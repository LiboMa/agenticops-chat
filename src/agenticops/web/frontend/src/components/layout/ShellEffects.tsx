import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { useBootstrap } from "@/hooks/useBootstrap";
import { useLocale } from "@/i18n/LocaleContext";
import { flushOnPageHide, recordLastRoute, savePreferences } from "@/lib/preferences";

/** The shell's background duties: keep the UI language and the server preference in step (never echoing a
 *  server value back), remember the last allow-listed place for "resume", and flush it as the page goes. */
export function ShellEffects() {
  const boot = useBootstrap();
  const { locale, setLocale } = useLocale();
  const { pathname } = useLocation();
  const synced = useRef(false);

  useEffect(() => {
    const prefs = boot.data?.preferences;
    if (!prefs || synced.current) return;
    synced.current = true;
    if (prefs.revision === 1) void savePreferences({ locale });  // never saved: this browser's language wins
    else if (prefs.locale !== locale) setLocale(prefs.locale);     // saved: apply it, no write back
  }, [boot.data, locale, setLocale]);

  useEffect(() => {
    recordLastRoute(pathname);
  }, [pathname]);

  useEffect(() => {
    window.addEventListener("pagehide", flushOnPageHide);
    return () => window.removeEventListener("pagehide", flushOnPageHide);
  }, []);

  return null;
}

/** "The last item you opened is gone or no longer yours to see" — a toast for the one navigation that carried
 *  it (it belongs to that history entry, so it never follows you to the next page), over the page, not in it. */
export function RestoreNotice() {
  const { t } = useLocale();
  const location = useLocation();
  const [dismissed, setDismissed] = useState<string | null>(null);
  const carried = Boolean((location.state as { restoreNotice?: boolean } | null)?.restoreNotice);
  if (!carried || dismissed === location.key) return null;
  const setOpen = (_: boolean) => setDismissed(location.key);
  return (
    <div role="status" className="fixed left-1/2 top-[calc(var(--topbar-h)+12px)] z-40 flex w-[min(560px,calc(100vw-30px))] -translate-x-1/2 items-start justify-between gap-3 rounded-md border border-amber-500/40 bg-amber-50 px-3 py-2 text-sm text-amber-800 shadow-lg dark:bg-amber-950 dark:text-amber-300">
      <span>{t("home.restoreNotice")}</span>
      <button type="button" onClick={() => setOpen(false)} className="text-xs underline">{t("home.dismiss")}</button>
    </div>
  );
}
