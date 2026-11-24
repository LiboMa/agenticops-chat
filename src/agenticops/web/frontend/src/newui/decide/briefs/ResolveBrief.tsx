import { useState } from "react";
import { useAnomaly } from "@/hooks/useAnomaly";
import { useFixPlan } from "@/hooks/useFixPlans";
import { useIssueExecutions } from "@/hooks/useIssueExecutions";
import { parseItem } from "@/lib/inbox";
import { useResolveIssue } from "../../hooks/useIssueDecisions";
import { useNfT } from "../../i18n";
import { resolveVm } from "../../lib/briefs/run";
import type { HoldTarget } from "../../lib/hold";
import { Message, StateBlock } from "../../shell/StateBlock";
import { BriefFrame } from "../BriefFrame";
import { Prov } from "../widgets/Cause";
import { HoldButton } from "../widgets/HoldButton";
import { StopLine } from "../widgets/RunSteps";
import { useHold } from "../widgets/useHold";
import { useBriefKeys, useDecision, type BriefProps } from "./briefContext";

/** A run that ended and left the issue open: either every declared check passed and automatic closing is off, or the
 *  run left no verdict at all. A person confirms the problem is gone and marks it resolved.
 *  «Resolved» is final — unlike a dismissal it cannot be reopened — so the key is HELD, as for an approval, and the
 *  hold is bound to what the page shows: this run, and the issue's status, which the request names so the server
 *  refuses it once the issue has moved. Not armed while the runs or the issue are still being read. */
export function ResolveBrief({ item, frame }: BriefProps) {
  const t = useNfT();
  const decide = useDecision(item);
  const issueId = parseItem(item.id)?.id ?? 0;
  const runsQ = useIssueExecutions(issueId);
  const issueQ = useAnomaly(issueId);
  const run = runsQ.data?.[0] ?? null;
  const planQ = useFixPlan(run?.fix_plan_id ?? 0);
  const resolve = useResolveIssue(issueId);
  const [error, setError] = useState<string | null>(null);
  const vm = run ? resolveVm(run, planQ.data ?? null) : null;

  const status = issueQ.data?.status ?? null;
  const target: HoldTarget | null = run && status && !runsQ.isFetching && !issueQ.isFetching && !frame.readOnly && !resolve.isPending
    ? { itemId: item.id, planId: run.id, hash: `${run.id}:${run.status}:${status}` } : null;
  const hold = useHold(target, async (tg) => {
    setError(null);
    setError(await decide(() => resolve.mutateAsync(tg.hash.slice(tg.hash.lastIndexOf(":") + 1)), t("toast.resolved", { ref: item.ref }), undefined,
                          t("pend.resolve")));
  });
  useBriefKeys({
    onKey: (key, _e, repeat) => {
      if (key === "a") { if (!repeat) hold.down("a"); return true; }
      hold.cancel();
      return false;
    },
    onKeyUp: (key) => { if (key === "a") hold.up(); },
  });

  const actions = (
    <>
      <HoldButton label={t("act.resolve")} disabled={!target} holding={hold.holding} hint={hold.hint} onDown={hold.down} onUp={hold.up} onCancel={hold.cancel} />
      <p className="note wide">{t("resolve.final")}</p>
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
              <StopLine stop={vm.stop} />
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
