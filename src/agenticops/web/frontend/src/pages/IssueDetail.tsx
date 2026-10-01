import { useEffect, useRef, useState, type ReactNode } from "react";
import { useParams, useSearchParams, Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useAnomaly } from "@/hooks/useAnomaly";
import { useAnomalyRca } from "@/hooks/useAnomalyRca";
import { useRcaFeedback } from "@/hooks/useSignals";
import {
  useFixPlans,
  useApproveFixPlan,
  useRejectFixPlan,
  useExecuteFixPlan,
} from "@/hooks/useFixPlans";
import { useUpdateIssueStatus } from "@/hooks/useIssueActions";
import { useIssueExecutions } from "@/hooks/useIssueExecutions";
import { useIssueTimeline } from "@/hooks/useIssueTimeline";
import { useAcceptExecution, useCancelExecution } from "@/hooks/useFixExecutions";
import { useLocale } from "@/i18n/LocaleContext";
import { useAuth } from "@/hooks/useAuth";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { ReasonDialog } from "@/components/plans/ReasonDialog";
import { Card, CardBody } from "@/components/ui/Card";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { IssueStatusBadge } from "@/components/ui/IssueStatusBadge";
import { IssueStatusStepper } from "@/components/ui/IssueStatusStepper";
import { IssueActionBar } from "@/components/ui/IssueActionBar";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { FixPlanStatusBadge } from "@/components/ui/FixPlanStatusBadge";
import { PipelineStepper } from "@/components/ui/PipelineStepper";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { PipelineTimeline } from "@/components/plans/PipelineTimeline";
import { RunbookStep } from "@/components/plans/RunbookStep";
import { CheckItem } from "@/components/plans/CheckItem";
import { RollbackPlan } from "@/components/plans/RollbackPlan";
import { ExecutionsTable } from "@/components/plans/ExecutionsTable";
import { ExecutionEvidence } from "@/components/plans/ExecutionEvidence";
import { VerificationChip } from "@/components/plans/VerificationChip";
import { LocalGraph } from "@/components/graph/LocalGraph";
import { formatFullDate, formatShortDate } from "@/lib/formatDate";
import { renderMarkdown } from "@/lib/renderMarkdown";
import { planLabel, shortHash } from "@/lib/plans";
import {
  anchorBadge, approvalBlockedReason, canApprovePlan, issueFacts, issueStatuses, latestExecution, newestFirst, parseIssueTab,
  ISSUE_TABS, type IssueTab,
} from "@/lib/issueDetail";
import { apiFetch } from "@/api/client";
import type {
  FixExecution, HealthIssue, IssueStatus, LocationVerdict, MergedAlert, FixPlan,
} from "@/api/types";

/* ================================================================== */
/*  Main component                                                     */
/* ================================================================== */

