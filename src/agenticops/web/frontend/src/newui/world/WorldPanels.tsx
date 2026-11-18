import { Link } from "react-router-dom";
import { Fragment, type RefObject } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { HealthIssue } from "@/api/types";
import type { AttentionItem } from "@/lib/attention";
import { Prov } from "../decide/widgets/Cause";
import { useNfT, type NfT } from "../i18n";
import type { WNode, WorldGraph } from "../lib/world/graph";
import { side } from "../lib/world/relations";
import { expected, hopMarks, type Ask, type Drawn, type Mismatch, type Scene, type View } from "../lib/world/scene";
import { utcStamp } from "../lib/time";

const num = (v: number) => v.toLocaleString("en-US");
const TONE: Record<string, string> = { critical: "var(--red)", warning: "var(--amber)", notice: "var(--mint)" };

/** A resource's health as a dot: the three open levels in colour, no open issue in star white, gone as a hollow ring. */
export function Dot({ node }: { node: Pick<WNode, "health" | "absent"> }) {
  return node.absent ? <i className="hdot gone" /> : <i className="hdot" style={{ background: TONE[node.health] ?? "rgb(var(--star))" }} />;
}
export const Name = ({ node }: { node: Pick<WNode, "name" | "absent"> }) => (node.absent ? <s>{node.name}</s> : <>{node.name}</>);
export const healthKey = (n: Pick<WNode, "health" | "absent">) => `health.${n.absent ? "gone" : n.health}`;

/** Search, filters, and how much of the map is in view. */
export function Tools({ g, ask, sc, search, pathMode, view, busy, turning, onView, onTurn, onAsk, onPick, onPath, onHome }: {
  g: WorldGraph; ask: Ask; sc: Scene; search: RefObject<HTMLInputElement>; pathMode: boolean;
  view: View;
  /** the 3D engine is being fetched */
  busy: boolean;
  turning: boolean;
  onView: (v: View) => void; onTurn: () => void;
  onAsk: (patch: Partial<Ask>) => void; onPick: (i: number) => void; onPath: () => void; onHome: () => void;
}) {
  const t = useNfT();
  const types = [...g.nodes.reduce((m, n) => m.set(n.type, (m.get(n.type) ?? 0) + 1), new Map<string, number>())].sort((a, b) => a[0].localeCompare(b[0]));
  return (
    <div className="wtools card">
      <div className={`tabs wview${busy ? " busy" : ""}`} role="tablist" aria-label={t("view.label")}>
        {(["2d", "3d"] as const).map((v) => (
          <button key={v} type="button" role="tab" aria-selected={view === v} onClick={() => onView(v)}>{t(`view.${v}`)}</button>
        ))}
        <kbd>V</kbd>
      </div>
      <label className="wsearch">
        <input ref={search} className="field" type="search" autoComplete="off" spellCheck={false} value={ask.q} placeholder={t("world.search")}
               aria-label={t("world.search")} onChange={(e) => onAsk({ q: e.target.value })}
               onKeyDown={(e) => {
                 if (e.key !== "Enter" || e.nativeEvent.isComposing || sc.hits[0] === undefined) return;
                 e.nativeEvent.stopPropagation();          // this Enter is the search's: leaving the field must not hand it to the lens
                 e.currentTarget.blur();
                 onPick(sc.hits[0]);
               }} />
        <kbd>F</kbd>
      </label>
      <div id="wres" role="listbox" aria-label={t("world.results")}>
        {ask.q.trim() && (sc.hits.length === 0 ? <p className="note" style={{ margin: "6px 2px 0" }}>{t("world.noMatch")}</p>
          : sc.hits.map((i) => (
            <button key={i} type="button" role="option" aria-selected={ask.sel === i} onClick={() => onPick(i)}>
              <Dot node={g.nodes[i]} /><span><Name node={g.nodes[i]} /></span><small>{g.nodes[i].type}</small>
            </button>
          )))}
      </div>
      <div className="wf">
        <select className="field" aria-label={t("node.type")} value={ask.type ?? ""} onChange={(e) => onAsk({ type: e.target.value || null })}>
          <option value="">{t("world.allTypes")}</option>
          {types.map(([type, n]) => <option key={type} value={type}>{type} · {n}</option>)}
        </select>
        <select className="field" aria-label={t("world.group")} value={ask.group ?? ""} onChange={(e) => onAsk({ group: e.target.value || null })}>
          <option value="">{t("world.allGroups")}</option>
          {g.groups.map((x) => <option key={x.id} value={x.id}>{x.type}: {x.name} · {x.count}</option>)}
        </select>
      </div>
      <button type="button" className="chip-btn" aria-pressed={ask.onlyAbnormal} onClick={() => onAsk({ onlyAbnormal: !ask.onlyAbnormal })}>{t("world.onlyAbnormal")}</button>
      <span className="wcount num">{t("world.showing", { n: num(sc.shown), total: num(sc.totals.present) })}</span>
      <div className="wf">
        <button type="button" className={`btn sm${pathMode ? " on" : ""}`} aria-pressed={pathMode} onClick={onPath}><span className="t">{t("world.path")}</span><kbd>L</kbd></button>
        <button type="button" className="btn sm quiet" onClick={onHome}><span className="t">{t("world.home")}</span><kbd>H</kbd></button>
        {view === "3d" && (
          <button type="button" className={`btn sm${turning ? " on" : ""}`} aria-pressed={turning} onClick={onTurn}><span className="t">{t("world.turn")}</span><kbd>R</kbd></button>
        )}
      </div>
    </div>
  );
}

