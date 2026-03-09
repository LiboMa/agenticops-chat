import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useAnomaly } from "@/hooks/useAnomaly";
import { useAnomalyRca } from "@/hooks/useAnomalyRca";
import { useFixPlans } from "@/hooks/useFixPlans";
import { useUpdateIssueStatus } from "@/hooks/useIssueActions";
import { useIssueExecutions } from "@/hooks/useIssueExecutions";
import { useIssueTimeline } from "@/hooks/useIssueTimeline";
import { useCancelExecution } from "@/hooks/useFixExecutions";
import { Card, CardBody } from "@/components/ui/Card";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { IssueStatusBadge } from "@/components/ui/IssueStatusBadge";
import { IssueStatusStepper } from "@/components/ui/IssueStatusStepper";
import { IssueActionBar } from "@/components/ui/IssueActionBar";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { FixPlanStatusBadge } from "@/components/ui/FixPlanStatusBadge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatFullDate } from "@/lib/formatDate";
import { renderMarkdown } from "@/lib/renderMarkdown";
import { apiFetch } from "@/api/client";
import type { IssueStatus, PipelineEvent } from "@/api/types";

export default function AnomalyDetail() {
  const { id } = useParams<{ id: string }>();
  const anomalyId = Number(id);

  const anomaly = useAnomaly(anomalyId);
  const rca = useAnomalyRca(anomalyId);
  const fixPlans = useFixPlans({ health_issue_id: anomalyId });
  const executions = useIssueExecutions(anomalyId);
  const timeline = useIssueTimeline(anomalyId);
  const updateStatusMut = useUpdateIssueStatus();
  const cancelExecMut = useCancelExecution();

  const [rcaLoading, setRcaLoading] = useState(false);
  const [fixPlanLoading, setFixPlanLoading] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const triggerRca = async () => {
    setRcaLoading(true);
    setActionMsg(null);
    try {
      await apiFetch<unknown>(`/issues/${anomalyId}/rca`, { method: "POST" });
      setActionMsg("RCA analysis triggered. It may take a minute — refresh to see results.");
      setTimeout(() => rca.refetch(), 10000);
    } catch (e: any) {
      setActionMsg(`RCA trigger failed: ${e.message}`);
    } finally {
      setRcaLoading(false);
    }
  };

  const triggerFixPlan = async () => {
    setFixPlanLoading(true);
    setActionMsg(null);
    try {
      await apiFetch<unknown>(`/issues/${anomalyId}/generate-fix-plan`, { method: "POST" });
      setActionMsg("Fix plan generation triggered. It may take a minute — refresh to see results.");
      setTimeout(() => fixPlans.refetch(), 10000);
    } catch (e: any) {
      setActionMsg(`Fix plan generation failed: ${e.message}`);
    } finally {
      setFixPlanLoading(false);
    }
  };

  const updateStatus = (status: IssueStatus) => {
    setActionMsg(null);
    updateStatusMut.mutate(
      { id: anomalyId, status },
      {
        onSuccess: () => {
          anomaly.refetch();
          executions.refetch();
        },
        onError: (err) => setActionMsg(`Status update failed: ${err.message}`),
      },
    );
  };

  if (anomaly.isLoading) return <Spinner label="Loading issue..." />;
  if (anomaly.error)
    return (
      <ErrorBanner
        message={anomaly.error.message}
        onRetry={() => anomaly.refetch()}
      />
    );

  const a = anomaly.data!;

  return (
    <div className="space-y-6">
      {/* Back link */}
      <Link
        to="/app/issues"
        className="inline-flex items-center text-sm text-slate-500 hover:text-slate-700 transition-colors"
      >
        <svg className="h-4 w-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
        Back to Issues
      </Link>

      {/* Action message banner */}
      {actionMsg && (
        <div className="p-3 rounded-lg bg-primary-50 border border-primary-200 text-sm text-primary-700">
          {actionMsg}
        </div>
      )}

      {/* Issue Header */}
      <Card>
        <CardBody>
          <div className="flex items-center gap-3 mb-4">
            <span className="font-mono text-sm bg-slate-100 text-slate-600 px-2 py-0.5 rounded">
              I#{a.id}
            </span>
            <SeverityBadge severity={a.severity} />
            <IssueStatusBadge status={a.status} />
            <h1 className="text-2xl font-semibold text-slate-900">{a.title}</h1>
          </div>
          <div
            className="text-slate-600 mb-6 report-content"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(a.description) }}
          />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-slate-400 block">Resource</span>
              <span className="font-mono text-slate-700">{a.resource_id}</span>
            </div>
            <div>
              <span className="text-slate-400 block">Type</span>
              <span className="text-slate-700">{a.resource_type}</span>
            </div>
            <div>
              <span className="text-slate-400 block">Region</span>
              <span className="text-slate-700">{a.region}</span>
            </div>
            <div>
              <span className="text-slate-400 block">Detected</span>
              <span className="text-slate-700">{formatFullDate(a.detected_at)}</span>
            </div>
          </div>

          {a.metric_name && (
            <div className="mt-6 p-4 bg-slate-50 rounded-lg border border-slate-100">
              <h3 className="font-semibold text-slate-900 mb-2">
                Metric Details
              </h3>
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-slate-400">Metric:</span>{" "}
                  <span className="text-slate-700">{a.metric_name}</span>
                </div>
                <div>
                  <span className="text-slate-400">Expected:</span>{" "}
                  <span className="text-slate-700">{a.expected_value}</span>
                </div>
                <div>
                  <span className="text-slate-400">Actual:</span>{" "}
                  <span className="text-slate-700">{a.actual_value}</span>
                </div>
              </div>
            </div>
          )}

          {a.resolved_at && (
            <div className="mt-4 text-xs text-slate-400">
              Resolved {formatFullDate(a.resolved_at)}
            </div>
          )}
        </CardBody>
      </Card>

      {/* Status Pipeline Stepper */}
      <Card>
        <CardBody>
          <h2 className="text-sm font-medium text-slate-500 mb-4 uppercase tracking-wider">
            Issue Lifecycle
          </h2>
          <IssueStatusStepper status={a.status} />
        </CardBody>
      </Card>

      {/* Pipeline Event Timeline */}
      {timeline.data && timeline.data.length > 0 && (
        <Card>
          <CardBody>
            <h2 className="text-sm font-medium text-slate-500 mb-4 uppercase tracking-wider">
              Pipeline Timeline
            </h2>
            <PipelineTimeline events={timeline.data} />
          </CardBody>
        </Card>
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
      />

      {/* RCA Section */}
      {rca.isLoading ? (
        <Spinner label="Loading RCA..." />
      ) : !rca.data ? (
        <Card>
          <CardBody>
            <div className="text-center py-8">
              <h2 className="text-lg font-semibold text-slate-900 mb-2">No Root Cause Analysis Yet</h2>
              <p className="text-slate-500 mb-4">
                Run RCA to analyze the root cause of this issue and get recommendations.
              </p>
              <button
                onClick={triggerRca}
                disabled={rcaLoading}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-50 transition-colors"
              >
                {rcaLoading ? "Analyzing..." : "Run Root Cause Analysis"}
              </button>
            </div>
          </CardBody>
        </Card>
      ) : rca.data ? (
        <Card>
          <CardBody>
            <h2 className="text-xl font-semibold text-slate-900 mb-4">
              Root Cause Analysis
            </h2>

            {/* Confidence bar */}
            <div className="mb-6">
              <div className="flex justify-between text-sm mb-1">
                <span className="text-slate-500">Confidence</span>
                <span className="font-medium text-slate-700">
                  {Math.round(rca.data.confidence_score * 100)}%
                </span>
              </div>
              <div className="w-full bg-slate-100 rounded-full h-2">
                <div
                  className="bg-primary-500 h-2 rounded-full transition-all"
                  style={{ width: `${rca.data.confidence_score * 100}%` }}
                />
              </div>
            </div>

            {/* Root Cause */}
            <div className="mb-6">
              <h3 className="font-semibold text-slate-900 mb-2">Root Cause</h3>
              <div
                className="text-slate-700 report-content"
                dangerouslySetInnerHTML={{ __html: renderMarkdown(rca.data.root_cause) }}
              />
            </div>

            {/* Contributing Factors */}
            {rca.data.contributing_factors.length > 0 && (
              <div className="mb-6">
                <h3 className="font-semibold text-slate-900 mb-2">
                  Contributing Factors
                </h3>
                <ul className="list-disc list-inside text-slate-600 space-y-1">
                  {rca.data.contributing_factors.map((f, i) => (
                    <li key={i}>{f}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Recommendations */}
            {rca.data.recommendations.length > 0 && (
              <div>
                <h3 className="font-semibold text-slate-900 mb-2">
                  Recommendations
                </h3>
                <ol className="list-decimal list-inside text-slate-600 space-y-1">
                  {rca.data.recommendations.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ol>
              </div>
            )}

            <div className="mt-4 text-xs text-slate-400">
              Model: {rca.data.llm_model} | Analyzed{" "}
              {formatFullDate(rca.data.created_at)}
            </div>
          </CardBody>
        </Card>
      ) : null}

      {/* Fix Plans Section */}
      {fixPlans.data && fixPlans.data.length === 0 && rca.data && (
        <Card>
          <CardBody>
            <div className="text-center py-8">
              <h2 className="text-lg font-semibold text-slate-900 mb-2">No Fix Plan Yet</h2>
              <p className="text-slate-500 mb-4">
                Generate a fix plan based on the RCA result to remediate this issue.
              </p>
              <button
                onClick={triggerFixPlan}
                disabled={fixPlanLoading}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 transition-colors"
              >
                {fixPlanLoading ? "Generating..." : "Generate Fix Plan"}
              </button>
            </div>
          </CardBody>
        </Card>
      )}
      {fixPlans.data && fixPlans.data.length > 0 && (
        <Card>
          <CardBody>
            <h2 className="text-xl font-semibold text-slate-900 mb-4">
              Fix Plans
            </h2>
            <div className="space-y-3">
              {fixPlans.data.map((fp) => (
                <Link
                  key={fp.id}
                  to={`/app/fix-plans/${fp.id}`}
                  className="flex items-center justify-between p-3 rounded-lg border border-slate-200 hover:border-primary-300 hover:bg-slate-50 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <RiskLevelBadge level={fp.risk_level} />
                    <span className="text-sm font-medium text-slate-900">
                      {fp.title}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <FixPlanStatusBadge status={fp.status} />
                    <svg
                      className="w-4 h-4 text-slate-400"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M9 5l7 7-7 7"
                      />
                    </svg>
                  </div>
                </Link>
              ))}
            </div>
          </CardBody>
        </Card>
      )}

      {/* Execution History */}
      {executions.data && executions.data.length > 0 && (
        <Card>
          <CardBody>
            <h2 className="text-xl font-semibold text-slate-900 mb-4">
              Execution History
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-200">
                    <th className="px-4 py-2 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      ID
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Executed By
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Duration
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Started
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {executions.data.map((ex) => (
                    <tr key={ex.id} className="hover:bg-slate-50 transition-colors">
                      <td className="px-4 py-2 text-sm font-mono text-slate-600">
                        #{ex.id}
                      </td>
                      <td className="px-4 py-2">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                            ex.status === "succeeded"
                              ? "bg-green-100 text-green-700"
                              : ex.status === "failed"
                                ? "bg-red-100 text-red-700"
                                : "bg-slate-100 text-slate-600"
                          }`}
                        >
                          {ex.status}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-sm text-slate-600">
                        {ex.executed_by}
                      </td>
                      <td className="px-4 py-2 text-sm text-slate-600">
                        {ex.duration_ms > 0
                          ? `${(ex.duration_ms / 1000).toFixed(1)}s`
                          : "-"}
                      </td>
                      <td className="px-4 py-2 text-sm text-slate-500">
                        {ex.started_at
                          ? formatFullDate(ex.started_at)
                          : "-"}
                      </td>
                      <td className="px-4 py-2">
                        {(ex.status === "pending" || ex.status === "running") && (
                          <button
                            onClick={() => {
                              if (!window.confirm("Cancel this execution?")) return;
                              cancelExecMut.mutate(ex.id, {
                                onError: (err) => setActionMsg(`Cancel failed: ${err.message}`),
                              });
                            }}
                            disabled={cancelExecMut.isPending}
                            className="px-3 py-1 text-xs font-medium text-red-600 border border-red-200 rounded-lg hover:bg-red-50 disabled:opacity-50 transition-colors"
                          >
                            Cancel
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
                      className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600 mb-2"
                    >
                      <strong>Execution #{ex.id} error:</strong>{" "}
                      {ex.error_message}
                    </div>
                  ))}
              </div>
            )}
          </CardBody>
        </Card>
      )}
    </div>
  );
}

/* ── Pipeline Timeline Component ────────────────────────────────── */

const STAGE_COLORS: Record<string, string> = {
  detection: "bg-blue-500",
  rca: "bg-amber-500",
  planning: "bg-violet-500",
  approval: "bg-emerald-500",
  execution: "bg-orange-500",
  resolution: "bg-green-600",
  notification: "bg-slate-400",
};

const STATUS_ICONS: Record<string, string> = {
  completed: "✓",
  started: "▶",
  failed: "✗",
  skipped: "–",
};

function PipelineTimeline({ events }: { events: PipelineEvent[] }) {
  return (
    <div className="relative">
      {/* Vertical line */}
      <div className="absolute left-[15px] top-2 bottom-2 w-0.5 bg-slate-200" />
      <div className="space-y-3">
        {events.map((ev, i) => {
          const color = STAGE_COLORS[ev.stage] || "bg-slate-400";
          const icon = STATUS_ICONS[ev.status] || "•";
          const isFailed = ev.status === "failed";
          return (
            <div key={ev.id ?? i} className="relative flex items-start gap-3 pl-0">
              {/* Dot */}
              <div
                className={`relative z-10 flex-shrink-0 w-[31px] h-[31px] rounded-full flex items-center justify-center text-white text-xs font-bold ${color} ${isFailed ? "ring-2 ring-red-300" : ""}`}
              >
                {icon}
              </div>
              {/* Content */}
              <div className="flex-1 min-w-0 pb-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium text-slate-900">
                    {ev.event_type.replace(/_/g, " ")}
                  </span>
                  <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wide ${
                    isFailed
                      ? "bg-red-100 text-red-700"
                      : ev.status === "started"
                        ? "bg-blue-100 text-blue-700"
                        : ev.status === "skipped"
                          ? "bg-slate-100 text-slate-500"
                          : "bg-green-100 text-green-700"
                  }`}>
                    {ev.status}
                  </span>
                  {ev.duration_ms != null && ev.duration_ms > 0 && (
                    <span className="text-[10px] text-slate-400">
                      {ev.duration_ms >= 1000
                        ? `${(ev.duration_ms / 1000).toFixed(1)}s`
                        : `${ev.duration_ms}ms`}
                    </span>
                  )}
                </div>
                {/* Detail chips */}
                {ev.detail && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {Object.entries(ev.detail).map(([k, v]) =>
                      v != null ? (
                        <span
                          key={k}
                          className="inline-flex items-center px-1.5 py-0.5 rounded bg-slate-100 text-[10px] text-slate-600 font-mono"
                        >
                          {k}: {typeof v === "object" ? JSON.stringify(v) : String(v).slice(0, 80)}
                        </span>
                      ) : null,
                    )}
                  </div>
                )}
                <div className="text-[10px] text-slate-400 mt-0.5">
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
