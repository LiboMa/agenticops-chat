import { useLocale } from "@/i18n/LocaleContext";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import type { ChangesState } from "@/lib/changesEnabled";

/** What a change page shows while change management is not known to be on (lib/changesEnabled): loading, «could
 *  not read the setting» with a retry, or — only when the settings say so — that it is off and who can turn it on. */
export function ChangesUnavailable({ state, onRetry, className = "" }: { state: Exclude<ChangesState, "on">; onRetry: () => void; className?: string }) {
  const { t } = useLocale();
  if (state === "loading") return <Spinner label={t("common.loading")} />;
  if (state === "failed") {
    return <div className={className}><ErrorBanner message={t("changes.settingsFailed")} onRetry={onRetry} actionLabel={t("common.retry")} /></div>;
  }
  return (
    <div className={`text-sm text-muted-foreground ${className}`}>
      <p>{t("changes.disabled")}</p>
      <p className="mt-1 text-xs">{t("changes.disabledHow")}</p>
    </div>
  );
}
