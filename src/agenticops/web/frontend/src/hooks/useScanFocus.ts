/** Stub: scan focus categories for Settings page. */
export type ScanFocus = "compute" | "storage" | "network" | "database" | "security";

export function useScanFocus() {
  return {
    categories: ["compute", "storage", "network", "database", "security"] as ScanFocus[],
    selected: ["compute", "network"] as ScanFocus[],
    toggle: (_cat: ScanFocus) => {},
    isLoading: false,
  };
}