/** «数据核对»: what the build holds, how every relation of it is shown, how old each part is — and whether the canvas
 *  holds exactly this result. `bad` = the numbers that differ; null = not checked yet. What the check proves is said on
 *  the card: the COUNTS the view reports for what it put on the canvas — not a colour, not a position. */
export function Check({ sc, view, bad, off, perf, buildId, builtAt, healthAt, asOf, building, newerFailed, now }: {
  sc: Scene; view: View; bad: Mismatch[] | null; perf: { fps: number; ms: number | null } | null;
  /** what the flat map left out because it is off the screen; null = the view leaves nothing out (3D) or not checked yet */
  off: Drawn | null;
  buildId: number | null; builtAt: string | null;
  /** when health and «gone» were last read; null = not known */
  healthAt: string | null;
  /** back in time (N15): the past moment the health and «gone» on the map are OF; null = they are of now */
  asOf: string | null;
  building: boolean;
  /** the newest build failed: the map is of an older one */
  newerFailed: { id: number; at: string | null } | null;
  now: number;
}) {
  const t = useNfT();
  const T = sc.totals, want = expected(sc, view);
  return (
    <div className={`wcheck card${bad?.length ? " bad" : ""}`} data-ok={bad === null ? "" : bad.length ? "0" : "1"} data-view={view} data-fps={perf?.fps ?? ""} data-ms={perf?.ms != null ? perf.ms.toFixed(2) : ""}>
      <h2>{t("check.title")}</h2>
      <p><Prov code />{t("check.totals", { present: num(T.present), gone: num(T.gone), open: sc.goneOpen, links: num(T.links), inferred: num(T.inferred) })}</p>
      <p><Prov code />{t("check.relations", { relations: num(T.relations), lines: num(T.lines), circles: num(T.contain - T.containExtra),
                                              ofAccount: num(T.ofAccount), ofGroup: num(T.ofGroup) })}
        {T.containExtra > 0 ? t("check.containExtra", { n: num(T.containExtra) }) : ""}
        {T.dropped > 0 ? t("check.dropped", { n: T.dropped }) : ""}</p>
      <p><Prov code />{builtAt ? t("check.fresh", { t: utcStamp(builtAt, now), id: buildId }) : t("check.fresh.unknown", { id: buildId })}
        {asOf ? t("check.health.asOf", { t: utcStamp(asOf, now) }) : healthAt ? t("check.health", { t: utcStamp(healthAt, now) }) : t("check.health.unknown")}
        {building ? t("check.building") : ""}{newerFailed ? t("check.newerFailed", { id: newerFailed.id, t: newerFailed.at ? utcStamp(newerFailed.at, now) : "—" }) : ""}</p>
      {bad === null ? <p>{t("check.pending")}</p>
        : bad.length ? <p className="mis" role="alert">{t("check.bad")}{bad.map((m) => t("check.item", { what: t(`check.${m.what}`), want: num(m.want), got: num(m.got) })).join("；")}</p>
        : <p className="ok"><Prov code />{t("check.ok", { view: t(`view.${view}`), n: num(want.bright), r: want.rings, rb: want.ringsBright, l: num(want.links), named: want.named })}
            {off && off.nodes + off.rings + off.links > 0 ? t("check.culled", { nodes: num(off.nodes), total: num(want.nodes), rings: off.rings, links: num(off.links) }) : ""}{t("check.scope")}</p>}
    </div>
  );
}

