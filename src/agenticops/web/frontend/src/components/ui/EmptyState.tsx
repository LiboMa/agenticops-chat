interface EmptyStateProps {
  message?: string;
  icon?: string;
}

export function EmptyState({
  message = "No data available.",
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-muted-foreground/60">
      <p className="text-sm">{message}</p>
    </div>
  );
}
