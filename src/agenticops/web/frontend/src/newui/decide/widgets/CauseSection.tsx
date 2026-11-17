import type { ReactNode } from "react";
import { useSettings } from "@/hooks/useSettings";
import { useFreshRca } from "../../hooks/useItemData";
import { useNfT } from "../../i18n";
import { causeVm } from "../../lib/briefs/cause";
import { Cause } from "./Cause";

/** An issue's newest diagnosis — read again each time a brief opens — and the settings that say how far it got by
 *  itself. */
export function useCause(issueId: number) {
  const rcaQ = useFreshRca(issueId);
  const settings = useSettings();
  const gate = settings.data?.rca_min_confidence_for_autofix;
  return { rcaQ, rca: rcaQ.data ?? null, gate, cause: causeVm(rcaQ.data, gate), autoFix: settings.data?.auto_fix_enabled };
}

/** The diagnosis as one section of a brief, with its loading / failed / none states. */
export function CauseSection({ heading, source, gateNote, children }: {
  heading: string; source: ReturnType<typeof useCause>; gateNote?: string | null; children?: ReactNode;
}) {
  const t = useNfT();
  const { rcaQ, cause } = source;
  return (
    <div className="sec">
      <h2>{heading}</h2>
      {rcaQ.isPending ? <div className="skel" style={{ height: 54 }} />
        : rcaQ.isError ? <p className="note err">{t("sec.failedLoad")}</p>
        : cause ? <Cause cause={cause} gateNote={gateNote} /> : <p className="note">{t("cause.none")}</p>}
      {children}
    </div>
  );
}