export default function IssueDetail() {
  const { id } = useParams<{ id: string }>();
  const issueId = Number(id);
  const { t } = useLocale();

  /* -- Data hooks -------------------------------------------------- */
  const anomaly = useAnomaly(issueId);
  const rca = useAnomalyRca(issueId);
  const fixPlans = useFixPlans({ health_issue_id: issueId });
  const executions = useIssueExecutions(issueId);
  const timeline = useIssueTimeline(issueId);
  const updateStatusMut = useUpdateIssueStatus();
  const cancelExecMut = useCancelExecution();
  const approveMut = useApproveFixPlan();
  const rejectMut = useRejectFixPlan();
  const executeMut = useExecuteFixPlan();

  // The issue poll can land on fix_executed after the runs poll has stopped; the banner needs the verdict the
  // backend wrote to the run in the same transaction, so a status move refetches the runs.
  const qc = useQueryClient();
  const issueStatus = anomaly.data?.status;
  const lastStatus = useRef(issueStatus);
  useEffect(() => {
    if (lastStatus.current !== undefined && lastStatus.current !== issueStatus) {
      qc.invalidateQueries({ queryKey: ["issue-executions", issueId] });
    }
    lastStatus.current = issueStatus;
  }, [issueStatus, issueId, qc]);

  /* -- Local state ------------------------------------------------- */
  // The tab lives in the URL (?tab=), so a link can open the Verification tab directly
  const [params, setParams] = useSearchParams();
  const tab = parseIssueTab(params.get("tab"));
  const setTab = (next: IssueTab) =>
    setParams((prev) => {
      const q = new URLSearchParams(prev);
      q.set("tab", next);
      return q;
    }, { replace: true });
  const [rcaLoading, setRcaLoading] = useState(false);
  const [fixPlanLoading, setFixPlanLoading] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  /* -- Handlers ---------------------------------------------------- */
  const triggerRca = async () => {
    setRcaLoading(true);
    setActionMsg(null);
    try {
      await apiFetch<unknown>(`/issues/${issueId}/rca`, { method: "POST" });
      setActionMsg(t("issues.rcaTriggered"));
      setTimeout(() => rca.refetch(), 10000);
    } catch (e: any) {
      setActionMsg(`${t("issues.rcaFailed")}: ${e.message}`);
    } finally {
      setRcaLoading(false);
    }
  };

  const triggerFixPlan = async () => {
    setFixPlanLoading(true);
    setActionMsg(null);
    try {
      await apiFetch<unknown>(`/issues/${issueId}/generate-fix-plan`, { method: "POST" });
      setActionMsg(t("issues.fixPlanTriggered"));
      setTimeout(() => fixPlans.refetch(), 10000);
    } catch (e: any) {
      setActionMsg(`${t("issues.fixPlanFailed")}: ${e.message}`);
    } finally {
      setFixPlanLoading(false);
    }
  };

  const updateStatus = (status: IssueStatus) => {
    setActionMsg(null);
    updateStatusMut.mutate(
      { id: issueId, status },
      {
        onSuccess: () => {
          anomaly.refetch();
          executions.refetch();
          timeline.refetch();
        },
        onError: (err) => setActionMsg(`Status update failed: ${err.message}`),
      },
    );
  };

  /* -- Loading / error states -------------------------------------- */
  if (anomaly.isLoading) return <Spinner label={t("common.loading")} />;
  if (anomaly.error)
    return (
      <ErrorBanner
        message={anomaly.error.message}
        onRetry={() => anomaly.refetch()}
      />
    );

  const a = anomaly.data!;
  const latestPlan = fixPlans.data?.length ? fixPlans.data[0] : null;
  const statuses = issueStatuses(a, executions.data);
  const badge = anchorBadge(a);

  /* -- Render ------------------------------------------------------ */
  return (
    <div className="space-y-6">
      {/* Back link */}
      <Link
        to="/app/issues"
        className="inline-flex items-center text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <svg className="h-4 w-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
        {t("common.back")}
      </Link>

      {/* Pipeline stepper (full-width, large) */}
      <Card>
        <CardBody>
          <IssueStatusStepper status={a.status} />
        </CardBody>
      </Card>

      {/* Action message banner */}
      {actionMsg && (
        <div className="p-3 rounded-lg bg-primary/10 border border-primary/20 text-sm text-primary">
          {actionMsg}
        </div>
      )}

      {/* Issue header */}
      <Card>
        <CardBody>
          <div className="flex items-center gap-3 mb-4 flex-wrap">
            <span className="font-mono text-sm bg-secondary text-muted-foreground px-2 py-0.5 rounded">
              I#{a.id}
            </span>
            <SeverityBadge severity={a.severity} />
            {/* three statuses: the issue's own, and its newest run's execution and verification */}
            <StatusLabel label={t("issues.statusBusiness")}>
              <IssueStatusBadge status={statuses.business} />
            </StatusLabel>
            <StatusLabel label={t("issues.statusExecution")}>
              <span className="text-xs font-medium text-foreground">{statuses.execution ?? "—"}</span>
            </StatusLabel>
            <StatusLabel label={t("issues.statusVerification")}>
              <VerificationChip status={statuses.verification} />
            </StatusLabel>
            {badge && (
              badge.kind === "resource" ? (
                <Link to={`/app/resources/${badge.ref}`} title={t("anchor.anchored")}
                      className="font-mono text-xs px-2 py-0.5 rounded border border-primary/30 text-primary hover:bg-primary/10">
                  {badge.label}
                </Link>
              ) : (
                <span className="text-xs px-2 py-0.5 rounded bg-amber-500/10 text-amber-600 dark:text-amber-400">
                  {t(`anchor.${badge.kind}`)}
                  {badge.kind === "ambiguous" && ` (${t("anchor.candidatesN").replace("{n}", String(badge.candidates))})`}
                </span>
              )
            )}
            {a.trace_id && (
              <button
                onClick={() => navigator.clipboard.writeText(a.trace_id!)}
                title="Click to copy trace ID"
                className="font-mono text-xs bg-secondary text-muted-foreground px-2 py-0.5 rounded border border-border hover:bg-accent transition-colors cursor-pointer"
              >
                {a.trace_id}
              </button>
            )}
          </div>
          <h1 className="text-2xl font-semibold text-foreground mb-2">{a.title}</h1>
          {a.resolved_at && (
            <div className="text-xs text-green-500 mb-2">
              Resolved {formatFullDate(a.resolved_at)}
            </div>
          )}
          <PipelineStepper status={a.status} className="w-40 mb-4" />
        </CardBody>
      </Card>

      {/* The pending item: a run that finished without a verdict waits for a human */}
      {statuses.pending && (
        <div className="flex flex-wrap items-center gap-3 p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-sm">
          <span className="flex-1 min-w-0 text-amber-700 dark:text-amber-300">
            <strong>{t("verification.pendingBanner")}</strong>
            {statuses.pending.verification_reason && `: ${statuses.pending.verification_reason}`}
          </span>
          {/* the Verification tab carries its own copy */}
          {tab !== "verification" && <AcceptanceActions execution={statuses.pending} />}
        </div>
      )}

      {/* Smart Action Bar */}
      <IssueActionBar
        issue={a}
        rca={rca.data}
        fixPlans={fixPlans.data}
        rcaLoading={rcaLoading}
        fixPlanLoading={fixPlanLoading}
        statusUpdating={updateStatusMut.isPending}
        onRunRca={triggerRca}
        onGenerateFixPlan={triggerFixPlan}
        onUpdateStatus={updateStatus}
        onViewFixPlan={() => setTab("fixPlan")}
      />

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-border">
        {ISSUE_TABS.map((key) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === key
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t(`issues.tab.${key}`)}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "investigate" && (
        <IssueTab
          issue={a}
          rca={rca}
          rcaLoading={rcaLoading}
          onRunRca={triggerRca}
          t={t}
        />
      )}
      {tab === "fixPlan" && (
        <FixPlanTab
          fixPlans={fixPlans}
          issueStatus={a.status}
          fixPlanLoading={fixPlanLoading}
          onGenerateFixPlan={triggerFixPlan}
          hasRca={!!rca.data}
          latestPlan={latestPlan}
          approveMut={approveMut}
          rejectMut={rejectMut}
          executeMut={executeMut}
          setActionMsg={setActionMsg}
          t={t}
        />
      )}
      {tab === "execution" && (
        <ExecutionTab executions={executions} cancelExecMut={cancelExecMut} setActionMsg={setActionMsg} t={t} />
      )}
      {tab === "verification" && <VerificationTab executions={executions} pending={statuses.pending} t={t} />}
      {tab === "timeline" && (
        <TimelineTab
          timeline={timeline}
          alerts={a.merged_alerts}
          occurrenceCount={a.occurrence_count}
          t={t}
        />
      )}
    </div>
  );
}

