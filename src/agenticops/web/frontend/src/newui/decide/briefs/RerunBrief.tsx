import { useNfT } from "../../i18n";
import { utcStamp } from "../../lib/time";
import { Prov } from "../widgets/Cause";
import { CauseSection } from "../widgets/CauseSection";
import { AgentAskBrief } from "./AgentAskBrief";
import type { BriefProps } from "./briefContext";
import { VerdictQuote } from "./shared";

/** A diagnosis a person judged wrong, an issue with no diagnosis at all, one whose diagnosis ended without a result
 *  (N11: it failed or timed out, and no agent is on it), or an issue a person reopened that nothing has diagnosed
 *  since (N26): ask the agent to diagnose it (again). */
export function RerunBrief({ item, frame }: BriefProps) {
  const t = useNfT();
  const missing = item.reason_detail === "rca_missing";
  const stopped = item.reason_detail === "rca_stopped";
  const reopened = item.reason_detail === "reopened";
  return (
    <AgentAskBrief item={item} frame={frame} spec={{
      main: { ask: "rca", label: t("act.rediagnose") },
      question: t(stopped ? "ask.rerun.stopped" : reopened ? "ask.rerun.reopened" : missing ? "ask.rerun.missing" : "ask.rerun"),
      stopped: stopped ? { heading: t("sec.stoppedRca"), text: t("rerun.stopped", { t: utcStamp(item.occurred_at, frame.now) }), agent: "rca" } : undefined,
    }}>
      {({ issueId, source }) => (
        <>
          {reopened && (
            <div className="sec">
              <h2>{t("sec.reopened")}</h2>
              <p><Prov code />{t("rerun.reopened", { t: utcStamp(item.occurred_at, frame.now) })}</p>
            </div>
          )}
          {!missing && !stopped && !reopened && (
            <div className="sec">
              <h2>{t("sec.humanVerdict")}</h2>
              <VerdictQuote issueId={issueId} rcaId={source.rca?.id ?? null} />
              <p className="note">{t("rerun.note")}</p>
            </div>
          )}
          {!stopped && <CauseSection heading={t(reopened ? "sec.earlierRca" : "sec.rejectedRca")} source={source} />}
        </>
      )}
    </AgentAskBrief>
  );
}
