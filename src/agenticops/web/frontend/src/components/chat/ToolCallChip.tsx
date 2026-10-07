export function ToolCallChip({ name, status, outcome }: { name: string; status: string; outcome?: string }) {
  // The optional ACP enhanced backend surfaces as the `enhanced_task` tool call.
  // Give it a distinct primary-tinted treatment so users can see when a turn was
  // delegated to an external coding agent (Claude Code).
  const isEnhanced = name === "enhanced_task";
  const label = isEnhanced ? "✦ Enhanced" : name;

  return (
    <span
      className={
        isEnhanced
          ? "inline-flex items-center gap-1.5 px-2.5 py-1 bg-primary-50 border border-primary-200 rounded-full text-xs font-medium text-primary-700"
          : "inline-flex items-center gap-1.5 px-2.5 py-1 bg-secondary border border-border rounded-full text-xs text-muted-foreground"
      }
    >
      {status === "running" ? (
        <span className="w-2 h-2 border border-primary-500 border-t-transparent rounded-full animate-spin" />
      ) : (
        // S5: the outcome comes from the tool's result — failed red, unknown grey, ok (or older rows) blue
        <span className={`w-2 h-2 rounded-full ${outcome === "error" ? "bg-red-500" : outcome === "unknown" ? "bg-muted-foreground/50" : "bg-primary-500"}`} />
      )}
      {label}
    </span>
  );
}
