import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useInboxPages } from "@/hooks/useAttention";
import { useAccounts } from "@/hooks/useAccounts";
import { useScopedAccountId } from "@/components/layout/AccountScope";
import { QueryState } from "@/components/ui/QueryState";
import { InboxQueue } from "@/components/inbox/InboxQueue";
import IssueDetail from "@/pages/IssueDetail";
import { ChangeDetailView } from "@/pages/ChangeDetail";
import { SPLIT_MEDIA } from "@/lib/caseQueue";
import { formatUtcTime } from "@/lib/formatDate";
import {
  INBOX_TABS, inboxParams, inboxSearch, parseItem, selectionState, tabCount, tabReasons, type InboxParams, type InboxTab,
} from "@/lib/inbox";
import type { AttentionItem } from "@/lib/attention";

const TAB_KEYS: Record<InboxTab, string> = {
  all: "inbox.tab.all", approval: "inbox.tab.approval", acceptance: "inbox.tab.acceptance",
  failed: "inbox.tab.failed", confirm: "inbox.tab.confirm",
};

/** The to-do workbench (MVP-2.8.0 S2): every item that waits on you, tabbed by the decision it needs, the longest
 *  wait first. At ≥ 1280 px the queue sits beside the item's own page; below that the two take turns, and back
 *  returns to the same tab and scroll. «Compact» lays the queue out as aligned lines with the item below. */