const LIST_MAX = 8;

/** How many resources are not normal now, which, and how the map relates to the queue. */
export function Happen({ g, sc, complete, readOnly, asOf, now, onPick, onDecide }: {
  g: WorldGraph; sc: Scene;
  /** back in time (N15): the moment the numbers are of; null = now. The queue is today's: in the past it is not tied in */
  asOf: string | null;
  now: number;
  /** the whole queue was read; false = it was cut, the numbers are of what was read */
  complete: boolean;
  /** a read-only account is never handed a decision: there is no queue to tie the map to */
  readOnly: boolean;
  onPick: (i: number) => void; onDecide: () => void;
}) {
  const t = useNfT();
  const ties = sc.ties;
  const waiting = ties ? ties.ringed.length + ties.quiet.length + ties.offMap.length : 0;
  return (
    <div className="happen card">
      <h2>{asOf ? t("world.then", { t: utcStamp(asOf, now) }) : t("world.now")}</h2>
      <div className="abn num">{num(sc.abnormal.length)}<small>{t("world.abnormal")}</small></div>
      {sc.abnormal.length ? (
        <ul className="abnlist">
          {sc.abnormal.slice(0, LIST_MAX).map((i) => (
            <li key={i}><button type="button" onClick={() => onPick(i)}><Dot node={g.nodes[i]} /><span>{g.nodes[i].name}</span><small>{g.nodes[i].type}</small></button></li>
          ))}
        </ul>
      ) : <p className="note">{t("world.noneAbnormal")}</p>}
      {sc.abnormal.length > LIST_MAX && <p className="note">{t("node.more", { n: num(sc.abnormal.length - LIST_MAX) })}</p>}
      {sc.goneOpen > 0 && <p className="note"><Prov code />{t("world.goneOpen", { n: sc.goneOpen })}</p>}
      {asOf ? <p className="note ties">{t("world.ties.past")}</p>
        : readOnly ? <p className="note ties">{t("world.ties.readOnly")}</p>
        : ties && waiting === 0 ? <p className="note ties"><Prov code />{t("world.ties.none")}</p>
        : ties ? (
        <p className="note ties">
          <Prov code />{t("world.ties", { n: waiting, ring: ties.ringed.length, quiet: ties.quiet.length, off: ties.offMap.length })}
          {!complete && t("world.ties.cut")}{"　"}
          <button type="button" className="linkish" onClick={onDecide}>{t("world.tiesGo")}</button>
        </p>
      ) : <p className="note ties">{t("world.ties.unknown")}</p>}
    </div>
  );
}

const NB_MAX = 7, ISSUES_MAX = 5;

/** The resource's OPEN issues (GET /api/resources/{id}/issues?open=true): the ones anchored to it — what its health
 *  on the map is made of — and the ones tied to it only by the alarm's resource id, which the health does not count.
 *  Open ones only: the newest twenty of any status could leave the one open issue out. */
function useOpenIssues(ref: number) {
  return useQuery({
    queryKey: ["resourceIssues", ref, "open"],
    queryFn: () => apiFetch<HealthIssue[]>(`/resources/${ref}/issues?open=true&limit=50`),
    enabled: ref > 0,
    staleTime: 15_000,
  });
}

