import { useState } from "react";
import { useFixPlan } from "@/hooks/useFixPlans";
import { useIssueExecutions } from "@/hooks/useIssueExecutions";
import { parseItem } from "@/lib/inbox";
import { useResolveIssue } from "../../hooks/useIssueDecisions";
import { useNfT } from "../../i18n";
import { resolveVm } from "../../lib/briefs/run";
import { Message, StateBlock } from "../../shell/StateBlock";
import { BriefFrame } from "../BriefFrame";
import { Prov } from "../widgets/Cause";
import { errorText, useBriefKeys, useDecide, type BriefProps } from "./briefContext";

/** A run that ended and left the issue open: either every declared check passed and automatic closing is off, or the
 *  run left no verdict at all. A person confirms the problem is gone and marks it resolved. */
export function ResolveBrief({ item, frame }: BriefProps) {
  const t = useNfT();
  const { done } = useDecide();
  const issueId = parseItem(item.id)?.id ?? 0;
  const runsQ = useIssueExecutions(issueId);
  const run = runsQ.data?.[0] ?? null;
  const planQ = useFixPlan(run?.fix_plan_id ?? 0);
  const resolve = useResolveIssue(issueId);
  const [error, setError] = useState<string | null>(null);
  const vm = run ? resolveVm(run, planQ.data ?? null) : null;

  const mark = async () => {
    if (resolve.isPending || frame.readOnly || !run) return;
    setError(null);
    try { await resolve.mutateAsync(); done(t("toast.resolved", { ref: item.ref })); }
    catch (e) { setError(t("err.failed", { msg: errorText(e) })); }
  };
  useBriefKeys({ onKey: (key, _e, repeat) => { if (key !== "a") return false; if (!repeat) void mark(); return true; } });

  const actions = (
    <>
      <button type="button" className="btn primary" disabled={!run || resolve.isPending} onClick={() => void mark()}><span className="t">{t("act.resolve")}</span><kbd>A</kbd></button>
      {error && <p className="note err wide" role="alert">{error}</p>}
    </>
  );
  return (
    <BriefFrame item={item} {...frame} ask={t(vm?.variant === "unverified" ? "ask.resolve.unverified" : "ask.resolve.passed")} actions={actions}>
      {runsQ.isPending ? <StateBlock kind="loading" />
        : runsQ.isError ? <StateBlock kind="failed" failKey="sec.failedLoad" onRetry={() => void runsQ.refetch()} />
        : !vm ? <Message big={t("resolve.none")} />
        : (
          <>
            <div className="sec">
              <h2>{t("sec.ran")}</h2>
              <p><Prov code />{t("ran.line", { run: vm.runId, done: vm.done, total: vm.total, duration: vm.duration })}</p>
              <p className="note"><Prov code />{
                vm.version === null ? t("ran.bind.noPlan")
                  : t(vm.matchesApproved === true ? "ran.bind.match" : vm.matchesApproved === false ? "ran.bind.drift" : "ran.bind.unknown", { v: vm.version, hash: vm.hash8 ?? "—" })
              }</p>
              {vm.variant === "unverified" && <p className="note"><Prov code />{t("resolve.unverified")}</p>}
            </div>
            {vm.variant === "passed" && (
              <div className="sec">
                <h2>{t("sec.auto")}</h2>
                <ul className="checks">{vm.passed.map((c) => <li key={c.id ?? c.label}><span className="pc">{c.id}</span><span>{c.label}</span><span className="st ok">{t("st.passed")}</span></li>)}</ul>
                <p className="note"><Prov code />{t("resolve.autoOff")}</p>
              </div>
            )}
          </>
        )}
    </BriefFrame>
  );
}
