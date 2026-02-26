import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  useFixPlan,
  useApproveFixPlan,
  useRejectFixPlan,
  useExecuteFixPlan,
} from "@/hooks/useFixPlans";
import { useFixExecutions } from "@/hooks/useFixExecutions";
import { Card, CardBody } from "@/components/ui/Card";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { FixPlanStatusBadge } from "@/components/ui/FixPlanStatusBadge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatFullDate } from "@/lib/formatDate";
import { renderMarkdown } from "@/lib/renderMarkdown";

export default function FixPlanDetail() {
  const { id } = useParams<{ id: string }>();
  const planId = Number(id);

  const plan = useFixPlan(planId);
  const executions = useFixExecutions(planId);
  const approveMut = useApproveFixPlan();
  const rejectMut = useRejectFixPlan();
  const executeMut = useExecuteFixPlan();

  const [approverName, setApproverName] = useState("");
  const [showApproveForm, setShowApproveForm] = useState(false);
  const [actionError, setActionError] = useState("");

  if (plan.isLoading) return <Spinner label="Loading fix plan..." />;
  if (plan.error)
    return (
      <ErrorBanner
        message={plan.error.message}
        onRetry={() => plan.refetch()}
      />
    );

  const p = plan.data!;
  const needsApproval = p.status === "draft" || p.status === "pending_approval";
  const canExecute = p.status === "approved";

  function handleApprove() {
    if (!approverName.trim()) return;
    setActionError("");
    approveMut.mutate(
      { id: planId, approved_by: approverName.trim() },
      {
        onSuccess: () => setShowApproveForm(false),
        onError: (err) => setActionError(err.message),
      },
    );
  }

  function handleReject() {
    if (!window.confirm("Are you sure you want to reject this fix plan?"))
      return;
    setActionError("");
    rejectMut.mutate(planId, {
      onError: (err) => setActionError(err.message),
    });
  }

  function handleExecute() {
    if (!window.confirm("Execute this fix plan now?")) return;
    setActionError("");
    executeMut.mutate(planId, {
      onError: (err) => setActionError(err.message),
    });
  }

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Back link */}
      <Link
        to="/app/fix-plans"
        className="inline-flex items-center text-sm text-slate-500 hover:text-slate-700 transition-colors"
      >
        <svg
          className="h-4 w-4 mr-1"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M15 19l-7-7 7-7"
          />
        </svg>
        Back to Fix Plans
      </Link>

      {/* Header */}
      <Card>
        <CardBody>
          <div className="flex items-center gap-3 mb-4">
            <RiskLevelBadge level={p.risk_level} />
            <FixPlanStatusBadge status={p.status} />
            <h1 className="text-2xl font-semibold text-slate-900">{p.title}</h1>
          </div>
          <div
            className="text-slate-600 mb-6 report-content"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(p.summary) }}
          />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-slate-400 block">Issue</span>
              <Link
                to={`/app/anomalies/${p.health_issue_id}`}
                className="font-mono text-primary-600 hover:underline"
              >
                #{p.health_issue_id}
              </Link>
            </div>
            <div>
              <span className="text-slate-400 block">Risk Level</span>
              <span className="font-medium text-slate-700">{p.risk_level}</span>
            </div>
            <div>
              <span className="text-slate-400 block">Impact</span>
              <span className="text-slate-700">{p.estimated_impact || "-"}</span>
            </div>
            <div>
              <span className="text-slate-400 block">Created</span>
              <span className="text-slate-700">{formatFullDate(p.created_at)}</span>
            </div>
            {p.approved_by && (
              <div>
                <span className="text-slate-400 block">Approved By</span>
                <span className="font-medium text-slate-700">{p.approved_by}</span>
              </div>
            )}
            {p.approved_at && (
              <div>
                <span className="text-slate-400 block">Approved At</span>
                <span className="text-slate-700">{formatFullDate(p.approved_at)}</span>
              </div>
            )}
          </div>
        </CardBody>
      </Card>

      {/* Steps */}
      <Card>
        <CardBody>
          <h2 className="text-xl font-semibold text-slate-900 mb-4">
            Remediation Steps
          </h2>
          {p.steps.length > 0 ? (
            <ol className="space-y-3">
              {p.steps.map((step, i) => (
                <li key={i} className="flex gap-3">
                  <span className="flex-shrink-0 w-7 h-7 rounded-full bg-primary-100 text-primary-700 flex items-center justify-center text-sm font-semibold">
                    {i + 1}
                  </span>
                  <div
                    className="text-slate-700 text-sm leading-relaxed pt-0.5 report-content"
                    dangerouslySetInnerHTML={{
                      __html: renderMarkdown(
                        typeof step === "string" ? step : JSON.stringify(step),
                      ),
                    }}
                  />
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-slate-400 text-sm">No steps defined.</p>
          )}

          {/* Pre-checks */}
          {p.pre_checks.length > 0 && (
            <div className="mt-6">
              <h3 className="font-semibold text-slate-900 mb-2">Pre-checks</h3>
              <ul className="list-disc list-inside text-sm text-slate-600 space-y-1">
                {p.pre_checks.map((c, i) => (
                  <li key={i}>{typeof c === "string" ? c : JSON.stringify(c)}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Post-checks */}
          {p.post_checks.length > 0 && (
            <div className="mt-6">
              <h3 className="font-semibold text-slate-900 mb-2">Post-checks</h3>
              <ul className="list-disc list-inside text-sm text-slate-600 space-y-1">
                {p.post_checks.map((c, i) => (
                  <li key={i}>{typeof c === "string" ? c : JSON.stringify(c)}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Rollback plan */}
          {Object.keys(p.rollback_plan).length > 0 && (
            <div className="mt-6">
              <h3 className="font-semibold text-slate-900 mb-2">
                Rollback Plan
              </h3>
              <pre className="bg-slate-900 text-slate-100 rounded-lg p-4 text-sm font-mono overflow-x-auto">
                {JSON.stringify(p.rollback_plan, null, 2)}
              </pre>
            </div>
          )}
        </CardBody>
      </Card>

      {/* Approval Actions */}
      {needsApproval && (
        <Card>
          <CardBody>
            <h2 className="text-xl font-semibold text-slate-900 mb-4">
              Approval Actions
            </h2>

            {(p.risk_level === "L2" || p.risk_level === "L3") && (
              <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-700">
                <strong>{p.risk_level} plan</strong> — requires human approval
                before execution.
              </div>
            )}

            {actionError && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
                {actionError}
              </div>
            )}

            <div className="flex items-center gap-3">
              {!showApproveForm ? (
                <button
                  onClick={() => setShowApproveForm(true)}
                  className="px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-lg hover:bg-green-700 transition-colors"
                >
                  Approve
                </button>
              ) : (
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    placeholder="Your name"
                    value={approverName}
                    onChange={(e) => setApproverName(e.target.value)}
                    className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                  />
                  <button
                    onClick={handleApprove}
                    disabled={approveMut.isPending || !approverName.trim()}
                    className="px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-lg hover:bg-green-700 disabled:opacity-50 transition-colors"
                  >
                    {approveMut.isPending ? "Approving..." : "Confirm"}
                  </button>
                  <button
                    onClick={() => setShowApproveForm(false)}
                    className="px-3 py-2 text-sm text-slate-500 hover:text-slate-700"
                  >
                    Cancel
                  </button>
                </div>
              )}
              <button
                onClick={handleReject}
                disabled={rejectMut.isPending}
                className="px-4 py-2 border border-red-200 text-red-600 text-sm font-medium rounded-lg hover:bg-red-50 disabled:opacity-50 transition-colors"
              >
                {rejectMut.isPending ? "Rejecting..." : "Reject"}
              </button>
            </div>
          </CardBody>
        </Card>
      )}

      {/* Execute Action */}
      {canExecute && (
        <Card>
          <CardBody>
            <h2 className="text-xl font-semibold text-slate-900 mb-4">
              Execute Plan
            </h2>

            {actionError && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
                {actionError}
              </div>
            )}

            <button
              onClick={handleExecute}
              disabled={executeMut.isPending}
              className="px-4 py-2 bg-primary-600 text-white text-sm font-medium rounded-lg hover:bg-primary-700 disabled:opacity-50 transition-colors"
            >
              {executeMut.isPending ? "Executing..." : "Execute Plan"}
            </button>
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
