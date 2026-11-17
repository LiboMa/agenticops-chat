import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useAccountScope } from "@/components/layout/AccountScope";
import { useAccounts } from "@/hooks/useAccounts";
import { useReadOnly } from "@/hooks/useBootstrap";
import { parseItem } from "@/lib/inbox";
import type { AttentionItem } from "@/lib/attention";
import { useDecideQueue } from "../hooks/useDecideQueue";
import { useMyItem } from "../hooks/useMyItem";
import { useNfT } from "../i18n";
import { briefKind, itemKind } from "../lib/briefKind";
import { swapGuard } from "../lib/keys";
import {
  currentItem, deepLinkState, emptyKind, flattenPages, groupCounts, parseFilter, pruneHandled, settle, situation, step, withoutHandled,
  type QueueFilter,
} from "../lib/queue";
import { storyPath } from "../lib/story";
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
  const location = useLocation();
  const { notify } = useShell();
  const { item: itemParam = null } = useParams();
  const [search] = useSearchParams();
  const filter = parseFilter(search.get("f"));
  const { accountId, setAccountId } = useAccountScope();
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

  // the person's own move (J / K / a click / a filter): the brief it opens takes their keys at once
  const ownMove = useRef(false);
  const pick = useCallback((id: string) => { ownMove.current = true; navigate(place(id, filter), { replace: true }); }, [navigate, filter]);
  const move = useCallback((delta: number) => {
    if (!items.length) return;
    const at = cur ? step(items.length, cur.index, delta)
      : Math.min(Math.max(lastIndex.current + (delta > 0 ? 0 : -1), 0), items.length - 1);   // the selected item left the list
    pick(items[at].id);
  }, [items, cur, pick]);
  const setFilter = (f: QueueFilter) => { lastIndex.current = 0; ownMove.current = true; navigate(place(null, f)); };
  // «经过»: the item's whole record; it comes back to this very place
  const openStory = (id: string) => navigate(storyPath(id), { state: { from: "decide", back: location.pathname + location.search } });

  // The brief on the page stays while its item is looked for again. A refresh can move the item to a page of the
  // list that is not loaded yet — after a new diagnosis it is a newer wait and sorts to the end of its group — and
  // taking the brief away for that second would lose what the person was just told (a refusal's reason) or was
  // typing. `held` is that item as it last stood; once the list has it again, or says it is gone, the list decides.
  const lastShown = useRef<AttentionItem | null>(null);
  if (cur) lastShown.current = cur.item;
  const held = !cur && link === "loading" && lastShown.current?.id === itemParam ? lastShown.current : null;
  const curId = cur?.item.id ?? held?.id ?? null;
  const peek = usePeek(curId);
  const shownKey = useRef<string | null>(null);        // the page as it was at the last render
  const guardUntil = useRef(0);                         // until when a brief's keys wait
  const changed = useRef<string | null>(null);          // the ref of an item whose page changed under the person

  // what the page shows NOW — an answer to a decision reads it when it arrives, not when the request was sent
  const now_ = useRef({ items, shown: { id: curId }, filter });
  now_.current = { items, shown: { id: curId }, filter };

  const briefKeys = useRef<BriefKeys | null>(null);
  const api = useMemo<DecideApi>(() => {
    const settled = (item: AttentionItem, ok: boolean, message: string) => {
      const { items: list, shown, filter: f } = now_.current;
      const r = settle(list, shown, item, ok);
      if (r.toast) notify(ok ? message : `${item.ref}　${message}`);                 // a failure names its item: the page may show another
      if (r.handled) setHandled((old) => new Map(old).set(item.id, situation(item)));
      if (r.goTo !== undefined) navigate(place(r.goTo, f), { replace: true });
    };
    return {
      setBriefKeys: (keys) => { briefKeys.current = keys; },
      done: (item, message) => settled(item, true, message),
      failed: (item, message) => settled(item, false, message),
      openPeek: peek.show,
    };
  }, [notify, navigate, peek.show]);

  useLensKeys({
    onKey: (key, e, repeat) => {
      if (peek.onKey(key)) return true;
      if (key === "j" || key === "arrowdown") { move(1); return true; }
      if (key === "k" || key === "arrowup") { move(-1); return true; }
      if (key === "enter" && curId) { if (!repeat && performance.now() >= guardUntil.current) openStory(curId); return true; }
      // a held key repeating, or a key pressed just after the page changed by itself, is not this brief's
      if (repeat || performance.now() < guardUntil.current) return true;
      return briefKeys.current?.onKey?.(key, e, repeat);
    },
    onKeyUp: (key) => briefKeys.current?.onKeyUp?.(key),
    onEscape: () => {
      if (peek.open) { peek.close(); return true; }
      return briefKeys.current?.onEscape?.() ?? false;
    },
  });

  // the item named by an address that is not on this list may still wait on the person — under another filter, or
  // in another account than the scope: ask the unfiltered, unscoped list before saying «not waiting on you»
  const elsewhere = useMyItem(link === "gone" ? itemParam : null);

  let key: string, body: React.ReactNode;
  if (view !== "ready") {
    key = view;
    body = <StateBlock kind={view} onRetry={() => void q.refetch()} />;
  } else if (link === "loading" && !held) {
    key = "seeking";
    body = <StateBlock kind="loading" />;
  } else if (link === "gone") {
    const gone = parseItem(itemParam);
    const ref = gone ? `${gone.kind === "issue" ? "I" : "C"}#${gone.id}` : itemParam;
    const still = elsewhere.data ?? null;                         // it does wait on this person, just not in this list
    key = `gone:${itemParam}:${still ? "elsewhere" : elsewhere.isPending ? "asking" : "gone"}`;
    body = elsewhere.isPending ? <StateBlock kind="loading" /> : still ? (
      <Message big={t("gone.elsewhere.big", { ref })}>
        <p>{t(filter !== "all" ? "gone.elsewhere.filter" : "gone.elsewhere.scope")}</p>
        <p className="row">
          <button type="button" className="btn primary" onClick={() => {
            ownMove.current = true;
            if (accountId !== null && still.account_id !== accountId) setAccountId(still.account_id ?? null);
            navigate(place(still.id, "all"));
          }}><span className="t">{t("gone.elsewhere.show")}</span></button>
        </p>
      </Message>
    ) : (
      <Message big={t("gone.big", { ref })}>
        <p>{t("gone.p")}</p>
        <p className="row">
          {items.length > 0 && <button type="button" className="btn primary" onClick={() => move(1)}><span className="t">{t("gone.next")}</span><kbd>J</kbd></button>}
          {gone && itemParam && <button type="button" className="btn" onClick={() => openStory(itemParam)}><span className="t">{t("gone.story")}</span></button>}
        </p>
      </Message>
    );
  } else if (!cur && !held) {
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
    const item = (cur?.item ?? held)!;
    const kind = briefKind(item);
    const Brief = (kind && BRIEFS[kind]?.[itemKind(item)]) || GenericBrief;
    // the brief is a new component when the item's situation changes (a confirmed diagnosis becomes «generate the plan»)
    key = `${item.id}:${kind ?? "generic"}`;
    body = <Brief item={item} frame={{ index: cur ? cur.index : lastIndex.current, total: total ?? items.length, now, readOnly,
                                       accountName: accounts.data?.find((a) => a.id === item.account_id)?.name ?? null }} />;
  }

  // a brief the person did not open — the item was decided elsewhere, changed situation, or a decision moved the
  // page on — does not take keys at once (lib/keys.swapGuard); when the SAME item came back as another situation
  // under the person's hands, say so: the page they were reading is gone
  if (shownKey.current !== key) {
    const until = swapGuard(shownKey.current, key, ownMove.current, performance.now());
    if (until !== null) guardUntil.current = until;
    if (until !== null && cur && shownKey.current?.startsWith(`${cur.item.id}:`)) changed.current = cur.item.ref;
    shownKey.current = key;
    ownMove.current = false;
  }
  useEffect(() => {
    if (!changed.current) return;
    notify(t("brief.changed", { ref: changed.current }));
    changed.current = null;
  }, [key, notify, t]);

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
