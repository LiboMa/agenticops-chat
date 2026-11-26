import { useNfT } from "../../i18n";
import { utcStamp } from "../../lib/time";
import { Prov } from "../widgets/Cause";
import { CauseSection } from "../widgets/CauseSection";
import { AgentAskBrief } from "./AgentAskBrief";
import type { BriefProps } from "./briefContext";
import { VerdictQuote } from "./shared";

/** A diagnosis that stands — a person confirmed it, or it passed the gate while auto-fix is off — and has no plan
 *  yet: nobody asks the SRE agent by itself, so a person does. Also (N26) one whose plan run ended without a plan
 *  and that no agent is on: nothing will write the plan by itself. */
export function GenerateBrief({ item, frame }: BriefProps) {
  const t = useNfT();
  const confirmed = item.reason_detail === "rca_confirmed";
  const stopped = item.reason_detail === "plan_stopped";
  return (
    <AgentAskBrief item={item} frame={frame} spec={{
      main: { ask: "plan", label: t("act.generate") },
      second: { ask: "rca", label: t("act.rediagnose") },
      question: t(stopped ? "ask.generate.stopped" : "ask.generate"),
      stopped: stopped ? { heading: t("sec.stoppedPlan"), text: t("generate.stopped", { t: utcStamp(item.occurred_at, frame.now) }), agent: "sre" } : undefined,
    }}>
      {({ issueId, source }) => (
        <>
          <CauseSection heading={t(confirmed ? "sec.confirmedRca" : stopped ? "sec.standingRca" : "sec.readyRca")} source={source}>
            {!confirmed && !stopped && <p className="note"><Prov code />{t("generate.ready")}</p>}
          </CauseSection>
          {confirmed && (
            <div className="sec">
              <h2>{t("sec.humanVerdict")}</h2>
              <VerdictQuote issueId={issueId} rcaId={source.rca?.id ?? null} />
            </div>
          )}
        </>
      )}
    </AgentAskBrief>
  );
}
