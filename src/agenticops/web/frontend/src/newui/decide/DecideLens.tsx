import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useAccountScope } from "@/components/layout/AccountScope";
import { useAccounts } from "@/hooks/useAccounts";
import { useReadOnly } from "@/hooks/useBootstrap";
import { parseItem } from "@/lib/inbox";
import { useDecideQueue } from "../hooks/useDecideQueue";
import { useNfT } from "../i18n";
import { briefKind, itemKind } from "../lib/briefKind";
import {
  currentItem, deepLinkState, emptyKind, flattenPages, groupCounts, parseFilter, pruneHandled, situation, step, withoutHandled,
  type QueueFilter,
} from "../lib/queue";
import { Message, StateBlock } from "../shell/StateBlock";
import { useLensKeys, useShell } from "../shell/shellContext";
import { DecideContext, type BriefKeys, type DecideApi } from "./briefs/briefContext";
import { BRIEFS } from "./briefs/registry";
import { Feed } from "./Feed";
import { GenericBrief } from "./GenericBrief";
import { usePeek } from "./widgets/usePeek";
import { Queue } from "./Queue";

const place = (id: string | null, filter: QueueFilter) =>
  ({ pathname: id ? `/app/new/decide/${id}` : "/app/new/decide", search: filter === "all" ? "" : `?f=${filter}` });

/** «待决»: the queue on the left, one item's brief in the middle. The address names the item (`/decide/I12`) and the
 *  filter (`?f=approval`), so a reload, a link and the browser's Back all land on the same page. */
