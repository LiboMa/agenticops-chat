import { useCallback, useSyncExternalStore } from "react";

/** Whether a CSS media query matches now, re-rendering when it flips. */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback((notify: () => void) => {
    const mql = window.matchMedia(query);
    mql.addEventListener("change", notify);
    return () => mql.removeEventListener("change", notify);
  }, [query]);
  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches, () => false);
}
