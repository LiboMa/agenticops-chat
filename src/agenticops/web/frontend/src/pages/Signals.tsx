import { useLocale } from "@/i18n/LocaleContext";
import { SignalsPanel } from "@/components/signals/SignalsPanel";

/** The signal ledger at /app/signals (spec §3): reached from the issue list and an issue's sources, not the sidebar. */
export default function Signals() {
  const { t } = useLocale();
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-foreground">{t("signals.title")}</h1>
      <SignalsPanel />
    </div>
  );
}
