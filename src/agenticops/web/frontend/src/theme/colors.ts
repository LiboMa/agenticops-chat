export const colors = {
  severity: {
    critical: { bg: "bg-red-500/10", text: "text-red-500 dark:text-red-400", dot: "bg-red-500" },
    high: { bg: "bg-orange-500/10", text: "text-orange-500 dark:text-orange-400", dot: "bg-orange-500" },
    medium: { bg: "bg-amber-500/10", text: "text-amber-500 dark:text-amber-400", dot: "bg-amber-400" },
    low: { bg: "bg-blue-500/10 dark:bg-green-500/10", text: "text-blue-500 dark:text-green-400", dot: "bg-blue-500 dark:bg-green-500" },
  },
  status: {
    open: { dot: "bg-red-500", label: "text-red-500 dark:text-red-400" },
    acknowledged: { dot: "bg-amber-500", label: "text-amber-600 dark:text-amber-400" },
    resolved: { dot: "bg-green-500", label: "text-green-600 dark:text-green-400" },
    running: { dot: "bg-green-500", label: "text-green-600 dark:text-green-400" },
    stopped: { dot: "bg-red-500", label: "text-red-500 dark:text-red-400" },
    available: { dot: "bg-green-500", label: "text-green-600 dark:text-green-400" },
  },
} as const;