/* ================================================================== */
/*  Issue Tab                                                          */
/* ================================================================== */

function IssueTab({
  issue: a,
  rca,
  rcaLoading,
  onRunRca,
  t,
}: {
  issue: HealthIssue;
  rca: ReturnType<typeof useAnomalyRca>;
  rcaLoading: boolean;
  onRunRca: () => void;
  t: (key: string) => string;
}) {
  const f = issueFacts(a);
  return (
    <div className="space-y-6">
      {/* Description + metadata */}
      <Card>
        <CardBody>
          <div
            className="text-muted-foreground mb-6 report-content"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(a.description) }}
          />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground block">{t("issues.resource")}</span>
              <span className="font-mono text-foreground">{a.resource_id}</span>
            </div>
            <div>
              <span className="text-muted-foreground block">{t("issues.type")}</span>
              <span className="text-foreground">{f.resourceType ?? "—"}</span>
            </div>
            <div>
              <span className="text-muted-foreground block">{t("issues.region")}</span>
              <span className="text-foreground">{f.region ?? "—"}</span>
            </div>
            <div>
              <span className="text-muted-foreground block">{t("issues.detected")}</span>
              <span className="text-foreground">{formatFullDate(a.detected_at)}</span>
            </div>
            {a.account_name && (
              <div>
                <span className="text-muted-foreground block">{t("issues.account")}</span>
                <span className="text-foreground">{a.account_name}</span>
              </div>
            )}
          </div>

          {f.metricName && (
            <div className="mt-6 p-4 bg-secondary rounded-lg border border-border/50">
              <h3 className="font-semibold text-foreground mb-2">{t("issues.metricDetails")}</h3>
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-muted-foreground">{t("issues.metric")}:</span>{" "}
                  <span className="text-foreground">{f.metricName}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">{t("issues.expected")}:</span>{" "}
                  <span className="text-foreground">{String(f.expected ?? "—")}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">{t("issues.actual")}:</span>{" "}
                  <span className="text-foreground">{String(f.actual ?? "—")}</span>
                </div>
              </div>
            </div>
          )}
        </CardBody>
      </Card>

      {/* RCA Section */}
      <RcaSection issueId={a.id} rca={rca} rcaLoading={rcaLoading} onRunRca={onRunRca} t={t} />

      {rca.data && <LocationSection issueId={a.id} rca={rca.data} t={t} />}

      {/* The neighbourhood, with the RCA causal chain highlighted */}
      <Card>
        <CardBody>
          <h2 className="text-lg font-semibold text-foreground mb-3">{t("graph.title")}</h2>
          <LocalGraph subject={{ issueId: a.id }} path={rca.data?.location?.path} />
        </CardBody>
      </Card>
    </div>
  );
}

/* ================================================================== */
/*  RCA Section                                                        */
/* ================================================================== */