/** The open resource: what it is, how it is, what is open on it, what it is linked to and how. */
export function NodeCard({ g, i, ask, mine, accountName, now, healthAt, asOf, onPick, onClose, onFocus, onPathFrom, onStory, onDecide }: {
  g: WorldGraph; i: number; ask: Ask;
  /** the items waiting on this person that sit on this resource */
  mine: AttentionItem[];
  accountName: (id: number | null) => string;
  now: number;
  /** when health and «gone» were last read; null = not known */
  healthAt: string | null;
  /** back in time (N15): the moment the health on this card is OF; null = now. The list of issues below it is
   *  read as of now either way, and says so */
  asOf: string | null;
  onPick: (i: number) => void; onClose: () => void; onFocus: () => void; onPathFrom: () => void;
  onStory: (item: string) => void; onDecide: (item: string) => void;
}) {
  const t = useNfT();
  const n = g.nodes[i], nb = g.adj[i], llm = nb.filter(([, k]) => g.edges[k].llm).length;
  const others = new Set(nb.map(([j]) => j)).size;             // two relations to the same resource are one neighbour
  const issues = useOpenIssues(n.ref);
  const open = issues.data ?? [];
  const anchored = open.filter((x) => x.resource_ref === n.ref), byId = open.filter((x) => x.resource_ref !== n.ref);
  const groups = n.groups.map((id) => g.groups.find((x) => x.id === id)).filter((x): x is NonNullable<typeof x> => !!x);
  return (
    <aside className="nodecard card" aria-label={t("node.resource")}>
      <button type="button" className="x" onClick={onClose} aria-label={t("peek.close")}>×</button>
      <h3><Name node={n} /></h3>
      <div className="sub">{n.type}　·　{accountName(n.acct)}</div>
      <p><Prov code /><Dot node={n} /><b>{t(healthKey(n))}</b></p>
      {n.absent ? <p className="note"><Prov code />{t(n.health !== "unknown" ? "node.gone.open" : "node.gone")}</p>
        : n.health === "unknown" ? <p className="note">{t(asOf ? "node.none.then" : "node.none")}</p> : null}
      {asOf && <p className="note"><Prov code />{t("node.issuesNow")}</p>}
      {issues.isPending ? <div className="skel" style={{ height: 18 }} />
        : issues.isError ? <p className="note err">{t("sec.failedLoad")}</p>
        : [[anchored, null] as const, [byId, "node.byId"] as const].map(([list, note]) => list.length > 0 && (
          <Fragment key={note ?? "anchored"}>
            {note && <p className="note"><Prov code />{t(note, { n: list.length })}</p>}
            <ul className="nb">
              {list.slice(0, ISSUES_MAX).map((x) => (
                <li key={x.id}><button type="button" onClick={() => onStory(`I${x.id}`)}><i className="hdot" style={{ background: "transparent" }} /><span>{x.title}</span><small className="num">I#{x.id}</small></button></li>
              ))}
            </ul>
            {list.length > ISSUES_MAX && <p className="note">{t("node.more", { n: list.length - ISSUES_MAX })}</p>}
          </Fragment>
        ))}
      <p><Prov code />{t("node.links", { n: others, links: nb.length })}{llm ? t("node.linksLlm", { n: llm }) : ""}</p>
      <ul className="nb">
        {nb.slice(0, NB_MAX).map(([j, k, out]) => {
          const e = g.edges[k], rel = side({ r: e.r, p: e.llm ? "llm" : "rule" }, out);
          return (
            <li key={`${j}:${k}`}>
              <button type="button" onClick={() => onPick(j)} title={e.llm && e.ev ? e.ev : undefined}>
                <Dot node={g.nodes[j]} /><span><Name node={g.nodes[j]} /></span><small>{t(`rel.${rel}`)} · {e.r}</small>
              </button>
            </li>
          );
        })}
      </ul>
      {nb.length > NB_MAX && <p className="note">{t("node.more", { n: nb.length - NB_MAX })}</p>}
      {groups.length > 0 && <p className="note">{t("node.groups", { groups: groups.map((x) => `${x.type}: ${x.name}`).join("、") })}</p>}
      <p className="note">{asOf ? t("node.asOf.past", { t: utcStamp(asOf, now) }) : healthAt ? t("node.asOf", { t: utcStamp(healthAt, now) }) : t("node.asOf.unknown")}</p>
      <div className="acts">
        {mine.map((item) => (
          <button key={item.id} type="button" className="btn primary sm" onClick={() => onDecide(item.id)}><span className="t">{t("node.go")}　{item.ref}</span></button>
        ))}
        <button type="button" className={`btn sm${ask.focus ? " on" : ""}`} aria-pressed={ask.focus} onClick={onFocus}><span className="t">{t("world.focus")}</span><kbd>G</kbd></button>
        <button type="button" className="btn sm" onClick={onPathFrom}><span className="t">{t("path.from")}</span></button>
        <Link className="btn sm quiet" to={`/app/resources/${n.ref}`}><span className="t">{t("node.classic")}</span></Link>
      </div>
    </aside>
  );
}

