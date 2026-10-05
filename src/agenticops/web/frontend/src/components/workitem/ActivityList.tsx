import { useState } from "react";
import type { ActivityEntry } from "@/lib/activity";
import { formatShortDate } from "@/lib/formatDate";

const DOT: Record<ActivityEntry["tone"], string> = { ok: "bg-emerald-500", warn: "bg-amber-500", bad: "bg-red-500", info: "bg-blue-500" };

/** The right rail's activity: one sentence per event, duplicates ×N, the raw events behind a toggle. */
export function ActivityList({ entries, t, emptyKey }: { entries: ActivityEntry[]; t: (k: string) => string; emptyKey: string }) {
  const [raw, setRaw] = useState(false);
  if (entries.length === 0) return <p className="text-xs text-muted-foreground">{t(emptyKey)}</p>;
  const total = entries.reduce((n, e) => n + e.raw.length, 0);
  const fill = (key: string, params: Record<string, string>) =>
    Object.entries(params).reduce((s, [k, v]) => s.replace(`{${k}}`, v), t(key));
  return (
    <div className="space-y-2">
      <ol className="space-y-1.5">
        {entries.map((e, i) => (
          <li key={i} className="flex gap-2 text-xs">
            <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${DOT[e.tone]}`} />
            <div className="min-w-0">
              <span className="text-muted-foreground font-mono mr-1">{formatShortDate(e.ts)}</span>
              <span className="text-foreground">{fill(e.labelKey, e.labelParams)}</span>
              {e.count > 1 && <span className="ml-1 text-muted-foreground">×{e.count}</span>}
              {e.summary && <span className="block text-muted-foreground break-words">{e.summary}</span>}
              <span className="block text-[10px] text-muted-foreground/70">{e.actor}</span>
            </div>
          </li>
        ))}
      </ol>
      <button onClick={() => setRaw(!raw)} className="text-xs text-primary hover:underline">
        {t("activity.raw").replace("{n}", String(total))}
      </button>
      {raw && (
        <pre className="max-h-80 overflow-auto rounded bg-secondary p-2 text-[10px] leading-snug">
          {JSON.stringify(entries.flatMap((e) => e.raw), null, 2)}
        </pre>
      )}
    </div>
  );
}
