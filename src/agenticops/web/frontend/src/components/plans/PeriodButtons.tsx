import { useLocale } from "@/i18n/LocaleContext";
import { PERIODS, type Period } from "@/lib/plans";

/** AgentMetrics' segmented period control, shared by the Changes tab (M22, allowAll) and the Audit tab (M36). */
export function PeriodButtons({ value, onChange, allowAll = false }: {
  value: Period | undefined;
  onChange: (p: Period | undefined) => void;
  allowAll?: boolean;
}) {
  const { t } = useLocale();
  return (
    <div className="flex gap-1 bg-secondary rounded-lg p-1">
      {allowAll && (
        <button
          onClick={() => onChange(undefined)}
          className={`px-2 py-1 text-xs rounded ${value === undefined ? "bg-background shadow text-foreground" : "text-muted-foreground"}`}
        >{t("plans.period.all")}</button>
      )}
      {PERIODS.map((p) => (
        <button
          key={p}
          onClick={() => onChange(p)}
          className={`px-2 py-1 text-xs rounded ${value === p ? "bg-background shadow text-foreground" : "text-muted-foreground"}`}
        >{p}</button>
      ))}
    </div>
  );
}