function RcaSection({
  issueId,
  rca,
  rcaLoading,
  onRunRca,
  t,
}: {
  issueId: number;
  rca: ReturnType<typeof useAnomalyRca>;
  rcaLoading: boolean;
  onRunRca: () => void;
  t: (key: string) => string;
}) {
  const feedback = useRcaFeedback(issueId);
  if (rca.isLoading) return <Spinner label="Loading RCA..." />;

  if (!rca.data) {
    return (
      <Card>
        <CardBody>
          <div className="text-center py-8">
            <h2 className="text-lg font-semibold text-foreground mb-2">
              {t("issues.noRca")}
            </h2>
            <p className="text-muted-foreground mb-4">
              {t("issues.rcaHint")}
            </p>
            <button
              onClick={onRunRca}
              disabled={rcaLoading}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
            >
              {rcaLoading ? t("issues.analyzing") : t("issues.runRca")}
            </button>
          </div>
        </CardBody>
      </Card>
    );
  }

  const r = rca.data;
  return (
    <Card>
      <CardBody>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-foreground flex items-center gap-2">
            {t("issues.rcaResults")}
            {r.evidence_verified === true && (
              <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300" title={t("issues.rcaEvidenceVerifiedHint")}>
                {t("issues.rcaEvidenceVerified")}
              </span>
            )}
            {r.evidence_verified === false && (
              <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300" title={t("issues.rcaEvidenceUnverifiedHint")}>
                {t("issues.rcaEvidenceUnverified")}
              </span>
            )}
            {r.critic_verdict && (
              <span
                className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                  r.critic_verdict === "supported"
                    ? "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300"
                    : "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300"
                }`}
                title={r.critic_notes ?? ""}
              >
                critic: {r.critic_verdict}
              </span>
            )}
          </h2>
          {/* Human verdict (ground-truth capture) */}
          <div className="flex items-center gap-1">
            {r.human_verdict ? (
              <span className="text-xs text-muted-foreground">
                {t("issues.rcaHumanVerdict")}: {r.human_verdict === "correct" ? "👍" : "👎"}
              </span>
            ) : (
              <>
                <button
                  onClick={() => feedback.mutate({ verdict: "correct" })}
                  disabled={feedback.isPending}
                  title={t("issues.rcaMarkCorrect")}
                  className="px-2 py-1 text-sm rounded-md bg-secondary hover:bg-accent transition-colors disabled:opacity-50"
                >
                  👍
                </button>
                <button
                  onClick={() => feedback.mutate({ verdict: "incorrect" })}
                  disabled={feedback.isPending}
                  title={t("issues.rcaMarkIncorrect")}
                  className="px-2 py-1 text-sm rounded-md bg-secondary hover:bg-accent transition-colors disabled:opacity-50"
                >
                  👎
                </button>
              </>
            )}
          </div>
        </div>

        {/* Confidence bar */}
        <div className="mb-6">
          <div className="flex justify-between text-sm mb-1">
            <span className="text-muted-foreground">{t("issues.confidence")}</span>
            <span className="font-medium text-foreground">
              {Math.round((r.confidence ?? 0) * 100)}%
            </span>
          </div>
          <div className="w-full bg-secondary rounded-full h-2">
            <div
              className="bg-primary h-2 rounded-full transition-all"
              style={{ width: `${(r.confidence ?? 0) * 100}%` }}
            />
          </div>
        </div>

        {/* Root Cause */}
        <div className="mb-6">
          <h3 className="font-semibold text-foreground mb-2">{t("issues.rootCause")}</h3>
          <div
            className="text-foreground report-content"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(r.root_cause) }}
          />
        </div>

        {/* Contributing Factors */}
        {r.contributing_factors.length > 0 && (
          <div className="mb-6">
            <h3 className="font-semibold text-foreground mb-2">{t("issues.contributingFactors")}</h3>
            <ul className="list-disc list-inside text-muted-foreground space-y-1">
              {r.contributing_factors.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Recommendations */}
        {r.recommendations.length > 0 && (
          <div>
            <h3 className="font-semibold text-foreground mb-2">{t("issues.recommendations")}</h3>
            <ol className="list-decimal list-inside text-muted-foreground space-y-1">
              {r.recommendations.map((rec, i) => (
                <li key={i}>{rec}</li>
              ))}
            </ol>
          </div>
        )}

        <div className="mt-4 text-xs text-muted-foreground">
          {t("issues.rcaModel")}: {r.model_id} | {t("issues.rcaAnalyzed")} {formatFullDate(r.created_at)}
        </div>
      </CardBody>
    </Card>
  );
}

/* ================================================================== */
/*  Fix Plan Tab                                                       */
/* ================================================================== */

function FixPlanTab({
  fixPlans,
  issueStatus,
  fixPlanLoading,
  onGenerateFixPlan,
  hasRca,
  latestPlan,
  approveMut,
  rejectMut,
  executeMut,
  setActionMsg,
  t,
}: {
  fixPlans: ReturnType<typeof useFixPlans>;
  issueStatus: IssueStatus;
  fixPlanLoading: boolean;
  onGenerateFixPlan: () => void;
  hasRca: boolean;
  latestPlan: FixPlan | null;
  approveMut: ReturnType<typeof useApproveFixPlan>;
  rejectMut: ReturnType<typeof useRejectFixPlan>;
  executeMut: ReturnType<typeof useExecuteFixPlan>;
  setActionMsg: (v: string | null) => void;
  t: (key: string) => string;
}) {
  const { confirm, dialog } = useConfirm();
  const [approvalDialog, setApprovalDialog] = useState<"approve" | "reject" | null>(null);
  const [claimedName, setClaimedName] = useState("");
  const { isAuthenticated } = useAuth();

  if (fixPlans.isLoading) return <Spinner label="Loading fix plans..." />;

  const plans = fixPlans.data ?? [];

  /* No plans yet */
  if (plans.length === 0) {
    return (
      <Card>
        <CardBody>
          <div className="text-center py-8">
            <h2 className="text-lg font-semibold text-foreground mb-2">
              {t("issues.noFixPlan")}
            </h2>
            <p className="text-muted-foreground mb-4">
              {hasRca ? t("issues.fixPlanHint") : t("issues.fixPlanHintNoRca")}
            </p>
            <button
              onClick={onGenerateFixPlan}
              disabled={fixPlanLoading || !hasRca}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 transition-colors"
            >
              {fixPlanLoading ? t("issues.generating") : t("issues.createFixPlan")}
            </button>
          </div>
        </CardBody>
      </Card>
    );
  }

  /* Show the latest (most relevant) plan inline */
  const fp = latestPlan ?? plans[0];
  const needsApproval = canApprovePlan(fp, issueStatus);
  // a plan of a resolved / dismissed issue can still be rejected, not approved
  const blocked = approvalBlockedReason(fp, issueStatus);
  const canExecute = fp.status === "approved";

  async function handleExecute() {
    if (!(await confirm("Execute this fix plan now?", { confirmText: "Execute" }))) return;
    executeMut.mutate(fp.id, { onError: (err) => setActionMsg(`Execute failed: ${err.message}`) });
  }

  return (
    <div className="space-y-6">
      {/* Plan header */}
      <Card>
        <CardBody>
          <div className="flex items-center gap-3 mb-4 flex-wrap">
            <RiskLevelBadge level={fp.risk_level} />
            <FixPlanStatusBadge status={fp.status} />
            <span className="text-sm font-medium text-muted-foreground">{planLabel(fp, t)}</span>
            <h2 className="text-xl font-semibold text-foreground">{fp.title}</h2>
          </div>
          {/* The content identity an approval is bound to: approving sends this hash back (409 if it changed) */}
          <p className="text-xs text-muted-foreground font-mono mb-4" title={fp.content_hash ?? undefined}>
            {t("plans.hash")} {shortHash(fp.content_hash)}
            {fp.approved_hash && ` · ${t("plans.approvedVersion").replace("{n}", String(fp.approved_version ?? fp.plan_version))} ${shortHash(fp.approved_hash)}`}
          </p>
          <div
            className="text-muted-foreground mb-6 report-content"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(fp.summary) }}
          />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground block">{t("issues.riskLevel")}</span>
              <span className="font-medium text-foreground">{fp.risk_level}</span>
            </div>
            <div>
              <span className="text-muted-foreground block">{t("issues.impact")}</span>
              <span className="text-foreground">{fp.estimated_impact || "-"}</span>
            </div>
            <div>
              <span className="text-muted-foreground block">{t("issues.created")}</span>
              <span className="text-foreground">{formatShortDate(fp.created_at)}</span>
            </div>
            {fp.approved_by && (
              <div>
                <span className="text-muted-foreground block">{t("issues.approvedBy")}</span>
                <span className="font-medium text-foreground">{fp.approved_by}</span>
              </div>
            )}
            {fp.approved_at && (
              <div>
                <span className="text-muted-foreground block">{t("issues.approvedAt")}</span>
                <span className="text-foreground">{formatFullDate(fp.approved_at)}</span>
              </div>
            )}
          </div>
        </CardBody>
      </Card>

      {/* Steps */}
      {fp.steps.length > 0 && (
        <Card>
          <CardBody>
            <h3 className="text-lg font-semibold text-foreground mb-4">{t("issues.steps")}</h3>
            <ol className="space-y-4">
              {fp.steps.map((step, i) => (
                <RunbookStep key={i} index={i + 1} step={step} />
              ))}
            </ol>

            {fp.pre_checks.length > 0 && (
              <div className="mt-6">
                <h4 className="font-semibold text-foreground mb-2">{t("issues.preChecks")}</h4>
                <ul className="space-y-1.5">
                  {fp.pre_checks.map((c, i) => (
                    <CheckItem key={i} item={c} />
                  ))}
                </ul>
              </div>
            )}

            {fp.post_checks.length > 0 && (
              <div className="mt-6">
                <h4 className="font-semibold text-foreground mb-2">{t("issues.postChecks")}</h4>
                <ul className="space-y-1.5">
                  {fp.post_checks.map((c, i) => (
                    <CheckItem key={i} item={c} />
                  ))}
                </ul>
              </div>
            )}

            {Object.keys(fp.rollback_plan).length > 0 && (
              <RollbackPlan plan={fp.rollback_plan} />
            )}
          </CardBody>
        </Card>
      )}

      {/* Approval workflow */}
      {(needsApproval || blocked) && (
        <Card>
          <CardBody>
            <h3 className="text-lg font-semibold text-foreground mb-4">{t("issues.approval")}</h3>

            {needsApproval && (fp.risk_level === "L2" || fp.risk_level === "L3") && (
              <div className="mb-4 p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg text-sm text-amber-500">
                <strong>{fp.risk_level} {t("issues.approvalWarning")}</strong>
              </div>
            )}
            {blocked && <p className="mb-4 text-sm text-muted-foreground">{t(`issue.approvalBlocked.${blocked}`)}</p>}

            <div className="flex items-center gap-3">
              {needsApproval && (
                <button
                  onClick={() => { approveMut.reset(); setApprovalDialog("approve"); }}
                  disabled={approveMut.isPending}
                  className="px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-lg hover:bg-green-700 disabled:opacity-50 transition-colors"
                >
                  {t("issues.approve")}
                </button>
              )}
              <button
                onClick={() => { rejectMut.reset(); setApprovalDialog("reject"); }}
                disabled={rejectMut.isPending}
                className="px-4 py-2 border border-red-500/30 text-red-500 text-sm font-medium rounded-lg hover:bg-red-500/10 disabled:opacity-50 transition-colors"
              >
                {rejectMut.isPending ? t("issues.rejecting") : t("issues.reject")}
              </button>
            </div>
          </CardBody>
        </Card>
      )}

      {(needsApproval || blocked) && approvalDialog && (
        <ReasonDialog
          title={`${t(approvalDialog === "approve" ? "plans.approveTitle" : "plans.rejectTitle")} ${planLabel(fp, t)}`}
          description={`${fp.title} · ${t("plans.hash")} ${shortHash(fp.content_hash)}`}
          confirmText={approvalDialog === "approve" ? t("issues.approve") : t("issues.reject")}
          variant={approvalDialog === "reject" ? "destructive" : "default"}
          required={approvalDialog === "reject"}
          busy={approveMut.isPending || rejectMut.isPending}
          error={(approvalDialog === "approve" ? approveMut.error : rejectMut.error)?.message ?? null}
          onConfirm={(reason) => {
            const done = { onSuccess: () => setApprovalDialog(null) };
            if (approvalDialog === "approve") {
              const name = claimedName.trim();
              approveMut.mutate({ id: fp.id, content_hash: fp.content_hash ?? "", reason: reason || undefined, approved_by: !isAuthenticated && name ? name : undefined }, done);
            } else rejectMut.mutate({ id: fp.id, reason }, done);
          }}
          onClose={() => setApprovalDialog(null)}
        >
          {approvalDialog === "approve" && !isAuthenticated && (
            <input type="text" value={claimedName} onChange={(e) => setClaimedName(e.target.value)} maxLength={100}
              placeholder={t("issues.approverPlaceholder")}
              className="w-full mb-3 border border-border bg-background text-foreground rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50" />
          )}
        </ReasonDialog>
      )}

      {/* Execute action */}
      {canExecute && (
        <Card>
          <CardBody>
            <h3 className="text-lg font-semibold text-foreground mb-4">{t("issues.executePlan")}</h3>
            <button
              onClick={handleExecute}
              disabled={executeMut.isPending}
              className="px-4 py-2 bg-primary text-primary-foreground text-sm font-medium rounded-lg hover:bg-primary/90 disabled:opacity-50 transition-colors"
            >
              {executeMut.isPending ? t("issues.executing") : t("issues.execute")}
            </button>
          </CardBody>
        </Card>
      )}

      {/* Other plans for this issue */}
      {plans.length > 1 && (
        <Card>
          <CardBody>
            <h3 className="text-sm font-medium text-muted-foreground mb-3 uppercase tracking-wider">
              {t("issues.allFixPlans")}
            </h3>
            <div className="space-y-2">
              {plans.map((p) => (
                <div
                  key={p.id}
                  className={`flex items-center justify-between p-3 rounded-lg border transition-colors ${
                    p.id === fp.id
                      ? "border-primary/50 bg-primary/5"
                      : "border-border"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <RiskLevelBadge level={p.risk_level} />
                    <span className="text-xs text-muted-foreground">{planLabel(p, t)}</span>
                    <span className="text-sm font-medium text-foreground">{p.title}</span>
                    {p.id === fp.id && (
                      <span className="text-[10px] text-primary font-medium uppercase">{t("issues.currentPlan")}</span>
                    )}
                  </div>
                  <FixPlanStatusBadge status={p.status} />
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      )}
      {dialog}
    </div>
  );
}

