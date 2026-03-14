export function ToolCallChip({ name, status }: { name: string; status: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-secondary border border-border rounded-full text-xs text-muted-foreground">
      {status === "running" ? (
        <span className="w-2 h-2 border border-primary-500 border-t-transparent rounded-full animate-spin" />
      ) : (
        <span className="w-2 h-2 bg-primary-500 rounded-full" />
      )}
      {name}
    </span>
  );
}
