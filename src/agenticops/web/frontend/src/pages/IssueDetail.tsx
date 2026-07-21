import { useState } from "react";
import { useParams, Link } from "react-router-dom";
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
import { useCancelExecution } from "@/hooks/useFixExecutions";
import { useLocale } from "@/i18n/LocaleContext";
import { useConfirm } from "@/components/ui/ConfirmDialog";
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
import { formatFullDate, formatShortDate } from "@/lib/formatDate";
import { renderMarkdown } from "@/lib/renderMarkdown";
import { apiFetch } from "@/api/client";
import type { IssueStatus, PipelineEvent, MergedAlert, FixPlan } from "@/api/types";

/* ================================================================== */
/*  Tab type                                                           */
/* ================================================================== */

type Tab = "issue" | "fixPlan" | "timeline";

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

  /* -- Local state ------------------------------------------------- */
  const [tab, setTab] = useState<Tab>("issue");
  const [rcaLoading, setRcaLoading] = useState(false);
  const [fixPlanLoading, setFixPlanLoading] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [approverName, setApproverName] = useState("");
  const [showApproveForm, setShowApproveForm] = useState(false);

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
            <IssueStatusBadge status={a.status} />
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
        {(
          [
            { key: "issue" as Tab, label: t("issues.tab.issue") },
            { key: "fixPlan" as Tab, label: t("issues.tab.fixPlan") },
            { key: "timeline" as Tab, label: t("issues.tab.timeline") },
          ] as const
        ).map((item) => (
          <button
            key={item.key}
            onClick={() => setTab(item.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === item.key
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "issue" && (
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
          executions={executions}
          fixPlanLoading={fixPlanLoading}
          onGenerateFixPlan={triggerFixPlan}
          hasRca={!!rca.data}
          latestPlan={latestPlan}
          approveMut={approveMut}
          rejectMut={rejectMut}
          executeMut={executeMut}
          cancelExecMut={cancelExecMut}
          approverName={approverName}
          setApproverName={setApproverName}
          showApproveForm={showApproveForm}
          setShowApproveForm={setShowApproveForm}
          setActionMsg={setActionMsg}
          t={t}
        />
      )}
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
  issue: NonNullable<ReturnType<typeof useAnomaly>["data"]>;
  rca: ReturnType<typeof useAnomalyRca>;
  rcaLoading: boolean;
  onRunRca: () => void;
  t: (key: string) => string;
}) {
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
              <span className="text-foreground">{a.resource_type}</span>
            </div>
            <div>
              <span className="text-muted-foreground block">{t("issues.region")}</span>
              <span className="text-foreground">{a.region}</span>
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

          {a.metric_name && (
            <div className="mt-6 p-4 bg-secondary rounded-lg border border-border/50">
              <h3 className="font-semibold text-foreground mb-2">{t("issues.metricDetails")}</h3>
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-muted-foreground">{t("issues.metric")}:</span>{" "}
                  <span className="text-foreground">{a.metric_name}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">{t("issues.expected")}:</span>{" "}
                  <span className="text-foreground">{a.expected_value}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">{t("issues.actual")}:</span>{" "}
                  <span className="text-foreground">{a.actual_value}</span>
                </div>
              </div>
            </div>
          )}
        </CardBody>
      </Card>

      {/* RCA Section */}
      <RcaSection issueId={a.id} rca={rca} rcaLoading={rcaLoading} onRunRca={onRunRca} t={t} />
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
          {t("issues.rcaModel")}: {r.llm_model} | {t("issues.rcaAnalyzed")} {formatFullDate(r.created_at)}
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
  executions,
  fixPlanLoading,
  onGenerateFixPlan,
  hasRca,
  latestPlan,
  approveMut,
  rejectMut,
  executeMut,
  cancelExecMut,
  approverName,
  setApproverName,
  showApproveForm,
  setShowApproveForm,
  setActionMsg,
  t,
}: {
  fixPlans: ReturnType<typeof useFixPlans>;
  executions: ReturnType<typeof useIssueExecutions>;
  fixPlanLoading: boolean;
  onGenerateFixPlan: () => void;
  hasRca: boolean;
  latestPlan: FixPlan | null;
  approveMut: ReturnType<typeof useApproveFixPlan>;
  rejectMut: ReturnType<typeof useRejectFixPlan>;
  executeMut: ReturnType<typeof useExecuteFixPlan>;
  cancelExecMut: ReturnType<typeof useCancelExecution>;
  approverName: string;
  setApproverName: (v: string) => void;
  showApproveForm: boolean;
  setShowApproveForm: (v: boolean) => void;
  setActionMsg: (v: string | null) => void;
  t: (key: string) => string;
}) {
  const { confirm, dialog } = useConfirm();

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
  const needsApproval = fp.status === "draft" || fp.status === "pending_approval";
  const canExecute = fp.status === "approved";

  function handleApprove() {
    if (!approverName.trim()) return;
    approveMut.mutate(
      { id: fp.id, approved_by: approverName.trim() },
      {
        onSuccess: () => {
          setShowApproveForm(false);
          fixPlans.refetch();
        },
        onError: (err) => setActionMsg(`Approve failed: ${err.message}`),
      },
    );
  }

  async function handleReject() {
    if (!(await confirm("Are you sure you want to reject this fix plan?", { variant: "destructive", confirmText: "Reject" }))) return;
    rejectMut.mutate(fp.id, {
      onSuccess: () => fixPlans.refetch(),
      onError: (err) => setActionMsg(`Reject failed: ${err.message}`),
    });
  }

  async function handleExecute() {
    if (!(await confirm("Execute this fix plan now?", { confirmText: "Execute" }))) return;
    executeMut.mutate(fp.id, {
      onSuccess: () => {
        fixPlans.refetch();
        executions.refetch();
      },
      onError: (err) => setActionMsg(`Execute failed: ${err.message}`),
    });
  }

  return (
    <div className="space-y-6">
      {/* Plan header */}
      <Card>
        <CardBody>
          <div className="flex items-center gap-3 mb-4 flex-wrap">
            <RiskLevelBadge level={fp.risk_level} />
            <FixPlanStatusBadge status={fp.status} />
            <h2 className="text-xl font-semibold text-foreground">{fp.title}</h2>
          </div>
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
      {needsApproval && (
        <Card>
          <CardBody>
            <h3 className="text-lg font-semibold text-foreground mb-4">{t("issues.approval")}</h3>

            {(fp.risk_level === "L2" || fp.risk_level === "L3") && (
              <div className="mb-4 p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg text-sm text-amber-500">
                <strong>{fp.risk_level} {t("issues.approvalWarning")}</strong>
              </div>
            )}

            <div className="flex items-center gap-3">
              {!showApproveForm ? (
                <button
                  onClick={() => setShowApproveForm(true)}
                  className="px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-lg hover:bg-green-700 transition-colors"
                >
                  {t("issues.approve")}
                </button>
              ) : (
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    placeholder={t("issues.approverPlaceholder")}
                    value={approverName}
                    onChange={(e) => setApproverName(e.target.value)}
                    className="border border-border bg-background text-foreground rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                  <button
                    onClick={handleApprove}
                    disabled={approveMut.isPending || !approverName.trim()}
                    className="px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-lg hover:bg-green-700 disabled:opacity-50 transition-colors"
                  >
                    {approveMut.isPending ? t("issues.approving") : t("common.confirm")}
                  </button>
                  <button
                    onClick={() => setShowApproveForm(false)}
                    className="px-3 py-2 text-sm text-muted-foreground hover:text-foreground"
                  >
                    {t("common.cancel")}
                  </button>
                </div>
              )}
              <button
                onClick={handleReject}
                disabled={rejectMut.isPending}
                className="px-4 py-2 border border-red-500/30 text-red-500 text-sm font-medium rounded-lg hover:bg-red-500/10 disabled:opacity-50 transition-colors"
              >
                {rejectMut.isPending ? t("issues.rejecting") : t("issues.reject")}
              </button>
            </div>
          </CardBody>
        </Card>
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

      {/* Execution history */}
      {executions.data && executions.data.length > 0 && (
        <Card>
          <CardBody>
            <h3 className="text-lg font-semibold text-foreground mb-4">{t("issues.executionHistory")}</h3>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-border">
                    <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">ID</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">{t("issues.tab.issue")}</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">{t("issues.executedBy")}</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">{t("issues.duration")}</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">{t("issues.started")}</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">{t("issues.actions")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {executions.data.map((ex) => (
                    <tr key={ex.id} className="hover:bg-secondary transition-colors">
                      <td className="px-4 py-2 text-sm font-mono text-muted-foreground">#{ex.id}</td>
                      <td className="px-4 py-2">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                            ex.status === "succeeded"
                              ? "bg-green-500/20 text-green-400"
                              : ex.status === "failed"
                                ? "bg-red-500/20 text-red-400"
                                : "bg-secondary text-muted-foreground"
                          }`}
                        >
                          {ex.status}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-sm text-muted-foreground">{ex.executed_by}</td>
                      <td className="px-4 py-2 text-sm text-muted-foreground">
                        {ex.duration_ms > 0 ? `${(ex.duration_ms / 1000).toFixed(1)}s` : "-"}
                      </td>
                      <td className="px-4 py-2 text-sm text-muted-foreground">
                        {ex.started_at ? formatFullDate(ex.started_at) : "-"}
                      </td>
                      <td className="px-4 py-2">
                        {(ex.status === "pending" || ex.status === "running") && (
                          <button
                            onClick={async () => {
                              if (!(await confirm("Cancel this execution?", { variant: "destructive", confirmText: "Cancel Execution" }))) return;
                              cancelExecMut.mutate(ex.id, {
                                onError: (err) => setActionMsg(`Cancel failed: ${err.message}`),
                              });
                            }}
                            disabled={cancelExecMut.isPending}
                            className="px-3 py-1 text-xs font-medium text-red-500 border border-red-500/30 rounded-lg hover:bg-red-500/10 disabled:opacity-50 transition-colors"
                          >
                            {t("common.cancel")}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {executions.data.some((ex) => ex.error_message) && (
              <div className="mt-4">
                {executions.data
                  .filter((ex) => ex.error_message)
                  .map((ex) => (
                    <div
                      key={ex.id}
                      className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-sm text-red-400 mb-2"
                    >
                      <strong>#{ex.id} {t("issues.executionError")}:</strong> {ex.error_message}
                    </div>
                  ))}
              </div>
            )}
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

/* ================================================================== */
/*  Pipeline Timeline                                                  */
/* ================================================================== */

const STAGE_COLORS: Record<string, string> = {
  detection: "bg-blue-500",
  rca: "bg-amber-500",
  planning: "bg-violet-500",
  approval: "bg-emerald-500",
  execution: "bg-orange-500",
  resolution: "bg-green-600",
  notification: "bg-muted-foreground/40",
};

const STATUS_ICONS: Record<string, string> = {
  completed: "\u2713",
  started: "\u25B6",
  failed: "\u2717",
  skipped: "\u2013",
};

function PipelineTimeline({ events }: { events: PipelineEvent[] }) {
  return (
    <div className="relative">
      <div className="absolute left-[15px] top-2 bottom-2 w-0.5 bg-muted" />
      <div className="space-y-3">
        {events.map((ev, i) => {
          const color = STAGE_COLORS[ev.stage] || "bg-muted-foreground/40";
          const icon = STATUS_ICONS[ev.status] || "\u2022";
          const isFailed = ev.status === "failed";
          return (
            <div key={ev.id ?? i} className="relative flex items-start gap-3 pl-0">
              <div
                className={`relative z-10 flex-shrink-0 w-[31px] h-[31px] rounded-full flex items-center justify-center text-white text-xs font-bold ${color} ${isFailed ? "ring-2 ring-red-300" : ""}`}
              >
                {icon}
              </div>
              <div className="flex-1 min-w-0 pb-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium text-foreground">
                    {ev.event_type.replace(/_/g, " ")}
                  </span>
                  <span
                    className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wide ${
                      isFailed
                        ? "bg-red-500/20 text-red-400"
                        : ev.status === "started"
                          ? "bg-blue-500/20 text-blue-400"
                          : ev.status === "skipped"
                            ? "bg-secondary text-muted-foreground"
                            : "bg-green-500/20 text-green-400"
                    }`}
                  >
                    {ev.status}
                  </span>
                  {ev.duration_ms != null && ev.duration_ms > 0 && (
                    <span className="text-[10px] text-muted-foreground">
                      {ev.duration_ms >= 1000
                        ? `${(ev.duration_ms / 1000).toFixed(1)}s`
                        : `${ev.duration_ms}ms`}
                    </span>
                  )}
                  {ev.trace_id && (
                    <span className="text-[10px] font-mono text-primary">
                      {ev.trace_id}
                    </span>
                  )}
                </div>
                {ev.detail && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {Object.entries(ev.detail).map(([k, v]) =>
                      v != null ? (
                        <span
                          key={k}
                          className="inline-flex items-center px-1.5 py-0.5 rounded bg-secondary text-[10px] text-muted-foreground font-mono"
                        >
                          {k}: {typeof v === "object" ? JSON.stringify(v) : String(v).slice(0, 80)}
                        </span>
                      ) : null,
                    )}
                  </div>
                )}
                <div className="text-[10px] text-muted-foreground mt-0.5">
                  {ev.actor !== "system" && <span className="mr-2">{ev.actor}</span>}
                  {formatFullDate(ev.created_at)}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ================================================================== */
/*  Runbook helper components                                          */
/* ================================================================== */

function RunbookStep({ index, step }: { index: number; step: unknown }) {
  const isObj = typeof step === "object" && step !== null && !Array.isArray(step);
  const s = isObj ? (step as Record<string, unknown>) : null;
  const action = s?.action ?? s?.description ?? s?.step;
  const command = s?.command as string | undefined;
  const text = typeof step === "string" ? step : typeof action === "string" ? action : null;

  return (
    <li className="border border-border rounded-lg p-4 bg-background">
      <div className="flex gap-3">
        <span className="flex-shrink-0 w-7 h-7 rounded-full bg-primary/20 text-primary flex items-center justify-center text-sm font-semibold">
          {index}
        </span>
        <div className="flex-1 min-w-0">
          {text ? (
            <div
              className="text-foreground text-sm leading-relaxed report-content"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(text) }}
            />
          ) : (
            <pre className="text-foreground text-sm whitespace-pre-wrap">
              {JSON.stringify(step, null, 2)}
            </pre>
          )}
          {command && <CommandBlock command={command} />}
        </div>
      </div>
    </li>
  );
}

function CommandBlock({ command }: { command: string }) {
  const { t } = useLocale();
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(command).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="mt-3 relative group">
      <div
        className="rounded-lg p-3 text-sm font-mono overflow-x-auto"
        style={{ backgroundColor: "#1e1e2e", color: "#cdd6f4" }}
      >
        <span className="select-none" style={{ color: "#a6e3a1" }}>
          ${" "}
        </span>
        {command}
      </div>
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 px-2 py-1 text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity"
        style={{ backgroundColor: "#313244", color: "#a6adc8" }}
      >
        {copied ? t("issues.copied") : t("issues.copy")}
      </button>
    </div>
  );
}

function CheckItem({ item }: { item: unknown }) {
  const isObj = typeof item === "object" && item !== null && !Array.isArray(item);
  const s = isObj ? (item as Record<string, unknown>) : null;
  const text = typeof item === "string" ? item : (s?.check ?? s?.description ?? s?.action);
  const command = s?.command as string | undefined;

  return (
    <li className="flex items-start gap-2 text-sm text-muted-foreground">
      <svg className="w-4 h-4 mt-0.5 flex-shrink-0 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      <div className="flex-1 min-w-0">
        <span>{typeof text === "string" ? text : JSON.stringify(item)}</span>
        {command && <CommandBlock command={command} />}
      </div>
    </li>
  );
}

function RollbackPlan({ plan }: { plan: Record<string, unknown> }) {
  const { t } = useLocale();
  const trigger = plan.trigger as string | undefined;
  const steps = Array.isArray(plan.steps) ? plan.steps : null;

  return (
    <div className="mt-6 border border-amber-500/30 rounded-lg bg-amber-500/5 overflow-hidden">
      <div className="px-4 py-3 border-b border-amber-500/30">
        <h4 className="font-semibold text-foreground">{t("issues.rollbackPlan")}</h4>
      </div>
      <div className="p-4 space-y-3">
        {trigger && (
          <div className="flex items-start gap-2 text-sm text-amber-500 bg-amber-500/10 rounded-lg px-3 py-2">
            <svg className="w-4 h-4 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span>
              <strong>{t("issues.rollbackTrigger")}:</strong> {trigger}
            </span>
          </div>
        )}
        {steps ? (
          <ol className="space-y-3">
            {steps.map((step: unknown, i: number) => (
              <RunbookStep key={i} index={i + 1} step={step} />
            ))}
          </ol>
        ) : (
          <dl className="space-y-2 text-sm">
            {Object.entries(plan)
              .filter(([k]) => k !== "trigger" && k !== "steps")
              .map(([k, v]) => (
                <div key={k}>
                  <dt className="font-medium text-foreground capitalize">
                    {k.replace(/_/g, " ")}
                  </dt>
                  <dd className="text-muted-foreground mt-0.5">
                    {typeof v === "string" ? (
                      v
                    ) : (
                      <pre
                        className="rounded-lg p-3 text-sm font-mono overflow-x-auto mt-1"
                        style={{ backgroundColor: "#1e1e2e", color: "#cdd6f4" }}
                      >
                        {JSON.stringify(v, null, 2)}
                      </pre>
                    )}
                  </dd>
                </div>
              ))}
          </dl>
        )}
      </div>
    </div>
  );
}
