import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useAccountScope } from "@/components/layout/AccountScope";
import { parseItem } from "@/lib/inbox";
import { DecideContext, type DecideApi } from "../decide/briefs/briefContext";
import { usePeek } from "../decide/widgets/usePeek";
import { useActivity } from "../hooks/useActivity";
import { useMyItem } from "../hooks/useMyItem";
import { useNfT } from "../i18n";
import { lanePath, laneViews, pickLane, recentCut, staleSince } from "../lib/live";
import { step } from "../lib/queue";
import { storyPath } from "../lib/story";
import { Message, StateBlock } from "../shell/StateBlock";
import { useLensKeys, useShell } from "../shell/shellContext";
import { Lanes } from "./Lanes";
import { Stream } from "./Stream";

/** «现场»: what agents are doing now, what is due next and what ended in the last day — one lane each, and the lane
 *  you opened. Everything is the server's own record (GET /api/ui/activity), refreshed every ten seconds; the agents'
 *  steps are not streamed, and the page says so. The lane lives in the address (`/app/new/live/I12%3Adiagnosis`). */
export function LiveLens() {
  const t = useNfT();
  const navigate = useNavigate();
  const location = useLocation();
  const { notify, setRootFlag } = useShell();
  const { lane: laneParam = null } = useParams();
  const { accountId } = useAccountScope();
  const q = useActivity(accountId);
  const lanes = useMemo(() => laneViews(q.data), [q.data]);
  // when the lane on the page began, as seen while it was listed as running: once it ends, only a result made since
  // then is «what it left behind» (a failed run left nothing, and an older result is not its result)
  const watched = useRef<{ id: string; since: string | null } | null>(null);
  const pick = pickLane(lanes, laneParam, watched.current?.id === laneParam ? watched.current.since : undefined);
  const lane = pick.lane;
  if (pick.state === "found" && lane && (lane.group === "running" || lane.group === "stalled")) watched.current = { id: lane.id, since: lane.at };
  const view = q.data ? "ready" : q.isError ? "failed" : "loading";
  const staleAt = staleSince({ isError: q.isError, hasData: !!q.data, dataUpdatedAt: q.dataUpdatedAt });
  const mine = useMyItem(lane?.item ?? null).data ?? null;
  const peek = usePeek(lane?.id ?? null);

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  // a phone shows the list or the lane, never both: the lane once the address names one
  useEffect(() => { setRootFlag("lane-open", !!laneParam); return () => setRootFlag("lane-open", false); }, [laneParam, setRootFlag]);

  // the lane the address named has ended: the address follows it to what it left behind
  const movedTo = pick.state === "moved" && lane ? lane.id : null;
  useEffect(() => {
    if (movedTo) navigate(lanePath(movedTo), { replace: true, state: { moved: true } });
  }, [movedTo, navigate]);
  const moved = pick.state === "moved" || (location.state as { moved?: boolean } | null)?.moved === true;

  const open = useCallback((id: string) => navigate(lanePath(id), { replace: !!laneParam }), [navigate, laneParam]);
  const move = (delta: number) => {
    if (!lanes.length) return;
    const at = lane ? lanes.findIndex((l) => l.id === lane.id) : -1;
    open(lanes[at < 0 ? 0 : step(lanes.length, at, delta)].id);
  };
  const here = location.pathname + location.search;
  const toStory = (item: string) => navigate(storyPath(item), { state: { from: "live", back: here } });
  const toDecide = (item: string) => navigate(`/app/new/decide/${item}`);

  const api = useMemo<DecideApi>(() => ({ setBriefKeys: () => {}, done: (_item, message) => notify(message),
                                          failed: (item, message) => notify(`${item.ref}　${message}`), openPeek: peek.show }), [notify, peek.show]);

  useLensKeys({
    onKey: (key, _e, repeat) => {
      if (peek.onKey(key)) return true;
      if (key === "j" || key === "arrowdown") { move(1); return true; }
      if (key === "k" || key === "arrowup") { move(-1); return true; }
      if (key === "enter" && lane?.item) { if (!repeat) toStory(lane.item); return true; }
      return false;
    },
    onEscape: () => {
      if (peek.open) { peek.close(); return true; }
      if (!laneParam) return false;
      navigate(lanePath(null));                         // on a phone: back to the list
      return true;
    },
  });

  const off = pick.state === "gone" || pick.state === "ended";
  const goneItem = off ? parseItem((laneParam ?? "").split(":")[0]) : null;
  return (
    <DecideContext.Provider value={api}>
      <section className={`view${staleAt !== null ? " stale" : ""}`} id="live">
        <Lanes lanes={lanes} currentId={lane?.id ?? null} view={view} staleAt={staleAt} now={now} cut={recentCut(q.data)}
               onPick={open} onRetry={() => void q.refetch()} />
        <article key={lane?.id ?? pick.state} className="stream card" aria-live="polite" aria-label={t("live.lane")}>
          {view === "loading" ? <StateBlock kind="loading" />
            : view === "failed" ? <StateBlock kind="failed" failKey="live.failed.p" onRetry={() => void q.refetch()} />
            : off ? (
              <Message big={t(pick.state === "ended" ? "live.ended.big" : "live.gone.big")}>
                <p>{t(pick.state === "ended" ? "live.ended.p" : "live.gone.p")}</p>
                <p className="row">
                  {goneItem && <button type="button" className="btn primary" onClick={() => toStory((laneParam ?? "").split(":")[0])}><span className="t">{t("gone.story")}</span></button>}
                  <button type="button" className="btn" onClick={() => navigate(lanePath(null), { replace: true })}><span className="t">{t("live.gone.list")}</span></button>
                </p>
              </Message>
            )
            : !lane ? <Message big={t("live.empty.big")}><p>{t("live.empty.p")}</p></Message>
            : <Stream lane={lane} moved={moved} mine={mine} now={now} onBack={() => navigate(lanePath(null))}
                      onStory={() => { if (lane.item) toStory(lane.item); }} onDecide={() => { if (lane.item) toDecide(lane.item); }} />}
        </article>
      </section>
      {peek.node}
    </DecideContext.Provider>
  );
}
