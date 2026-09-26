import React from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { changeStepState, CHANGE_STEP_KEYS, type ChangeStepInput } from "@/lib/changeStepper";

export const ChangeStepper = React.memo(function ChangeStepper({
  cr,
  compact = false,
}: {
  cr: ChangeStepInput;
  compact?: boolean;
}) {
  const { t } = useLocale();
  const { index, tone } = changeStepState(cr);

  // Circle/dot colour for step i — shared by the full stepper and the compact dots.
  const colorFor = (i: number): string => {
    if (i < index) return "bg-emerald-500 text-white";
    if (i === index) {
      if (tone === "done") return "bg-emerald-500 text-white";
      if (tone === "warn") return "bg-amber-500 text-white";
      if (tone === "bad") return "bg-red-500 text-white";
      return "bg-primary text-primary-foreground";
    }
    return "bg-secondary text-muted-foreground";
  };
  const showCheck = (i: number) => i < index || (i === index && tone === "done");
  // Current step reads the human status when it needs attention; otherwise the step name.
  const currentLabel = tone === "warn" || tone === "bad" ? t(`changes.status.${cr.status}`) : t(CHANGE_STEP_KEYS[index]);

  if (compact) {
    return (
      <div className="flex items-center gap-1" title={t(CHANGE_STEP_KEYS[index])}>
        {CHANGE_STEP_KEYS.map((key, i) => (
          <span key={key} className={`h-2 w-2 rounded-full ${colorFor(i)}`} />
        ))}
        <span className="text-xs text-foreground">{t(`changes.status.${cr.status}`)}</span>
      </div>
    );
  }

  return (
    <ol className="flex items-center gap-2 text-xs">
      {CHANGE_STEP_KEYS.map((key, i) => (
        <li key={key} className="flex items-center gap-2">
          <span className={`w-6 h-6 rounded-full flex items-center justify-center font-semibold ${colorFor(i)}`}>{showCheck(i) ? "✓" : i + 1}</span>
          <span className={i <= index ? "text-foreground font-medium" : "text-muted-foreground"}>
            {i === index ? currentLabel : t(key)}
          </span>
          {i < CHANGE_STEP_KEYS.length - 1 && <span className="w-6 h-px bg-border" />}
        </li>
      ))}
    </ol>
  );
});
