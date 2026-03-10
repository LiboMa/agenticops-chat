interface ErrorBannerProps {
  message: string;
  onRetry?: () => void;
}

export function ErrorBanner({ message, onRetry }: ErrorBannerProps) {
  return (
    <div className="bg-red-900/20 border border-red-900/50 rounded-lg p-4 flex items-start gap-3">
      <svg
        className="h-5 w-5 text-red-400 mt-0.5 shrink-0"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1.5}
          d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"
        />
      </svg>
      <div className="flex-1">
        <p className="text-sm text-red-400">{message}</p>
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="text-sm font-medium text-red-400 hover:text-red-300 px-3 py-1 rounded-md border border-red-900/50 hover:bg-red-900/30 transition-colors duration-150"
        >
          Retry
        </button>
      )}
    </div>
  );
}