/* ================================================================== */
/*  Status labels + acceptance                                         */
/* ================================================================== */

function StatusLabel({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</span>
      {children}
    </span>
  );
}

/** Accept / reject a run pending acceptance; both need a reason, and the identity is the session's. */
function AcceptanceActions({ execution }: { execution: FixExecution }) {
  const { t } = useLocale();
  const accept = useAcceptExecution();
  const [decision, setDecision] = useState<"accepted" | "rejected" | null>(null);
  return (
    <>
      <div className="flex items-center gap-2">
        <button
          onClick={() => { accept.reset(); setDecision("accepted"); }}
          className="px-3 py-1.5 bg-green-600 text-white text-xs font-medium rounded-lg hover:bg-green-700 transition-colors"
        >
          {t("verification.accept")}
        </button>
        <button
          onClick={() => { accept.reset(); setDecision("rejected"); }}
          className="px-3 py-1.5 border border-red-500/30 text-red-500 text-xs font-medium rounded-lg hover:bg-red-500/10 transition-colors"
        >
          {t("verification.reject")}
        </button>
      </div>
      {decision && (
        <ReasonDialog
          title={`${t(decision === "accepted" ? "verification.acceptTitle" : "verification.rejectTitle")} #${execution.id}`}
          description={t(decision === "accepted" ? "verification.acceptHint" : "verification.rejectHint")}
          confirmText={t(decision === "accepted" ? "verification.accept" : "verification.reject")}
          variant={decision === "rejected" ? "destructive" : "default"}
          required
          busy={accept.isPending}
          error={accept.error?.message ?? null}
          onConfirm={(reason) =>
            accept.mutate({ id: execution.id, decision, reason }, { onSuccess: () => setDecision(null) })}
          onClose={() => setDecision(null)}
        />
      )}
    </>
  );
}