/** While finding a path: what to click next, the chain once there is one, and what a path is not. */
export function PathHint({ g, ask, sc, onExit }: { g: WorldGraph; ask: Ask; sc: Scene; onExit: () => void }) {
  const t = useNfT();
  const name = (i: number) => g.nodes[i].name;
  return (
    <p className="wpast whint" role="status">
      {ask.a === null ? t("path.pick1") : ask.b === null ? t("path.pick2", { a: name(ask.a) })
        : sc.path ? (
          <>
            <Prov code />{t("path.found", { n: sc.path.length - 1 })}
            <span className="chain">
              {sc.path.map((i, k) => {
                // the relation between this resource and the one before it, by name, with the arrow the way the BUILD
                // wrote it («a ←contains— b» = b contains a); a guess is said to be one
                const hop = k ? sc.pathHops?.[k - 1] : null, [l, r] = hop ? hopMarks(hop) : ["", ""];
                return <Fragment key={i}>{hop && <small className={hop.llm ? "hop llm" : "hop"}> {l}{hop.r}{hop.llm ? t("path.inferredHop") : ""}{r} </small>}{name(i)}</Fragment>;
              })}
            </span>
            {"　"}{sc.pathInferred > 0 && <b>{t("path.inferred", { n: sc.pathInferred })}</b>}{t("path.caveat")}
          </>
        )
        : <><Prov code />{t("path.none", { a: name(ask.a), b: name(ask.b) })}</>}
      {"　"}<button type="button" className="btn sm quiet" onClick={onExit}><span className="t">{t("path.exit")}</span><kbd>Esc</kbd></button>
    </p>
  );
}

export function Legend({ t, view }: { t: NfT; view: View }) {
  return (
    <div className="legend">
      <span><i style={{ background: "var(--red)" }} />{t("health.critical")}</span>
      <span><i style={{ background: "var(--amber)" }} />{t("health.warning")}</span>
      <span><i style={{ background: "var(--mint)" }} />{t("health.notice")}</span>
      <span><i style={{ background: "rgb(var(--star))", opacity: 0.6 }} />{t("legend.none")}</span>
      {/* the flat map draws a gone resource hollow, the 3D view as a fainter sphere: the legend shows what is drawn */}
      <span>{view === "3d" ? <i style={{ background: "rgb(var(--star))", opacity: 0.22 }} /> : <i className="gonei" />}{t(view === "3d" ? "legend.gone3d" : "legend.gone")}</span>
      <span><i className={view === "3d" ? "curve" : "dash"} />{t(view === "3d" ? "legend.llm3d" : "legend.llm")}</span>
      <span><i style={{ background: "var(--mint)", width: 5, height: 5 }} />{t(view === "3d" ? "legend.flow3d" : "legend.flow")}</span>
      <span className="sch">{t("legend.schematic")}</span>
    </div>
  );
}
