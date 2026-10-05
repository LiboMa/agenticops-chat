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

/** "The last item you opened is gone or no longer yours to see" — shown once after a failed restore. */
export function RestoreNotice() {
  const { t } = useLocale();
  const { state } = useLocation();
  const [open, setOpen] = useState(Boolean((state as { restoreNotice?: boolean } | null)?.restoreNotice));
  useEffect(() => {
    if ((state as { restoreNotice?: boolean } | null)?.restoreNotice) setOpen(true);
  }, [state]);
  if (!open) return null;
  return (
    <div role="status" className="mb-4 flex items-start justify-between gap-3 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
      <span>{t("home.restoreNotice")}</span>
      <button type="button" onClick={() => setOpen(false)} className="text-xs underline">{t("home.dismiss")}</button>
    </div>
  );
}