export function DecideLens() {
  const t = useNfT();
  const navigate = useNavigate();
  const { notify } = useShell();
  const { item: itemParam = null } = useParams();
  const [search] = useSearchParams();
  const filter = parseFilter(search.get("f"));
  const { accountId } = useAccountScope();
  const accounts = useAccounts();
  const readOnly = useReadOnly();
  const q = useDecideQueue({ accountId, filter });

  // what was decided a moment ago leaves the list at once; the server's list catches up at its next refresh
  const [handled, setHandled] = useState<ReadonlyMap<string, string>>(new Map());
  const listed = useMemo(() => flattenPages(q.data?.pages), [q.data]);
  useEffect(() => { setHandled((old) => pruneHandled(listed, old)); }, [listed]);
  const items = useMemo(() => withoutHandled(listed, handled), [listed, handled]);
  const first = q.data?.pages[0];
  const counts = groupCounts(first?.counts);
  const total = first?.total ?? null;
  const loaded = q.data !== undefined;
  const view = loaded ? "ready" : q.isError ? "failed" : "loading";
  const link = deepLinkState({ item: itemParam, items, ready: loaded, hasMore: !!q.hasNextPage });

  // the place the selected item had: when it leaves the list, «next» is whatever now stands there
  const lastIndex = useRef(0);
  const cur = link === "found" || link === "none" ? currentItem(items, itemParam, 0) : null;
  if (link === "found" && cur) lastIndex.current = cur.index;

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  // no item in the address: the first of the list, written into the address
  const firstId = link === "none" && cur ? cur.item.id : null;
  useEffect(() => {
    if (firstId) navigate(place(firstId, filter), { replace: true });
  }, [firstId, filter, navigate]);

  // an address that names an item further down, and the rows near the end of what is listed: fetch on
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = q;
  const nearEnd = !!cur && cur.index >= items.length - 5;
  useEffect(() => {
    if ((link === "loading" || nearEnd) && hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [link, nearEnd, hasNextPage, isFetchingNextPage, fetchNextPage]);

  const pick = useCallback((id: string) => navigate(place(id, filter), { replace: true }), [navigate, filter]);
  const move = useCallback((delta: number) => {
    if (!items.length) return;
    const at = cur ? step(items.length, cur.index, delta)
      : Math.min(Math.max(lastIndex.current + (delta > 0 ? 0 : -1), 0), items.length - 1);   // the selected item left the list
    pick(items[at].id);
  }, [items, cur, pick]);
  const setFilter = (f: QueueFilter) => { lastIndex.current = 0; navigate(place(null, f)); };

  const curId = cur?.item.id ?? null;
  const peek = usePeek(curId);

  const briefKeys = useRef<BriefKeys | null>(null);
  const api = useMemo<DecideApi>(() => ({
    setBriefKeys: (keys) => { briefKeys.current = keys; },
    // the item that was decided leaves the list now, and the one after it takes the page
    done: (message) => {
      notify(message);
      const at = items.findIndex((i) => i.id === curId);
      const next = at < 0 ? null : items[at + 1] ?? items[at - 1] ?? null;
      if (at >= 0) setHandled((old) => new Map(old).set(items[at].id, situation(items[at])));
      navigate(place(next ? next.id : null, filter), { replace: true });
    },
    openPeek: peek.show,
  }), [notify, navigate, items, curId, filter, peek.show]);

  useLensKeys({
    onKey: (key, e, repeat) => {
      if (peek.onKey(key)) return true;
      if (key === "j" || key === "arrowdown") { move(1); return true; }
      if (key === "k" || key === "arrowup") { move(-1); return true; }
      return briefKeys.current?.onKey?.(key, e, repeat);
    },
    onKeyUp: (key) => briefKeys.current?.onKeyUp?.(key),
    onEscape: () => {
      if (peek.open) { peek.close(); return true; }
      return briefKeys.current?.onEscape?.() ?? false;
    },
  });

  let key: string, body: React.ReactNode;
  if (view !== "ready") {
    key = view;
    body = <StateBlock kind={view} onRetry={() => void q.refetch()} />;
  } else if (link === "loading") {
    key = "seeking";
    body = <StateBlock kind="loading" />;
  } else if (link === "gone") {
    const gone = parseItem(itemParam);
    key = `gone:${itemParam}`;
    body = (
      <Message big={t("gone.big", { ref: gone ? `${gone.kind === "issue" ? "I" : "C"}#${gone.id}` : itemParam })}>
        <p>{t("gone.p")}</p>
        <p className="row">
          {items.length > 0 && <button type="button" className="btn primary" onClick={() => move(1)}><span className="t">{t("gone.next")}</span><kbd>J</kbd></button>}
          {gone && <Link className="btn" to={gone.kind === "issue" ? `/app/issues/${gone.id}` : `/app/changes/${gone.id}`}><span className="t">{t("gone.open")}</span></Link>}
        </p>
      </Message>
    );
  } else if (!cur) {
    const why = emptyKind({ filter, counts, readOnly });
    key = `empty:${why}`;
    body = why === "readOnly" ? (
      <Message big={t("empty.readOnly.big")}>
        <p>{t("empty.readOnly.p")}</p>
        <p><Link className="btn" to="/app/issues"><span className="t">{t("empty.readOnly.open")}</span></Link></p>
      </Message>
    ) : why === "filtered" ? (
      <Message big={t("empty.filtered.big")}>
        <p>{t("empty.filtered.p", { n: counts?.all })}</p>
        <p><button type="button" className="btn" onClick={() => setFilter("all")}><span className="t">{t("empty.filtered.all")}</span></button></p>
      </Message>
    ) : (
      <Message big={t("clear.big")}>
        <p>{t("clear.p")}</p>
        <p style={{ fontSize: "var(--fs-sm)", marginTop: 18 }}>{t("clear.honest")}</p>
      </Message>
    );
  } else {
    const item = cur.item;
    const kind = briefKind(item);
    const Brief = (kind && BRIEFS[kind]?.[itemKind(item)]) || GenericBrief;
    // the brief is a new component when the item's situation changes (a confirmed diagnosis becomes «generate the plan»)
    key = `${item.id}:${kind ?? "generic"}`;
    body = <Brief item={item} frame={{ index: cur.index, total: total ?? items.length, now, readOnly,
                                       accountName: accounts.data?.find((a) => a.id === item.account_id)?.name ?? null }} />;
  }

  return (
    <DecideContext.Provider value={api}>
      <section className="view" id="decide">
        <Queue items={items} currentId={curId} filter={filter} counts={counts} view={view}
               staleSince={loaded && q.isError ? q.dataUpdatedAt : null} total={total} hasMore={!!hasNextPage}
               loadingMore={isFetchingNextPage} now={now} onFilter={setFilter} onPick={pick} onMore={() => void fetchNextPage()} />
        <article key={key} className="brief card swap" aria-live="polite" aria-label={t("brief.label")}>{body}</article>
        <Feed now={now} />
      </section>
      {peek.node}
    </DecideContext.Provider>
  );
}
