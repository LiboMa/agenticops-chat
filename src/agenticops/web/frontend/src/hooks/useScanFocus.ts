import { useState, useCallback, useEffect } from "react";
import type { ScanFocus } from "@/api/types";

const STORAGE_KEY = "aiops_scan_focus";

const ALL_CATEGORIES: ScanFocus[] = [
  "computing",
  "networking",
  "databases",
  "storage",
  "security",
  "billing",
];

function load(): Set<ScanFocus> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw || raw === "all") return new Set<ScanFocus>(["all"]);
    const parts = raw.split(",") as ScanFocus[];
    const valid = parts.filter((p) => ALL_CATEGORIES.includes(p) || p === "all");
    return valid.length ? new Set(valid) : new Set<ScanFocus>(["all"]);
  } catch {
    return new Set<ScanFocus>(["all"]);
  }
}

function save(selected: Set<ScanFocus>) {
  const value = selected.has("all") ? "all" : [...selected].join(",");
  localStorage.setItem(STORAGE_KEY, value);
}

/**
 * Shared scan focus state persisted in localStorage.
 * Used by Dashboard (toggle panel) and Chat (send with messages).
 */
export function useScanFocus() {
  const [selected, setSelected] = useState<Set<ScanFocus>>(load);

  // Listen for changes from other tabs / components
  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setSelected(load());
    };
    window.addEventListener("storage", handler);
    return () => window.removeEventListener("storage", handler);
  }, []);

  const toggle = useCallback((value: ScanFocus) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (value === "all") {
        // Clicking "All" resets to all
        save(new Set(["all"]));
        return new Set(["all"]);
      }
      // Remove "all" when selecting a specific category
      next.delete("all");
      if (next.has(value)) {
        next.delete(value);
      } else {
        next.add(value);
      }
      // If nothing selected, revert to "all"
      if (next.size === 0) {
        save(new Set(["all"]));
        return new Set(["all"]);
      }
      // If all 6 categories selected, simplify to "all"
      if (next.size === ALL_CATEGORIES.length) {
        save(new Set(["all"]));
        return new Set(["all"]);
      }
      save(next);
      return next;
    });
  }, []);

  // Serialized value for API calls: "all" or "computing,security"
  const focusValue = selected.has("all") ? "all" : [...selected].join(",");

  return { selected, toggle, focusValue, ALL_CATEGORIES };
}
