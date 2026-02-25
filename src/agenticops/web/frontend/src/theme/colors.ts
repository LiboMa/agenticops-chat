export const colors = {
  navy: {
    700: "#0D3B76",
    800: "#082B56",
    900: "#051B37",
  },
  pdGreen: {
    500: "#05A82D",
    600: "#048A24",
  },
  severity: {
    critical: { bg: "bg-red-600", text: "text-white", dot: "bg-red-600" },
    high: { bg: "bg-orange-500", text: "text-white", dot: "bg-orange-500" },
    medium: { bg: "bg-yellow-500", text: "text-white", dot: "bg-yellow-500" },
    low: { bg: "bg-blue-500", text: "text-white", dot: "bg-blue-500" },
  },
  status: {
    open: { dot: "bg-red-500", label: "text-red-700" },
    acknowledged: { dot: "bg-yellow-500", label: "text-yellow-700" },
    resolved: { dot: "bg-green-500", label: "text-green-700" },
    running: { dot: "bg-green-500", label: "text-green-700" },
    stopped: { dot: "bg-red-500", label: "text-red-700" },
    available: { dot: "bg-green-500", label: "text-green-700" },
  },
} as const;
