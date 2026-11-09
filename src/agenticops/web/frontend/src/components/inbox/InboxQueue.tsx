import { useRef } from "react";
import { Link } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { StatusText, type StatusTone } from "@/components/ui/StatusText";
import { formatFullDate } from "@/lib/formatDate";
import { reasonKey, type AttentionItem } from "@/lib/attention";
import { inboxSearch, waitLabel, type InboxParams } from "@/lib/inbox";

const SEV_TONE: Record<string, StatusTone> = { critical: "danger", high: "danger", medium: "warn", low: "info" };
const RISK_TONE: Record<string, StatusTone> = { L3: "danger", L2: "warn", L1: "info", L0: "neutral" };

/** The workbench's queue (MVP-2.8.0 S2): rows are real links that keep the query; Up / Down / Home / End move the
 *  focus between rows. `compact` = one aligned line per item (title · resource · account · decision · wait). */
export function InboxQueue({ items, params, selected, accountName, compact, now }: {
  items: AttentionItem[]; params: InboxParams; selected: string | null;
  accountName: (id: number | null) => string | null; compact: boolean; now: number;
}) {
  const { t } = useLocale();
  const listRef = useRef<HTMLUListElement>(null);
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
    const links = [...(listRef.current?.querySelectorAll<HTMLElement>("a[data-item-id]") ?? [])];
    if (!links.length) return;
    e.preventDefault();
    const at = links.findIndex((l) => l === document.activeElement);
    const next = e.key === "Home" ? 0 : e.key === "End" ? links.length - 1
      : e.key === "ArrowDown" ? Math.min(links.length - 1, at + 1) : Math.max(0, at - 1);
    links[next]?.focus();
  };
  return (
    <ul ref={listRef} onKeyDown={onKeyDown} className={compact ? "divide-y divide-border rounded-lg border border-border bg-card" : "space-y-2"}>
      {items.map((it) => {
        const current = it.id === selected;
        const tone = it.severity ? SEV_TONE[it.severity] ?? "neutral" : it.risk_level ? RISK_TONE[it.risk_level] ?? "neutral" : null;
        const level = it.severity ? t(`severity.${it.severity}`) : it.risk_level ?? null;
        const where = [it.resource?.name || it.resource?.resource_id, it.resource?.type, accountName(it.account_id), it.region]
          .filter(Boolean).join(" · ");
        const wait = waitLabel(it.occurred_at, now, t);
        return (
          <li key={it.id}>
            <Link to={{ search: inboxSearch({ ...params, item: it.id }) }} data-item-id={it.id}
                  aria-current={current ? "page" : undefined}
                  className={`block outline-none transition-colors focus-visible:ring-2 focus-visible:ring-primary/60 ${
                    compact ? "grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 px-3 py-2.5 md:grid-cols-[88px_minmax(0,1fr)_minmax(0,220px)_160px]"
                            : "rounded-lg border px-3 py-2.5"} ${
                    current ? (compact ? "bg-selected" : "border-primary/50 bg-selected") : compact ? "hover:bg-accent" : "border-border bg-card hover:bg-accent"}`}>
              {compact ? (
                <>
                  <span className="flex items-center gap-2 font-mono text-xs text-muted-foreground">{it.ref}
                    {tone && level && <StatusText tone={tone} className="text-[11px]">{level}</StatusText>}</span>
                  <span className="min-w-0 truncate text-sm font-medium text-foreground">{it.title}</span>
                  <span className="col-span-2 min-w-0 truncate text-xs text-muted-foreground md:col-span-1">{where || "—"}</span>
                  <span className="col-span-2 text-xs md:col-span-1">
                    <span className="text-primary">{t(reasonKey(it))}</span>
                    {wait && <span className="ml-2 text-muted-foreground" title={formatFullDate(it.occurred_at)}>{wait}</span>}
                  </span>
                </>
              ) : (
                <>
                  <span className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-2 font-mono text-xs text-muted-foreground">{it.ref}</span>
                    {tone && level && <StatusText tone={tone} className="text-[11px]">{level}</StatusText>}
                  </span>
                  <span className="mt-1 line-clamp-2 block text-sm font-medium text-foreground [overflow-wrap:anywhere]">{it.title}</span>
                  {where && <span className="mt-0.5 block truncate text-xs text-muted-foreground" title={where}>{where}</span>}
                  <span className="mt-1 flex items-center justify-between gap-2 text-xs">
                    <span className="text-primary">{t(reasonKey(it))}</span>
                    {wait && <span className="shrink-0 text-muted-foreground" title={formatFullDate(it.occurred_at)}>{wait}</span>}
                  </span>
                </>
              )}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
