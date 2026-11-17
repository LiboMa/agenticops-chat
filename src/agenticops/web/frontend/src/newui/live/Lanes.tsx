import { laneLabel } from "../decide/Feed";
import { useNfT, type NfT } from "../i18n";
import { LANE_GROUPS, type LaneView, type recentCut } from "../lib/live";
import { utcStamp } from "../lib/time";

/** A lane's edge colour, as the stylesheet names it. */
export const LANE_CLASS: Record<LaneView["tone"], string> = { run: "run", late: "held", wait: "done", done: "done", bad: "stop", you: "wait" };

/** The agent's name; one this page does not know keeps the server's word. */
export function agentName(agent: string, t: NfT): string {
  const name = t(`by.${agent}`);
  return name === `by.${agent}` ? agent : name;
}

/** What a lane is doing, in a few words: «诊断 · 已经 3 分钟», «诊断停了 · 42 天前», «13:00 UTC 开始», «执行 · 失败». */
export function laneState(lane: LaneView, now: number, t: NfT): string {
  if (lane.group === "upcoming") return t("live.due", { t: utcStamp(lane.at, now) });
  if (lane.group === "recent") {
    const what = t(`lane.${lane.kind}`) === `lane.${lane.kind}` ? lane.kind : t(`lane.${lane.kind}`);
    return `${what} · ${t(`outcome.${lane.outcome ?? "done"}`)}`;
  }
  return laneLabel({ kind: lane.kind, since: lane.at, basis: lane.basis ?? "" }, now, t);
}

/** The left rail of «现场»: every lane in its group — at work now, due next, ended in the last day. */
export function Lanes({ lanes, currentId, view, staleAt, cut, now, onPick, onRetry }: {
  lanes: LaneView[]; currentId: string | null; view: "loading" | "failed" | "ready";
  /** the list is older than the newest attempt: when it was fetched (epoch ms) */
  staleAt: number | null;
  /** «ended in the last day» shows only the newest of what ended (lib/live.recentCut); null = everything is listed */
  cut: ReturnType<typeof recentCut>;
  now: number; onPick: (id: string) => void; onRetry: () => void;
}) {
  const t = useNfT();
  return (
    <aside className="lanes" aria-label={t("live.title")}>
      <div className="rail-title">
        <span>{t("live.title")}</span>
        <span className={`conn${staleAt !== null || view === "failed" ? " off" : ""}`}><i />{t(staleAt !== null || view === "failed" ? "live.offline" : "live.polled")}</span>
      </div>
      {staleAt !== null && (
        <p className="stalebar" role="alert">
          {t("live.stale", { t: utcStamp(staleAt, now) })}{"　"}
          <button type="button" className="btn sm" onClick={onRetry}><span className="t">{t("state.retry")}</span></button>
        </p>
      )}
      {view === "loading" && [0, 1, 2].map((k) => (
        <div key={k} className="lane"><div className="skel" style={{ width: "50%" }} /><div className="skel" style={{ width: "86%", marginTop: 10 }} /></div>
      ))}
      {view === "ready" && LANE_GROUPS.map((g) => {
        const part = lanes.filter((l) => l.group === g);
        // «at work now» is always said, even when it is nobody: an empty list must not read as a broken page
        if (!part.length && g !== "running") return null;
        return (
          <div key={g} style={{ display: "contents" }}>
            <h2 className="lgroup">{t(`live.group.${g}`)}<span className="num">{part.length}</span></h2>
            {!part.length && <p className="q-note" style={{ margin: "0 2px 4px" }}>{t("feed.none")}</p>}
            {g === "recent" && cut && (
              <p className="q-note" style={{ margin: "0 2px 4px" }}>
                {[cut.work && t("live.cut.work", { shown: cut.work.shown, total: cut.work.total }),
                  cut.schedules && t("live.cut.schedules", { shown: cut.schedules.shown, total: cut.schedules.total })].filter(Boolean).join("　")}
              </p>
            )}
            {part.map((l) => (
              <button key={l.id} type="button" className={`lane ${LANE_CLASS[l.tone]}`} aria-selected={l.id === currentId} onClick={() => onPick(l.id)}>
                <span className="lt"><span className="ag">{agentName(l.agent, t)}</span><span className="st">{laneState(l, now, t)}</span></span>
                <span className="ti">{l.title}</span>
                <span className="sb">
                  {[l.ref, l.group === "recent" && l.at ? `${utcStamp(l.at, now)} UTC` : null, l.overdue && !l.stopped ? t("lane.overdue") : null].filter(Boolean).join("　")}
                </span>
              </button>
            ))}
          </div>
        );
      })}
      {view === "ready" && <p className="note" style={{ margin: "6px 2px 0" }}>{t("live.honest")}</p>}
    </aside>
  );
}
