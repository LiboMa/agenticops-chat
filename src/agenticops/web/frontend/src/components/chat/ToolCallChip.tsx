export function ToolCallChip({ name, status }: { name: string; status: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-slate-100 border border-slate-200 rounded-full text-xs text-slate-600">
      {status === "running" ? (
        <span className="w-2 h-2 border border-primary-500 border-t-transparent rounded-full animate-spin" />
      ) : (
        <span className="w-2 h-2 bg-primary-500 rounded-full" />
      )}
      {name}
    </span>
  );
}
