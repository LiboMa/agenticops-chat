import { useNfT } from "../../i18n";
import type { EvidenceVm } from "../../lib/briefs/cause";

/** One piece of evidence beside the brief (Space; ← → move; Esc or Space closes). It shows what the diagnosis stored:
 *  the kind, where it came from and the summary — the raw output is not kept, and the panel says so. */
export function Peek({ evidence, index, onClose }: { evidence: EvidenceVm[]; index: number; onClose: () => void }) {
  const t = useNfT();
  const e = evidence[index];
  if (!e) return null;
  return (
    <aside className="peek" aria-label={t("peek.label")}>
      <h3><span className="num" style={{ color: "var(--mint)" }}>{e.label}</span>　{e.type}</h3>
      <div className="src">{t("peek.from", { type: e.type, ref: e.ref })}</div>
      <pre>{e.summary}</pre>
      <p className="note">{t("peek.summaryOnly")}</p>
      <div className="nav">
        <span><kbd>←</kbd> <kbd>→</kbd> {t("peek.next")}　<span className="num">{index + 1} / {evidence.length}</span></span>
        <button type="button" className="btn sm" onClick={onClose}><span className="t">{t("peek.close")}</span><kbd>Esc</kbd></button>
      </div>
    </aside>
  );
}