export default function Inbox() {
  const { t } = useLocale();
  const [search, setSearch] = useSearchParams();
  const params = inboxParams(search);
  const wide = useMediaQuery(SPLIT_MEDIA);
  const accountId = useScopedAccountId();
  const accounts = useAccounts();
  const pages = useInboxPages({ accountId, reasons: tabReasons(params.decision), q: params.q });
  const [q, setQ] = useState(params.q);
  useEffect(() => setQ(params.q), [params.q]);   // back / forward: the box follows the URL
  useEffect(() => {
    if (q.trim() === params.q) return;
    const timer = setTimeout(() => go({ q: q.trim(), item: null }, true), 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 60_000); return () => clearInterval(id); }, []);

  const go = (patch: Partial<InboxParams>, replace = false) =>
    setSearch(inboxSearch({ ...params, ...patch }).replace(/^\?/, ""), { replace });

  const first = pages.data?.pages[0];
  const items: AttentionItem[] = pages.data?.pages.flatMap((p) => p.items) ?? [];
  const nameOf = (id: number | null) => (id == null ? null : accounts.data?.find((a) => a.id === id)?.name ?? null);
  let state = selectionState(items, params.item);
  if (state === "gone" && pages.hasNextPage) state = "selected";  // it may be on a page not loaded yet
  const target = parseItem(params.item);
  const nextItem = items.find((i) => i.id !== params.item) ?? null;
  const compact = params.layout === "compact";

  // Narrow: the list's scroll comes back when you return from an item
  const scrollKey = `aiops-inbox-scroll:${inboxSearch({ ...params, item: null })}`;
  useLayoutEffect(() => {
    if (wide || params.item || !pages.data) return;
    const y = Number(sessionStorage.getItem(scrollKey) ?? "");
    if (y > 0) { window.scrollTo(0, y); sessionStorage.removeItem(scrollKey); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wide, params.item, !!pages.data]);
  const paneRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => { paneRef.current?.scrollTo({ top: 0 }); }, [params.item]);

  const backTo = `/app/inbox${inboxSearch({ ...params, item: null })}`;
  const pane = (
    <div ref={paneRef} className={wide && !compact ? "min-h-0 overflow-y-auto pr-1" : ""}>
      {state === "selected" && target?.kind === "issue" && (
        <IssueDetail key={params.item!} issueId={target.id} embedded={wide}
                     back={wide ? undefined : { to: backTo, label: t("inbox.back") }} />
      )}
      {state === "selected" && target?.kind === "change" && (
        <ChangeDetailView key={params.item!} crId={target.id} embedded={wide} back={wide ? undefined : { to: backTo }} />
      )}
      {state !== "selected" && (
        <div role="status" className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border px-6 py-16 text-center text-sm text-muted-foreground">
          <p>{state === "gone" ? t("inbox.gone") : t("inbox.selectPrompt")}</p>
          {nextItem && (
            <Link to={{ search: inboxSearch({ ...params, item: nextItem.id }) }}
                  className="rounded-md border border-primary/40 px-3 py-1.5 text-sm font-medium text-primary hover:bg-selected">
              {t("inbox.next")} · {nextItem.ref}
            </Link>
          )}
        </div>
      )}
    </div>
  );

  // Narrow, an item open: the item's page full screen, its own back control returns to the list
  if (!wide && params.item) return pane;

  const queue = (
    <div className={wide && !compact ? "flex min-h-0 flex-col gap-3" : "space-y-3"}>
      <QueryState query={pages} isEmpty={(d) => d.pages.every((p) => p.items.length === 0)}
                  emptyText={params.q || params.decision !== "all" ? t("inbox.emptyFiltered") : t("inbox.empty")}
                  onRetry={() => void pages.refetch()}>
        {() => (
          <div className={wide && !compact ? "min-h-0 flex-1 overflow-y-auto pr-1" : ""}
               onClickCapture={() => { if (!wide) sessionStorage.setItem(scrollKey, String(window.scrollY)); }}>
            <InboxQueue items={items} params={params} selected={params.item} accountName={nameOf} compact={compact} now={now} />
            {pages.hasNextPage && (
              <button type="button" onClick={() => void pages.fetchNextPage()} disabled={pages.isFetchingNextPage}
                      className="mt-2 w-full rounded-lg border border-border bg-card py-2 text-sm font-medium hover:bg-accent disabled:opacity-60">
                {t("inbox.more").replace("{n}", String((first?.total ?? 0) - items.length))}
              </button>
            )}
          </div>
        )}
      </QueryState>
    </div>
  );

  return (
    <div className={wide && !compact ? "flex h-[calc(100dvh-var(--topbar-h)-3rem)] flex-col gap-4" : "space-y-4"}>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[22px] font-semibold text-foreground">{t("nav.inbox")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t("inbox.intro")}</p>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          {first && <span>{t("inbox.updatedAt").replace("{time}", formatUtcTime(first.generated_at))}</span>}
          <button type="button" onClick={() => void pages.refetch()} disabled={pages.isFetching}
                  className="rounded-md border border-border bg-card px-2.5 py-1.5 font-medium text-foreground hover:bg-accent disabled:opacity-60">
            {t("security.refresh")}
          </button>
        </div>
      </header>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="tablist" aria-label={t("nav.inbox")} className="flex flex-wrap gap-1 border-b border-border">
          {INBOX_TABS.map((tab) => {
            const active = params.decision === tab;
            return (
              <button key={tab} type="button" role="tab" aria-selected={active} onClick={() => go({ decision: tab, item: null })}
                      className={`-mb-px border-b-2 px-3 py-2 text-sm ${active ? "border-primary font-medium text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
                {t(TAB_KEYS[tab])}
                <span className="ml-1.5 tabular-nums text-xs opacity-80">{first ? tabCount(first.counts, tab) : "…"}</span>
              </button>
            );
          })}
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} aria-label={t("inbox.search")}
                 placeholder={t("inbox.search")}
                 className="w-full rounded-lg border border-border bg-card px-3 py-1.5 text-sm sm:w-64" />
          {wide && (
            <div role="group" aria-label={t("inbox.layout")} className="flex rounded-md border border-border p-0.5 text-xs">
              {(["split", "compact"] as const).map((l) => (
                <button key={l} type="button" aria-pressed={params.layout === l} onClick={() => go({ layout: l }, true)}
                        className={`rounded px-2 py-1 ${params.layout === l ? "bg-selected font-medium text-primary" : "text-muted-foreground"}`}>
                  {t(`inbox.layout.${l}`)}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {wide && !compact ? (
        <div className="grid min-h-0 flex-1 grid-cols-[380px_minmax(0,1fr)] grid-rows-[minmax(0,1fr)] gap-5 max-[1350px]:grid-cols-[340px_minmax(0,1fr)]">
          {queue}
          {pane}
        </div>
      ) : (
        <>
          {queue}
          {wide && compact && params.item && pane}
        </>
      )}
    </div>
  );
}
