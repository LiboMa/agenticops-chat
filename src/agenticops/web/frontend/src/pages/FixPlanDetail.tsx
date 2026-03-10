import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  useFixPlan,
  useApproveFixPlan,
  useRejectFixPlan,
  useExecuteFixPlan,
} from "@/hooks/useFixPlans";
import { useFixExecutions, useCancelExecution } from "@/hooks/useFixExecutions";
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
  const cancelExecMut = useCancelExecution();

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
        className="inline-flex items-center text-sm text-[#9b9b9b] hover:text-[#ececec] transition-colors"
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
            <h1 className="text-2xl font-semibold text-[#ececec]">{p.title}</h1>
          </div>
          <div
            className="text-[#9b9b9b] mb-6 report-content"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(p.summary) }}
          />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-[#666] block">Issue</span>
              <Link
                to={`/app/issues/${p.health_issue_id}`}
                className="font-mono text-blue-400 hover:underline"
              >
                #{p.health_issue_id}
              </Link>
            </div>
            <div>
              <span className="text-[#666] block">Risk Level</span>
              <span className="font-medium text-[#ececec]">{p.risk_level}</span>
            </div>
            <div>
              <span className="text-[#666] block">Impact</span>
              <span className="text-[#ececec]">{p.estimated_impact || "-"}</span>
            </div>
            <div>
              <span className="text-[#666] block">Created</span>
              <span className="text-[#ececec]">{formatFullDate(p.created_at)}</span>
            </div>
            {p.approved_by && (
              <div>
                <span className="text-[#666] block">Approved By</span>
                <span className="font-medium text-[#ececec]">{p.approved_by}</span>
              </div>
            )}
            {p.approved_at && (
              <div>
                <span className="text-[#666] block">Approved At</span>
                <span className="text-[#ececec]">{formatFullDate(p.approved_at)}</span>
              </div>
            )}
          </div>
        </CardBody>
      </Card>

      {/* Steps */}
      <Card>
        <CardBody>
          <h2 className="text-xl font-semibold text-[#ececec] mb-4">
            Remediation Steps
          </h2>
          {p.steps.length > 0 ? (
            <ol className="space-y-4">
              {p.steps.map((step, i) => (
                <RunbookStep key={i} index={i + 1} step={step} />
              ))}
            </ol>
          ) : (
            <p className="text-[#666] text-sm">No steps defined.</p>
          )}

          {/* Pre-checks */}
          {p.pre_checks.length > 0 && (
            <div className="mt-6">
              <h3 className="font-semibold text-[#ececec] mb-2">Pre-checks</h3>
              <ul className="space-y-1.5">
                {p.pre_checks.map((c, i) => (
                  <CheckItem key={i} item={c} />
                ))}
              </ul>
            </div>
          )}

          {/* Post-checks */}
          {p.post_checks.length > 0 && (
            <div className="mt-6">
              <h3 className="font-semibold text-[#ececec] mb-2">Post-checks</h3>
              <ul className="space-y-1.5">
                {p.post_checks.map((c, i) => (
                  <CheckItem key={i} item={c} />
                ))}
              </ul>
            </div>
          )}

          {/* Rollback plan */}
          {Object.keys(p.rollback_plan).length > 0 && (
            <RollbackPlan plan={p.rollback_plan} />
          )}
        </CardBody>
      </Card>

      {/* Approval Actions */}
      {needsApproval && (
        <Card>
          <CardBody>
            <h2 className="text-xl font-semibold text-[#ececec] mb-4">
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
                    className="border border-[#424242] rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
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
                    className="px-3 py-2 text-sm text-[#9b9b9b] hover:text-[#ececec]"
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
            <h2 className="text-xl font-semibold text-[#ececec] mb-4">
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
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
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
            <h2 className="text-xl font-semibold text-[#ececec] mb-4">
              Execution History
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-[#424242]">
                    <th className="px-4 py-2 text-left text-xs font-medium text-[#9b9b9b] uppercase tracking-wider">
                      ID
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-[#9b9b9b] uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-[#9b9b9b] uppercase tracking-wider">
                      Executed By
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-[#9b9b9b] uppercase tracking-wider">
                      Duration
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-[#9b9b9b] uppercase tracking-wider">
                      Started
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-[#9b9b9b] uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#424242]/50">
                  {executions.data.map((ex) => (
                    <tr key={ex.id} className="hover:bg-[#383838] transition-colors">
                      <td className="px-4 py-2 text-sm font-mono text-[#9b9b9b]">
                        #{ex.id}
                      </td>
                      <td className="px-4 py-2">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                            ex.status === "succeeded"
                              ? "bg-green-100 text-green-700"
                              : ex.status === "failed"
                                ? "bg-red-100 text-red-700"
                                : "bg-[#383838] text-[#9b9b9b]"
                          }`}
                        >
                          {ex.status}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-sm text-[#9b9b9b]">
                        {ex.executed_by}
                      </td>
                      <td className="px-4 py-2 text-sm text-[#9b9b9b]">
                        {ex.duration_ms > 0
                          ? `${(ex.duration_ms / 1000).toFixed(1)}s`
                          : "-"}
                      </td>
                      <td className="px-4 py-2 text-sm text-[#9b9b9b]">
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
                                onError: (err) => setActionError(err.message),
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

/* ── Runbook Components ─────────────────────────────────────────── */

function RunbookStep({ index, step }: { index: number; step: unknown }) {
  const isObj = typeof step === "object" && step !== null && !Array.isArray(step);
  const s = isObj ? (step as Record<string, unknown>) : null;
  const action = s?.action ?? s?.description ?? s?.step;
  const command = s?.command as string | undefined;
  const text = typeof step === "string" ? step : (typeof action === "string" ? action : null);

  return (
    <li className="border border-[#424242] rounded-lg p-4 bg-[#2f2f2f]">
      <div className="flex gap-3">
        <span className="flex-shrink-0 w-7 h-7 rounded-full bg-primary-100 text-primary-700 flex items-center justify-center text-sm font-semibold">
          {index}
        </span>
        <div className="flex-1 min-w-0">
          {text ? (
            <div
              className="text-[#ececec] text-sm leading-relaxed report-content"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(text) }}
            />
          ) : (
            <pre className="text-[#ececec] text-sm whitespace-pre-wrap">
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
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(command).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="mt-3 relative group">
      <div className="bg-[#171717] text-[#ececec] rounded-lg p-3 text-sm font-mono overflow-x-auto">
        <span className="text-[#9b9b9b] select-none">$ </span>
        {command}
      </div>
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 px-2 py-1 text-xs rounded bg-[#383838] text-[#666] hover:bg-[#424242] opacity-0 group-hover:opacity-100 transition-opacity"
      >
        {copied ? "Copied" : "Copy"}
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
    <li className="flex items-start gap-2 text-sm text-[#9b9b9b]">
      <svg className="w-4 h-4 mt-0.5 flex-shrink-0 text-[#666]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
  const trigger = plan.trigger as string | undefined;
  const steps = Array.isArray(plan.steps) ? plan.steps : null;

  return (
    <div className="mt-6 border border-amber-200 rounded-lg bg-amber-50 overflow-hidden">
      <div className="px-4 py-3 border-b border-amber-200">
        <h3 className="font-semibold text-[#ececec]">Rollback Plan</h3>
      </div>
      <div className="p-4 space-y-3">
        {trigger && (
          <div className="flex items-start gap-2 text-sm text-amber-700 bg-amber-100 rounded-lg px-3 py-2">
            <svg className="w-4 h-4 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span><strong>Trigger:</strong> {trigger}</span>
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
                  <dt className="font-medium text-[#ececec] capitalize">{k.replace(/_/g, " ")}</dt>
                  <dd className="text-[#9b9b9b] mt-0.5">
                    {typeof v === "string" ? v : <pre className="bg-[#171717] text-[#ececec] rounded-lg p-3 text-sm font-mono overflow-x-auto mt-1">{JSON.stringify(v, null, 2)}</pre>}
                  </dd>
                </div>
              ))}
          </dl>
        )}
      </div>
    </div>
  );
}
