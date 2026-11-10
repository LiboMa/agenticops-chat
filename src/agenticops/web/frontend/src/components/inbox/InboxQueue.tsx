import { useRef } from "react";
import { Link, type To } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { StatusText, type StatusTone } from "@/components/ui/StatusText";
import { formatFullDate } from "@/lib/formatDate";
import { reasonKey, type AttentionItem } from "@/lib/attention";
import { waitLabel, type DecisionGroup } from "@/lib/inbox";

const SEV_TONE: Record<string, StatusTone> = { critical: "danger", high: "danger", medium: "warn", low: "info" };
const RISK_TONE: Record<string, StatusTone> = { L3: "danger", L2: "warn", L1: "info", L0: "neutral" };

/** «问题 · 在等我»'s list (MVP-2.8.0; the workbench's queue): one heading per decision group with its count, then the
 *  items — issues and changes (marked «变更»). Rows are real links; Up / Down / Home / End move the focus across all
 *  the groups' rows. */
export function InboxQueue({ groups, selected, accountName, now, hrefFor }: {
  groups: { group: DecisionGroup; count: number; items: AttentionItem[] }[];
  selected: string | null;
  accountName: (id: number | null) => string | null;
  now: number;
  hrefFor: (id: string) => To;
}) {
  const { t } = useLocale();
  const listRef = useRef<HTMLDivElement>(null);
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
    <div ref={listRef} onKeyDown={onKeyDown} className="space-y-3">
      {groups.map((g) => (
        <section key={g.group} aria-labelledby={`waiting-group-${g.group}`}>
          <h2 id={`waiting-group-${g.group}`} className="flex items-center justify-between px-1 pb-1 text-xs font-medium text-muted-foreground">
            <span>{t(`cases.waiting.group.${g.group}`)}</span>
            <span className="tabular-nums">{g.count}</span>
          </h2>
          <ul className="space-y-1.5">
            {g.items.map((it) => {
              const current = it.id === selected;
              const tone = it.severity ? SEV_TONE[it.severity] ?? "neutral" : it.risk_level ? RISK_TONE[it.risk_level] ?? "neutral" : null;
              const level = it.severity ? t(`severity.${it.severity}`) : it.risk_level ?? null;
              const where = [it.resource?.name || it.resource?.resource_id, it.resource?.type, accountName(it.account_id), it.region]
                .filter(Boolean).join(" · ");
              const wait = waitLabel(it.occurred_at, now, t);
              const change = it.id.startsWith("C");
              return (
                <li key={it.id}>
                  <Link to={hrefFor(it.id)} data-item-id={it.id} aria-current={current ? "page" : undefined}
                        className={`block rounded-md border px-3 py-2 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-primary/60 ${
                          current ? "border-primary/50 bg-selected" : "border-border bg-card hover:bg-accent"}`}>
                    <span className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
                        {change && <span className="rounded border border-primary/40 px-1 font-sans text-[10px] text-primary">{t("cases.waiting.change")}</span>}
                        {it.ref}
                      </span>
                      {tone && level && <StatusText tone={tone} className="text-[11px]">{level}</StatusText>}
                    </span>
                    <span className="mt-0.5 line-clamp-2 block text-sm font-medium text-foreground [overflow-wrap:anywhere]">{it.title}</span>
                    {where && <span className="mt-0.5 block truncate text-xs text-muted-foreground" title={where}>{where}</span>}
                    <span className="mt-0.5 flex items-center justify-between gap-2 text-xs">
                      <span className="text-primary">{t(reasonKey(it))}</span>
                      {wait && <span className="shrink-0 text-muted-foreground" title={formatFullDate(it.occurred_at)}>{wait}</span>}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
