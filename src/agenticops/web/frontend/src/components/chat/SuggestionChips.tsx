interface Props {
  suggestions: string[];
  onPick: (text: string) => void;
  disabled?: boolean;
}

/** Follow-up action chips under the last assistant message (click = send). */
export function SuggestionChips({ suggestions, onPick, disabled }: Props) {
  if (suggestions.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {suggestions.map((s, i) => (
        <button
          key={i}
          onClick={() => onPick(s)}
          disabled={disabled}
          className="px-3 py-1 rounded-full border border-border text-xs text-muted-foreground
                     hover:bg-muted hover:border-primary-400 hover:text-foreground
                     disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {s}
        </button>
      ))}
    </div>
  );
}
