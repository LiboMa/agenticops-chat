import { useMemo } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { useNfT } from "../i18n";
import { eventSentence, itemRef } from "../lib/eventText";
import type { RecentEvent } from "../lib/pulse";
import { utcHm, utcStamp } from "../lib/time";
import { REPLAY_MS, STEP_MS, atOf, valueOf } from "../lib/world/replay";

interface Props {
  /** the moment asked for; null = now */
  asOf: number | null;
  /** the moment's reading is still on its way: the map shows the one before */
  busy: boolean;
  failed: boolean;
  events: RecentEvent[] | undefined;
  /** the server left the oldest events of the day out */
  cut: boolean;
  /** how many moments there are to go to */
  moments: number;
  playing: boolean;
  now: number;
  onAt: (at: number | null) => void;
  onJump: (dir: -1 | 1) => void;
  onPlay: () => void;
  onNow: () => void;
}

/** «Back in time» (N15): the map as of a moment of the last 24 hours. A slider in five-minute steps, the day's events
 *  as marks above it, `[` `]` to the event before / after, `P` to play the day, `0` back to now. In the past the bar
 *  says what is of that moment and what is of today — the map must not be read as that moment's topology. */
export function Replay({ asOf, busy, failed, events, cut, moments, playing, now, onAt, onJump, onPlay, onNow }: Props) {
  const t = useNfT();
  const { t: classic } = useLocale();
  // what happened at the moment on the bar (its minute): said in the items' own timeline sentences
  const here = useMemo(() => {
    if (asOf === null) return [];
    const minute = Math.floor(asOf / 60_000);
    return (events ?? []).filter((e) => Math.floor(Date.parse(e.at) / 60_000) === minute);
  }, [events, asOf]);
  const when = asOf === null ? t("replay.now") : `${utcStamp(asOf, now)} UTC`;
  return (
    <div className={`scrub card${asOf !== null ? " past" : ""}`} role="group" aria-label={t("replay.label")}>
      <div className="row">
        <span>{t("replay.label")}</span>
        <b aria-live="polite">{when}</b>
        {busy && <span className="wait" role="status">{t("replay.loading")}</span>}
        <span className="spacer" />
        <button type="button" className="chip-btn" onClick={() => onJump(-1)} disabled={!moments}>{t("replay.prev")}<kbd>[</kbd></button>
        <button type="button" className="chip-btn" onClick={() => onJump(1)} disabled={asOf === null}>{t("replay.next")}<kbd>]</kbd></button>
        <button type="button" className="chip-btn" onClick={onPlay} aria-pressed={playing} disabled={!moments}>{t(playing ? "replay.stop" : "replay.play")}<kbd>P</kbd></button>
        <button type="button" className="chip-btn" onClick={onNow} disabled={asOf === null}>{t("replay.toNow")}<kbd>0</kbd></button>
      </div>
      <div className="ticks" aria-hidden="true">
        {(events ?? []).map((e) => {
          const at = Date.parse(e.at);
          return Number.isFinite(at) && at >= now - REPLAY_MS && at <= now
            ? <i key={e.id} className={e.kind} style={{ left: `${((at - (now - REPLAY_MS)) / REPLAY_MS) * 100}%` }} /> : null;
        })}
      </div>
      <input type="range" min={0} max={REPLAY_MS / STEP_MS} step={1} value={valueOf(asOf, now)} aria-label={t("replay.slider")} aria-valuetext={when}
             onChange={(e) => onAt(atOf(Number(e.target.value), now))} />
      {here.length > 0 && (
        <ul className="built here">
          {here.slice(0, 3).map((e) => <li key={e.id}>{utcHm(e.at)}{"　"}{itemRef(e.item)}{"　"}{eventSentence(e, classic)}</li>)}
          {here.length > 3 && <li>{t("replay.more", { n: here.length - 3 })}</li>}
        </ul>
      )}
      {failed && <p className="built err" role="alert">{t("replay.failed")}</p>}
      {asOf !== null && <p className="built">{t("replay.note")}</p>}
      {cut && <p className="built">{t("replay.cut")}</p>}
    </div>
  );
}
