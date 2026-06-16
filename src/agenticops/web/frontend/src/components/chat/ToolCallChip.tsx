export function ToolCallChip({ name, status }: { name: string; status: string }) {
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
        <span className="w-2 h-2 bg-primary-500 rounded-full" />
      )}
      {label}
    </span>
  );
}