/* ================================================================== */
/*  Root-cause location                                                */
/* ================================================================== */

const LOCATION_CHIP: Record<string, string> = {
  valid: "bg-green-500/20 text-green-600 dark:text-green-400",
  partial: "bg-amber-500/20 text-amber-600 dark:text-amber-400",
  invalid: "bg-red-500/20 text-red-600 dark:text-red-400",
  absent: "bg-secondary text-muted-foreground",
};
const LOCATION_VERDICTS: LocationVerdict[] = ["correct", "partial", "incorrect"];

function LocationSection({ issueId, rca: r, t }: {
  issueId: number;
  rca: NonNullable<ReturnType<typeof useAnomalyRca>["data"]>;
  t: (key: string) => string;
}) {
  const feedback = useRcaFeedback(issueId);
  const status = r.location_status ?? "absent";
  const loc = r.location;
  const judgeable = status === "valid" || status === "partial";
  return (
    <Card>
      <CardBody>
        <div className="flex items-center gap-2 mb-3">
          <h2 className="text-lg font-semibold text-foreground">{t("location.title")}</h2>
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${LOCATION_CHIP[status] ?? LOCATION_CHIP.absent}`}>
            {t(`location.status.${status}`)}
          </span>
        </div>

        {loc && loc.candidates.length > 0 ? (
          <ol className="space-y-2 mb-4">
            {loc.candidates.map((c) => (
              <li key={c.ref} className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-mono text-xs text-muted-foreground">#{c.rank}</span>
                <Link to={`/app/resources/${c.ref}`} className="font-medium text-primary hover:underline">
                  {c.name || c.resource_id || `#${c.ref}`}
                </Link>
                {c.type && <span className="text-xs text-muted-foreground">{c.type}</span>}
                {c.supporting.length > 0 && (
                  <span className="text-xs text-green-600 dark:text-green-400">
                    {t("location.supporting")} {c.supporting.join(", ")}
                  </span>
                )}
                {c.refuting.length > 0 && (
                  <span className="text-xs text-red-600 dark:text-red-400">
                    {t("location.refuting")} {c.refuting.join(", ")}
                  </span>
                )}
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-muted-foreground mb-4">{t("location.noCandidates")}</p>
        )}

        {loc && loc.path.length > 0 && (
          <p className="text-xs text-muted-foreground mb-3">
            {t("location.path")}:{" "}
            {loc.path.map((e) => `${e.src_name || `#${e.src_ref}`} → ${e.dst_name || `#${e.dst_ref}`} (${e.relation_type})`).join(" · ")}
          </p>
        )}
        {loc && loc.dropped.length > 0 && (
          <div className="text-xs text-muted-foreground mb-3">
            <span>{t("location.dropped")}:</span>
            <ul className="list-disc list-inside">
              {loc.dropped.map((d, i) => <li key={i}>{d}</li>)}
            </ul>
          </div>
        )}

        {/* The human verdict on the location — the ground truth the location-accuracy stats count */}
        <div className="flex flex-wrap items-center gap-2 text-sm border-t border-border pt-3">
          <span className="text-muted-foreground">{t("location.verdict")}:</span>
          {r.location_verdict ? (
            <span className="text-foreground">
              {t(`location.verdict.${r.location_verdict}`)}
              <span className="text-xs text-muted-foreground">
                {r.location_verdict_by && ` · ${r.location_verdict_by}`}
                {r.location_verdict_at && ` · ${formatFullDate(r.location_verdict_at)}`}
              </span>
            </span>
          ) : judgeable ? (
            LOCATION_VERDICTS.map((v) => (
              <button key={v} onClick={() => feedback.mutate({ location_verdict: v })} disabled={feedback.isPending}
                      className="px-2.5 py-1 text-xs rounded-md bg-secondary hover:bg-accent transition-colors disabled:opacity-50">
                {t(`location.verdict.${v}`)}
              </button>
            ))
          ) : (
            <span className="text-xs text-muted-foreground">{t("location.cannotJudge")}</span>
          )}
          {feedback.error && <span className="text-xs text-destructive">{feedback.error.message}</span>}
        </div>
      </CardBody>
    </Card>
  );
}

