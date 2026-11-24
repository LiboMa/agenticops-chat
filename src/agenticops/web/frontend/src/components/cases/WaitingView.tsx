import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useWaitingPages } from "@/hooks/useAttention";
import { useAccounts } from "@/hooks/useAccounts";
import { useReadOnly } from "@/hooks/useBootstrap";
import { useScopedAccountId } from "@/components/layout/AccountScope";
import { QueryState } from "@/components/ui/QueryState";
import { InboxQueue } from "@/components/inbox/InboxQueue";
import { QuickViews } from "@/components/cases/QuickViews";
import IssueDetail from "@/pages/IssueDetail";
import { ChangeDetailView } from "@/pages/ChangeDetail";
import { SPLIT_MEDIA, waitingSearch } from "@/lib/caseQueue";
import { groupItems, parseItem, selectionState } from "@/lib/inbox";
import { resolveIssueScope } from "@/lib/issueScope";
import type { AttentionItem } from "@/lib/attention";

/** «问题 · 在等我» (MVP-2.8.0, owner 2026-11-10: the to-do workbench merged into Issues): everything waiting on you —
 *  issues and changes — grouped by the decision it needs, the longest wait first in each group. At ≥ 1280 px the
 *  list sits beside the selected item's own page (an issue's or a change's); below that the two take turns and back
 *  returns to the same search and scroll. The selected item lives in the URL (`?item=I12|C3`). */
