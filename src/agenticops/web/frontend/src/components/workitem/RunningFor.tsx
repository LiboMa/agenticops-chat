import { useEffect, useState } from "react";
import { Spinner } from "@/components/ui/Spinner";
import { formatElapsed, parseApiDate } from "@/lib/formatDate";

import { fillPlaceholders } from "@/lib/placeholders";
/** A spinner with the time since the run started, ticking each second; a queued run has no start yet. */
export function RunningFor({ since, t }: { since: string | null; t: (key: string) => string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const h = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(h);
  }, []);
  const start = parseApiDate(since)?.getTime();
  return (
    <Spinner label={start === undefined ? t("workitem.sub.executing")
      : fillPlaceholders(t("workitem.runningFor"), { elapsed: formatElapsed(now - start) })} />
  );
}
