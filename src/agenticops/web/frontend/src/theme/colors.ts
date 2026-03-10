export const colors = {
  severity: {
    critical: { bg: "bg-red-900/30", text: "text-red-400", dot: "bg-red-500" },
    high: { bg: "bg-orange-900/30", text: "text-orange-400", dot: "bg-orange-500" },
    medium: { bg: "bg-amber-900/30", text: "text-amber-400", dot: "bg-amber-500" },
    low: { bg: "bg-blue-900/30", text: "text-blue-400", dot: "bg-blue-500" },
  },
  status: {
    open: { dot: "bg-red-500", label: "text-red-400" },
    acknowledged: { dot: "bg-amber-500", label: "text-amber-400" },
    resolved: { dot: "bg-green-500", label: "text-green-400" },
    running: { dot: "bg-green-500", label: "text-green-400" },
    stopped: { dot: "bg-red-500", label: "text-red-400" },
    available: { dot: "bg-green-500", label: "text-green-400" },
  },
} as const;
