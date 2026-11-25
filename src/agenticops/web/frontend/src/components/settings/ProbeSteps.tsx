import { useLocale } from "@/i18n/LocaleContext";
import type { ProbeResult } from "@/hooks/useModelProviders";

const STEPS = ["list", "chat", "tools"] as const;

/** A connection test's three steps (MVP-2.9.0 N35): read the model list, one short chat, one tool call — each passed
 *  or failed with the reason the server gave (it never quotes a key). */
export function ProbeSteps({ result, compact = false }: { result: ProbeResult; compact?: boolean }) {
  const { t } = useLocale();
  return (
    <ul className={compact ? "space-y-0.5 text-xs" : "mt-3 space-y-1.5 text-sm"}>
      {STEPS.map((step) => {
        const s = result[step];
        return (
          <li key={step} className="flex flex-wrap items-baseline gap-x-2">
            <span aria-hidden className={s.ok ? "text-emerald-600 dark:text-emerald-400" : "text-destructive"}>{s.ok ? "✓" : "✗"}</span>
            <span className="font-medium text-foreground">{t(`settings.providers.step.${step}`)}</span>
            <span className="sr-only">{s.ok ? t("settings.providers.passed") : t("settings.providers.failed")}</span>
            {s.ok && typeof s.ms === "number" && <span className="text-muted-foreground">{s.ms} ms</span>}
            {s.ok && step === "list" && typeof s.count === "number" && (
              <span className="text-muted-foreground">{t("settings.providers.modelsListed").replace("{n}", String(s.count))}</span>
            )}
            {!s.ok && s.error && <span className="basis-full text-destructive [overflow-wrap:anywhere] sm:basis-auto">{s.error}</span>}
          </li>
        );
      })}
      {!compact && result.model_id && (
        <li className="pt-1 text-xs text-muted-foreground">{t("settings.providers.testedModel")} <span className="font-mono">{result.model_id}</span></li>
      )}
    </ul>
  );
}
