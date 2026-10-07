import React, { useState, useCallback } from "react";
import { useConfirm } from "./ConfirmDialog";
import { useUpdateIssueStatus } from "@/hooks/useIssueActions";
import { useIssueFeedback } from "@/hooks/useAgentMemory";
import { useLocale } from "@/i18n/LocaleContext";
import type { HealthIssue, IssueStatus } from "@/api/types";

/** Statuses where the resolve / confirm / dismiss quick actions are offered; resolved and dismissed offer reopen. */
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

/** The issue list's row quick actions (R3), icon buttons in WorkItemTable's rowActions column. */
export function IssueQuickActions({ issue }: { issue: HealthIssue }) {
  const { t } = useLocale();
  const isClosed = issue.status === "resolved" || issue.status === "dismissed";
  const canAct = ACTIONABLE.has(issue.status);

  const statusMut = useUpdateIssueStatus();
  const feedbackMut = useIssueFeedback();
  const { confirm, dialog } = useConfirm();
  const [toast, setToast] = useState<string | null>(null);

  const busy = statusMut.isPending || feedbackMut.isPending;
  const ref = `I#${issue.id}`;

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2500);
  }, []);
  const showError = useCallback((err: Error) => showToast(t("workitem.quick.failed").replace("{error}", err.message)), [showToast, t]);

  const handleStatus = async (e: React.MouseEvent, target: IssueStatus, message: string, confirmText: string,
                              variant?: "destructive") => {
    e.stopPropagation();
    if (busy) return;
    if (!(await confirm(message, { title: `${ref} · ${issue.title}`, confirmText, cancelText: t("common.cancel"), variant }))) return;
    statusMut.mutate(
      { id: issue.id, status: target },
      {
        onSuccess: () => showToast(t("workitem.quick.statusDone").replace("{ref}", ref).replace("{status}", t(`issues.status.${target}`))),
        onError: showError,
      },
    );
  };

  const handleConfirmed = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (busy) return;
    feedbackMut.mutate(
      { issueId: issue.id, feedback: { type: "confirmed", confidence: 5 } },
      { onSuccess: () => showToast(t("workitem.quick.confirmed")), onError: showError },
    );
  };

  const resolveLabel = t("workitem.menu.markResolved");
  const dismissLabel = t("workitem.menu.dismiss");
  const reopenLabel = t("workitem.menu.reopen");

  return (
    <>
      {toast ? (
        // clamped to the column: a long failure message must not widen it (the whole text is the tooltip)
        <span data-pinned title={toast} className="max-w-24 line-clamp-2 break-words text-[11px] leading-tight text-right text-primary">
          {toast}
        </span>
      ) : (
        <>
          {canAct && (
            <>
              <IconBtn
                label={resolveLabel}
                onClick={(e) => handleStatus(e, "resolved", t("workitem.confirm.resolve"), resolveLabel)}
                disabled={busy}
                className="text-green-600 hover:bg-green-50 dark:hover:bg-green-950"
                icon={<IconCheck />}
              />
              <IconBtn
                label={t("workitem.quick.confirmTitle")}
                onClick={handleConfirmed}
                disabled={busy}
                className="text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-950"
                icon={<IconThumbUp />}
              />
              <IconBtn
                label={dismissLabel}
                onClick={(e) => handleStatus(e, "dismissed", t("workitem.confirm.dismiss"), dismissLabel, "destructive")}
                disabled={busy}
                className="text-muted-foreground hover:bg-secondary"
                icon={<IconX />}
              />
            </>
          )}
          {isClosed && (
            <IconBtn
              label={reopenLabel}
              onClick={(e) => handleStatus(e, "open", t("workitem.confirm.reopen"), reopenLabel)}
              disabled={busy}
              className="text-amber-600 hover:bg-amber-50 dark:hover:bg-amber-950"
              icon={<IconRefresh />}
            />
          )}
        </>
      )}
      {dialog}
    </>
  );
}

/* ── Icon button (the label is its tooltip and accessible name) ──── */

function IconBtn({
  label,
  onClick,
  disabled,
  className = "",
  icon,
}: {
  label: string;
  onClick: (e: React.MouseEvent) => void;
  disabled: boolean;
  className?: string;
  icon: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className={`inline-flex items-center justify-center p-1.5 rounded-md transition-colors disabled:opacity-40 ${className}`}
    >
      {icon}
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
