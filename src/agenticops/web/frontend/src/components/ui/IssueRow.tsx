import React, { useState, useCallback } from "react";
import { PipelineStepper } from "./PipelineStepper";
import { SeverityBadge } from "./SeverityBadge";
import { useConfirm } from "./ConfirmDialog";
import { formatShortDate } from "@/lib/formatDate";
import { useUpdateIssueStatus } from "@/hooks/useIssueActions";
import { useIssueFeedback } from "@/hooks/useAgentMemory";
import type { Anomaly, IssueStatus } from "@/api/types";

interface Props {
  issue: Anomaly;
  onClick: (issue: Anomaly) => void;
}

const STATUS_LABELS: Record<string, string> = {
  open: "open",
  investigating: "investigating",
  acknowledged: "acknowledged",
  root_cause_identified: "rca_done",
  fix_planned: "fix_planned",
  fix_approved: "approved",
  fix_executing: "executing",
  fix_executed: "executed",
  resolved: "resolved",
  dismissed: "dismissed",
};

/** Meta line: drop "unknown" placeholders, show the tail of ARNs (the id part carries the signal). */
function shortResourceRef(type: string | null | undefined, id: string | null | undefined): string {
  const t = type && type !== "unknown" ? type : "";
  let rid = id ?? "";
  if (rid.startsWith("arn:")) {
    rid = rid.split(/[/:]/).filter(Boolean).pop() ?? rid;
  }
  if (rid.length > 28) rid = "…" + rid.slice(-28);
  if (t && rid) return `${t}/${rid}`;
  return t || rid;
}

/** Statuses where inline quick-actions are available */
const ACTIONABLE = new Set<string>([
  "open",
  "investigating",
  "acknowledged",
  "root_cause_identified",
  "fix_planned",
  "fix_approved",
  "fix_executing",
  "fix_executed",
]);

