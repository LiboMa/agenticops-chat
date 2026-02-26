interface EmptyStateProps {
  message?: string;
  icon?: string;
}

export function EmptyState({
  message = "No data available.",
  icon = "inbox",
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-slate-400">
      {icon === "inbox" && (
        <svg
          className="h-12 w-12 mb-3"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"
          />
        </svg>
      )}
      <p className="text-sm">{message}</p>
    </div>
  );
}
