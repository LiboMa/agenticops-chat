import { useState } from "react";
import { useNfT } from "../../i18n";
import { BriefFrame } from "../BriefFrame";
import { AgentAtWork } from "../widgets/AgentAtWork";
import { Prov } from "../widgets/Cause";
import { CauseSection, useCause } from "../widgets/CauseSection";
import { useBriefKeys, useDecide, type BriefProps } from "./briefContext";
import { DismissForm, useAgentAsk, VerdictQuote } from "./shared";

/** A diagnosis that stands — a person confirmed it, or it passed the gate while auto-fix is off — and has no plan
 *  yet: nobody asks the SRE agent by itself, so a person does. */
export function GenerateBrief({ item, frame }: BriefProps) {
  const t = useNfT();
  const { openPeek } = useDecide();
  const agent = useAgentAsk(item);
  const source = useCause(agent.issueId);
  const [closing, setClosing] = useState(false);
  const confirmed = item.reason_detail === "rca_confirmed";

  useBriefKeys({
    onKey: (key, _e, repeat) => {
      if (closing) return false;
      if (key === " " && source.cause?.evidence.length) { openPeek(source.cause.evidence, 0); return true; }
      if (frame.readOnly) return false;
      if (key === "a") { if (!repeat) void agent.ask("plan"); return true; }
      if (key === "m") { if (!repeat) void agent.ask("rca"); return true; }
      if (key === "d") { agent.setError(null); setClosing(true); return true; }
      return false;
    },
    onEscape: () => { if (!closing) return false; setClosing(false); return true; },
  });

  const actions = closing ? <DismissForm item={item} onCancel={() => setClosing(false)} /> : (
    <>
      <button type="button" className="btn primary" disabled={agent.busy} onClick={() => void agent.ask("plan")}><span className="t">{t("act.generate")}</span><kbd>A</kbd></button>
      <button type="button" className="btn" disabled={agent.busy} onClick={() => void agent.ask("rca")}><span className="t">{t("act.rediagnose")}</span><kbd>M</kbd></button>
      <span className="spacer" />
      <button type="button" className="btn quiet" onClick={() => setClosing(true)}><span className="t">{t("act.close")}</span><kbd>D</kbd></button>
      {agent.error && <p className="note err wide" role="alert">{agent.error}</p>}
    </>
  );
  return (
    <BriefFrame item={item} {...frame} ask={t("ask.generate")} actions={actions}>
      <AgentAtWork lane={agent.lane} now={frame.now} />
      <CauseSection heading={t(confirmed ? "sec.confirmedRca" : "sec.readyRca")} source={source}>
        {!confirmed && <p className="note"><Prov code />{t("generate.ready")}</p>}
      </CauseSection>
      {confirmed && (
        <div className="sec">
          <h2>{t("sec.humanVerdict")}</h2>
          <VerdictQuote issueId={agent.issueId} rcaId={source.rca?.id ?? null} />
        </div>
      )}
    </BriefFrame>
  );
}
