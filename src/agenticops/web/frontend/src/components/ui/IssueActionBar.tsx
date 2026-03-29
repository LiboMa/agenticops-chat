import React, { useState } from "react";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { useIssueFeedback } from "@/hooks/useAgentMemory";
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
  onViewFixPlan?: () => void;
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
  onViewFixPlan,
}: IssueActionBarProps) {
  const { confirm, dialog } = useConfirm();
  const feedbackMut = useIssueFeedback();
  const [feedbackMsg, setFeedbackMsg] = useState<string | null>(null);
  const status = issue.status;
  const latestPlan = fixPlans?.length ? fixPlans[0] : null;

  const handleResolve = async () => {
    if (await confirm("Are you sure you want to resolve this issue?")) {
      onUpdateStatus("resolved");
    }
  };

  const handleReopen = async () => {
    if (await confirm("Reopen this issue?")) {
      onUpdateStatus("open");
    }
  };

  const handleDismiss = async () => {
    if (await confirm("Dismiss this issue? It will be hidden from active views.", { variant: "destructive", confirmText: "Dismiss" })) {
      onUpdateStatus("dismissed");
    }
  };

  const handleFalsePositive = async () => {
    if (await confirm("Mark as false positive? This creates an agent memory so similar issues are suppressed in the future.", { confirmText: "False Positive" })) {
      feedbackMut.mutate(
        { issueId: issue.id, feedback: { type: "false_positive", confidence: 4 } },
        {
          onSuccess: () => setFeedbackMsg("Marked as false positive — agent memory created."),
          onError: (err) => setFeedbackMsg(`Feedback failed: ${err.message}`),
        },
      );
    }
  };

  const handleConfirmed = async () => {
    feedbackMut.mutate(
      { issueId: issue.id, feedback: { type: "confirmed", confidence: 5 } },
      {
        onSuccess: () => setFeedbackMsg("Issue confirmed — conflicting memories archived."),
        onError: (err) => setFeedbackMsg(`Feedback failed: ${err.message}`),
      },
    );
  };

  if (status === "dismissed") {
    return (
      <>
        <div className="flex items-center justify-between p-4 rounded-lg bg-muted/50 border border-border">
          <div className="flex items-center gap-2 text-muted-foreground">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
            </svg>
            <span className="font-medium">This issue has been dismissed</span>
          </div>
          <button
            onClick={handleReopen}
            disabled={statusUpdating}
            className="px-3 py-1.5 text-sm font-medium rounded-lg border border-border text-muted-foreground bg-background hover:bg-secondary disabled:opacity-50 transition-colors"
          >
            {statusUpdating ? "Updating..." : "Reopen"}
          </button>
        </div>
        {dialog}
      </>
    );
  }

  if (status === "resolved") {
    return (
      <>
        <div className="flex items-center justify-between p-4 rounded-lg bg-green-500/10 border border-green-500/20">
          <div className="flex items-center gap-2 text-green-600 dark:text-green-400">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span className="font-medium">This issue has been resolved</span>
            {issue.resolved_at && (
              <span className="text-sm text-green-600 dark:text-green-400 ml-2">
                {new Date(issue.resolved_at).toLocaleDateString()}
              </span>
            )}
          </div>
          <button
            onClick={handleReopen}
            disabled={statusUpdating}
            className="px-3 py-1.5 text-sm font-medium rounded-lg border border-border text-muted-foreground bg-background hover:bg-secondary disabled:opacity-50 transition-colors"
          >
            {statusUpdating ? "Updating..." : "Reopen"}
          </button>
        </div>
        {dialog}
      </>
    );
  }

  return (
    <>
      <div className="flex items-center gap-3 p-4 rounded-lg bg-secondary border border-border">
        {/* Primary action based on status */}
        {(status === "open" || status === "investigating" || status === "acknowledged") && (
          <button
            onClick={onRunRca}
            disabled={rcaLoading}
            className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
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
          <button
            onClick={onViewFixPlan}
            className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
            Review Fix Plan for Approval
          </button>
        )}

        {status === "fix_approved" && (
          <div className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg bg-primary/10 text-primary border border-primary/20">
            <svg className="animate-pulse h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Awaiting execution...
          </div>
        )}

        {status === "fix_executed" && (
          <button
            onClick={async () => {
              if (await confirm("Mark this issue as resolved?")) {
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

        {/* Secondary: Resolve (available at every non-fix_executed status; resolved/dismissed already returned early) */}
        {status !== "fix_executed" && (
          <button
            onClick={handleResolve}
            disabled={statusUpdating}
            className="px-3 py-2 text-sm font-medium rounded-lg border border-border text-muted-foreground bg-background hover:bg-secondary disabled:opacity-50 transition-colors"
          >
            {statusUpdating ? "Updating..." : "Resolve"}
          </button>
        )}

        {/* Divider */}
        <div className="w-px h-6 bg-border mx-1" />

        {/* Feedback: False Positive */}
        <button
          onClick={handleFalsePositive}
          disabled={feedbackMut.isPending}
          title="Mark as false positive — creates agent memory for future suppression"
          className="px-3 py-2 text-sm font-medium rounded-lg border border-amber-300 text-amber-700 bg-amber-50 hover:bg-amber-100 disabled:opacity-50 transition-colors dark:border-amber-700 dark:text-amber-400 dark:bg-amber-950 dark:hover:bg-amber-900"
        >
          {feedbackMut.isPending ? "..." : "False Positive"}
        </button>

        {/* Feedback: Confirmed */}
        <button
          onClick={handleConfirmed}
          disabled={feedbackMut.isPending}
          title="Confirm this issue is real — archives conflicting memories"
          className="px-3 py-2 text-sm font-medium rounded-lg border border-green-300 text-green-700 bg-green-50 hover:bg-green-100 disabled:opacity-50 transition-colors dark:border-green-700 dark:text-green-400 dark:bg-green-950 dark:hover:bg-green-900"
        >
          {feedbackMut.isPending ? "..." : "Confirmed"}
        </button>

        {/* Dismiss */}
        <button
          onClick={handleDismiss}
          disabled={statusUpdating}
          className="px-3 py-2 text-sm font-medium rounded-lg border border-border text-muted-foreground bg-background hover:bg-secondary disabled:opacity-50 transition-colors"
        >
          {statusUpdating ? "Updating..." : "Dismiss"}
        </button>
      </div>
      {feedbackMsg && (
        <div className="p-2.5 rounded-lg bg-primary/10 border border-primary/20 text-sm text-primary">
          {feedbackMsg}
        </div>
      )}
      {dialog}
    </>
  );
});
