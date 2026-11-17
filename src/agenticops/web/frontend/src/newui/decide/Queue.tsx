import { useEffect, useRef } from "react";
import type { AttentionItem } from "@/lib/attention";
import { useNfT, type NfT } from "../i18n";
import { FILTERS, toneOf, waitedParts, type GroupCounts, type QueueFilter } from "../lib/queue";
import { utcHm } from "../lib/time";

/** "等了 3 小时" — how long an item has waited on a person. */
export function waitedText(sinceIso: string | null | undefined, now: number, t: NfT): string {
  const w = waitedParts(sinceIso, now);
  if (!w) return "";
  return w.unit === "now" ? t("waited.now") : t("waited", { t: t(`unit.${w.unit}`, { n: w.n }) });
}

interface Props {
  items: AttentionItem[];
  currentId: string | null;
  filter: QueueFilter;
  counts: GroupCounts | null;
  /** how the list stands: loading / failed draw no rows */
  view: "loading" | "failed" | "ready";
  /** a refresh failed and the rows are the last good ones: when they were fetched */
  staleSince: number | null;
  total: number | null;
  hasMore: boolean;
  loadingMore: boolean;
  now: number;
  onFilter: (f: QueueFilter) => void;
  onPick: (id: string) => void;
  onMore: () => void;
}

/** The left rail of «待决»: how many things wait, the filter pills, and the rows — the most severe first. */
export function Queue({ items, currentId, filter, counts, view, staleSince, total, hasMore, loadingMore, now, onFilter, onPick, onMore }: Props) {
  const t = useNfT();
  const selected = useRef<HTMLButtonElement>(null);
  useEffect(() => { selected.current?.scrollIntoView({ block: "nearest", inline: "nearest" }); }, [currentId]);
  const big = view === "failed" ? "—" : counts ? counts.all.toLocaleString("en-US") : view === "loading" ? "…" : "—";

  return (
    <aside className="side-q">
      <div className="rail-title"><span>{t("queue.title")}</span><b>{big}</b></div>
      <div className="pills">
        {FILTERS.map((g) => (
          <button key={g} type="button" aria-pressed={filter === g} onClick={() => onFilter(g)}>
            {t(`filter.${g}`)}{g !== "all" && !!counts?.[g] && <span className="n">{counts[g]}</span>}
          </button>
        ))}
      </div>
      {staleSince !== null && <p className="q-stale" role="status">{t("queue.stale", { t: utcHm(staleSince) })}</p>}
      <div className="queue" role="listbox" aria-label={t("queue.label")}>
        {view === "loading" && [0, 1, 2, 3].map((i) => <div key={i} className="skel" style={{ height: 62, borderRadius: 10 }} />)}
        {view === "ready" && items.map((i) => {
          const on = i.id === currentId;
          return (
            <button key={i.id} ref={on ? selected : undefined} type="button" className={`q ${toneOf(i)}`} role="option"
                    aria-selected={on} onClick={() => onPick(i.id)}>
              <span className="r"><span className="id">{i.ref}</span><span>{waitedText(i.occurred_at, now, t)}</span></span>
              <span className="t">{i.title}</span>
              <span className="need">{t(`need.${i.reason}`)}</span>
            </button>
          );
        })}
        {view === "ready" && hasMore && (
          <button type="button" className="q-more" onClick={onMore} disabled={loadingMore}>
            {loadingMore ? t("queue.moreLoading") : t("queue.more")}
          </button>
        )}
      </div>
      {view === "ready" && total !== null && items.length < total && (
        <p className="q-note">{t("queue.of", { shown: items.length, total })}</p>
      )}
      <p className="hint"><kbd>J</kbd><kbd>K</kbd>{t("hint.move")} <kbd>?</kbd>{t("hint.all")}</p>
    </aside>
  );
}
