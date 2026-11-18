import { useEffect, useState } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { useRecentEvents } from "../hooks/useRecentEvents";
import { useNfT } from "../i18n";
import { eventSentence, itemRef } from "../lib/eventText";
import { bandTally, bandTicks, pulseX } from "../lib/pulse";
import { utcHm } from "../lib/time";

/** The top bar's band «the last 24 hours» (N15): one mark per thing that happened — an issue found (red), an agent's
 *  start or end (mint), a person's decision (amber), a change's course (violet) — where its time is; recent hours
 *  get more room, and the hour marks say so. A mark's sentence is the item's own timeline sentence. The band's
 *  name carries the numbers (a tooltip needs a pointer); the map's replay walks the same events by keyboard. */
export function Pulse({ accountId }: { accountId: number | null }) {
  const t = useNfT();
  const { t: classic } = useLocale();
  const q = useRecentEvents(accountId);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(id);
  }, []);
  const events = q.data?.events;
  const n = bandTally(events);
  const failed = q.isError && !q.data;
  const name = failed ? t("pulse.failed") : !q.data ? t("pulse.label")
    : t("pulse.aria", { signal: n.signal, agent: n.agent, decision: n.decision, change: n.change }) + (q.data.cut ? t("pulse.cut") : "");
  return (
    <div className={`pulse${failed ? " off" : ""}`} role="img" aria-label={name} title={failed ? t("pulse.failed") : undefined}>
      <span className="lbl">{t("pulse.label")}</span>
      {[12, 6, 3, 1].map((h) => <span key={h} className="hm" style={{ left: `${pulseX(h)}%` }} aria-hidden="true">{h}h</span>)}
      {bandTicks(events, now).map((tick) => (
        <i key={tick.id} className={`tick ${tick.kind}`} style={{ left: `${tick.left}%` }} aria-hidden="true"
           data-tip={`${utcHm(tick.event.at)} UTC　${itemRef(tick.event.item)}　${eventSentence(tick.event, classic)}`} />
      ))}
      <span className="now" title={t("pulse.now", { t: utcHm(now) })} aria-hidden="true" />
    </div>
  );
}
