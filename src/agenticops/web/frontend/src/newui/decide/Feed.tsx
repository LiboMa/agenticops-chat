import { useNavigate } from "react-router-dom";
import { useAccountScope } from "@/components/layout/AccountScope";
import { useActivity } from "../hooks/useActivity";
import { useNfT, type NfT } from "../i18n";
import { railRows, type ActivityLane } from "../lib/activity";
import { waitedParts } from "../lib/queue";

/** "诊断 · 已经 3 分钟": what a lane is doing and for how long — or that nothing on record says since when. */
export function laneLabel(lane: Pick<ActivityLane, "kind" | "since">, now: number, t: NfT): string {
  const w = waitedParts(lane.since, now);
  const span = !w ? t("lane.sinceUnknown") : t("lane.for", { t: w.unit === "now" ? t("unit.min", { n: 0 }) : t(`unit.${w.unit}`, { n: w.n }) });
  return `${t(`lane.${lane.kind}`)} · ${span}`;
}

/** The rail beside the brief: what agents are doing now, and the last few things that ended — so a decision does
 *  not just vanish from the queue. Every card opens that work in «现场». */
export function Feed({ now }: { now: number }) {
  const t = useNfT();
  const navigate = useNavigate();
  const { accountId } = useAccountScope();
  const q = useActivity(accountId);
  const rows = railRows(q.data);
  const open = (id: string) => navigate(`/app/new/live/${encodeURIComponent(id)}`);
  return (
    <aside className="side-live">
      <div className="rail-title"><span>{t("feed.title")}</span></div>
      <div className="feed">
        {q.isError && !q.data ? <p className="q-note">{t("feed.failed")}</p>
          : q.isPending ? <div className="skel" style={{ height: 56, borderRadius: 10 }} />
          : rows.running.length === 0 ? <p className="q-note">{t("feed.none")}</p>
          : rows.running.map((l) => (
            <button key={l.id} type="button" className={`f run${l.overdue ? " late" : ""}`} onClick={() => open(l.id)}>
              <span className="h"><span><span className="dot" />{laneLabel(l, now, t)}</span><span className="num">{l.ref ?? ""}</span></span>
              <span className="b">{l.title}</span>
              {l.overdue && <span className="b late-note">{t("lane.overdue")}</span>}
            </button>
          ))}
        {rows.recent.length > 0 && <div className="lgroup"><span>{t("feed.recent")}</span></div>}
        {rows.recent.map((l) => (
          <button key={l.id} type="button" className="f" onClick={() => open(l.id)}>
            <span className="h"><span>{t(`lane.${l.kind}`)} · {t(`outcome.${l.outcome}`)}</span><span className="num">{l.ref ?? ""}</span></span>
            <span className="b">{l.title}</span>
          </button>
        ))}
      </div>
    </aside>
  );
}