export const IssueRow = React.memo(function IssueRow({ issue, onClick }: Props) {
  const isResolved = issue.status === "resolved";
  const isDismissed = issue.status === "dismissed";
  const isCritical = issue.severity === "critical" && !isResolved && !isDismissed;
  const canAct = ACTIONABLE.has(issue.status);

  const statusMut = useUpdateIssueStatus();
  const feedbackMut = useIssueFeedback();
  const { confirm, dialog } = useConfirm();
  const [toast, setToast] = useState<string | null>(null);

  const busy = statusMut.isPending || feedbackMut.isPending;

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2500);
  }, []);

  const handleStatus = useCallback(
    async (e: React.MouseEvent, target: IssueStatus, confirmMsg: string) => {
      e.stopPropagation();
      if (busy) return;
      if (!(await confirm(confirmMsg))) return;
      statusMut.mutate(
        { id: issue.id, status: target },
        {
          onSuccess: () => showToast(`#${issue.id} ${target}`),
          onError: (err) => showToast(`Error: ${err.message}`),
        },
      );
    },
    [busy, confirm, issue.id, statusMut, showToast],
  );

  const handleResolve = useCallback(
    (e: React.MouseEvent) => handleStatus(e, "resolved", `Resolve issue #${issue.id}?`),
    [handleStatus, issue.id],
  );

  const handleDismiss = useCallback(
    (e: React.MouseEvent) => handleStatus(e, "dismissed", `Dismiss issue #${issue.id}? It will be hidden from active views.`),
    [handleStatus, issue.id],
  );

  const handleReopen = useCallback(
    (e: React.MouseEvent) => handleStatus(e, "open", `Reopen issue #${issue.id}?`),
    [handleStatus, issue.id],
  );

  const handleConfirmed = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      if (busy) return;
      feedbackMut.mutate(
        { issueId: issue.id, feedback: { type: "confirmed", confidence: 5 } },
        {
          onSuccess: () => showToast("Confirmed"),
          onError: (err) => showToast(`Error: ${err.message}`),
        },
      );
    },
    [busy, feedbackMut, issue.id, showToast],
  );

  return (
    <>
      <div
        onClick={() => onClick(issue)}
        className={`group relative flex items-center gap-3 px-4 py-3 border-b border-border/50 cursor-pointer transition-colors hover:bg-accent ${
          isResolved || isDismissed ? "opacity-50" : ""
        } ${isCritical ? "bg-red-500/5" : ""}`}
      >
        <SeverityBadge severity={issue.severity} />
        <div className="flex-1 min-w-0">
          <div className="text-sm text-foreground">
            <span className="text-muted-foreground font-mono">#{issue.id}</span>{" "}
            {issue.title}
            {(issue.occurrence_count ?? 1) > 1 && (
              <span
                className="ml-2 inline-flex items-center px-1.5 py-0.5 text-xs font-semibold rounded-full bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300"
                title={`Recurred ${issue.occurrence_count} times (signal-gate merged)`}
              >
                ×{issue.occurrence_count}
              </span>
            )}
          </div>
          <div className="text-xs text-muted-foreground mt-0.5">
            {[
              issue.region && issue.region !== "unknown" ? issue.region : "",
              shortResourceRef(issue.resource_type, issue.resource_id),
              formatShortDate(issue.detected_at),
            ].filter(Boolean).join(" · ")}
          </div>
        </div>

        <PipelineStepper status={issue.status} className="w-20 flex-shrink-0" />

        <span
          className={`text-xs w-16 text-right flex-shrink-0 ${
            isResolved ? "text-green-500" : isDismissed ? "text-slate-400" : "text-primary"
          }`}
        >
          {STATUS_LABELS[issue.status] ?? issue.status}
          {isResolved && " \u2713"}
        </span>

        {/* ── Inline actions (hover reveal) ──────────────────── */}
        {canAct && (
          <div className="hidden group-hover:flex items-center gap-1 absolute right-3 top-1/2 -translate-y-1/2 bg-card/95 backdrop-blur-sm border border-border rounded-lg shadow-md px-1.5 py-1 z-10">
            <InlineBtn
              label="Resolve"
              title="Resolve this issue"
              onClick={handleResolve}
              disabled={busy}
              className="text-green-600 hover:bg-green-50 dark:hover:bg-green-950"
              icon={<IconCheck />}
            />
            <InlineBtn
              label="Confirmed"
              title="Confirm this is a real issue"
              onClick={handleConfirmed}
              disabled={busy}
              className="text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-950"
              icon={<IconThumbUp />}
            />
            <InlineBtn
              label="Dismiss"
              title="Dismiss this issue"
              onClick={handleDismiss}
              disabled={busy}
              className="text-muted-foreground hover:bg-secondary"
              icon={<IconX />}
            />
          </div>
        )}

        {/* Terminal-state inline actions */}
        {(isResolved || isDismissed) && (
          <div className="hidden group-hover:flex items-center absolute right-3 top-1/2 -translate-y-1/2 bg-card/95 backdrop-blur-sm border border-border rounded-lg shadow-md px-1.5 py-1 z-10">
            <InlineBtn
              label="Reopen"
              title="Reopen this issue"
              onClick={handleReopen}
              disabled={busy}
              className="text-amber-600 hover:bg-amber-50 dark:hover:bg-amber-950"
              icon={<IconRefresh />}
            />
          </div>
        )}

        {/* Toast */}
        {toast && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-medium px-2 py-1 rounded-md bg-primary/10 text-primary border border-primary/20 z-20 animate-in fade-in slide-in-from-right-2 duration-150">
            {toast}
          </span>
        )}
      </div>
      {dialog}
    </>
  );
});

/* ── Inline button ────────────────────────────────────────────────── */

function InlineBtn({
  label,
  title,
  onClick,
  disabled,
  className = "",
  icon,
}: {
  label: string;
  title: string;
  onClick: (e: React.MouseEvent) => void;
  disabled: boolean;
  className?: string;
  icon: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-md transition-colors disabled:opacity-40 ${className}`}
    >
      {icon}
      {label}
    </button>
  );
}

/* ── Icons (inline SVG, 14×14) ───────────────────────────────────── */

function IconCheck() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
    </svg>
  );
}

function IconThumbUp() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 10h4.764a2 2 0 011.789 2.894l-3.5 7A2 2 0 0115.263 21H7V10l4-8 1 1v4a1 1 0 001 1h1z" />
    </svg>
  );
}

function IconX() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
    </svg>
  );
}

function IconRefresh() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
    </svg>
  );
}
