import React from "react";
import { Link } from "react-router-dom";
import type { IssueStatus, Anomaly, RCAResult, FixPlan } from "@/api/types";

interface IssueActionBarProps {
  issue: Anomaly;
  rca: RCAResult | null | undefined;
  fixPlans: FixPlan[] | undefined;
  rcaLoading: boolean;
  fixPlanLoading: boolean;
  statusUpdating: boolean;
  onRunRca: () => void;
  onGenerateFixPlan: () => void;
  onUpdateStatus: (status: IssueStatus) => void;
}

export const IssueActionBar = React.memo(function IssueActionBar({
  issue,
  rca,
  fixPlans,
  rcaLoading,
  fixPlanLoading,
  statusUpdating,
  onRunRca,
  onGenerateFixPlan,
  onUpdateStatus,
}: IssueActionBarProps) {
  const status = issue.status;
  const latestPlan = fixPlans?.length ? fixPlans[0] : null;

  const handleResolve = () => {
    if (window.confirm("Are you sure you want to resolve this issue?")) {
      onUpdateStatus("resolved");
    }
  };

  const handleReopen = () => {
    if (window.confirm("Reopen this issue?")) {
      onUpdateStatus("open");
    }
  };

  if (status === "resolved") {
    return (
      <div className="flex items-center justify-between p-4 rounded-lg bg-green-50 border border-green-200">
        <div className="flex items-center gap-2 text-green-700">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span className="font-medium">This issue has been resolved</span>
          {issue.resolved_at && (
            <span className="text-sm text-green-600 ml-2">
              {new Date(issue.resolved_at).toLocaleDateString()}
            </span>
          )}
        </div>
        <button
          onClick={handleReopen}
          disabled={statusUpdating}
          className="px-3 py-1.5 text-sm font-medium rounded-lg border border-slate-300 text-slate-600 bg-white hover:bg-slate-50 disabled:opacity-50 transition-colors"
        >
          {statusUpdating ? "Updating..." : "Reopen"}
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 p-4 rounded-lg bg-slate-50 border border-slate-200">
      {/* Primary action based on status */}
      {(status === "open" || status === "investigating" || status === "acknowledged") && (
        <button
          onClick={onRunRca}
          disabled={rcaLoading}
          className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-50 transition-colors"
        >
          {rcaLoading ? (
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : (
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          )}
          Run RCA
        </button>
      )}

      {status === "root_cause_identified" && (
        <button
          onClick={onGenerateFixPlan}
          disabled={fixPlanLoading || !rca}
          title={!rca ? "RCA result required" : "Generate a fix plan from the RCA result"}
          className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 transition-colors"
        >
          {fixPlanLoading ? (
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : (
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
          )}
          Generate Fix Plan
        </button>
      )}

      {status === "fix_planned" && latestPlan && (
        <Link
          to={`/app/fix-plans/${latestPlan.id}`}
          className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 transition-colors"
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          Review Fix Plan for Approval
        </Link>
      )}

      {status === "fix_approved" && (
        <div className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg bg-indigo-50 text-indigo-700 border border-indigo-200">
          <svg className="animate-pulse h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          Awaiting execution...
        </div>
      )}

      {status === "fix_executed" && (
        <button
          onClick={() => {
            if (window.confirm("Mark this issue as resolved?")) {
              onUpdateStatus("resolved");
            }
          }}
          disabled={statusUpdating}
          className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 transition-colors"
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          {statusUpdating ? "Updating..." : "Mark Resolved"}
        </button>
      )}

      {/* Secondary: Resolve (available at every non-fix_executed status; resolved already returned early) */}
      {status !== "fix_executed" && (
        <button
          onClick={handleResolve}
          disabled={statusUpdating}
          className="px-3 py-2 text-sm font-medium rounded-lg border border-slate-300 text-slate-600 bg-white hover:bg-slate-50 disabled:opacity-50 transition-colors"
        >
          {statusUpdating ? "Updating..." : "Resolve"}
        </button>
      )}
    </div>
  );
});
