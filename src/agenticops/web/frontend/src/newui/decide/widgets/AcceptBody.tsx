import { useEffect, useState } from "react";
import type { FixExecution, FixPlan } from "@/api/types";
import { useLocale } from "@/i18n/LocaleContext";
import { acceptReason, canAccept, checklistItems, confirmedIds } from "@/lib/acceptChecklist";
import { runSummary } from "@/lib/runSummary";
import { useNfT } from "../../i18n";
import { acceptVm } from "../../lib/briefs/accept";
import { Prov } from "./Cause";
import { RecordedSteps } from "../../live/LiveSteps";
import { StopLine } from "./RunSteps";

/** The acceptance checklist of one run: a box per declared check still to verify (no result, or a warning), then
 *  one overall confirmation — the classic page's rules (lib/acceptChecklist). The ticks start empty for every run. */
export function useAcceptChecklist(run: FixExecution | null, runPlan: FixPlan | null) {
  const { t: classic } = useLocale();            // the checklist's sentences and the default reason are the classic page's
  const [ticked, setTicked] = useState<ReadonlySet<number>>(new Set());
  useEffect(() => { setTicked(new Set()); }, [run?.id]);
  const items = run ? checklistItems(runSummary(run, runPlan), classic) : [];
  const toggle = (k: number) => setTicked((old) => { const next = new Set(old); if (next.has(k)) next.delete(k); else next.add(k); return next; });
  return {
    vm: run ? acceptVm(run, runPlan) : null,
    ticked, toggle,
    tickNext: () => { const k = items.findIndex((_, i) => !ticked.has(i)); if (k >= 0) toggle(k); },
    ready: !!run && canAccept(items, ticked),
    confirmed: () => confirmedIds(items, ticked),
    reason: () => acceptReason("", items, classic),
    overallIndex: items.length - 1,
  };
}

/** What ran, what the code verified, and what a person must look at — with the tick boxes (none for a read-only
 *  account). `why` = the server's sentence on why this run needs a person. */
export function AcceptBody({ list, readOnly, why, item, now }: {
  list: ReturnType<typeof useAcceptChecklist>; readOnly: boolean; why?: string | null;
  /** the work item ("I12" / "C3"): the run's recorded steps are read under it */
  item: string; now: number;
}) {
  const t = useNfT();
  const vm = list.vm;
  if (!vm) return null;
  const reason = why ?? vm.reason;
  const box = (k: number, label: string) => readOnly ? null : (
    <button type="button" className="tickbox" role="checkbox" aria-checked={list.ticked.has(k)} aria-label={label} onClick={() => list.toggle(k)}>
      {list.ticked.has(k) ? "✓" : ""}
    </button>
  );
  return (
    <>
      <div className="sec">
        <h2>{t("sec.ran")}</h2>
        <p><Prov code />{t("ran.line", { run: vm.runId, done: vm.stepsDone, total: vm.stepsTotal, duration: vm.duration })}</p>
        <p className="note"><Prov code />{
          vm.planVersion === null ? t("ran.bind.noPlan")
            : t(vm.matchesApproved === true ? "ran.bind.match" : vm.matchesApproved === false ? "ran.bind.drift" : "ran.bind.unknown",
                { v: vm.planVersion, hash: vm.hash8 ?? "—" })
        }</p>
        {reason && <p className="note"><Prov code />{t("ran.why", { reason })}</p>}
        <StopLine stop={vm.stop} />
        <RecordedSteps item={item} executionId={vm.runId} now={now} />
      </div>
      {vm.failed.length > 0 && (
        <div className="sec">
          <h2>{t("sec.failedChecks")}</h2>
          <ul className="checks">{vm.failed.map((c) => <li key={c.id ?? c.label}><span className="pc">{c.id}</span><span>{c.label}</span><span className="st bad">{t("st.failed")}</span></li>)}</ul>
        </div>
      )}
      {vm.passed.length > 0 && (
        <div className="sec">
          <h2>{t("sec.auto")}</h2>
          <ul className="checks">{vm.passed.map((c) => <li key={c.id ?? c.label}><span className="pc">{c.id}</span><span>{c.label}</span><span className="st ok">{t("st.passed")}</span></li>)}</ul>
        </div>
      )}
      <div className="sec">
        <h2>{t("sec.need")}</h2>
        <ul className="checks">
          {vm.toVerify.map((c, k) => (
            <li key={c.id ?? c.label}>{box(k, `${t("accept.tick")} ${c.id ?? c.label}`)}<span className="pc">{c.id}</span><span>{c.label}</span><span className="st need">{t(`state.${c.state}`)}</span></li>
          ))}
          {!readOnly && <li>{box(list.overallIndex, t("accept.overall"))}<span className="pc" /><span>{t("accept.overall")}</span></li>}
        </ul>
        {!readOnly && <p className="note">{t("accept.note")}</p>}
      </div>
    </>
  );
}
