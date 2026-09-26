import { useLocale } from "@/i18n/LocaleContext";
import { RunbookStep } from "./RunbookStep";

export function RollbackPlan({ plan }: { plan: Record<string, unknown> }) {
  const { t } = useLocale();
  const trigger = plan.trigger as string | undefined;
  const steps = Array.isArray(plan.steps) ? plan.steps : null;

  return (
    <div className="mt-6 border border-amber-500/30 rounded-lg bg-amber-500/5 overflow-hidden">
      <div className="px-4 py-3 border-b border-amber-500/30">
        <h4 className="font-semibold text-foreground">{t("issues.rollbackPlan")}</h4>
      </div>
      <div className="p-4 space-y-3">
        {trigger && (
          <div className="flex items-start gap-2 text-sm text-amber-500 bg-amber-500/10 rounded-lg px-3 py-2">
            <svg className="w-4 h-4 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span>
              <strong>{t("issues.rollbackTrigger")}:</strong> {trigger}
            </span>
          </div>
        )}
        {steps ? (
          <ol className="space-y-3">
            {steps.map((step: unknown, i: number) => (
              <RunbookStep key={i} index={i + 1} step={step} />
            ))}
          </ol>
        ) : (
          <dl className="space-y-2 text-sm">
            {Object.entries(plan)
              .filter(([k]) => k !== "trigger" && k !== "steps")
              .map(([k, v]) => (
                <div key={k}>
                  <dt className="font-medium text-foreground capitalize">
                    {k.replace(/_/g, " ")}
                  </dt>
                  <dd className="text-muted-foreground mt-0.5">
                    {typeof v === "string" ? (
                      v
                    ) : (
                      <pre
                        className="rounded-lg p-3 text-sm font-mono overflow-x-auto mt-1"
                        style={{ backgroundColor: "#1e1e2e", color: "#cdd6f4" }}
                      >
                        {JSON.stringify(v, null, 2)}
                      </pre>
                    )}
                  </dd>
                </div>
              ))}
          </dl>
        )}
      </div>
    </div>
  );
}