/* ================================================================== */
/*  Execution + Verification Tabs                                      */
/* ================================================================== */

function ExecutionTab({ executions, cancelExecMut, setActionMsg, t }: {
  executions: ReturnType<typeof useIssueExecutions>;
  cancelExecMut: ReturnType<typeof useCancelExecution>;
  setActionMsg: (v: string | null) => void;
  t: (key: string) => string;
}) {
  const { confirm, dialog } = useConfirm();
  if (executions.isLoading) return <Spinner label={t("common.loading")} />;
  // a failed fetch must not read as "no executions"
  if (executions.error) return <ErrorBanner message={executions.error.message} onRetry={() => executions.refetch()} />;
  const runs = newestFirst(executions.data);
  if (runs.length === 0) {
    return (
      <Card>
        <CardBody>
          <div className="text-center py-8 text-muted-foreground text-sm">{t("issues.noExecutions")}</div>
        </CardBody>
      </Card>
    );
  }
  return (
    <div className="space-y-6">
      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold text-foreground mb-4">{t("issues.executionHistory")}</h3>
          <ExecutionsTable
            executions={runs}
            onCancel={async (id) => {
              if (!(await confirm("Cancel this execution?", { variant: "destructive", confirmText: "Cancel Execution" }))) return;
              cancelExecMut.mutate(id, {
                onError: (err) => setActionMsg(`Cancel failed: ${err.message}`),
              });
            }}
            cancelPending={cancelExecMut.isPending}
          />
        </CardBody>
      </Card>
      {/* newest first (newestFirst), whatever order the API returns them in; the newest opens by default */}
      {runs.map((ex, i) => (
        <Card key={ex.id}>
          <CardBody>
            <details open={i === 0}>
              <summary className="cursor-pointer text-sm font-semibold text-foreground">
                {t("issues.executionN").replace("{n}", String(ex.id))}
                <span className="ml-2 text-xs font-normal text-muted-foreground">
                  {ex.status}{ex.started_at && ` · ${formatFullDate(ex.started_at)}`}
                </span>
              </summary>
              <div className="mt-4">
                <ExecutionEvidence execution={ex} />
              </div>
            </details>
          </CardBody>
        </Card>
      ))}
      {dialog}
    </div>
  );
}

/** The newest run's verdict. Accept / reject is offered only for `pending` — the same item the page banner shows
 *  (issueStatuses), never recomputed here from the run's own verification_status. */
