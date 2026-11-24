import { useEffect, useRef } from "react";
import { closesOnEscape, openOverlay } from "@/lib/escapeStack";

/** A hand-drawn overlay closes on Escape (the house rule): bound while `active`; of several open overlays only the
 *  one opened last closes (`lib/escapeStack`). The key press is marked handled, so nothing under it acts on it too. */
export function useCloseOnEscape(onClose: () => void, active = true): void {
  const latest = useRef(onClose);
  latest.current = onClose;
  useEffect(() => {
    if (!active) return;
    const close = () => latest.current();
    const release = openOverlay(close);
    const onKey = (e: KeyboardEvent) => {
      if (!closesOnEscape(close, e)) return;
      e.preventDefault();
      close();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      release();
    };
  }, [active]);
}
