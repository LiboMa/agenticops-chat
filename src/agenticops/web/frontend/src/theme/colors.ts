export const colors = {
  severity: {
    critical: { bg: "bg-red-100", text: "text-red-700", dot: "bg-red-500" },
    high: { bg: "bg-orange-100", text: "text-orange-700", dot: "bg-orange-500" },
    medium: { bg: "bg-amber-100", text: "text-amber-700", dot: "bg-amber-500" },
    low: { bg: "bg-blue-100", text: "text-blue-700", dot: "bg-blue-500" },
  },
  status: {
    open: { dot: "bg-red-500", label: "text-red-700" },
    acknowledged: { dot: "bg-amber-500", label: "text-amber-700" },
    resolved: { dot: "bg-green-500", label: "text-green-700" },
    running: { dot: "bg-green-500", label: "text-green-700" },
    stopped: { dot: "bg-red-500", label: "text-red-700" },
    available: { dot: "bg-green-500", label: "text-green-700" },
  },
} as const;
