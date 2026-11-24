import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useAccountScope } from "@/components/layout/AccountScope";
import { useLocale } from "@/i18n/LocaleContext";
import { waitedText } from "../decide/Queue";
import { useAllItems } from "../hooks/useAllItems";
import { useNfT } from "../i18n";
import { boxAfterAddress, SEVERITY_CHOICES, itemsQuery, itemsSearch, sortsOf, statusesOf, type ItemGroup, type ItemKind, type ItemRow, type ItemSort, type ItemsQuery } from "../lib/items";
import { storyPath } from "../lib/story";
import { utcHm, utcStamp } from "../lib/time";
import { useLensKeys } from "../shell/shellContext";
import { Message, StateBlock } from "../shell/StateBlock";

const KINDS: ItemKind[] = ["issue", "change"];
const GROUPS: ItemGroup[] = ["open", "closed", "all"];
const SEV_TONE: Record<string, string> = { critical: "crit", high: "crit", medium: "warn", low: "info" };

/** «所有事项» (round 3, N18): every issue and every change request, in any state — NewUI's own table, where the
 *  classic interface had the issue list. Filters, search and order are the server's and live in the address; a row
 *  opens the item's story and comes back here. `J` / `K` move along the rows, Enter opens. */
export function ItemsLens() {
  const t = useNfT();
  const { t: classicT } = useLocale();                       // the product's own words for a status, a severity, a wait
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const q = itemsQuery(params);
  const { accountId } = useAccountScope();
  const list = useAllItems(q, accountId);
  const body = useRef<HTMLTableSectionElement>(null);

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const set = useCallback((patch: Partial<ItemsQuery>) => {
    const next = { ...q, ...patch };
    // a choice that belongs to the other kind does not travel with a change of kind
    if (patch.kind && patch.kind !== q.kind) { next.status = null; next.severity = null; if (next.sort === "severity") next.sort = "newest"; }
    setParams(new URLSearchParams(itemsSearch(next)), { replace: true });
  }, [q, setParams]);

  // the search is sent a moment after the typing stops; the address stays the one source of the choice
  const [typed, setTyped] = useState(q.q);
  useEffect(() => { setTyped((now) => boxAfterAddress(now, q.q)); }, [q.q]);
  useEffect(() => {
    if (typed.trim() === q.q) return;
    const id = window.setTimeout(() => set({ q: typed.trim() }), 300);
    return () => window.clearTimeout(id);
  }, [typed, q.q, set]);

  const origin = { from: "items" as const, back: location.pathname + location.search };
  const rowLinks = () => [...(body.current?.querySelectorAll<HTMLAnchorElement>("a.ttl") ?? [])];
  useLensKeys({
    onKey: (key) => {
      if (key !== "j" && key !== "k") return false;
      const links = rowLinks(), at = links.indexOf(document.activeElement as HTMLAnchorElement);
      const to = links[key === "j" ? Math.min(links.length - 1, at + 1) : Math.max(0, at - 1)];
      to?.focus();
      to?.scrollIntoView({ block: "nearest" });
      return true;
    },
  });

  const shown = list.rows.length;
  const level = (r: ItemRow) => {
    if (!r.level) return <span className="quiet">{t("items.unrated")}</span>;
    return q.kind === "issue" ? <span className={`sev ${SEV_TONE[r.level] ?? ""}`}>{classicT(`severity.${r.level}`)}</span> : <span className="num">{r.level}</span>;
  };

  return (
    <section className="view" id="items">
      <div className="card ipage">
        <header className="ihead">
          <h1>{t("items.title")}</h1>
          <div className="iseg" role="group" aria-label={t("items.kind.label")}>
            {KINDS.map((k) => (
              <button key={k} type="button" className="chip-btn" aria-pressed={q.kind === k} onClick={() => set({ kind: k })}>{t(`items.kind.${k}`)}</button>
            ))}
          </div>
          <span className="icount num" role="status">
            {list.total === null ? "" : shown < list.total ? t("items.shown", { shown, n: list.total.toLocaleString("en-US") }) : t("items.total", { n: list.total.toLocaleString("en-US") })}
          </span>
        </header>

        <div className="ifilters">
          <div className="iseg" role="group" aria-label={t("items.group.label")}>
            {GROUPS.map((g) => (
              <button key={g} type="button" className="chip-btn" aria-pressed={q.group === g && !q.status} onClick={() => set({ group: g, status: null })}>{t(`items.group.${g}`)}</button>
            ))}
          </div>
          <select aria-label={t("items.status.label")} value={q.status ?? ""} onChange={(e) => set({ status: e.target.value || null })}>
            <option value="">{t("items.status.any")}</option>
            {statusesOf(q.kind).map((s) => <option key={s} value={s}>{classicT(`${q.kind === "issue" ? "issues" : "changes"}.status.${s}`)}</option>)}
          </select>
          {q.kind === "issue" && (
            <select aria-label={t("items.sev.label")} value={q.severity ?? ""} onChange={(e) => set({ severity: e.target.value || null })}>
              <option value="">{t("items.sev.any")}</option>
              {SEVERITY_CHOICES.map((s) => <option key={s} value={s}>{classicT(`severity.${s}`)}</option>)}
            </select>
          )}
          <select aria-label={t("items.sort.label")} value={q.sort} onChange={(e) => set({ sort: e.target.value as ItemSort })}>
            {sortsOf(q.kind).map((s) => <option key={s} value={s}>{t(`items.sort.${s}`)}</option>)}
          </select>
          <input className="field isearch" type="search" value={typed} maxLength={200} aria-label={t(`items.search.${q.kind}`)}
                 placeholder={t(`items.search.${q.kind}`)} onChange={(e) => setTyped(e.target.value)} />
        </div>

        {list.staleAt !== null && (
          <p className="note warn" role="status">{t("items.stale", { t: utcHm(list.staleAt) })}{"　"}
            <button type="button" className="more-btn" onClick={list.retry}>{t("state.retry")}</button></p>
        )}

        <div className="iscroll">
          {list.status === "loading" ? <StateBlock kind="loading" />
            : list.status === "failed" ? <StateBlock kind="failed" failKey="items.failed.p" onRetry={list.retry} />
            : shown === 0 ? <Message big={t("items.empty")}><p>{t("items.empty.hint")}</p></Message>
            : (
              <>
                <table className="tgrid itable">
                  <thead>
                    <tr>
                      <th scope="col">{t("items.col.ref")}</th><th scope="col">{t("items.col.title")}</th><th scope="col">{t("items.col.status")}</th>
                      <th scope="col">{t(`items.col.level.${q.kind}`)}</th><th scope="col">{t("items.col.wait")}</th>
                      <th scope="col" className="wide">{t("items.col.account")}</th><th scope="col" className="wide">{t(`items.col.time.${q.kind}`)}</th>
                    </tr>
                  </thead>
                  <tbody ref={body}>
                    {list.rows.map((r) => (
                      <tr key={r.item} className={r.closed ? "closed" : undefined} onClick={(e) => {
                        // the whole row opens the item; a click on the link itself is the link's own
                        if ((e.target as HTMLElement).closest("a")) return;
                        navigate(storyPath(r.item), { state: origin });
                      }}>
                        <td className="num">{r.ref}</td>
                        <td className="ititle"><Link className="ttl" to={storyPath(r.item)} state={origin}>{r.title}</Link>{r.sub && <small>{r.sub}</small>}</td>
                        <td>{classicT(r.statusKey)}</td>
                        <td>{level(r)}</td>
                        <td>{r.waitKey ? <>{classicT(r.waitKey)}{r.waitSince && <small>{waitedText(r.waitSince, now, t)}</small>}</> : <span className="quiet">—</span>}</td>
                        <td className="wide">{r.account ?? <span className="quiet">—</span>}</td>
                        <td className="wide num">{utcStamp(r.time, now)} UTC</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {list.hasMore && (
                  <p className="imore">
                    <button type="button" className="btn" disabled={list.loadingMore} onClick={list.more}>
                      <span className="t">{list.loadingMore ? t("items.more.busy") : t("items.more", { n: Math.min(50, (list.total ?? 0) - shown) })}</span>
                    </button>
                    {list.moreFailed && <span className="note err" role="alert">{t("items.more.failed")}</span>}
                  </p>
                )}
              </>
            )}
        </div>
      </div>
    </section>
  );
}