function VerificationTab({ executions, pending, t }: {
  executions: ReturnType<typeof useIssueExecutions>;
  pending: FixExecution | null;
  t: (key: string) => string;
}) {
  if (executions.isLoading) return <Spinner label={t("common.loading")} />;
  // a failed fetch must not read as "not executed"
  if (executions.error) return <ErrorBanner message={executions.error.message} onRetry={() => executions.refetch()} />;
  const runs = executions.data ?? [];
  const latest = latestExecution(runs);
  if (!latest) {
    return (
      <Card>
        <CardBody>
          <div className="text-center py-8 text-muted-foreground text-sm">{t("verification.noExecution")}</div>
        </CardBody>
      </Card>
    );
  }
  return (
    <div className="space-y-6">
      <Card>
        <CardBody>
          <div className="flex flex-wrap items-center gap-3 mb-4">
            <h3 className="text-lg font-semibold text-foreground">
              {t("issues.executionN").replace("{n}", String(latest.id))}
            </h3>
            <VerificationChip status={latest.verification_status} />
            {pending?.id === latest.id && (
              <div className="ml-auto"><AcceptanceActions execution={pending} /></div>
            )}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            <div className="md:col-span-2">
              <span className="text-muted-foreground block">{t("verification.reason")}</span>
              <span className="text-foreground whitespace-pre-wrap">{latest.verification_reason || "—"}</span>
            </div>
            <div>
              <span className="text-muted-foreground block">{t("verification.acceptedBy")}</span>
              <span className="text-foreground">{latest.accepted_by || "—"}</span>
            </div>
            <div>
              <span className="text-muted-foreground block">{t("verification.acceptedAt")}</span>
              <span className="text-foreground">{latest.accepted_at ? formatFullDate(latest.accepted_at) : "—"}</span>
            </div>
            <div className="md:col-span-2">
              <span className="text-muted-foreground block">{t("verification.note")}</span>
              <span className="text-foreground whitespace-pre-wrap">{latest.acceptance_note || "—"}</span>
            </div>
          </div>
        </CardBody>
      </Card>

      {runs.length > 1 && (
        <Card>
          <CardBody>
            <h3 className="text-sm font-medium text-muted-foreground mb-3 uppercase tracking-wider">
              {t("verification.history")}
            </h3>
            <ul className="space-y-2 text-sm">
              {runs.map((ex) => (
                <li key={ex.id} className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-muted-foreground">#{ex.id}</span>
                  <VerificationChip status={ex.verification_status} />
                  <span className="text-muted-foreground">{ex.verification_reason}</span>
                  {ex.accepted_by && (
                    <span className="text-xs text-muted-foreground">· {ex.accepted_by}: {ex.acceptance_note}</span>
                  )}
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      )}
    </div>
  );
}

/* ================================================================== */
/*  Timeline Tab                                                       */
/* ================================================================== */

function TimelineTab({
  timeline,
  alerts,
  occurrenceCount,
  t,
}: {
  timeline: ReturnType<typeof useIssueTimeline>;
  alerts: MergedAlert[] | undefined;
  occurrenceCount: number | undefined;
  t: (key: string) => string;
}) {
  if (timeline.isLoading) return <Spinner label="Loading timeline..." />;

  const events = timeline.data ?? [];

  return (
    <div className="space-y-6">
      {events.length === 0 ? (
        <Card>
          <CardBody>
            <div className="text-center py-8 text-muted-foreground text-sm">
              {t("issues.noTimeline")}
            </div>
          </CardBody>
        </Card>
      ) : (
        <Card>
          <CardBody>
            <h3 className="text-sm font-medium text-muted-foreground mb-4 uppercase tracking-wider">
              {t("issues.pipelineTimeline")}
            </h3>
            <PipelineTimeline events={events} />
          </CardBody>
        </Card>
      )}

      {alerts && alerts.length > 0 && (
        <MergedAlertsSection alerts={alerts} occurrenceCount={occurrenceCount} />
      )}
    </div>
  );
}

/* ================================================================== */
/*  Merged Alerts                                                      */
/* ================================================================== */

const SEV_CHIP: Record<string, string> = {
  critical: "bg-red-500/20 text-red-400",
  high: "bg-orange-500/20 text-orange-400",
  medium: "bg-yellow-500/20 text-yellow-400",
  low: "bg-secondary text-muted-foreground",
};

function MergedAlertsSection({
  alerts,
  occurrenceCount,
}: {
  alerts: MergedAlert[];
  occurrenceCount?: number;
}) {
  const { t } = useLocale();
  const [expanded, setExpanded] = useState(false);
  const displayed = expanded ? alerts : alerts.slice(-5);

  return (
    <Card>
      <CardBody>
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-2 w-full text-left"
        >
          <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
            {t("issues.mergedAlerts")} ({alerts.length})
          </h3>
          {occurrenceCount && occurrenceCount > 1 && (
            <span className="text-xs bg-primary/10 text-primary px-2 py-0.5 rounded-full">
              {occurrenceCount} {t("issues.occurrences")}
            </span>
          )}
          <span className="ml-auto text-muted-foreground text-xs">
            {expanded ? t("issues.collapse") : t("issues.expand")}
          </span>
        </button>
        <div className="mt-3 space-y-2">
          {displayed.map((alert, i) => (
            <div key={i} className="flex items-center gap-3 text-sm py-1.5 px-2 rounded bg-secondary">
              <span className="text-xs text-muted-foreground whitespace-nowrap font-mono">
                {new Date(alert.timestamp).toLocaleString()}
              </span>
              <span className="text-xs bg-muted text-muted-foreground px-1.5 py-0.5 rounded">
                {alert.source}
              </span>
              <span className={`text-xs px-1.5 py-0.5 rounded ${SEV_CHIP[alert.severity] || SEV_CHIP.low}`}>
                {alert.severity}
              </span>
              <span className="text-foreground flex-1">{alert.title}</span>
            </div>
          ))}
          {!expanded && alerts.length > 5 && (
            <div className="text-xs text-muted-foreground text-center">
              {t("issues.showingLast")} {alerts.length}
            </div>
          )}
        </div>
      </CardBody>
    </Card>
  );
}
