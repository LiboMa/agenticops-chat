import { useLocale } from "@/i18n/LocaleContext";

interface Props {
  suggestions: string[];
  onPick: (text: string) => void;
  disabled?: boolean;
}

/** «下一步» under the last answer: what the user would likely ask next — a click sends it. */
export function SuggestionChips({ suggestions, onPick, disabled }: Props) {
  const { t } = useLocale();
  if (suggestions.length === 0) return null;
  return (
    <div className="mt-4">
      <div className="mb-2 text-xs text-muted-foreground">{t("chat.nextSteps")}</div>
      <div className="flex flex-wrap gap-2">
        {suggestions.map((s, i) => (
          <button key={i} type="button" onClick={() => onPick(s)} disabled={disabled}
                  className="inline-flex items-center gap-1.5 rounded-full border border-border bg-background px-3 py-1.5 text-[13px] text-foreground transition-colors hover:border-primary/50 hover:bg-selected disabled:cursor-not-allowed disabled:opacity-50">
            <span className="text-muted-foreground" aria-hidden>↳</span>{s}
          </button>
        ))}
      </div>
    </div>
  );
}
