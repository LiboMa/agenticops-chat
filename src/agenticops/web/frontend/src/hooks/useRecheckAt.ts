import { useEffect, useRef, useState } from "react";
import { scheduleAt } from "@/lib/recheck";

/** One timer to `at` (epoch ms; null = none): then `onDue` (refetch what the decision reads) and a re-render, so a
 *  state only time changes is decided again even when no query notifies (equal poll results do not). Cleared on
 *  unmount and whenever `at` changes. */
export function useRecheckAt(at: number | null, onDue: () => void): void {
  const [, rerender] = useState(0);
  const due = useRef(onDue);
  due.current = onDue;
  useEffect(() => {
    if (at === null) return;
    return scheduleAt(at, () => {
      due.current();
      rerender((n) => n + 1);
    });
  }, [at]);
}