export function WaitingView() {
  const { t } = useLocale();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const wide = useMediaQuery(SPLIT_MEDIA);
  const readOnly = useReadOnly();
  const accountId = useScopedAccountId();
  const accounts = useAccounts();
  const urlQ = (params.get("q") ?? "").trim().slice(0, 200);
  const raw = params.get("item");
  const item = raw && parseItem(raw) ? raw : null;
  const pages = useWaitingPages({ accountId, q: urlQ });

  const [q, setQ] = useState(urlQ);
  useEffect(() => setQ(urlQ), [urlQ]);   // back / forward: the box follows the URL
  useEffect(() => {
    if (q.trim() === urlQ) return;
    const timer = setTimeout(() => {
      const next = new URLSearchParams(params);
      if (q.trim()) next.set("q", q.trim()); else next.delete("q");
      next.delete("item");
      navigate({ pathname: "/app/issues", search: next.toString() ? `?${next}` : "" }, { replace: true });
    }, 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 60_000); return () => clearInterval(id); }, []);

  const first = pages.data?.pages[0];
  const items: AttentionItem[] = pages.data?.pages.flatMap((p) => p.items) ?? [];
  const groups = groupItems(items, first?.counts);
  const nameOf = (id: number | null) => (id == null ? null : accounts.data?.find((a) => a.id === id)?.name ?? null);
  // the ids this list has shown (search + account): one that was here and has left is gone — handled — even while
  // more pages could be loaded (S2 review); a new search starts a new set
  const viewKey = `${accountId ?? "all"}|${urlQ}`;
  const seen = useRef<{ key: string; ids: Set<string> }>({ key: viewKey, ids: new Set() });
  if (seen.current.key !== viewKey) seen.current = { key: viewKey, ids: new Set() };
  const ready = pages.status === "success";
  const state = selectionState(items, item, { ready, hasMore: !!pages.hasNextPage, seen: seen.current.ids });
  if (ready) for (const i of items) seen.current.ids.add(i.id);
  const target = parseItem(item);
  const nextItem = items.find((i) => i.id !== item) ?? null;
  const hrefFor = (id: string) => ({ pathname: "/app/issues", search: waitingSearch(params, id) });
  const backTo = { pathname: "/app/issues", search: waitingSearch(params, null) };

  // Narrow: the list's scroll comes back when you return from an item
  const scrollKey = `aiops-waiting-scroll:${waitingSearch(params, null)}`;
  useLayoutEffect(() => {
    if (wide || item || !pages.data) return;
    const y = Number(sessionStorage.getItem(scrollKey) ?? "");
    if (y > 0) { window.scrollTo(0, y); sessionStorage.removeItem(scrollKey); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wide, item, !!pages.data]);
  const paneRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => { paneRef.current?.scrollTo({ top: 0 }); }, [item]);

  const pane = (
    <div ref={paneRef} className={wide ? "relative min-h-0 overflow-y-auto pr-1" : ""}>
      {state === "selected" && target?.kind === "issue" && (
        <IssueDetail key={item!} issueId={target.id} embedded={wide}
                     back={wide ? undefined : { to: `${backTo.pathname}${backTo.search}`, label: t("inbox.back") }} />
      )}
      {state === "selected" && target?.kind === "change" && (
        <ChangeDetailView key={item!} crId={target.id} embedded={wide} back={wide ? undefined : { to: `${backTo.pathname}${backTo.search}` }} />
      )}
      {state !== "selected" && !wide && item && (
        <Link to={backTo} className="mb-3 inline-flex min-h-[44px] items-center text-sm text-primary hover:underline">
          ← {t("inbox.back")}
        </Link>
      )}
      {state !== "selected" && (
        <div role="status" className="flex h-full flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border px-6 py-16 text-center text-sm text-muted-foreground">
          <p>{state === "gone" ? t("inbox.gone") : t("inbox.selectPrompt")}</p>
          {nextItem && (
            <Link to={hrefFor(nextItem.id)}
                  className="rounded-md border border-primary/40 px-3 py-1.5 text-sm font-medium text-primary hover:bg-selected">
              {t("inbox.next")} · {nextItem.ref}
            </Link>
          )}
        </div>
      )}
    </div>
  );

  // Narrow, an item open: the item's page full screen, its own back control returns to the list
  if (!wide && item) return pane;

  const empty = readOnly ? t("cases.waiting.viewerEmpty") : urlQ ? t("inbox.emptyFiltered") : t("cases.waiting.empty");
  const queue = (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold text-foreground">{t("issues.title")}</h1>
        <Link to="/app/signals" className="text-xs text-primary hover:underline">{t("workitem.rawSignals")}</Link>
      </div>
      <div className="space-y-2">
        <QuickViews view="waiting" scope={resolveIssueScope(params.get("scope"))} accountId={accountId} />
        <input type="search" value={q} maxLength={200} onChange={(e) => setQ(e.target.value)}
               placeholder={t("inbox.search")} aria-label={t("inbox.search")}
               className="w-full rounded-md border border-border bg-card px-2.5 py-1.5 text-[16px] placeholder:text-muted-foreground sm:text-sm" />
      </div>
      <nav aria-label={t("cases.waiting.queue")} className={wide ? "relative min-h-0 flex-1 overflow-y-auto pr-1" : ""}
           onClickCapture={() => { if (!wide) sessionStorage.setItem(scrollKey, String(window.scrollY)); }}>
        <QueryState query={pages} isEmpty={(d) => d.pages.every((p) => p.items.length === 0)} emptyText={empty}
                    onRetry={() => void pages.refetch()}>
          {() => (
            <>
              <InboxQueue groups={groups} selected={item} accountName={nameOf} now={now} hrefFor={hrefFor} />
              {pages.hasNextPage && (
                <button type="button" onClick={() => void pages.fetchNextPage()} disabled={pages.isFetchingNextPage}
                        className="mt-3 w-full rounded-lg border border-border bg-card py-2 text-sm font-medium hover:bg-accent disabled:opacity-60">
                  {t("inbox.more").replace("{n}", String((first?.total ?? 0) - items.length))}
                </button>
              )}
            </>
          )}
        </QueryState>
      </nav>
    </div>
  );
  if (!wide) return queue;
  return (
    <div className="grid h-[calc(100vh-var(--topbar-h)-3rem)] grid-rows-[minmax(0,1fr)] grid-cols-[300px_minmax(0,960px)] gap-5 max-[1350px]:grid-cols-[280px_minmax(0,960px)]">
      {queue}
      {pane}
    </div>
  );
}
