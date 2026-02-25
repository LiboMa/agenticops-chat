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
        className="inline-flex items-center text-sm text-gray-500 hover:text-gray-700"
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
            <h1 className="text-2xl font-bold text-gray-900">{p.title}</h1>
          </div>
          <p className="text-gray-600 mb-6">{p.summary}</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-gray-500 block">Issue</span>
              <Link
                to={`/app/anomalies/${p.health_issue_id}`}
                className="font-mono text-pd-green-600 hover:underline"
              >
                #{p.health_issue_id}
              </Link>
            </div>
            <div>
              <span className="text-gray-500 block">Risk Level</span>
              <span className="font-medium">{p.risk_level}</span>
            </div>
            <div>
              <span className="text-gray-500 block">Impact</span>
              <span>{p.estimated_impact || "-"}</span>
            </div>
            <div>
              <span className="text-gray-500 block">Created</span>
              <span>{formatFullDate(p.created_at)}</span>
            </div>
            {p.approved_by && (
              <div>
                <span className="text-gray-500 block">Approved By</span>
                <span className="font-medium">{p.approved_by}</span>
              </div>
            )}
            {p.approved_at && (
              <div>
                <span className="text-gray-500 block">Approved At</span>
                <span>{formatFullDate(p.approved_at)}</span>
              </div>
            )}
          </div>
        </CardBody>
      </Card>

      {/* Steps */}
      <Card>
        <CardBody>
          <h2 className="text-xl font-bold text-gray-900 mb-4">
            Remediation Steps
          </h2>
          {p.steps.length > 0 ? (
            <ol className="space-y-3">
              {p.steps.map((step, i) => (
                <li key={i} className="flex gap-3">
                  <span className="flex-shrink-0 w-7 h-7 rounded-full bg-pd-green-100 text-pd-green-700 flex items-center justify-center text-sm font-semibold">
                    {i + 1}
                  </span>
                  <div
                    className="text-gray-700 text-sm leading-relaxed pt-0.5"
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
            <p className="text-gray-500 text-sm">No steps defined.</p>
          )}

          {/* Pre-checks */}
          {p.pre_checks.length > 0 && (
            <div className="mt-6">
              <h3 className="font-semibold text-gray-900 mb-2">Pre-checks</h3>
              <ul className="list-disc list-inside text-sm text-gray-700 space-y-1">
                {p.pre_checks.map((c, i) => (
                  <li key={i}>{typeof c === "string" ? c : JSON.stringify(c)}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Post-checks */}
          {p.post_checks.length > 0 && (
            <div className="mt-6">
              <h3 className="font-semibold text-gray-900 mb-2">Post-checks</h3>
              <ul className="list-disc list-inside text-sm text-gray-700 space-y-1">
                {p.post_checks.map((c, i) => (
                  <li key={i}>{typeof c === "string" ? c : JSON.stringify(c)}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Rollback plan */}
          {Object.keys(p.rollback_plan).length > 0 && (
            <div className="mt-6">
              <h3 className="font-semibold text-gray-900 mb-2">
                Rollback Plan
              </h3>
              <pre className="bg-gray-50 rounded-lg p-4 text-sm text-gray-700 overflow-x-auto">
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
            <h2 className="text-xl font-bold text-gray-900 mb-4">
              Approval Actions
            </h2>

            {(p.risk_level === "L2" || p.risk_level === "L3") && (
              <div className="mb-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg text-sm text-yellow-800">
                <strong>{p.risk_level} plan</strong> — requires human approval
                before execution.
              </div>
            )}

            {actionError && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                {actionError}
              </div>
            )}

            <div className="flex items-center gap-3">
              {!showApproveForm ? (
                <button
                  onClick={() => setShowApproveForm(true)}
                  className="px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-md hover:bg-green-700 transition-colors"
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
                    className="border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
                  />
                  <button
                    onClick={handleApprove}
                    disabled={approveMut.isPending || !approverName.trim()}
                    className="px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-md hover:bg-green-700 disabled:opacity-50 transition-colors"
                  >
                    {approveMut.isPending ? "Approving..." : "Confirm"}
                  </button>
                  <button
                    onClick={() => setShowApproveForm(false)}
                    className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700"
                  >
                    Cancel
                  </button>
                </div>
              )}
              <button
                onClick={handleReject}
                disabled={rejectMut.isPending}
                className="px-4 py-2 border border-red-300 text-red-600 text-sm font-medium rounded-md hover:bg-red-50 disabled:opacity-50 transition-colors"
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
            <h2 className="text-xl font-bold text-gray-900 mb-4">
              Execute Plan
            </h2>

            {actionError && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                {actionError}
              </div>
            )}

            <button
              onClick={handleExecute}
              disabled={executeMut.isPending}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50 transition-colors"
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
            <h2 className="text-xl font-bold text-gray-900 mb-4">
              Execution History
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200">
                    <th className="px-4 py-2 text-left text-xs font-semibold text-gray-500 uppercase">
                      ID
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-semibold text-gray-500 uppercase">
                      Status
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-semibold text-gray-500 uppercase">
                      Executed By
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-semibold text-gray-500 uppercase">
                      Duration
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-semibold text-gray-500 uppercase">
                      Started
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {executions.data.map((ex) => (
                    <tr key={ex.id} className="hover:bg-gray-50">
                      <td className="px-4 py-2 text-sm font-mono">
                        #{ex.id}
                      </td>
                      <td className="px-4 py-2">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${
                            ex.status === "succeeded"
                              ? "bg-green-100 text-green-800"
                              : ex.status === "failed"
                                ? "bg-red-100 text-red-800"
                                : "bg-gray-100 text-gray-700"
                          }`}
                        >
                          {ex.status}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-sm text-gray-600">
                        {ex.executed_by}
                      </td>
                      <td className="px-4 py-2 text-sm text-gray-600">
                        {ex.duration_ms > 0
                          ? `${(ex.duration_ms / 1000).toFixed(1)}s`
                          : "-"}
                      </td>
                      <td className="px-4 py-2 text-sm text-gray-500">
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
                      className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 mb-2"
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
